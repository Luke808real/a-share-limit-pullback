from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from limit_pullback.config import load_strategy_config
from limit_pullback.models.enums import (
    DataQuality,
    EventFlag,
    PatternType,
    SetupStage,
    SetupTerminationReason,
)
from limit_pullback.models.market import DailyBarsResult, LimitUpPoolResult
from limit_pullback.models.signal import SupportSnapshot
from limit_pullback.models.strategy import PriceCluster
from limit_pullback.replay import replay_stock
from limit_pullback.strategy.engine import _evaluate_invalid_reasons
from limit_pullback.strategy.math import calculate_indicators
from limit_pullback.strategy.structure import detect_anchor
from tests.synthetic_data import (
    append_b2_confirm_bar,
    append_b2_ready_bar,
    append_invalid_bar,
    append_pullback_bars,
    base_setup_bars,
    business_dates,
    full_limit_pool,
    make_bar,
)


GENERATED_AT = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)


class SyntheticDailyProvider:
    provider_name = "SYNTHETIC_DAILY"
    provider_version = "1"

    def __init__(self, bars, quality=DataQuality.OK):
        self.bars = tuple(bars)
        self.quality = quality
        self.request = None

    def fetch_daily_bars(self, request):
        self.request = request
        return DailyBarsResult(
            bars=self.bars,
            quality=self.quality,
            fetched_at=GENERATED_AT,
        )


class SyntheticPoolProvider:
    provider_name = "SYNTHETIC_POOL"
    provider_version = "1"

    def __init__(self, records):
        self.records = tuple(records)
        self.requests = []

    def fetch_limit_up_pool(self, request):
        self.requests.append(request)
        records = tuple(
            record
            for record in self.records
            if (
                record.trade_date == request.trade_date
                and (not request.codes or record.code in request.codes)
            )
        )
        return LimitUpPoolResult(
            trade_date=request.trade_date,
            records=records,
            quality=DataQuality.OK,
            fetched_at=GENERATED_AT,
        )


def _config(project_root):
    return load_strategy_config(project_root / "config" / "strategy.yaml")


def _replay(project_root, bars, *, as_of=None, records=None):
    return replay_stock(
        code=bars[0].code,
        start=None,
        as_of=as_of or bars[-1].trade_date,
        lookback_calendar_days=1000,
        config=_config(project_root),
        daily_provider=SyntheticDailyProvider(bars),
        limit_pool_provider=SyntheticPoolProvider(
            records if records is not None else full_limit_pool(bars)
        ),
        clock=lambda: GENERATED_AT,
    )


def _first(output, stage):
    return next(item for item in output.timeline if item.setup_stage is stage)


def test_anchor_and_first_b1_do_not_use_same_day_structure(project_root):
    bars = append_pullback_bars(base_setup_bars())
    output = _replay(project_root, bars)
    anchor = _first(output, SetupStage.LIMIT_ANCHOR)
    b1 = _first(output, SetupStage.B1_READY)

    assert anchor.event_flags == ()
    assert anchor.support_snapshot is None
    assert anchor.invalid_price_snapshot is None
    assert anchor.target_s1 is None
    assert b1.support_snapshot is not None
    assert b1.invalid_price_snapshot is not None
    assert b1.target_s1 is not None
    assert b1.support_snapshot.frozen_as_of == b1.trade_date
    assert b1.support_snapshot.eligible_from > b1.trade_date
    assert b1.invalid_price_snapshot.eligible_from > b1.trade_date
    assert b1.target_s1.eligible_from > b1.trade_date
    assert b1.event_flags == ()
    assert b1.setup_stage is not SetupStage.INVALID


def test_structure_snapshots_become_usable_on_next_trading_day(project_root):
    bars = append_pullback_bars(base_setup_bars())
    output = _replay(project_root, bars)
    b1 = _first(output, SetupStage.B1_READY)
    b1_index = output.timeline.index(b1)
    following = output.timeline[b1_index + 1]

    assert b1.support_snapshot.eligible_from <= following.trade_date
    assert b1.target_s1.eligible_from <= following.trade_date
    assert b1.invalid_price_snapshot.eligible_from <= following.trade_date
    assert following.support_snapshot == b1.support_snapshot
    assert following.target_s1 == b1.target_s1
    assert EventFlag.SUPPORT_WARNING in following.event_flags
    assert EventFlag.NEAR_S1 not in following.event_flags


