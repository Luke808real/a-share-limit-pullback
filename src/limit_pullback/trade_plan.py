"""Pure post-close B-point preparation and next-day plan generation."""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from collections.abc import Sequence
from datetime import date, time
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import (
    DataQuality,
    EntryRoomState,
    EventFlag,
    ExecutionLabel,
    SetupStage,
)
from limit_pullback.models.signal import StrategySignal
from limit_pullback.models.strategy import PriceCluster
from limit_pullback.models.trade_plan import (
    TradePlan,
    TradePlanConfig,
    TradePlanOutput,
)
from limit_pullback.screen.state import load_state, state_path
from limit_pullback.screen.runner import _bars_prefix_hash, _digest
from limit_pullback.screen.models import ScreenState
from limit_pullback.strategy.math import calculate_indicators
from limit_pullback.strategy.structure import (
    cluster_price_candidates,
    detect_anchor,
    generate_support_candidates,
    select_support_cluster,
)
from limit_pullback.screen.canonical import FIXED_FETCHED_AT
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata


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


@lru_cache(maxsize=16)
def _is_ancestor(candidate: str, current: str) -> bool:
    """Accept state commits from this branch's existing history only."""

    if candidate == current:
        return True
    if not candidate or not current or current == "unknown":
        return False
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", candidate, current],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return False
    return result.returncode == 0


def _pool_prefix_hash_from_rows(
    rows: Sequence[dict[str, object]],
    up_to: date,
) -> str:
    """Match ``screen.runner._pool_prefix_hash`` without model materialization."""

    prefix = [
        (
            str(row["code"]),
            row["trade_date"].isoformat(),
            str(row.get("reconciliation_status", "PROVISIONAL")),
            str(row["limit_price"]),
            str(row["name"]),
        )
        for row in rows
        if row["trade_date"] <= up_to
    ]
    return _digest(json.dumps(prefix, sort_keys=True))


def _next_open_session(
    as_of: date,
    trade_calendar: Sequence[date] | None,
) -> date | None:
    """Resolve a known next session without guessing weekends or holidays."""

    if not trade_calendar:
        return None
    future_dates = sorted({value for value in trade_calendar if value > as_of})
    return future_dates[0] if future_dates else None


def _state_provenance_valid(
    *,
    code: str,
    state: ScreenState,
    signal: StrategySignal,
    snapshot_id: str,
    as_of: date,
    reconciliation_policy_version: str,
    config_hash: str,
    current_commit: str,
) -> bool:
    """Guard plan generation against stale, cross-code, or mixed states."""

    return (
        state.code == code
        and state.snapshot_id == snapshot_id
        and state.last_processed_date == as_of
        and state.setup_id == signal.setup_id
        and signal.code == code
        and signal.trade_date == as_of
        and state.reconciliation_policy_version == reconciliation_policy_version
        and state.config_hash == config_hash
        and _is_ancestor(state.strategy_commit, current_commit)
    )


def _execution_config(
    strategy_config: StrategyConfig,
    trade_plan_config: TradePlanConfig | None,
) -> TradePlanConfig:
    if trade_plan_config is not None:
        return trade_plan_config
    return TradePlanConfig(
        prep_support_distance_max=strategy_config.b1.prep_support_distance_max,
        prep_volume_to_anchor_max=strategy_config.b1.prep_volume_to_anchor_max,
        prep_volume_to_post_anchor_max=(
            strategy_config.b1.prep_volume_to_post_anchor_max
        ),
    )


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


def _prep_volume_metrics(
    bars: Sequence[DailyBar],
    signal: StrategySignal,
    config: StrategyConfig,
    trade_plan_config: TradePlanConfig,
) -> tuple[bool, Decimal | None]:
    """Return execution-layer contraction and recent-average/anchor ratio.

    B1_PREP intentionally permits a one- or two-day pullback sample. The
    frozen B1 structure check above retains its original minimum history.
    """

    anchor_bar = _anchor_bar(bars, signal)
    if anchor_bar is None or anchor_bar.volume <= ZERO:
        return False, None
    post_anchor = tuple(
        bar for bar in bars if bar.trade_date > anchor_bar.trade_date
    )
    if not post_anchor:
        return False, None
    recent_days = min(config.b1.recent_volume_days, len(post_anchor))
    recent = post_anchor[-recent_days:]
    recent_average = sum((bar.volume for bar in recent), ZERO) / Decimal(
        len(recent)
    )
    post_anchor_max = max(bar.volume for bar in post_anchor)
    anchor_limit = anchor_bar.volume * trade_plan_config.prep_volume_to_anchor_max
    contracted = (
        bars[-1].volume <= anchor_limit
        and recent_average <= anchor_limit
        and recent_average
        <= post_anchor_max * trade_plan_config.prep_volume_to_post_anchor_max
    )
    return contracted, recent_average / anchor_bar.volume


