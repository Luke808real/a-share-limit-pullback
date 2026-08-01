"""Pure post-close B-point preparation and next-day plan generation."""

from __future__ import annotations

import subprocess
from collections import Counter
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import (
    DataQuality,
    EntryRoomState,
    EventFlag,
    ExecutionLabel,
    SetupStage,
)
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.signal import StrategySignal
from limit_pullback.models.strategy import PriceCluster
from limit_pullback.models.trade_plan import TradePlan, TradePlanOutput
from limit_pullback.screen.canonical import CanonicalMarketData, load_canonical_market
from limit_pullback.screen.state import load_state, state_path
from limit_pullback.strategy.math import calculate_indicators
from limit_pullback.strategy.structure import (
    cluster_price_candidates,
    detect_anchor,
    generate_support_candidates,
    select_support_cluster,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.parquet import sha256_file


ZERO = Decimal("0")
ONE = Decimal("1")
RATIO_QUANTUM = Decimal("0.0001")


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip()


def _cluster_from_support(signal: StrategySignal) -> PriceCluster | None:
    if signal.support is None:
        return None
    return PriceCluster(
        low=signal.support.support_low,
        high=signal.support.support_high,
        center=signal.support.support_center,
        sources=signal.support.sources,
    )


def _computed_support(
    *,
    bars: Sequence[DailyBar],
    limit_pool: Sequence[LimitUpRecord],
    signal: StrategySignal,
    config: StrategyConfig,
    as_of: date,
) -> PriceCluster | None:
    existing = _cluster_from_support(signal)
    if existing is not None or signal.anchor is None:
        return existing
    anchor = detect_anchor(bars, as_of, config, limit_pool)
    if anchor is None:
        return None
    indicators = calculate_indicators(bars, config.indicators, as_of)
    candidates = generate_support_candidates(
        bars, indicators, anchor, as_of, config
    )
    return select_support_cluster(
        cluster_price_candidates(candidates, config.support.cluster_distance),
        bars[-1].close,
        config,
    )


def _anchor_bar(
    bars: Sequence[DailyBar], signal: StrategySignal
) -> DailyBar | None:
    if signal.anchor is None:
        return None
    return next(
        (bar for bar in bars if bar.trade_date == signal.anchor.anchor_date),
        None,
    )


def _volume_contracted(
    bars: Sequence[DailyBar],
    signal: StrategySignal,
    config: StrategyConfig,
) -> bool:
    anchor_bar = _anchor_bar(bars, signal)
    if anchor_bar is None or anchor_bar.volume <= ZERO:
        return False
    post_anchor = tuple(
        bar for bar in bars if bar.trade_date > anchor_bar.trade_date
    )
    if not post_anchor:
        return False
    current = bars[-1]
    current_contracted = (
        current.volume <= anchor_bar.volume * config.b1.volume_to_anchor_max
    )
    recent_days = config.b1.recent_volume_days
    if len(post_anchor) < recent_days or len(post_anchor) < 2:
        return False
    recent = post_anchor[-recent_days:]
    recent_average = sum((bar.volume for bar in recent), ZERO) / Decimal(
        len(recent)
    )
    post_anchor_max = max(bar.volume for bar in post_anchor)
    recent_contracted = (
        recent_average
        <= post_anchor_max * config.b1.recent_volume_to_post_anchor_max
    )
    return current_contracted and recent_contracted


def _near_support(
    current: DailyBar,
    support: PriceCluster | None,
    config: StrategyConfig,
) -> bool:
    if support is None or current.close < support.low:
        return False
    distance = (current.close - support.low) / support.low
    return distance <= config.events.support_warning.close_to_support_low_max


def _no_distribution_damage(
    bars: Sequence[DailyBar],
    signal: StrategySignal,
    config: StrategyConfig,
) -> bool:
    anchor_bar = _anchor_bar(bars, signal)
    if anchor_bar is None:
        return False
    indicators = calculate_indicators(bars, config.indicators, bars[-1].trade_date)
    recent_days = min(config.b1.recent_volume_days, len(indicators))
    recent_indicators = indicators[-recent_days:]
    recent_bars = bars[-recent_days:]
    return not any(
        indicator.kline.is_long_bearish and bar.volume >= anchor_bar.volume
        for indicator, bar in zip(recent_indicators, recent_bars, strict=True)
    )


def _ratio(value: Decimal) -> Decimal:
    return value.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP)