def test_failed_recovery_requires_support_eligible_on_previous_day(project_root):
    config = _config(project_root)
    bars = base_setup_bars()
    first_date, current_date = business_dates(
        bars[-1].trade_date + timedelta(days=1),
        2,
    )
    bars.append(
        make_bar(
            first_date,
            open_price="10.95",
            high="11.00",
            low="10.85",
            close="10.90",
            preclose="11.00",
            volume="400",
        )
    )
    bars.append(
        make_bar(
            current_date,
            open_price="10.92",
            high="11.02",
            low="10.90",
            close="10.98",
            preclose="10.90",
            volume="350",
        )
    )
    indicators = calculate_indicators(bars, config.indicators, current_date)
    anchor = detect_anchor(
        bars,
        current_date,
        config,
        full_limit_pool(bars),
    )
    support_snapshot = SupportSnapshot(
        support_low=Decimal("11.00"),
        support_high=Decimal("11.00"),
        support_center=Decimal("11.00"),
        sources=("ANCHOR_PRICE",),
        frozen_as_of=first_date,
        eligible_from=current_date,
        reference_close=Decimal("11.00"),
        max_above_reference_close=Decimal("0.002"),
    )

    reasons = _evaluate_invalid_reasons(
        ordered=bars,
        indicators=indicators,
        current=bars[-1],
        anchor=anchor,
        support=PriceCluster(
            low=Decimal("11.00"),
            high=Decimal("11.00"),
            center=Decimal("11.00"),
            sources=("ANCHOR_PRICE",),
        ),
        support_snapshot=support_snapshot,
        invalid_price=Decimal("10.95"),
        config=config,
    )

    assert "FAILED_SUPPORT_RECOVERY" not in reasons


def test_replay_advances_b1_b2_and_reuses_frozen_snapshots(project_root):
    bars = append_pullback_bars(base_setup_bars())
    append_b2_ready_bar(bars)
    append_b2_confirm_bar(bars)

    output = _replay(project_root, bars)
    b1 = _first(output, SetupStage.B1_READY)
    ready = _first(output, SetupStage.B2_READY)
    confirmed = _first(output, SetupStage.B2_CONFIRMED)
    b1_index = output.timeline.index(b1)

    assert output.timeline[b1_index + 1].setup_stage is SetupStage.B2_READY
    assert ready.b2_trigger_snapshot is not None
    assert ready.b2_trigger_snapshot.frozen_as_of == ready.trade_date
    assert ready.b2_trigger_snapshot.eligible_from > ready.trade_date
    assert confirmed.trade_date > ready.trade_date
    assert confirmed.b2_trigger_snapshot == ready.b2_trigger_snapshot
    confirmed_bar = next(
        bar for bar in bars if bar.trade_date == confirmed.trade_date
    )
    assert confirmed_bar.close >= confirmed.b2_trigger_snapshot.trigger_price
    assert b1.anchor_snapshot == ready.anchor_snapshot == confirmed.anchor_snapshot
    assert b1.support_snapshot == ready.support_snapshot == confirmed.support_snapshot
    assert b1.target_s1 == ready.target_s1 == confirmed.target_s1
    assert (
        b1.initial_invalid_price
        == ready.initial_invalid_price
        == confirmed.initial_invalid_price
    )
    assert ready.setup_stage is not SetupStage.B2_CONFIRMED


def test_replay_invalid_is_terminal_until_a_new_setup(project_root):
    bars = append_pullback_bars(base_setup_bars())
    append_invalid_bar(bars)
    invalid_date = bars[-1].trade_date
    rebound_date = business_dates(invalid_date + timedelta(days=1), 1)[0]
    bars.append(
        make_bar(
            rebound_date,
            open_price="10.45",
            high="10.95",
            low="10.40",
            close="10.90",
            preclose="10.40",
            volume="600",
        )
    )
    new_anchor_date = business_dates(rebound_date + timedelta(days=1), 1)[0]
    bars.append(
        make_bar(
            new_anchor_date,
            open_price="10.85",
            high="11.99",
            low="10.80",
            close="11.99",
            preclose="10.90",
            volume="1200",
        )
    )

    output = _replay(project_root, bars)
    invalid = next(
        item for item in output.timeline if item.trade_date == invalid_date
    )
    rebound = next(
        item for item in output.timeline if item.trade_date == rebound_date
    )
    new_anchor = next(
        item for item in output.timeline if item.trade_date == new_anchor_date
    )

    assert invalid.setup_stage is SetupStage.INVALID
    assert rebound.setup_stage is SetupStage.INVALID
    assert rebound.setup_id == invalid.setup_id
    assert new_anchor.setup_stage is SetupStage.LIMIT_ANCHOR
    assert new_anchor.setup_id != invalid.setup_id
    assert new_anchor.anchor_snapshot.anchor_date == new_anchor_date