def _near_support(
    current: DailyBar,
    support: PriceCluster | None,
    trade_plan_config: TradePlanConfig,
) -> bool:
    if support is None or current.close < support.low:
        return False
    distance = (current.close - support.low) / support.low
    return distance <= trade_plan_config.prep_support_distance_max


def _distance_to_support_pct(
    current: DailyBar,
    support: PriceCluster | None,
) -> Decimal | None:
    if support is None or support.low <= ZERO:
        return None
    return (current.close - support.low) / support.low


def _days_since_anchor(
    bars: Sequence[DailyBar], signal: StrategySignal
) -> int | None:
    anchor_bar = _anchor_bar(bars, signal)
    if anchor_bar is None:
        return None
    return sum(bar.trade_date > anchor_bar.trade_date for bar in bars)


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
    trade_plan_config: TradePlanConfig,
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
    days_since_anchor = _days_since_anchor(bars, signal)
    if days_since_anchor is None:
        reasons.append("NO_VALID_ANCHOR")
    elif not (
        config.b1.days_after_anchor_min
        <= days_since_anchor
        <= config.b1.days_after_anchor_max
    ):
        reasons.append("OUTSIDE_PULLBACK_WINDOW")
    if signal.data_quality is DataQuality.UNUSABLE:
        reasons.append("DATA_QUALITY_UNUSABLE")
    if EventFlag.S2_EXHAUSTED in signal.event_flags:
        reasons.append("S2_EXHAUSTED")
    if EventFlag.S1_BREAKOUT in signal.event_flags:
        reasons.append("S1_BREAKOUT")
    if signal.entry_room_state is EntryRoomState.NONE:
        reasons.append("ENTRY_ROOM_NONE")
    if support is None:
        reasons.append("NO_RELIABLE_SUPPORT")
    elif not _near_support(bars[-1], support, trade_plan_config):
        reasons.append("PRICE_NOT_NEAR_SUPPORT")
    if not _prep_volume_metrics(bars, signal, config, trade_plan_config)[0]:
        reasons.append("VOLUME_NOT_CONTRACTED")
    if not _no_distribution_damage(bars, signal, config):
        reasons.append("BEARISH_VOLUME_DAMAGE")
    return not reasons, tuple(sorted(set(reasons)))


def _cancel_conditions(
    signal: StrategySignal,
    *,
    prep_reasons: Sequence[str] = (),
    extra_reasons: Sequence[str] = (),
) -> tuple[str, ...]:
    reasons = set(prep_reasons) | set(extra_reasons)
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


def _preferred_in_buy_zone(
    entry_reference: Decimal | None,
    buy_zone_low: Decimal | None,
    buy_zone_high: Decimal | None,
) -> Decimal | None:
    if buy_zone_low is None or buy_zone_high is None:
        return entry_reference
    if (
        entry_reference is not None
        and buy_zone_low <= entry_reference <= buy_zone_high
    ):
        return entry_reference
    midpoint = (buy_zone_low + buy_zone_high) / Decimal("2")
    # Decimal context precision can round an extremely narrow cluster just
    # outside one endpoint; clamp so the execution invariant is exact.
    return min(max(midpoint, buy_zone_low), buy_zone_high)