def _risk_reward_fields(
    *,
    entry: Decimal | None,
    invalid: Decimal | None,
    s1: Decimal | None,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if entry is None or invalid is None:
        return None, None, None
    risk = _ratio((entry - invalid) / entry)
    reward = _ratio((s1 - entry) / entry) if s1 is not None else None
    if s1 is None or s1 <= entry or entry <= invalid or risk <= ZERO:
        return risk, reward, None
    return risk, reward, _ratio(reward / risk)


def _prep_conditions(
    *,
    signal: StrategySignal,
    bars: Sequence[DailyBar],
    support: PriceCluster | None,
    config: StrategyConfig,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if signal.anchor is None:
        reasons.append("NO_VALID_ANCHOR")
    if signal.setup_stage not in {
        SetupStage.WATCH_PULLBACK,
        SetupStage.B1_READY,
    }:
        reasons.append("STRUCTURE_NOT_WATCH_OR_B1")
    if signal.setup_stage is SetupStage.INVALID:
        reasons.append("INVALID_SETUP")
    if signal.data_quality is DataQuality.UNUSABLE:
        reasons.append("DATA_QUALITY_UNUSABLE")
    if signal.event_flags & {
        EventFlag.S2_EXHAUSTED,
        EventFlag.S1_BREAKOUT,
    }:
        reasons.append("TERMINAL_PRESSURE_EVENT")
    if signal.entry_room_state is EntryRoomState.NONE:
        reasons.append("ENTRY_ROOM_NONE")
    if support is None:
        reasons.append("NO_RELIABLE_SUPPORT")
    elif not _near_support(bars[-1], support, config):
        reasons.append("PRICE_NOT_NEAR_SUPPORT")
    if not _volume_contracted(bars, signal, config):
        reasons.append("VOLUME_NOT_CONTRACTED")
    if not _no_distribution_damage(bars, signal, config):
        reasons.append("BEARISH_VOLUME_DAMAGE")
    return not reasons, tuple(sorted(set(reasons)))


def _cancel_conditions(
    signal: StrategySignal,
    *,
    prep_reasons: Sequence[str] = (),
) -> tuple[str, ...]:
    reasons = set(prep_reasons)
    if signal.setup_stage is SetupStage.INVALID:
        reasons.add("INVALID_SETUP")
    if EventFlag.S2_EXHAUSTED in signal.event_flags:
        reasons.add("S2_EXHAUSTED")
    if EventFlag.S1_BREAKOUT in signal.event_flags:
        reasons.add("S1_BREAKOUT_CONFIRMED")
    if signal.data_quality is DataQuality.UNUSABLE:
        reasons.add("DATA_QUALITY_UNUSABLE")
    if signal.entry_room_state is EntryRoomState.NONE:
        reasons.add("ENTRY_ROOM_NONE")
    return tuple(sorted(reasons))


def build_trade_plan(
    *,
    signal: StrategySignal,
    bars: Sequence[DailyBar],
    limit_pool: Sequence[LimitUpRecord],
    config: StrategyConfig,
    plan_date: date,
    for_trade_date: date,
    snapshot_id: str,
    strategy_commit: str,
    config_hash: str,
) -> TradePlan:
    """Build one plan using only bars and pool records at or before T."""

    ordered = tuple(sorted(
        (bar for bar in bars if bar.trade_date <= plan_date),
        key=lambda bar: bar.trade_date,
    ))
    if not ordered or ordered[-1].trade_date != plan_date:
        raise ValueError("trade plan requires a bar exactly on plan_date")
    current = ordered[-1]
    support = _computed_support(
        bars=ordered,
        limit_pool=tuple(record for record in limit_pool if record.trade_date <= plan_date),
        signal=signal,
        config=config,
        as_of=plan_date,
    )
    prep_ok, prep_reasons = _prep_conditions(
        signal=signal,
        bars=ordered,
        support=support,
        config=config,
    )

    if signal.setup_stage is SetupStage.WATCH_PULLBACK:
        label = ExecutionLabel.B1_PREP if prep_ok else ExecutionLabel.WATCH_ONLY
        actionable = prep_ok
    elif signal.setup_stage is SetupStage.B1_READY:
        label = ExecutionLabel.B1_READY
        actionable = signal.is_entry_candidate
    elif signal.setup_stage is SetupStage.B2_READY:
        label = ExecutionLabel.B2_READY
        actionable = signal.is_entry_candidate
    elif signal.setup_stage is SetupStage.B2_CONFIRMED:
        label = ExecutionLabel.B2_CONFIRMED
        actionable = signal.is_entry_candidate
    else:
        label = ExecutionLabel.WATCH_ONLY
        actionable = False

    if label is ExecutionLabel.B1_PREP:
        support_low = support.low if support is not None else None
        support_high = support.high if support is not None else None
        preferred = support.center if support is not None else None
        invalid = (
            (support.low * (ONE - config.support.invalid_buffer)).quantize(
                config.anchor.price_tick, rounding=ROUND_HALF_UP
            )
            if support is not None
            else None
        )
        entry_room = EntryRoomState.OPEN_SPACE
        s1 = None
        trigger = None
    elif signal.setup_stage is SetupStage.B1_READY:
        support_low = signal.support.support_low if signal.support else None
        support_high = signal.support.support_high if signal.support else None
        preferred = signal.entry_reference_price
        invalid = signal.invalid_price
        entry_room = signal.entry_room_state
        s1 = signal.target_s1.s1_low if signal.target_s1 else None
        trigger = None
    elif signal.setup_stage in {SetupStage.B2_READY, SetupStage.B2_CONFIRMED}:
        trigger = (
            signal.b2_trigger.trigger_price if signal.b2_trigger else None
        )
        preferred = (
            current.close
            if signal.setup_stage is SetupStage.B2_CONFIRMED
            else trigger
        )
        support_low = signal.support.support_low if signal.support else None
        support_high = signal.support.support_high if signal.support else None
        invalid = signal.invalid_price
        entry_room = signal.entry_room_state
        s1 = signal.target_s1.s1_low if signal.target_s1 else None
    else:
        support_low = support.low if support is not None else None
        support_high = support.high if support is not None else None
        preferred = None
        invalid = signal.invalid_price
        entry_room = None
        s1 = signal.target_s1.s1_low if signal.target_s1 else None
        trigger = None

    risk_pct, reward_pct, rr = _risk_reward_fields(
        entry=preferred,
        invalid=invalid,
        s1=s1,
    )
    return TradePlan(
        code=signal.code,
        plan_date=plan_date,
        for_trade_date=for_trade_date,
        setup_stage=signal.setup_stage,
        execution_label=label,
        anchor_date=signal.anchor.anchor_date if signal.anchor else None,
        anchor_price=signal.anchor.anchor_price if signal.anchor else None,
        buy_zone_low=support_low,
        buy_zone_high=support_high,
        preferred_entry=preferred,
        trigger_price=trigger,
        support_price=(support.center if label is ExecutionLabel.B1_PREP and support else
                       signal.support.support_center if signal.support else None),
        invalid_price=invalid,
        s1_price=s1,
        s2_price=None,
        entry_room_state=entry_room,
        risk_pct=risk_pct,
        reward_pct=reward_pct,
        rr=rr,
        setup_quality_score=signal.setup_quality_score,
        entry_quality_score=signal.entry_quality_score,
        data_quality=signal.data_quality,
        quality_flags=signal.quality_flags,
        is_actionable=actionable,
        cancel_conditions=_cancel_conditions(
            signal,
            prep_reasons=(
                prep_reasons
                if label in {ExecutionLabel.B1_PREP, ExecutionLabel.WATCH_ONLY}
                else ()
            ),
        ),
        snapshot_id=snapshot_id,
        strategy_commit=strategy_commit,
        config_hash=config_hash,
    )


def _sort_key(plan: TradePlan) -> tuple[object, ...]:
    label_priority = {
        ExecutionLabel.B1_PREP: 0,
        ExecutionLabel.B1_READY: 1,
        ExecutionLabel.B2_READY: 2,
        ExecutionLabel.B2_CONFIRMED: 3,
        ExecutionLabel.WATCH_ONLY: 4,
    }
    entry_distance = (
        abs(plan.preferred_entry - plan.support_price) / plan.support_price
        if plan.preferred_entry is not None and plan.support_price
        else Decimal("999999")
    )
    return (
        0 if plan.is_actionable else 1,
        label_priority[plan.execution_label],
        -plan.setup_quality_score,
        -(plan.entry_quality_score or ZERO),
        -(plan.rr or Decimal("-1")),
        entry_distance,
        plan.code,
    )


def build_trade_plan_output(
    *,
    layout: WarehouseLayout,
    as_of: date,
    snapshot_id: str,
    config: StrategyConfig,
    config_hash: str,
    strategy_commit: str | None = None,
) -> TradePlanOutput:
    """Build the latest cross-section from persisted screen states."""

    market: CanonicalMarketData = load_canonical_market(
        layout, snapshot_id=snapshot_id
    )
    if market.snapshot.as_of < as_of:
        raise ValueError(
            f"SNAPSHOT_AS_OF_BEFORE_REQUESTED: {market.snapshot.as_of} < {as_of}"
        )
    commit = strategy_commit or _git_head()
    plans: list[TradePlan] = []
    reject_counts: Counter[str] = Counter()
    watch_count = b1_prep_count = b1_ready_count = 0
    b2_ready_count = b2_confirmed_count = actionable_count = 0
    entry_room_none = invalid_count = 0
    for code in market.universe:
        state = load_state(state_path(layout.root, code))
        if state is None or state.snapshot_id != snapshot_id or state.last_processed_date != as_of:
            reject_counts["STALE_OR_MISSING_SCREEN_STATE"] += 1
            continue
        signal = StrategySignal.model_validate_json(state.signal_json)
        bars = market.bars_by_code.get(code, ())
        code_pool = tuple(record for record in market.pool_records if record.code == code)
        plan = build_trade_plan(
            signal=signal,
            bars=bars,
            limit_pool=code_pool,
            config=config,
            plan_date=as_of,
            for_trade_date=as_of + timedelta(days=1),
            snapshot_id=snapshot_id,
            strategy_commit=commit,
            config_hash=config_hash,
        )
        if signal.setup_stage is SetupStage.WATCH_PULLBACK:
            watch_count += 1
        elif signal.setup_stage is SetupStage.B1_READY:
            b1_ready_count += 1
        elif signal.setup_stage is SetupStage.B2_READY:
            b2_ready_count += 1
        elif signal.setup_stage is SetupStage.B2_CONFIRMED:
            b2_confirmed_count += 1
        if plan.execution_label is ExecutionLabel.B1_PREP:
            b1_prep_count += 1
        if signal.entry_room_state is EntryRoomState.NONE:
            entry_room_none += 1
            reject_counts["ENTRY_ROOM_NONE"] += 1
        if signal.setup_stage is SetupStage.INVALID:
            invalid_count += 1
            reject_counts["INVALID"] += 1
        if signal.data_quality is DataQuality.UNUSABLE:
            reject_counts["DATA_QUALITY_UNUSABLE"] += 1
        if EventFlag.S2_EXHAUSTED in signal.event_flags:
            reject_counts["S2_EXHAUSTED"] += 1
        if EventFlag.S1_BREAKOUT in signal.event_flags:
            reject_counts["S1_BREAKOUT"] += 1
        if plan.is_actionable:
            actionable_count += 1
        include = (
            signal.setup_stage is SetupStage.WATCH_PULLBACK
            or plan.is_actionable
        )
        if include:
            plans.append(plan)
    plans.sort(key=_sort_key)
    top_candidates = tuple(plans[:20])
    return TradePlanOutput(
        plan_date=as_of,
        for_trade_date=as_of + timedelta(days=1),
        snapshot_id=snapshot_id,
        strategy_commit=commit,
        config_hash=config_hash,
        universe=len(market.universe),
        watch_count=watch_count,
        b1_prep_count=b1_prep_count,
        b1_ready_count=b1_ready_count,
        b2_ready_count=b2_ready_count,
        b2_confirmed_count=b2_confirmed_count,
        actionable_count=actionable_count,
        entry_room_none_reject_count=entry_room_none,
        invalid_reject_count=invalid_count,
        reject_counts=dict(sorted(reject_counts.items())),
        plans=tuple(plans),
        top_candidates=top_candidates,
    )