def test_replay_invalid_prices_never_loosen_within_setup(project_root):
    bars = append_pullback_bars(base_setup_bars())
    append_b2_ready_bar(bars)
    append_invalid_bar(bars)
    output = _replay(project_root, bars)
    setup_items = tuple(
        item
        for item in output.timeline
        if (
            item.setup_stage
            in {
                SetupStage.B1_READY,
                SetupStage.B2_READY,
                SetupStage.B2_CONFIRMED,
                SetupStage.INVALID,
            }
            and item.initial_invalid_price is not None
        )
    )

    assert len({item.initial_invalid_price for item in setup_items}) == 1
    invalid_prices = tuple(item.invalid_price for item in setup_items)
    assert invalid_prices == tuple(sorted(invalid_prices))


def test_replay_timeline_before_t_is_unchanged_by_future_prices(project_root):
    bars = append_pullback_bars(base_setup_bars())
    cutoff = bars[-1].trade_date
    first = _replay(project_root, bars)

    future_a = list(bars)
    append_b2_ready_bar(future_a)
    append_b2_confirm_bar(future_a)
    second = _replay(project_root, future_a)

    future_b = list(future_a)
    future_b[-1] = future_b[-1].model_copy(
        update={
            "open": Decimal("10.90"),
            "high": Decimal("11.00"),
            "low": Decimal("10.70"),
            "close": Decimal("10.80"),
            "volume": Decimal("250"),
            "amount": Decimal("2700"),
        }
    )
    third = _replay(project_root, future_b)

    expected = tuple(item.model_dump_json() for item in first.timeline)
    assert tuple(
        item.model_dump_json()
        for item in second.timeline
        if item.trade_date <= cutoff
    ) == expected
    assert tuple(
        item.model_dump_json()
        for item in third.timeline
        if item.trade_date <= cutoff
    ) == expected


def test_future_bars_do_not_change_historical_s1_or_entry_room(project_root):
    bars = append_pullback_bars(base_setup_bars())
    cutoff = bars[-1].trade_date
    baseline = _replay(project_root, bars)
    extended_bars = list(bars)
    append_b2_ready_bar(extended_bars)
    extended_bars[-1] = extended_bars[-1].model_copy(
        update={"high": Decimal("99.99")}
    )
    extended = _replay(project_root, extended_bars)

    def frozen_values(output):
        return tuple(
            (
                item.trade_date,
                item.immediate_resistance,
                item.target_s1,
                item.resistance_candidates,
                item.entry_reference_price,
                item.entry_headroom_pct,
                item.entry_room_state,
            )
            for item in output.timeline
            if item.trade_date <= cutoff
        )

    assert frozen_values(extended) == frozen_values(baseline)


def test_replay_explains_events_and_both_patterns(project_root):
    bars = append_pullback_bars(base_setup_bars())
    output = _replay(project_root, bars)
    warning = next(
        item
        for item in output.timeline
        if EventFlag.SUPPORT_WARNING in item.event_flags
    )
    b1 = _first(output, SetupStage.B1_READY)

    assert warning.event_reasons[EventFlag.SUPPORT_WARNING]
    assert set(b1.pattern_scores) == {
        PatternType.AIR_REFUEL,
        PatternType.BEARISH_PULLBACK,
    }
    assert set(b1.pattern_conditions) == set(b1.pattern_scores)
    for conditions in b1.pattern_conditions.values():
        assert (
            conditions.matched
            or conditions.failed
            or conditions.unavailable
        )
    assert b1.primary_pattern_reason


def test_replay_marks_stale_data_explicitly(project_root):
    bars = append_pullback_bars(base_setup_bars())
    requested_as_of = bars[-1].trade_date + timedelta(days=3)

    output = _replay(project_root, bars, as_of=requested_as_of)

    assert output.requested_as_of == requested_as_of
    assert output.actual_last_bar_date == bars[-1].trade_date
    assert output.is_stale
    assert "STALE_DATA" in output.quality_flags
    assert output.replay_data_quality is DataQuality.DEGRADED


def test_replay_metadata_lists_every_requested_pool_date(project_root):
    bars = append_pullback_bars(base_setup_bars())
    pool = SyntheticPoolProvider(full_limit_pool(bars))

    output = replay_stock(
        code="600000",
        start=None,
        as_of=bars[-1].trade_date,
        lookback_calendar_days=1000,
        config=_config(project_root),
        daily_provider=SyntheticDailyProvider(bars),
        limit_pool_provider=pool,
        clock=lambda: GENERATED_AT,
    )

    requested_dates = tuple(request.trade_date for request in pool.requests)
    assert output.used_limit_pool_dates == requested_dates
    assert len(output.limit_pool_data) == len(requested_dates)
    assert output.daily_provider == "SYNTHETIC_DAILY"
    assert output.daily_provider_version == "1"
    assert output.limit_pool_provider == "SYNTHETIC_POOL"
    assert output.limit_pool_provider_version == "1"