def build_trade_plan(
    *,
    signal: StrategySignal,
    bars: Sequence[DailyBar],
    limit_pool: Sequence[LimitUpRecord],
    config: StrategyConfig,
    plan_date: date,
    for_trade_date: date | None = None,
    snapshot_id: str,
    strategy_commit: str,
    config_hash: str,
    trade_plan_config: TradePlanConfig | None = None,
    execution_config_hash: str | None = None,
    trade_calendar: Sequence[date] | None = None,
) -> TradePlan:
    """Build one plan using only bars and pool records at or before T."""

    if signal.trade_date != plan_date:
        raise ValueError(
            "trade plan signal.trade_date must equal plan_date"
        )
    ordered = tuple(sorted(
        (bar for bar in bars if bar.trade_date <= plan_date),
        key=lambda bar: bar.trade_date,
    ))
    if not ordered or ordered[-1].trade_date != plan_date:
        raise ValueError("trade plan requires a bar exactly on plan_date")
    current = ordered[-1]
    resolved_for_trade_date = (
        for_trade_date
        if for_trade_date is not None
        else _next_open_session(plan_date, trade_calendar)
    )
    execution_config = _execution_config(config, trade_plan_config)
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
        trade_plan_config=execution_config,
    )
    days_since_anchor = _days_since_anchor(ordered, signal)
    distance_to_support_pct = _distance_to_support_pct(current, support)
    _, volume_contraction = _prep_volume_metrics(
        ordered, signal, config, execution_config
    )
    price_above_buy_zone = False

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
        preferred = (
            _preferred_in_buy_zone(
                support.center,
                support_low,
                support_high,
            )
            if support is not None
            else None
        )
        price_above_buy_zone = (
            support_high is not None
            and current.close > support_high + config.anchor.price_tick
        )
        invalid = (
            (support.low * (ONE - config.support.invalid_buffer)).quantize(
                config.anchor.price_tick, rounding=ROUND_HALF_UP
            )
            if support is not None
            else None
        )
        entry_room = signal.entry_room_state
        s1 = None
        trigger = None
    elif signal.setup_stage is SetupStage.B1_READY:
        support_low = signal.support.support_low if signal.support else None
        support_high = signal.support.support_high if signal.support else None
        preferred = _preferred_in_buy_zone(
            signal.entry_reference_price,
            support_low,
            support_high,
        )
        price_above_buy_zone = (
            support_high is not None
            and current.close > support_high + config.anchor.price_tick
        )
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
        entry_room = signal.entry_room_state
        s1 = signal.target_s1.s1_low if signal.target_s1 else None
        trigger = None

    if signal.setup_stage in {
        SetupStage.B1_READY,
    }:
        actionable = actionable and not price_above_buy_zone
    if label is ExecutionLabel.B1_PREP:
        actionable = actionable and not price_above_buy_zone

    risk_pct, reward_pct, rr = _risk_reward_fields(
        entry=preferred,
        invalid=invalid,
        s1=s1,
    )
    return TradePlan(
        code=signal.code,
        plan_date=plan_date,
        for_trade_date=resolved_for_trade_date,
        setup_stage=signal.setup_stage,
        execution_label=label,
        anchor_date=signal.anchor.anchor_date if signal.anchor else None,
        anchor_price=signal.anchor.anchor_price if signal.anchor else None,
        days_since_anchor=days_since_anchor,
        current_close=current.close,
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
        distance_to_support_pct=distance_to_support_pct,
        volume_contraction=volume_contraction,
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
            extra_reasons=(
                ("PRICE_ABOVE_BUY_ZONE",)
                if price_above_buy_zone
                else ()
            ),
        ),
        snapshot_id=snapshot_id,
        strategy_commit=strategy_commit,
        config_hash=config_hash,
        execution_config_hash=execution_config_hash,
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
        entry_distance,
        -(plan.rr or Decimal("-1")),
        plan.code,
    )


_DAILY_PLAN_COLUMNS = (
    "code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "turnover_rate",
    "pct_change",
    "trade_status",
    "is_st",
    "reconciliation_status",
)


def _snapshot_file(
    layout: WarehouseLayout,
    snapshot_id: str,
    snapshot_files: dict[str, str],
    dataset: str,
) -> Path:
    suffix = f"/{dataset}/{snapshot_id}.parquet"
    relative = next((path for path in snapshot_files if path.endswith(suffix)), None)
    if relative is None:
        raise ValueError(f"snapshot is missing {dataset} parquet")
    path = layout.root / relative
    if not path.exists():
        raise ValueError(f"snapshot parquet does not exist: {path}")
    return path


def _as_time(value: object) -> time | None:
    if value is None or isinstance(value, time):
        return value
    text = str(value)
    return time.fromisoformat(text) if text else None


