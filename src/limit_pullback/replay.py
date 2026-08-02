"""Single-stock, strict point-in-time, in-memory daily replay."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone

from limit_pullback.instruments import parse_instrument_code
from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import (
    DataQuality,
    EvaluationMode,
    EventFlag,
    SetupStage,
    SetupTerminationReason,
)
from limit_pullback.models.inspect import DataSourceReport
from limit_pullback.models.market import (
    DailyBar,
    DailyBarsRequest,
    LimitUpPoolRequest,
    LimitUpRecord,
)
from limit_pullback.models.replay import (
    ReplayOutput,
    ReplayTimelineItem,
    ReplayTransitionSummary,
    SetupSummary,
)
from limit_pullback.models.signal import StrategySignal
from limit_pullback.providers.base import DailyBarProvider, LimitUpPoolProvider
from limit_pullback.quality import (
    QUALITY_ORDER,
    daily_prefix_quality as _daily_prefix_quality,
    merge_signal_quality as _merge_signal_quality,
    missing_fields as _missing_fields,
    quality_flag_date as _quality_flag_date,
    timeline_item as _timeline_item,
    worst_quality as _worst_quality,
)
from limit_pullback.strategy.engine import evaluate_strategy
from limit_pullback.strategy.indicators import SequencePrefixView
from limit_pullback.strategy.math import calculate_indicators
from limit_pullback.strategy.structure import is_limit_close


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _provider_metadata(provider: object) -> tuple[str, str]:
    name = getattr(provider, "provider_name", type(provider).__name__)
    version = getattr(provider, "provider_version", "unknown")
    return str(name), str(version)


def _first_stage(
    timeline: Sequence[ReplayTimelineItem],
    stage: SetupStage,
) -> date | None:
    return next(
        (item.trade_date for item in timeline if item.setup_stage is stage),
        None,
    )


def _first_event(
    timeline: Sequence[ReplayTimelineItem],
    event: EventFlag,
) -> date | None:
    return next(
        (item.trade_date for item in timeline if event in item.event_flags),
        None,
    )


def _transition_summary(
    timeline: Sequence[ReplayTimelineItem],
) -> ReplayTransitionSummary:
    anchor_dates = tuple(
        item.anchor_snapshot.anchor_date
        for item in timeline
        if item.anchor_snapshot is not None
    )
    return ReplayTransitionSummary(
        first_anchor_date=min(anchor_dates) if anchor_dates else None,
        first_b1_date=_first_stage(timeline, SetupStage.B1_READY),
        first_b2_ready_date=_first_stage(timeline, SetupStage.B2_READY),
        first_b2_confirmed_date=_first_stage(
            timeline,
            SetupStage.B2_CONFIRMED,
        ),
        first_near_s1_date=_first_event(timeline, EventFlag.NEAR_S1),
        first_s1_breakout_date=_first_event(
            timeline,
            EventFlag.S1_BREAKOUT,
        ),
        first_s2_exhausted_date=_first_event(
            timeline,
            EventFlag.S2_EXHAUSTED,
        ),
        invalid_date=_first_stage(timeline, SetupStage.INVALID),
    )


def _setup_summaries(
    timeline: Sequence[ReplayTimelineItem],
) -> tuple[SetupSummary, ...]:
    setup_ids: list[str] = []
    grouped: dict[str, list[ReplayTimelineItem]] = {}
    for item in timeline:
        if item.anchor_snapshot is None:
            continue
        if item.setup_id not in grouped:
            setup_ids.append(item.setup_id)
            grouped[item.setup_id] = []
        grouped[item.setup_id].append(item)

    summaries: list[SetupSummary] = []
    for setup_index, setup_id in enumerate(setup_ids):
        items = tuple(grouped[setup_id])
        profiles = {item.score_profile for item in items}
        if len(profiles) != 1:
            raise ValueError(f"setup {setup_id} changed score profile")
        invalid_date = _first_stage(items, SetupStage.INVALID)
        if invalid_date is not None:
            closed_date = invalid_date
            termination_reason = SetupTerminationReason.INVALIDATED
        elif setup_index + 1 < len(setup_ids):
            next_setup_id = setup_ids[setup_index + 1]
            closed_date = grouped[next_setup_id][0].anchor_snapshot.anchor_date
            termination_reason = (
                SetupTerminationReason.SUPERSEDED_BY_NEW_ANCHOR
            )
        elif items[-1].trade_date < timeline[-1].trade_date:
            closed_date = next(
                item.trade_date
                for item in timeline
                if item.trade_date > items[-1].trade_date
            )
            termination_reason = SetupTerminationReason.EXPIRED
        else:
            closed_date = None
            termination_reason = SetupTerminationReason.ACTIVE
        summaries.append(
            SetupSummary(
                setup_id=setup_id,
                anchor_date=items[0].anchor_snapshot.anchor_date,
                score_profile=next(iter(profiles)),
                data_quality=_worst_quality(
                    tuple(item.data_quality for item in items)
                ),
                first_b1_date=_first_stage(items, SetupStage.B1_READY),
                first_b2_ready_date=_first_stage(items, SetupStage.B2_READY),
                first_b2_confirmed_date=_first_stage(
                    items,
                    SetupStage.B2_CONFIRMED,
                ),
                first_near_s1_date=_first_event(items, EventFlag.NEAR_S1),
                first_s1_breakout_date=_first_event(
                    items,
                    EventFlag.S1_BREAKOUT,
                ),
                first_s2_exhausted_date=_first_event(
                    items,
                    EventFlag.S2_EXHAUSTED,
                ),
                invalid_date=invalid_date,
                final_stage=items[-1].setup_stage,
                closed_date=closed_date,
                termination_reason=termination_reason,
            )
        )
    return tuple(summaries)


def replay_stock(
    *,
    code: str,
    start: date | None,
    as_of: date,
    lookback_calendar_days: int,
    config: StrategyConfig,
    daily_provider: DailyBarProvider,
    limit_pool_provider: LimitUpPoolProvider,
    clock: Callable[[], datetime] = _now_utc,
) -> ReplayOutput:
    """Replay one stock from oldest to newest without exposing future rows."""

    code = parse_instrument_code(code).normalized_code
    if lookback_calendar_days < 1:
        raise ValueError("lookback_calendar_days must be at least 1")
    if start is not None and start > as_of:
        raise ValueError("start cannot be after as_of")

    default_start = as_of - timedelta(days=lookback_calendar_days - 1)
    fetch_start = min(default_start, start) if start is not None else default_start
    daily_name, daily_version = _provider_metadata(daily_provider)
    pool_name, pool_version = _provider_metadata(limit_pool_provider)
    daily_result = daily_provider.fetch_daily_bars(
        DailyBarsRequest(
            codes=(code,),
            start_date=fetch_start,
            end_date=as_of,
        )
    )
    bars = tuple(sorted(
        (
            bar
            for bar in daily_result.bars
            if (
                bar.code == code
                and fetch_start <= bar.trade_date <= as_of
            )
        ),
        key=lambda item: item.trade_date,
    ))
    if not bars:
        raise ValueError(f"daily source returned no usable bars for {code}")
    if len({bar.trade_date for bar in bars}) != len(bars):
        raise ValueError("daily source returned duplicate trade dates")
    full_indicators = calculate_indicators(bars, config.indicators)

    candidate_pool_dates = tuple(sorted({
        bar.trade_date
        for bar in bars
        if (
            bar.trade_status
            and bar.is_st is not True
            and is_limit_close(bar, config)
        )
    }))
    pool_records: list[LimitUpRecord] = []
    pool_reports: list[DataSourceReport] = []
    pool_quality_by_date: dict[date, DataQuality] = {}
    pool_flags_by_date: dict[date, tuple[str, ...]] = {}
    for pool_date in candidate_pool_dates:
        result = limit_pool_provider.fetch_limit_up_pool(
            LimitUpPoolRequest(
                trade_date=pool_date,
                codes=(code,),
            )
        )
        pool_quality_by_date[pool_date] = result.quality
        pool_flags_by_date[pool_date] = result.quality_flags
        pool_records.extend(
            record
            for record in result.records
            if record.code == code and record.trade_date == pool_date
        )
        pool_reports.append(
            DataSourceReport(
                provider=pool_name,
                requested_start=pool_date,
                requested_end=pool_date,
                fetched_at=result.fetched_at,
                quality=result.quality,
                record_count=len(result.records),
                quality_flags=result.quality_flags,
                missing_fields=_missing_fields(result.quality_flags),
            )
        )
    pool_records.sort(key=lambda item: (item.trade_date, item.code))

    previous_signal: StrategySignal | None = None
    timeline: list[ReplayTimelineItem] = []
    all_timeline: list[ReplayTimelineItem] = []
    for index, current in enumerate(bars):
        bars_up_to_trade_date = SequencePrefixView(bars, 0, index + 1)
        pool_up_to_trade_date = tuple(
            record
            for record in pool_records
            if record.trade_date <= current.trade_date
        )
        signal = evaluate_strategy(
            bars=bars_up_to_trade_date,
            as_of=current.trade_date,
            config=config,
            generated_at=clock(),
            limit_pool=pool_up_to_trade_date,
            previous_signal=previous_signal,
            precomputed_indicators=full_indicators,
            indicator_end_index=index + 1,
        )
        daily_prefix_flags = tuple(
            flag
            for flag in daily_result.quality_flags
            if (
                (flag_date := _quality_flag_date(flag)) is None
                or flag_date <= current.trade_date
            )
        )
        relevant_source_qualities = [
            _daily_prefix_quality(daily_result.quality, daily_prefix_flags)
        ]
        relevant_source_flags = list(daily_prefix_flags)
        if signal.anchor is not None:
            anchor_pool_quality = pool_quality_by_date.get(
                signal.anchor.anchor_date
            )
            if anchor_pool_quality is not None:
                relevant_source_qualities.append(anchor_pool_quality)
                relevant_source_flags.extend(
                    pool_flags_by_date.get(signal.anchor.anchor_date, ())
                )
        signal = _merge_signal_quality(
            signal,
            relevant_source_qualities,
            source_flags=relevant_source_flags,
            insufficient_history=(
                len(bars_up_to_trade_date)
                < config.universe.minimum_listing_trade_days
            ),
        )
        timeline_item = _timeline_item(signal)
        all_timeline.append(timeline_item)
        if start is None or current.trade_date >= start:
            timeline.append(timeline_item)
        previous_signal = signal

    if not timeline:
        raise ValueError("no available trading dates fall on or after start")

    actual_last_bar_date = bars[-1].trade_date
    is_stale = actual_last_bar_date < as_of
    aggregate_flags: set[str] = set(daily_result.quality_flags)
    for report in pool_reports:
        aggregate_flags.update(
            f"{report.requested_start}:{flag}"
            for flag in report.quality_flags
        )
    source_qualities = [
        daily_result.quality,
        *(report.quality for report in pool_reports),
    ]
    replay_data_quality = _worst_quality(source_qualities)
    if len(bars) < config.universe.minimum_listing_trade_days:
        aggregate_flags.add("INSUFFICIENT_TRADING_HISTORY")
        replay_data_quality = DataQuality.UNUSABLE
    if is_stale:
        aggregate_flags.add("STALE_DATA")
        if (
            QUALITY_ORDER[replay_data_quality]
            < QUALITY_ORDER[DataQuality.DEGRADED]
        ):
            replay_data_quality = DataQuality.DEGRADED
    missing_fields = tuple(sorted({
        *_missing_fields(daily_result.quality_flags),
        *(
            field
            for report in pool_reports
            for field in report.missing_fields
        ),
    }))
    daily_report = DataSourceReport(
        provider=daily_name,
        requested_start=fetch_start,
        requested_end=as_of,
        fetched_at=daily_result.fetched_at,
        quality=daily_result.quality,
        record_count=len(bars),
        quality_flags=daily_result.quality_flags,
        missing_fields=_missing_fields(daily_result.quality_flags),
    )
    frozen_timeline = tuple(timeline)
    frozen_all_timeline = tuple(all_timeline)
    setup_summaries = _setup_summaries(frozen_all_timeline)
    current_setup_summary = (
        next(
            (
                summary
                for summary in reversed(setup_summaries)
                if summary.setup_id == frozen_all_timeline[-1].setup_id
            ),
            None,
        )
        if frozen_all_timeline[-1].anchor_snapshot is not None
        else None
    )
    return ReplayOutput(
        evaluation_mode=EvaluationMode.POINT_IN_TIME_REPLAY,
        code=code,
        requested_start=start,
        requested_as_of=as_of,
        actual_first_bar_date=bars[0].trade_date,
        actual_last_bar_date=actual_last_bar_date,
        lookback_calendar_days=lookback_calendar_days,
        is_stale=is_stale,
        daily_provider=daily_name,
        daily_provider_version=daily_version,
        limit_pool_provider=pool_name,
        limit_pool_provider_version=pool_version,
        used_limit_pool_dates=candidate_pool_dates,
        daily_data=daily_report,
        limit_pool_data=tuple(pool_reports),
        replay_data_quality=replay_data_quality,
        current_setup_data_quality=(
            current_setup_summary.data_quality
            if current_setup_summary is not None
            else None
        ),
        quality_flags=tuple(sorted(aggregate_flags)),
        missing_fields=missing_fields,
        transitions=_transition_summary(frozen_all_timeline),
        current_setup_summary=current_setup_summary,
        setup_summaries=setup_summaries,
        timeline=frozen_timeline,
    )