def test_setup_summaries_do_not_mix_lifecycle_dates(project_root):
    bars = append_pullback_bars(base_setup_bars())
    append_invalid_bar(bars)
    invalid_date = bars[-1].trade_date
    rebound_date, new_anchor_date = business_dates(
        invalid_date + timedelta(days=1),
        2,
    )
    bars.append(
        make_bar(
            rebound_date,
            open_price="10.45",
            high="10.95",
            low="10.40",
            close="10.90",
            preclose="10.40",
            volume="600",
        )
    )
    bars.append(
        make_bar(
            new_anchor_date,
            open_price="10.85",
            high="11.99",
            low="10.80",
            close="11.99",
            preclose="10.90",
            volume="1200",
        )
    )

    output = _replay(project_root, bars)
    assert len(output.setup_summaries) >= 2
    old_summary = output.setup_summaries[-2]
    current = output.current_setup_summary

    assert old_summary.invalid_date == invalid_date
    assert old_summary.closed_date == invalid_date
    assert (
        old_summary.termination_reason
        is SetupTerminationReason.INVALIDATED
    )
    assert current.anchor_date == new_anchor_date
    assert current.first_b1_date is None
    assert current.first_b2_ready_date is None
    assert current.invalid_date is None
    assert current.final_stage is SetupStage.LIMIT_ANCHOR
    assert current.termination_reason is SetupTerminationReason.ACTIVE


def test_new_anchor_supersedes_active_setup(project_root):
    bars = append_pullback_bars(base_setup_bars())
    old_anchor_date = bars[130].trade_date
    new_anchor_date = business_dates(
        bars[-1].trade_date + timedelta(days=1),
        1,
    )[0]
    bars.append(
        make_bar(
            new_anchor_date,
            open_price="10.95",
            high="12.08",
            low="10.90",
            close="12.08",
            preclose="10.98",
            volume="1200",
        )
    )

    output = _replay(project_root, bars)
    old_summary = next(
        summary
        for summary in output.setup_summaries
        if summary.anchor_date == old_anchor_date
    )

    assert (
        old_summary.termination_reason
        is SetupTerminationReason.SUPERSEDED_BY_NEW_ANCHOR
    )
    assert old_summary.closed_date == new_anchor_date
    assert (
        output.current_setup_summary.termination_reason
        is SetupTerminationReason.ACTIVE
    )


def test_setup_expires_when_anchor_leaves_lookback(project_root):
    bars = append_pullback_bars(base_setup_bars())
    for trade_date in business_dates(
        bars[-1].trade_date + timedelta(days=1),
        12,
    ):
        previous_close = bars[-1].close
        bars.append(
            make_bar(
                trade_date,
                open_price="11.00",
                high="11.05",
                low="10.98",
                close="11.01",
                preclose=str(previous_close),
                volume="300",
            )
        )

    output = _replay(project_root, bars)
    old_summary = output.setup_summaries[-1]

    assert old_summary.termination_reason is SetupTerminationReason.EXPIRED
    assert old_summary.closed_date is not None
    assert old_summary.closed_date > old_summary.anchor_date


def test_replay_and_current_setup_quality_are_separate(project_root):
    bars = append_pullback_bars(base_setup_bars())
    new_anchor_date = business_dates(
        bars[-1].trade_date + timedelta(days=1),
        1,
    )[0]
    bars.append(
        make_bar(
            new_anchor_date,
            open_price="10.95",
            high="12.08",
            low="10.90",
            close="12.08",
            preclose="10.98",
            volume="1200",
        )
    )
    new_record = full_limit_pool(bars)[0].model_copy(
        update={
            "trade_date": new_anchor_date,
            "limit_price": Decimal("12.08"),
        }
    )

    class MixedQualityPoolProvider(SyntheticPoolProvider):
        def fetch_limit_up_pool(self, request):
            self.requests.append(request)
            records = tuple(
                record
                for record in self.records
                if record.trade_date == request.trade_date
            )
            return LimitUpPoolResult(
                trade_date=request.trade_date,
                records=records,
                quality=(
                    DataQuality.OK if records else DataQuality.PARTIAL
                ),
                quality_flags=(
                    () if records
                    else (f"CODE_NOT_IN_LIMIT_POOL:{request.codes[0]}",)
                ),
                fetched_at=GENERATED_AT,
            )

    output = replay_stock(
        code="600000",
        start=None,
        as_of=new_anchor_date,
        lookback_calendar_days=1000,
        config=_config(project_root),
        daily_provider=SyntheticDailyProvider(bars),
        limit_pool_provider=MixedQualityPoolProvider((new_record,)),
        clock=lambda: GENERATED_AT,
    )

    assert output.replay_data_quality is DataQuality.PARTIAL
    assert output.setup_summaries[-2].data_quality is DataQuality.PARTIAL
    assert output.current_setup_summary.score_profile.value == "FULL"
    assert output.current_setup_data_quality is DataQuality.OK
    assert output.current_setup_summary.data_quality is DataQuality.OK