def _daily_bar_from_row(row: dict[str, object]) -> DailyBar:
    def decimal(name: str) -> Decimal | None:
        value = row.get(name)
        return Decimal(str(value)) if value is not None else None

    return DailyBar(
        trade_date=row["trade_date"],
        code=str(row["code"]),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        preclose=Decimal(str(row["preclose"])),
        volume=Decimal(str(row["volume"])),
        amount=Decimal(str(row["amount"])),
        turnover_rate=decimal("turnover_rate"),
        pct_change=decimal("pct_change"),
        trade_status=bool(row.get("trade_status", True)),
        is_st=(bool(row["is_st"]) if row.get("is_st") is not None else None),
        source="CANONICAL_SCREEN",
        fetched_at=FIXED_FETCHED_AT,
    )


def _pool_record_from_row(row: dict[str, object]) -> LimitUpRecord:
    def decimal(name: str) -> Decimal | None:
        value = row.get(name)
        return Decimal(str(value)) if value is not None else None

    return LimitUpRecord(
        trade_date=row["trade_date"],
        code=str(row["code"]),
        name=str(row["name"]),
        limit_price=Decimal(str(row["limit_price"])),
        first_seal_time=_as_time(row.get("first_seal_time")),
        last_seal_time=_as_time(row.get("last_seal_time")),
        open_count=(
            int(row["open_count"]) if row.get("open_count") is not None else None
        ),
        consecutive_count=(
            int(row["consecutive_count"])
            if row.get("consecutive_count") is not None
            else None
        ),
        turnover_rate=decimal("turnover_rate"),
        float_market_cap=decimal("float_market_cap"),
        total_market_cap=decimal("total_market_cap"),
        industry=(str(row["industry"]) if row.get("industry") is not None else None),
        source="CANONICAL_POOL",
        fetched_at=FIXED_FETCHED_AT,
    )


def _load_plan_inputs(
    *,
    layout: WarehouseLayout,
    snapshot,
    as_of: date,
    codes: set[str],
) -> tuple[
    dict[str, tuple[DailyBar, ...]],
    dict[str, tuple[LimitUpRecord, ...]],
    str,
    int,
]:
    """Load only plan-eligible codes, one parquet row group at a time.

    The published daily file is code-sorted and contains millions of rows. A
    trade-plan cross-section only needs bars for WATCH/B1/B2 states, so reading
    the four row groups sequentially keeps peak memory bounded without changing
    any strategy or snapshot semantics.
    """

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    daily_path = _snapshot_file(
        layout, snapshot.snapshot_id, snapshot.canonical_file_hashes, "daily_bars"
    )
    pool_path = _snapshot_file(
        layout,
        snapshot.snapshot_id,
        snapshot.canonical_file_hashes,
        "limit_up_pool",
    )

    pool_by_code: dict[str, list[LimitUpRecord]] = {}
    pool_hash_rows: list[dict[str, object]] = []
    pool_parquet = pq.ParquetFile(pool_path)
    pool_columns = (
        "code",
        "trade_date",
        "name",
        "limit_price",
        "first_seal_time",
        "last_seal_time",
        "open_count",
        "consecutive_count",
        "turnover_rate",
        "float_market_cap",
        "total_market_cap",
        "industry",
        "reconciliation_status",
    )
    for batch in pool_parquet.iter_batches(
        columns=list(pool_columns),
        batch_size=65536,
        use_threads=False,
    ):
        for row in batch.to_pylist():
            pool_hash_rows.append(row)
            if str(row["code"]) not in codes:
                continue
            record = _pool_record_from_row(row)
            pool_by_code.setdefault(record.code, []).append(record)
        del batch

    pool_prefix_hash = _pool_prefix_hash_from_rows(
        pool_hash_rows,
        as_of,
    )
    del pool_hash_rows

    canonical_codes: set[str] = set()
    daily_parquet = pq.ParquetFile(daily_path)
    for batch in daily_parquet.iter_batches(
        columns=["code", "reconciliation_status"],
        batch_size=65536,
        use_threads=False,
    ):
        status_mask = pc.equal(
            batch["reconciliation_status"], pa.scalar("CONFIRMED")
        )
        confirmed_codes = pc.unique(pc.filter(batch["code"], status_mask))
        canonical_codes.update(str(value) for value in confirmed_codes.to_pylist())
        del confirmed_codes, status_mask
        del batch

    bars_by_code: dict[str, list[DailyBar]] = {code: [] for code in codes}
    if not codes:
        return {}, {
            code: tuple(records) for code, records in pool_by_code.items()
        }, pool_prefix_hash, len(canonical_codes)

    parquet_file = daily_parquet
    code_column_index = parquet_file.schema_arrow.names.index("code")
    codes_by_group: dict[int, set[str]] = {}
    for code in sorted(codes):
        for group_index in range(parquet_file.num_row_groups):
            statistics = parquet_file.metadata.row_group(group_index).column(
                code_column_index
            ).statistics
            if statistics is None or statistics.min is None or statistics.max is None:
                matches = True
            else:
                minimum = (
                    statistics.min.decode()
                    if isinstance(statistics.min, bytes)
                    else str(statistics.min)
                )
                maximum = (
                    statistics.max.decode()
                    if isinstance(statistics.max, bytes)
                    else str(statistics.max)
                )
                matches = minimum <= code <= maximum
            if matches:
                codes_by_group.setdefault(group_index, set()).add(code)

    for group_index, group_codes in sorted(codes_by_group.items()):
        value_set = pa.array(sorted(group_codes), type=pa.string())
        # Batch the row-group scan: a single row group is large enough to
        # create an avoidable memory spike when all Decimal columns are
        # materialized at once.
        for batch in parquet_file.iter_batches(
            row_groups=[group_index],
            columns=list(_DAILY_PLAN_COLUMNS),
            batch_size=65536,
            use_threads=False,
        ):
            code_mask = pc.is_in(batch["code"], value_set=value_set)
            status_mask = pc.equal(
                batch["reconciliation_status"], pa.scalar("CONFIRMED")
            )
            filtered = batch.filter(pc.and_(code_mask, status_mask))
            for row in filtered.to_pylist():
                bar = _daily_bar_from_row(row)
                bars_by_code.setdefault(bar.code, []).append(bar)
            del filtered, batch

    return (
        {
            code: tuple(sorted(bars, key=lambda bar: bar.trade_date))
            for code, bars in bars_by_code.items()
        },
        {
            code: tuple(sorted(records, key=lambda record: record.trade_date))
            for code, records in pool_by_code.items()
        },
        pool_prefix_hash,
        len(canonical_codes),
    )


def build_trade_plan_output(
    *,
    layout: WarehouseLayout,
    as_of: date,
    snapshot_id: str,
    config: StrategyConfig,
    config_hash: str,
    strategy_commit: str | None = None,
    trade_plan_config: TradePlanConfig | None = None,
    execution_config_hash: str | None = None,
    trade_calendar: Sequence[date] | None = None,
) -> TradePlanOutput:
    """Build the latest cross-section from persisted screen states.

    This deliberately does not call ``load_canonical_market``: that helper is
    useful for single-stock replay but materializes the entire multi-million
    row canonical snapshot. Trade-plan generation reads state JSON first and
    then streams only the small set of eligible codes from parquet.
    """

    if not layout.duckdb_path.exists():
        raise ValueError("no dataset snapshot published")
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(snapshot_id)
    if snapshot is None:
        raise ValueError(f"unknown snapshot: {snapshot_id}")
    if snapshot.as_of < as_of:
        raise ValueError(
            f"SNAPSHOT_AS_OF_BEFORE_REQUESTED: {snapshot.as_of} < {as_of}"
        )
    commit = strategy_commit or _git_head()
    execution_config = _execution_config(config, trade_plan_config)
    next_trade_date = _next_open_session(as_of, trade_calendar)
    plans: list[TradePlan] = []
    reject_counts: Counter[str] = Counter()
    watch_count = b1_prep_count = b1_ready_count = 0
    b2_ready_count = b2_confirmed_count = actionable_count = 0
    entry_room_none = invalid_count = price_above_buy_zone = 0
    state_dir = layout.root / "screen" / "states"
    state_paths = tuple(
        sorted(
            path
            for path in state_dir.glob("*.json")
            if len(path.stem) == 6 and path.stem.isdigit()
        )
    )
    eligible_entries: list[tuple[str, ScreenState, StrategySignal]] = []
    for path in state_paths:
        code = path.stem
        try:
            state = load_state(state_path(layout.root, code))
            signal = (
                StrategySignal.model_validate_json(state.signal_json)
                if state is not None
                else None
            )
        except Exception:
            state = None
            signal = None
        provenance_ok = (
            state is not None
            and signal is not None
            and _state_provenance_valid(
                code=code,
                state=state,
                signal=signal,
                snapshot_id=snapshot_id,
                as_of=as_of,
                reconciliation_policy_version=(
                    snapshot.reconciliation_policy_version
                ),
                config_hash=config_hash,
                current_commit=commit,
            )
        )
        if not provenance_ok:
            reject_counts["STALE_OR_MISSING_SCREEN_STATE"] += 1
            continue
        assert state is not None and signal is not None
        if signal.setup_stage is SetupStage.WATCH_PULLBACK:
            watch_count += 1
        elif signal.setup_stage is SetupStage.B1_READY:
            b1_ready_count += 1
        elif signal.setup_stage is SetupStage.B2_READY:
            b2_ready_count += 1
        elif signal.setup_stage is SetupStage.B2_CONFIRMED:
            b2_confirmed_count += 1
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
        if signal.setup_stage in {
            SetupStage.WATCH_PULLBACK,
            SetupStage.B1_READY,
            SetupStage.B2_READY,
            SetupStage.B2_CONFIRMED,
        }:
            eligible_entries.append((code, state, signal))

    bars_by_code, pool_by_code, pool_prefix_hash, canonical_universe = _load_plan_inputs(
        layout=layout,
        snapshot=snapshot,
        as_of=as_of,
        codes={code for code, _, _ in eligible_entries},
    )
    for code, state, signal in eligible_entries:
        bars = bars_by_code.get(code, ())
        if not bars:
            reject_counts["MISSING_CANONICAL_BARS"] += 1
            continue
        if (
            _bars_prefix_hash(bars, as_of) != state.bars_prefix_hash
            or state.limit_pool_prefix_hash != pool_prefix_hash
        ):
            reject_counts["STALE_OR_MISSING_SCREEN_STATE"] += 1
            continue
        plan = build_trade_plan(
            signal=signal,
            bars=bars,
            limit_pool=pool_by_code.get(code, ()),
            config=config,
            plan_date=as_of,
            for_trade_date=next_trade_date,
            snapshot_id=snapshot_id,
            strategy_commit=commit,
            config_hash=config_hash,
            trade_plan_config=execution_config,
            execution_config_hash=execution_config_hash,
        )
        if plan.execution_label is ExecutionLabel.B1_PREP:
            b1_prep_count += 1
        if "PRICE_ABOVE_BUY_ZONE" in plan.cancel_conditions:
            price_above_buy_zone += 1
            reject_counts["PRICE_ABOVE_BUY_ZONE"] += 1
        if plan.is_actionable:
            actionable_count += 1
        if signal.setup_stage is SetupStage.WATCH_PULLBACK or plan.is_actionable:
            plans.append(plan)
    plans.sort(key=_sort_key)
    ambush_watch_pool = tuple(
        plan
        for plan in plans
        if plan.execution_label is ExecutionLabel.B1_PREP
    )
    formed_b_point_pool = tuple(
        plan
        for plan in plans
        if plan.execution_label
        in {
            ExecutionLabel.B1_READY,
            ExecutionLabel.B2_READY,
            ExecutionLabel.B2_CONFIRMED,
        }
        and plan.is_actionable
    )
    top_candidates = tuple(plans[:20])
    return TradePlanOutput(
        plan_date=as_of,
        for_trade_date=next_trade_date,
        snapshot_id=snapshot_id,
        strategy_commit=commit,
        config_hash=config_hash,
        execution_config_hash=execution_config_hash,
        universe=canonical_universe,
        watch_count=watch_count,
        b1_prep_count=b1_prep_count,
        b1_ready_count=b1_ready_count,
        b2_ready_count=b2_ready_count,
        b2_confirmed_count=b2_confirmed_count,
        actionable_count=actionable_count,
        entry_room_none_reject_count=entry_room_none,
        invalid_reject_count=invalid_count,
        price_above_buy_zone_reject_count=price_above_buy_zone,
        reject_counts=dict(sorted(reject_counts.items())),
        plans=tuple(plans),
        ambush_watch_pool=ambush_watch_pool,
        formed_b_point_pool=formed_b_point_pool,
        top_candidates=top_candidates,
    )
