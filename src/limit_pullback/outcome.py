"""Phase 2D.0 causal signal outcome study.

This module deliberately is not a backtest engine.  It replays each code once,
freezes the first occurrence of each setup/execution label, and only then
labels the frozen event with later canonical daily bars.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import subprocess
from time import perf_counter, process_time
from typing import Iterable, Iterator, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from limit_pullback.config import load_outcome_study_config, load_trade_plan_config
from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import (
    DataQuality,
    EventFlag,
    ExecutionLabel,
    FillStatus,
    FillType,
    OutcomeStatus,
    PatternOutcome,
    SetupStage,
)
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.outcome import (
    OutcomeEpisode,
    OutcomeStats,
    OutcomeStudyConfig,
    OutcomeStudySummary,
)
from limit_pullback.models.signal import StrategySignal
from limit_pullback.quality import merge_signal_quality
from limit_pullback.screen.canonical import FIXED_FETCHED_AT
from limit_pullback.strategy.engine import evaluate_strategy
from limit_pullback.trade_plan import build_trade_plan
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import SnapshotRecord
from limit_pullback.warehouse.parquet import sha256_file


ZERO = Decimal("0")
ONE = Decimal("1")
RATIO_QUANTUM = Decimal("0.0001")
DATASET_MODE = "FINAL_VINTAGE_CAUSAL"
TARGET_LABELS = frozenset(
    {
        ExecutionLabel.B1_PREP,
        ExecutionLabel.B1_READY,
        ExecutionLabel.B2_READY,
        ExecutionLabel.B2_CONFIRMED,
    }
)
QUALITY_GROUP_KEYS = ("<60", "60-70", "70-80", ">=80")
DAYS_GROUP_KEYS = ("D+1", "D+2", "D+3", "D+4", "D+5+")


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


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _snapshot_file(
    layout: WarehouseLayout, snapshot: SnapshotRecord, dataset: str
) -> Path:
    suffix = f"/{dataset}/{snapshot.snapshot_id}.parquet"
    relative = next(
        (path for path in snapshot.canonical_file_hashes if path.endswith(suffix)),
        None,
    )
    if relative is None:
        raise ValueError(f"snapshot is missing {dataset} parquet")
    path = layout.root / relative
    if not path.exists():
        raise ValueError(f"snapshot parquet does not exist: {path}")
    return path


def _decimal(value: object) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _daily_bar(row: dict[str, object]) -> DailyBar:
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
        turnover_rate=_decimal(row.get("turnover_rate")),
        pct_change=_decimal(row.get("pct_change")),
        trade_status=bool(row.get("trade_status", True)),
        is_st=(bool(row["is_st"]) if row.get("is_st") is not None else None),
        source="CANONICAL_SCREEN",
        fetched_at=FIXED_FETCHED_AT,
    )


def _pool_record(row: dict[str, object]) -> LimitUpRecord:
    def _as_time(value: object) -> time | None:
        if value is None or isinstance(value, time):
            return value
        return time.fromisoformat(str(value))

    return LimitUpRecord(
        trade_date=row["trade_date"],
        code=str(row["code"]),
        name=str(row["name"]),
        limit_price=Decimal(str(row["limit_price"])),
        first_seal_time=_as_time(row.get("first_seal_time")),
        last_seal_time=_as_time(row.get("last_seal_time")),
        open_count=(int(row["open_count"]) if row.get("open_count") is not None else None),
        consecutive_count=(
            int(row["consecutive_count"])
            if row.get("consecutive_count") is not None
            else None
        ),
        turnover_rate=_decimal(row.get("turnover_rate")),
        float_market_cap=_decimal(row.get("float_market_cap")),
        total_market_cap=_decimal(row.get("total_market_cap")),
        industry=(str(row["industry"]) if row.get("industry") is not None else None),
        source="CANONICAL_POOL",
        fetched_at=FIXED_FETCHED_AT,
    )


def _iter_confirmed_code_bars(path: Path) -> Iterator[tuple[str, tuple[DailyBar, ...]]]:
    """Stream code-sorted canonical rows without materializing the market."""

    parquet = pq.ParquetFile(path)
    columns = [
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
    ]
    current_code: str | None = None
    current: list[DailyBar] = []
    previous_code: str | None = None
    for batch in parquet.iter_batches(
        columns=columns,
        batch_size=65536,
        use_threads=False,
    ):
        for row in batch.to_pylist():
            if str(row.get("reconciliation_status")) != "CONFIRMED":
                continue
            code = str(row["code"])
            if previous_code is not None and code < previous_code:
                raise ValueError("canonical daily bars are not code sorted")
            previous_code = code
            if current_code is None:
                current_code = code
            if code != current_code:
                yield current_code, tuple(current)
                current_code = code
                current = []
            current.append(_daily_bar(row))
        del batch
    if current_code is not None:
        yield current_code, tuple(current)


def _load_pool_by_code(path: Path) -> dict[str, tuple[LimitUpRecord, ...]]:
    table = pq.read_table(path)
    records: dict[str, list[LimitUpRecord]] = defaultdict(list)
    for row in table.to_pylist():
        status = str(row.get("reconciliation_status"))
        if status not in {"CONFIRMED", "CONFIRMED_SINGLE_SOURCE"}:
            continue
        record = _pool_record(row)
        records[record.code].append(record)
    return {
        code: tuple(sorted(values, key=lambda item: item.trade_date))
        for code, values in records.items()
    }


@dataclass(frozen=True)
class _FrozenEvent:
    code: str
    setup_id: str
    execution_label: ExecutionLabel
    setup_stage: SetupStage
    signal_date: date
    anchor_date: date | None
    anchor_price: Decimal | None
    support_low: Decimal | None
    support_high: Decimal | None
    support_center: Decimal | None
    b2_trigger_price: Decimal | None
    setup_quality_score: Decimal
    entry_quality_score: Decimal | None
    days_since_anchor: int | None
    entry_room_state: object
    is_entry_candidate: bool
    preferred_entry: Decimal | None
    buy_zone_low: Decimal | None
    buy_zone_high: Decimal | None
    invalid_price: Decimal | None
    s1_price: Decimal | None
    entry_reference_price: Decimal | None
    data_quality: str
    quality_flags: tuple[str, ...]
    snapshot_id: str
    strategy_commit: str
    strategy_config_hash: str
    trade_plan_config_hash: str
    outcome_config_hash: str
    frozen_event_hash: str
    raw_signal_days: int = 1
    snapshot_created_at: datetime | None = None


def _event_payload(event: _FrozenEvent) -> dict[str, object]:
    return {
        "code": event.code,
        "setup_id": event.setup_id,
        "execution_label": event.execution_label.value,
        "setup_stage": event.setup_stage.value,
        "signal_date": event.signal_date.isoformat(),
        "anchor_date": event.anchor_date.isoformat() if event.anchor_date else None,
        "anchor_price": str(event.anchor_price) if event.anchor_price else None,
        "support_low": str(event.support_low) if event.support_low else None,
        "support_high": str(event.support_high) if event.support_high else None,
        "support_center": str(event.support_center) if event.support_center else None,
        "b2_trigger_price": (
            str(event.b2_trigger_price) if event.b2_trigger_price else None
        ),
        "setup_quality_score": str(event.setup_quality_score),
        "entry_quality_score": (
            str(event.entry_quality_score)
            if event.entry_quality_score is not None
            else None
        ),
        "days_since_anchor": event.days_since_anchor,
        "entry_room_state": (
            event.entry_room_state.value
            if hasattr(event.entry_room_state, "value")
            else event.entry_room_state
        ),
        "is_entry_candidate": event.is_entry_candidate,
        "preferred_entry": str(event.preferred_entry) if event.preferred_entry else None,
        "buy_zone_low": str(event.buy_zone_low) if event.buy_zone_low else None,
        "buy_zone_high": str(event.buy_zone_high) if event.buy_zone_high else None,
        "invalid_price": str(event.invalid_price) if event.invalid_price else None,
        "s1_price": str(event.s1_price) if event.s1_price else None,
        "entry_reference_price": (
            str(event.entry_reference_price)
            if event.entry_reference_price
            else None
        ),
        "data_quality": event.data_quality,
        "quality_flags": event.quality_flags,
        "snapshot_id": event.snapshot_id,
        "snapshot_created_at": (
            event.snapshot_created_at.isoformat()
            if event.snapshot_created_at is not None
            else None
        ),
        "strategy_commit": event.strategy_commit,
        "strategy_config_hash": event.strategy_config_hash,
        "trade_plan_config_hash": event.trade_plan_config_hash,
        "outcome_config_hash": event.outcome_config_hash,
    }


def _freeze_event(
    *,
    signal: StrategySignal,
    plan,
    snapshot_id: str,
    strategy_commit: str,
    strategy_config_hash: str,
    trade_plan_config_hash: str,
    outcome_config_hash: str,
    snapshot_created_at: datetime | None = None,
) -> _FrozenEvent:
    event = _FrozenEvent(
        code=signal.code,
        setup_id=signal.setup_id,
        execution_label=plan.execution_label,
        setup_stage=signal.setup_stage,
        signal_date=signal.trade_date,
        anchor_date=signal.anchor.anchor_date if signal.anchor else None,
        anchor_price=signal.anchor.anchor_price if signal.anchor else None,
        support_low=(signal.support.support_low if signal.support else None),
        support_high=(signal.support.support_high if signal.support else None),
        support_center=(signal.support.support_center if signal.support else None),
        b2_trigger_price=(signal.b2_trigger.trigger_price if signal.b2_trigger else None),
        setup_quality_score=signal.setup_quality_score,
        entry_quality_score=signal.entry_quality_score,
        days_since_anchor=plan.days_since_anchor,
        entry_room_state=signal.entry_room_state,
        is_entry_candidate=signal.is_entry_candidate and plan.is_actionable,
        preferred_entry=plan.preferred_entry,
        buy_zone_low=plan.buy_zone_low,
        buy_zone_high=plan.buy_zone_high,
        invalid_price=plan.invalid_price,
        s1_price=plan.s1_price,
        entry_reference_price=signal.entry_reference_price,
        data_quality=signal.data_quality.value,
        quality_flags=signal.quality_flags,
        snapshot_id=snapshot_id,
        snapshot_created_at=snapshot_created_at,
        strategy_commit=strategy_commit,
        strategy_config_hash=strategy_config_hash,
        trade_plan_config_hash=trade_plan_config_hash,
        outcome_config_hash=outcome_config_hash,
        frozen_event_hash="pending",
    )
    return replace(event, frozen_event_hash=_hash_payload(_event_payload(event)))


def _pattern_result(
    future: Sequence[DailyBar],
    *,
    horizon: int,
    s1: Decimal,
    invalid: Decimal,
) -> PatternOutcome:
    window = future[:horizon]
    for bar in window:
        hit_s1 = bar.high >= s1
        hit_invalid = bar.low <= invalid
        if hit_s1 and hit_invalid:
            return PatternOutcome.AMBIGUOUS
        if hit_s1:
            return PatternOutcome.S1_BEFORE_INVALID
        if hit_invalid:
            return PatternOutcome.INVALID_BEFORE_S1
    if len(window) < horizon:
        return PatternOutcome.CENSORED
    return PatternOutcome.NEITHER


def _trigger_outcome(
    future: Sequence[DailyBar],
    *,
    max_holding_sessions: int,
    s1: Decimal,
    invalid: Decimal,
) -> tuple[OutcomeStatus, date | None, Decimal | None, int | None, Decimal | None, Decimal | None]:
    window = future[:max_holding_sessions]
    for index, bar in enumerate(window, start=1):
        hit_s1 = bar.high >= s1
        hit_invalid = bar.low <= invalid
        if hit_s1 and hit_invalid:
            return OutcomeStatus.AMBIGUOUS_INTRADAY, bar.trade_date, None, index, None, Decimal("-1")
        if hit_s1:
            return OutcomeStatus.WIN_S1, bar.trade_date, s1, index, None, None
        if hit_invalid:
            return OutcomeStatus.LOSS_INVALID, bar.trade_date, invalid, index, Decimal("-1"), Decimal("-1")
    if len(window) < max_holding_sessions:
        return OutcomeStatus.CENSORED, None, None, None, None, None
    return OutcomeStatus.TIMEOUT, window[-1].trade_date, None, len(window), None, None


def _apply_mfe_mae(
    future: Sequence[DailyBar],
    *,
    fill_price: Decimal,
    max_holding_sessions: int,
    fill_type: FillType,
    fill_date: date,
    outcome: OutcomeStatus,
    resolution_date: date | None,
) -> tuple[Decimal | None, Decimal | None]:
    window = future[:max_holding_sessions]
    if not window or fill_price <= ZERO:
        return None, None
    # Excursions describe the resolved trade, not bars after its first
    # resolution.  TIMEOUT keeps the configured holding window.  For an
    # intraday touch, the fill-day high is unknowable relative to the touch
    # and is therefore excluded, while its low remains valid for MAE.
    if (
        outcome in {
            OutcomeStatus.WIN_S1,
            OutcomeStatus.LOSS_INVALID,
            OutcomeStatus.AMBIGUOUS_INTRADAY,
        }
        and resolution_date is not None
    ):
        window = tuple(bar for bar in window if bar.trade_date <= resolution_date)
    highs = (
        bar.high
        for bar in window
        if not (
            fill_type is FillType.INTRADAY_TOUCH_FILL
            and bar.trade_date == fill_date
        )
    )
    max_high = max(highs, default=None)
    min_low = min(bar.low for bar in window)
    mfe = _quantize(max_high / fill_price - ONE) if max_high is not None else None
    return mfe, _quantize(min_low / fill_price - ONE)


def _complete_event(
    event: _FrozenEvent,
    bars: Sequence[DailyBar],
    config: OutcomeStudyConfig,
    *,
    date_index: dict[date, int] | None = None,
) -> OutcomeEpisode:
    if date_index is None:
        date_index = {bar.trade_date: index for index, bar in enumerate(bars)}
    signal_index = date_index.get(event.signal_date)
    future = (
        bars[signal_index + 1 :]
        if signal_index is not None
        else tuple(bar for bar in bars if bar.trade_date > event.signal_date)
    )
    next_date = future[0].trade_date if future else None
    patterns: dict[int, PatternOutcome | None] = {h: None for h in config.forward_horizons}
    if event.s1_price is not None and event.invalid_price is not None:
        patterns = {
            horizon: _pattern_result(
                future,
                horizon=horizon,
                s1=event.s1_price,
                invalid=event.invalid_price,
            )
            for horizon in config.forward_horizons
        }

    base = dict(
        code=event.code,
        setup_id=event.setup_id,
        execution_label=event.execution_label,
        setup_stage=event.setup_stage,
        signal_date=event.signal_date,
        anchor_date=event.anchor_date,
        anchor_price=event.anchor_price,
        support_low=event.support_low,
        support_high=event.support_high,
        support_center=event.support_center,
        b2_trigger_price=event.b2_trigger_price,
        setup_quality_score=event.setup_quality_score,
        entry_quality_score=event.entry_quality_score,
        days_since_anchor=event.days_since_anchor,
        entry_room_state=event.entry_room_state,
        is_entry_candidate=event.is_entry_candidate,
        preferred_entry=event.preferred_entry,
        buy_zone_low=event.buy_zone_low,
        buy_zone_high=event.buy_zone_high,
        invalid_price=event.invalid_price,
        s1_price=event.s1_price,
        entry_reference_price=event.entry_reference_price,
        next_trade_date=next_date,
        future_sessions_available=len(future),
        raw_signal_days=event.raw_signal_days,
        data_quality=event.data_quality,
        quality_flags=event.quality_flags,
        snapshot_id=event.snapshot_id,
        snapshot_created_at=event.snapshot_created_at,
        strategy_commit=event.strategy_commit,
        strategy_config_hash=event.strategy_config_hash,
        trade_plan_config_hash=event.trade_plan_config_hash,
        outcome_config_hash=event.outcome_config_hash,
        frozen_event_hash=event.frozen_event_hash,
        pattern_1d=patterns.get(1),
        pattern_3d=patterns.get(3),
        pattern_5d=patterns.get(5),
        pattern_10d=patterns.get(10),
    )

    if event.execution_label is ExecutionLabel.B1_PREP:
        return OutcomeEpisode(
            **base,
            fill_status=FillStatus.NO_FILL,
            fill_type=FillType.NONE,
            outcome=OutcomeStatus.NO_FILL,
            eligibility_reason="B1_PREP_CONVERSION_ONLY",
        )
    if event.preferred_entry is None or event.invalid_price is None or event.s1_price is None:
        return OutcomeEpisode(
            **base,
            fill_status=FillStatus.NO_FILL,
            fill_type=FillType.NONE,
            outcome=OutcomeStatus.NO_FILL,
            eligibility_reason="INCOMPLETE_FROZEN_TRADE_PLAN",
        )
    if event.preferred_entry <= event.invalid_price:
        return OutcomeEpisode(
            **base,
            fill_status=FillStatus.NO_FILL,
            fill_type=FillType.NONE,
            outcome=OutcomeStatus.NO_FILL,
            eligibility_reason="RISK_NON_POSITIVE",
        )
    if not future:
        return OutcomeEpisode(
            **base,
            fill_status=FillStatus.CENSORED,
            fill_type=FillType.NONE,
            outcome=OutcomeStatus.CENSORED,
            eligibility_reason="NO_FUTURE_CONFIRMED_SESSION",
        )

    first = future[0]
    if first.open <= event.invalid_price:
        return OutcomeEpisode(
            **base,
            fill_status=FillStatus.CANCEL_GAP_INVALID,
            fill_type=FillType.NONE,
            outcome=OutcomeStatus.CANCEL_GAP_INVALID,
            eligibility_reason="T_PLUS_1_OPEN_AT_OR_BELOW_INVALID",
        )
    if event.invalid_price < first.open <= event.preferred_entry:
        fill_price = first.open
        fill_type = FillType.OPEN_FILL
    elif first.open > event.preferred_entry and first.low <= event.preferred_entry:
        fill_price = event.preferred_entry
        fill_type = FillType.INTRADAY_TOUCH_FILL
    else:
        return OutcomeEpisode(
            **base,
            fill_status=FillStatus.NO_FILL,
            fill_type=FillType.NONE,
            outcome=OutcomeStatus.NO_FILL,
            eligibility_reason="T_PLUS_1_ENTRY_NOT_TOUCHED",
        )

    if fill_type is FillType.INTRADAY_TOUCH_FILL:
        # The fill-day high may precede the preferred-entry touch.  Only a
        # same-day invalidation is orderable from daily OHLC; a simultaneous
        # target/invalid range remains conservative ambiguity.  Otherwise,
        # target evaluation starts at the next trading session.
        if first.low <= event.invalid_price:
            if first.high >= event.s1_price:
                outcome = OutcomeStatus.AMBIGUOUS_INTRADAY
                resolution_date = first.trade_date
                exit_price = None
                holding = 1
                r_value = None
                conservative_r = Decimal("-1")
            else:
                outcome = OutcomeStatus.LOSS_INVALID
                resolution_date = first.trade_date
                exit_price = event.invalid_price
                holding = 1
                r_value = Decimal("-1")
                conservative_r = Decimal("-1")
        else:
            remaining_sessions = config.max_holding_sessions - 1
            if remaining_sessions == 0:
                # The fill session is the complete holding window.  Its high
                # is intentionally unusable for an intraday touch, so with
                # no later session there is no target/invalid resolution.
                outcome = OutcomeStatus.TIMEOUT
                resolution_date = first.trade_date
                exit_price = None
                holding = 1
                r_value = None
                conservative_r = None
            else:
                outcome, resolution_date, exit_price, holding, r_value, conservative_r = _trigger_outcome(
                    future[1:],
                    max_holding_sessions=remaining_sessions,
                    s1=event.s1_price,
                    invalid=event.invalid_price,
                )
                if holding is not None:
                    holding += 1
    else:
        outcome, resolution_date, exit_price, holding, r_value, conservative_r = _trigger_outcome(
            future,
            max_holding_sessions=config.max_holding_sessions,
            s1=event.s1_price,
            invalid=event.invalid_price,
        )
    risk_abs = fill_price - event.invalid_price
    if outcome is OutcomeStatus.WIN_S1 and risk_abs > ZERO:
        r_value = _quantize((event.s1_price - fill_price) / risk_abs)
        conservative_r = r_value
    mfe, mae = _apply_mfe_mae(
        future,
        fill_price=fill_price,
        max_holding_sessions=config.max_holding_sessions,
        fill_type=fill_type,
        fill_date=first.trade_date,
        outcome=outcome,
        resolution_date=resolution_date,
    )
    return OutcomeEpisode(
        **base,
        fill_status=FillStatus.FILLED,
        fill_type=fill_type,
        fill_date=first.trade_date,
        fill_price=fill_price,
        outcome=outcome,
        resolution_date=resolution_date,
        exit_price=exit_price,
        r_multiple=r_value,
        conservative_r_multiple=conservative_r,
        mfe_pct=mfe,
        mae_pct=mae,
        holding_sessions_to_resolution=holding,
        eligibility_reason=(
            "RISK_NON_POSITIVE" if risk_abs <= ZERO else None
        ),
    )


def _stats(
    events: Sequence[OutcomeEpisode],
    *,
    actionable_only: bool = False,
) -> OutcomeStats:
    cohort_events = [event for event in events if not actionable_only or event.is_entry_candidate]
    episodes = len(cohort_events)
    raw_days = sum(event.raw_signal_days for event in cohort_events)
    # Outcome episodes measure the frozen structural signal.  "Eligible"
    # means the frozen plan has all prices needed for an entry attempt; the
    # separate is_entry_candidate field remains available for later filtering.
    eligible_events = [
        event
        for event in cohort_events
        if event.preferred_entry is not None
        and event.invalid_price is not None
        and event.s1_price is not None
    ]
    filled = [event for event in cohort_events if event.fill_status is FillStatus.FILLED]
    wins = [event for event in cohort_events if event.outcome is OutcomeStatus.WIN_S1]
    losses = [event for event in cohort_events if event.outcome is OutcomeStatus.LOSS_INVALID]
    ambiguous = [
        event for event in cohort_events if event.outcome is OutcomeStatus.AMBIGUOUS_INTRADAY
    ]
    timeout = [event for event in cohort_events if event.outcome is OutcomeStatus.TIMEOUT]
    censored = [event for event in cohort_events if event.outcome is OutcomeStatus.CENSORED]
    no_fill = [event for event in cohort_events if event.outcome is OutcomeStatus.NO_FILL]
    cancelled = [
        event for event in cohort_events if event.outcome is OutcomeStatus.CANCEL_GAP_INVALID
    ]
    strict_r = [event.r_multiple for event in [*wins, *losses] if event.r_multiple is not None]
    win_r = [event.r_multiple for event in wins if event.r_multiple is not None]
    loss_r = [event.r_multiple for event in losses if event.r_multiple is not None]
    conservative_r = [
        event.conservative_r_multiple
        for event in [*wins, *losses, *ambiguous]
        if event.conservative_r_multiple is not None
    ]
    conservative_denominator = len(wins) + len(losses) + len(ambiguous)
    strict_denominator = len(wins) + len(losses)

    def ratio(numerator: int, denominator: int) -> Decimal:
        return _quantize(Decimal(numerator) / Decimal(denominator)) if denominator else ZERO

    def mean(values: Sequence[Decimal]) -> Decimal | None:
        return _quantize(sum(values, ZERO) / Decimal(len(values))) if values else None

    def median(values: Sequence[Decimal]) -> Decimal | None:
        if not values:
            return None
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return _quantize(ordered[middle])
        return _quantize((ordered[middle - 1] + ordered[middle]) / Decimal("2"))

    mfe = [event.mfe_pct for event in filled if event.mfe_pct is not None]
    mae = [event.mae_pct for event in filled if event.mae_pct is not None]
    holding = [
        Decimal(event.holding_sessions_to_resolution)
        for event in filled
        if event.holding_sessions_to_resolution is not None
    ]
    strict_expectancy = mean(strict_r)
    conservative_expectancy = mean(conservative_r)
    return OutcomeStats(
        episodes=episodes,
        raw_signal_days=raw_days,
        eligible=len(eligible_events),
        no_fill=len(no_fill),
        cancel_gap_invalid=len(cancelled),
        filled=len(filled),
        resolved=len(wins) + len(losses) + len(ambiguous) + len(timeout),
        wins=len(wins),
        losses=len(losses),
        ambiguous=len(ambiguous),
        timeout=len(timeout),
        censored=len(censored),
        fill_rate=ratio(len(filled), len(eligible_events)),
        strict_win_rate=ratio(len(wins), strict_denominator),
        conservative_win_rate=ratio(len(wins), conservative_denominator),
        strict_resolved=strict_denominator,
        conservative_resolved=conservative_denominator,
        strict_resolved_expectancy_r=strict_expectancy,
        conservative_resolved_expectancy_r=conservative_expectancy,
        strict_average_r=strict_expectancy,
        conservative_average_r=conservative_expectancy,
        average_win_r=mean(win_r),
        average_loss_r=mean(loss_r),
        average_r=strict_expectancy,
        expectancy_r=strict_expectancy,
        median_r=median(strict_r),
        median_mfe=median(mfe),
        median_mae=median(mae),
        median_holding_sessions=median(holding),
    )


def _group_bucket(value: Decimal | None, *, prefix: str = "") -> str:
    if value is None:
        return f"{prefix}UNKNOWN"
    if value < Decimal("60"):
        return f"{prefix}<60"
    if value < Decimal("70"):
        return f"{prefix}60-70"
    if value < Decimal("80"):
        return f"{prefix}70-80"
    return f"{prefix}>=80"


def _days_bucket(days: int | None) -> str:
    if days is None:
        return "UNKNOWN"
    return f"D+{days}" if days <= 4 else "D+5+"


def _group_stats(
    events: Sequence[OutcomeEpisode],
    key_fn,
    *,
    actionable_only: bool = False,
    expected_keys: Sequence[str] = (),
) -> dict[str, OutcomeStats]:
    """Aggregate one diagnostic dimension without mixing cohorts."""

    groups: dict[str, list[OutcomeEpisode]] = {
        key: [] for key in expected_keys
    }
    for event in events:
        if actionable_only and not event.is_entry_candidate:
            continue
        groups.setdefault(key_fn(event), []).append(event)
    ordered_keys = [key for key in expected_keys if key in groups]
    ordered_keys.extend(sorted(key for key in groups if key not in expected_keys))
    return {key: _stats(groups[key]) for key in ordered_keys}


def _summary_markdown(summary: OutcomeStudySummary) -> str:
    lines = [
        "# Phase 2D.0 Signal Outcome Study",
        "",
        f"MODE: `{summary.dataset_mode}`",
        "",
        "NOT: `STRICT_HISTORICAL_VINTAGE_PIT`",
        "",
        f"- snapshot: `{summary.snapshot_id}`",
        f"- date range: {summary.start} .. {summary.end}",
        f"- CONFIRMED sessions: {summary.confirmed_date_count}",
        f"- CONFIRMED codes: {summary.confirmed_code_count}",
        f"- provisional-only dates: {summary.provisional_only_date_count}",
        f"- raw signal days: {summary.raw_signal_days}",
        f"- episodes: {summary.episode_count}",
        "",
    ]
    def append_stats(title: str, stats_by_stage: dict[str, OutcomeStats]) -> None:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(
            [
                f"## {title}",
                "",
                "| stage | episodes | raw days | eligible | filled | fill rate | strict win | conservative win | strict resolved expectancy R | conservative resolved expectancy R | median MFE | median MAE |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for stage, stats in stats_by_stage.items():
            lines.append(
                f"| {stage} | {stats.episodes} | {stats.raw_signal_days} | "
                f"{stats.eligible} | {stats.filled} | {stats.fill_rate} | "
                f"{stats.strict_win_rate} | {stats.conservative_win_rate} | "
                f"{stats.strict_resolved_expectancy_r} | "
                f"{stats.conservative_resolved_expectancy_r} | "
                f"{stats.median_mfe} | {stats.median_mae} |"
            )

    append_stats("Actionable stage outcomes", summary.actionable_stage_stats)
    append_stats("Structural stage outcomes", summary.structural_stage_stats)

    def append_group(title: str, groups: dict[str, OutcomeStats]) -> None:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(
            [
                f"## {title}",
                "",
                "| group | episodes | eligible | filled | fill rate | strict win | conservative win | strict resolved expectancy R | conservative resolved expectancy R |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for group, stats in groups.items():
            lines.append(
                f"| {group} | {stats.episodes} | {stats.eligible} | "
                f"{stats.filled} | {stats.fill_rate} | "
                f"{stats.strict_win_rate} | {stats.conservative_win_rate} | "
                f"{stats.strict_resolved_expectancy_r} | "
                f"{stats.conservative_resolved_expectancy_r} |"
            )

    append_group(
        "ACTIONABLE setup_quality groups",
        summary.actionable_setup_quality_groups,
    )
    append_group(
        "ACTIONABLE entry_quality groups",
        summary.actionable_entry_quality_groups,
    )
    append_group(
        "ACTIONABLE days_since_anchor groups",
        summary.actionable_days_since_anchor_groups,
    )
    append_group(
        "STRUCTURAL setup_quality groups",
        summary.structural_setup_quality_groups,
    )
    append_group(
        "STRUCTURAL entry_quality groups",
        summary.structural_entry_quality_groups,
    )
    append_group(
        "STRUCTURAL days_since_anchor groups",
        summary.structural_days_since_anchor_groups,
    )
    lines.extend(
        [
            "",
            "Legacy setup_quality_groups/entry_quality_groups/days_since_anchor_groups are ACTIONABLE aliases.",
            "",
            "Strict expectancy excludes AMBIGUOUS_INTRADAY and TIMEOUT from its resolved denominator.",
            "Conservative expectancy counts AMBIGUOUS_INTRADAY as -1R; TIMEOUT is excluded.",
        ]
    )
    lines.extend(
        [
            "",
            "## Performance",
            "",
            "```json",
            json.dumps(summary.performance, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Pattern outcome",
            "",
            "```json",
            json.dumps(summary.pattern_success, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {limitation}" for limitation in summary.limitations)
    lines.extend(["", "## Audit", "", "```json", json.dumps(summary.audit, ensure_ascii=False, indent=2, sort_keys=True, default=str), "```", ""])
    return "\n".join(lines)


def _write_episodes(path: Path, episodes: Sequence[OutcomeEpisode]) -> None:
    rows = [event.model_dump(mode="json") for event in episodes]
    if not rows:
        table = pa.table({"code": pa.array([], type=pa.string())})
    else:
        keys = tuple(rows[0])
        normalized = {
            key: [
                (json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (list, dict)) else value)
                for row in rows
                for value in [row.get(key)]
            ]
            for key in keys
        }
        table = pa.Table.from_pydict(normalized)
    pq.write_table(table, path, compression="zstd")


def _load_snapshot(layout: WarehouseLayout, snapshot_id: str) -> SnapshotRecord:
    if not layout.duckdb_path.exists():
        raise ValueError("no dataset snapshot published")
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(snapshot_id)
    if snapshot is None:
        raise ValueError(f"unknown snapshot: {snapshot_id}")
    return snapshot


def _replay_code(
    *,
    code: str,
    bars: Sequence[DailyBar],
    pool: Sequence[LimitUpRecord],
    start: date,
    end: date,
    config: StrategyConfig,
    trade_plan_config,
    snapshot_id: str,
    strategy_commit: str,
    strategy_config_hash: str,
    trade_plan_config_hash: str,
    outcome_config_hash: str,
    snapshot_created_at: datetime | None = None,
) -> tuple[
    list[_FrozenEvent],
    Counter[tuple[str, ExecutionLabel]],
    dict[str, dict[SetupStage, list[date]]],
    dict[str, float],
]:
    replay_cpu_started = process_time()
    ordered = tuple(sorted((bar for bar in bars if bar.trade_date <= end), key=lambda item: item.trade_date))
    if not ordered:
        return [], Counter(), {}, {
            "evaluate_strategy_calls": 0,
            "trade_plan_calls": 0,
            "process_cpu_seconds": process_time() - replay_cpu_started,
        }
    pool_ordered = tuple(sorted((record for record in pool if record.trade_date <= end), key=lambda item: item.trade_date))
    pool_prefix: list[LimitUpRecord] = []
    pool_index = 0
    previous_signal: StrategySignal | None = None
    seen: set[tuple[str, ExecutionLabel]] = set()
    raw_counts: Counter[tuple[str, ExecutionLabel]] = Counter()
    stage_dates: dict[str, dict[SetupStage, list[date]]] = defaultdict(lambda: defaultdict(list))
    events: list[_FrozenEvent] = []
    prefix: list[DailyBar] = []
    metrics: dict[str, float] = {
        "evaluate_strategy_calls": 0,
        "trade_plan_calls": 0,
    }

    for current in ordered:
        prefix.append(current)
        while pool_index < len(pool_ordered) and pool_ordered[pool_index].trade_date <= current.trade_date:
            pool_prefix.append(pool_ordered[pool_index])
            pool_index += 1
        if prefix[-1].trade_date > current.trade_date or (
            pool_prefix and pool_prefix[-1].trade_date > current.trade_date
        ):
            raise ValueError("causal replay prefix contains a future row")
        signal = evaluate_strategy(
            bars=prefix,
            as_of=current.trade_date,
            config=config,
            generated_at=datetime.combine(current.trade_date, time(23, 59, 59), tzinfo=timezone.utc),
            limit_pool=tuple(pool_prefix),
            previous_signal=previous_signal,
        )
        metrics["evaluate_strategy_calls"] += 1
        signal = merge_signal_quality(
            signal,
            (DataQuality.OK,),
            insufficient_history=len(prefix) < config.universe.minimum_listing_trade_days,
        )
        if signal.setup_id and signal.setup_stage is not SetupStage.NORMAL:
            stage_dates[signal.setup_id][signal.setup_stage].append(current.trade_date)
        if current.trade_date < start:
            previous_signal = signal
            continue

        # TradePlan is built from this exact prefix; no future calendar is used.
        if signal.setup_stage is SetupStage.WATCH_PULLBACK or signal.setup_stage in {
            SetupStage.B1_READY,
            SetupStage.B2_READY,
            SetupStage.B2_CONFIRMED,
        }:
            plan = build_trade_plan(
                signal=signal,
                bars=prefix,
                limit_pool=tuple(pool_prefix),
                config=config,
                plan_date=current.trade_date,
                for_trade_date=None,
                snapshot_id=snapshot_id,
                strategy_commit=strategy_commit,
                config_hash=strategy_config_hash,
                trade_plan_config=trade_plan_config,
                execution_config_hash=trade_plan_config_hash,
            )
            metrics["trade_plan_calls"] += 1
            if plan.execution_label in TARGET_LABELS:
                key = (signal.setup_id, plan.execution_label)
                raw_counts[key] += 1
                if key not in seen:
                    seen.add(key)
                    events.append(
                        _freeze_event(
                            signal=signal,
                            plan=plan,
                            snapshot_id=snapshot_id,
                            strategy_commit=strategy_commit,
                            strategy_config_hash=strategy_config_hash,
                            trade_plan_config_hash=trade_plan_config_hash,
                            outcome_config_hash=outcome_config_hash,
                            snapshot_created_at=snapshot_created_at,
                        )
                    )
        previous_signal = signal
    metrics["process_cpu_seconds"] = process_time() - replay_cpu_started
    return events, raw_counts, stage_dates, metrics


def _replay_code_worker(
    task: dict[str, object],
) -> tuple[
    list[_FrozenEvent],
    Counter[tuple[str, ExecutionLabel]],
    dict[str, dict[SetupStage, list[date]]],
    dict[str, float],
]:
    """Pickle-safe process worker; one code remains sequential inside it."""

    events, raw_counts, stage_dates, metrics = _replay_code(**task)  # type: ignore[arg-type]
    # `_replay_code` uses nested defaultdicts for the serial path.  Their
    # local lambda factories are not pickleable under macOS spawn, so return a
    # plain structure across the process boundary.
    return (
        events,
        raw_counts,
        {
            setup_id: {
                stage: list(dates) for stage, dates in by_stage.items()
            }
            for setup_id, by_stage in stage_dates.items()
        },
        metrics,
    )


def _update_prep_metrics(
    event: OutcomeEpisode,
    *,
    bars: Sequence[DailyBar],
    stage_dates: dict[SetupStage, list[date]],
    date_index: dict[date, int] | None = None,
) -> OutcomeEpisode:
    if event.execution_label is not ExecutionLabel.B1_PREP:
        return event
    if date_index is None:
        date_index = {bar.trade_date: index for index, bar in enumerate(bars)}
    signal_index = date_index.get(event.signal_date)
    future = (
        bars[signal_index + 1 :]
        if signal_index is not None
        else tuple(bar for bar in bars if bar.trade_date > event.signal_date)
    )
    b1_dates = set(stage_dates.get(SetupStage.B1_READY, ()))
    conversion = {}
    mfe_mae = {}
    reference = next((bar.close for bar in bars if bar.trade_date == event.signal_date), None)
    for horizon in (1, 3, 5):
        window = future[:horizon]
        conversion[horizon] = any(bar.trade_date in b1_dates for bar in window)
        if window and reference is not None and reference > ZERO:
            mfe_mae[horizon] = (
                _quantize(max(bar.high for bar in window) / reference - ONE),
                _quantize(min(bar.low for bar in window) / reference - ONE),
            )
        else:
            mfe_mae[horizon] = (None, None)
    return event.model_copy(
        update={
            "prep_conversion_1d": conversion[1],
            "prep_conversion_3d": conversion[3] if len(future) >= 3 else None,
            "prep_conversion_5d": conversion[5] if len(future) >= 5 else None,
            "prep_mfe_1d": mfe_mae[1][0],
            "prep_mfe_3d": mfe_mae[3][0],
            "prep_mfe_5d": mfe_mae[5][0],
            "prep_mae_1d": mfe_mae[1][1],
            "prep_mae_3d": mfe_mae[3][1],
            "prep_mae_5d": mfe_mae[5][1],
        }
    )


def _compare_frozen(left: OutcomeEpisode, right: OutcomeEpisode) -> bool:
    fields = (
        "code",
        "setup_id",
        "execution_label",
        "setup_stage",
        "signal_date",
        "anchor_date",
        "anchor_price",
        "support_low",
        "support_high",
        "support_center",
        "b2_trigger_price",
        "setup_quality_score",
        "entry_quality_score",
        "entry_room_state",
        "preferred_entry",
        "buy_zone_low",
        "buy_zone_high",
        "invalid_price",
        "s1_price",
        "entry_reference_price",
        "snapshot_created_at",
        "frozen_event_hash",
    )
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def _audit_events(
    events: Sequence[OutcomeEpisode],
    *,
    bars_by_code: dict[str, tuple[DailyBar, ...]],
    pool_by_code: dict[str, tuple[LimitUpRecord, ...]],
    config: StrategyConfig,
    trade_plan_config,
    snapshot_id: str,
    strategy_commit: str,
    strategy_config_hash: str,
    trade_plan_config_hash: str,
    outcome_config_hash: str,
    snapshot_created_at: datetime | None = None,
    sample_size: int = 20,
) -> dict[str, object]:
    candidates = sorted(
        (event for event in events if event.code in bars_by_code),
        key=lambda event: _hash_payload((event.code, event.setup_id, event.execution_label.value, event.signal_date.isoformat())),
    )[:sample_size]
    mismatches: list[str] = []
    for expected in candidates:
        raw, _, _, _ = _replay_code(
            code=expected.code,
            bars=bars_by_code[expected.code],
            pool=pool_by_code.get(expected.code, ()),
            start=expected.signal_date,
            end=expected.signal_date,
            config=config,
            trade_plan_config=trade_plan_config,
            snapshot_id=snapshot_id,
            strategy_commit=strategy_commit,
            strategy_config_hash=strategy_config_hash,
            trade_plan_config_hash=trade_plan_config_hash,
            outcome_config_hash=outcome_config_hash,
            snapshot_created_at=snapshot_created_at,
        )
        matches = [
            _complete_event(event, bars_by_code[expected.code], OutcomeStudyConfig())
            for event in raw
            if event.setup_id == expected.setup_id and event.execution_label is expected.execution_label
        ]
        if not matches or not _compare_frozen(expected, matches[0]):
            mismatches.append(f"{expected.code}:{expected.setup_id}:{expected.signal_date}")
    return {
        "sample_size": len(candidates),
        "mismatches": mismatches,
        "passed": not mismatches and len(candidates) >= min(sample_size, len(events)),
    }


def run_outcome_study(
    *,
    layout: WarehouseLayout,
    snapshot_id: str,
    start: date,
    end: date,
    strategy_config: StrategyConfig,
    strategy_config_path: str | Path,
    trade_plan_config_path: str | Path,
    outcome_config_path: str | Path,
    strategy_commit: str | None = None,
    audit_sample_size: int = 20,
    workers: int = 1,
) -> OutcomeStudySummary:
    if start > end:
        raise ValueError("start cannot be after end")
    if workers < 1:
        raise ValueError("workers must be at least 1")
    # Decimal-heavy strategy evaluation is GIL-bound.  Use processes, but cap
    # concurrency so each code stays sequential and a 16GB workstation is not
    # swamped by one full DailyBar prefix per worker.
    worker_count = min(workers, os.cpu_count() or 1, 8)
    total_started = perf_counter()
    timing: dict[str, float] = {}
    load_started = perf_counter()
    snapshot = _load_snapshot(layout, snapshot_id)
    timing["load_snapshot_seconds"] = perf_counter() - load_started
    if snapshot.as_of < end:
        raise ValueError(f"SNAPSHOT_AS_OF_BEFORE_REQUESTED: {snapshot.as_of} < {end}")
    outcome_config = load_outcome_study_config(outcome_config_path)
    trade_plan_config = load_trade_plan_config(trade_plan_config_path)
    strategy_hash = sha256_file(strategy_config_path)
    trade_plan_hash = sha256_file(trade_plan_config_path)
    outcome_hash = sha256_file(outcome_config_path)
    commit = strategy_commit or _git_head()
    daily_path = _snapshot_file(layout, snapshot, "daily_bars")
    pool_path = _snapshot_file(layout, snapshot, "limit_up_pool")
    pool_started = perf_counter()
    pool_by_code = _load_pool_by_code(pool_path)
    timing["load_pool_seconds"] = perf_counter() - pool_started

    all_events: list[OutcomeEpisode] = []
    raw_counts: Counter[tuple[str, ExecutionLabel]] = Counter()
    bars_for_audit: dict[str, tuple[DailyBar, ...]] = {}
    audit_candidates: dict[str, tuple[str, tuple[DailyBar, ...]]] = {}
    audit_candidate_limit = max(audit_sample_size * 2, audit_sample_size)
    code_count = 0
    confirmed_dates: set[date] = set()
    counters: dict[str, float] = {
        "bars_processed": 0,
        "evaluate_strategy_calls": 0,
        "trade_plan_calls": 0,
        "episodes_generated": 0,
        "total_child_cpu_seconds": 0,
    }

    def consume_result(
        code: str,
        bars: tuple[DailyBar, ...],
        result: tuple[
            list[_FrozenEvent],
            Counter[tuple[str, ExecutionLabel]],
            dict[str, dict[SetupStage, list[date]]],
            dict[str, float],
        ],
    ) -> None:
        label_started = perf_counter()
        raw_events, code_counts, stage_dates, replay_metrics = result
        raw_counts.update(code_counts)
        outcome_bars = tuple(bar for bar in bars if bar.trade_date <= end)
        date_index = {bar.trade_date: index for index, bar in enumerate(outcome_bars)}
        code_events = [
            _complete_event(
                event,
                outcome_bars,
                outcome_config,
                date_index=date_index,
            )
            for event in raw_events
        ]
        for event in code_events:
            event = event.model_copy(
                update={
                    "raw_signal_days": code_counts[
                        (event.setup_id, event.execution_label)
                    ]
                }
            )
            event = _update_prep_metrics(
                event,
                bars=outcome_bars,
                stage_dates=stage_dates.get(event.setup_id, {}),
                date_index=date_index,
            )
            all_events.append(event)
        counters["bars_processed"] += len(outcome_bars)
        counters["evaluate_strategy_calls"] += replay_metrics.get(
            "evaluate_strategy_calls", 0
        )
        counters["trade_plan_calls"] += replay_metrics.get("trade_plan_calls", 0)
        counters["episodes_generated"] += len(code_events)
        counters["total_child_cpu_seconds"] += replay_metrics.get(
            "process_cpu_seconds", 0
        )
        if code_events:
            candidate_key = min(
                _hash_payload(
                    (
                        event.code,
                        event.setup_id,
                        event.execution_label.value,
                        event.signal_date.isoformat(),
                    )
                )
                for event in code_events
            )
            audit_candidates[code] = (candidate_key, bars)
            if len(audit_candidates) > audit_candidate_limit:
                drop_code = max(
                    audit_candidates,
                    key=lambda item: audit_candidates[item][0],
                )
                del audit_candidates[drop_code]
        timing["outcome_label_seconds"] = timing.get(
            "outcome_label_seconds", 0.0
        ) + perf_counter() - label_started

    pending: dict[Future, tuple[str, tuple[DailyBar, ...]]] = {}
    context = mp.get_context("spawn")
    executor: ProcessPoolExecutor | None = None
    if worker_count > 1:
        executor = ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=context,
        )
    try:
        replay_started = perf_counter()
        for code, bars in _iter_confirmed_code_bars(daily_path):
            code_count += 1
            confirmed_dates.update(
                bar.trade_date for bar in bars if start <= bar.trade_date <= end
            )
            task = {
                "code": code,
                "bars": bars,
                "pool": pool_by_code.get(code, ()),
                "start": start,
                "end": end,
                "config": strategy_config,
                "trade_plan_config": trade_plan_config,
                "snapshot_id": snapshot_id,
                "strategy_commit": commit,
                "strategy_config_hash": strategy_hash,
                "trade_plan_config_hash": trade_plan_hash,
                "outcome_config_hash": outcome_hash,
                "snapshot_created_at": snapshot.created_at,
            }
            if executor is None:
                consume_result(code, bars, _replay_code(**task))  # type: ignore[arg-type]
                continue
            future = executor.submit(_replay_code_worker, task)
            pending[future] = (code, bars)
            if len(pending) >= worker_count * 2:
                done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
                for finished in done:
                    finished_code, finished_bars = pending.pop(finished)
                    consume_result(finished_code, finished_bars, finished.result())
        while pending:
            done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for finished in done:
                finished_code, finished_bars = pending.pop(finished)
                consume_result(finished_code, finished_bars, finished.result())
        timing["replay_seconds"] = perf_counter() - replay_started
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    bars_for_audit = {
        code: value[1]
        for code, value in sorted(
            audit_candidates.items(), key=lambda item: item[1][0]
        )
    }
    all_events.sort(key=lambda event: (event.code, event.signal_date, event.execution_label.value, event.setup_id))
    audit_started = perf_counter()
    audit = _audit_events(
        all_events,
        bars_by_code=bars_for_audit,
        pool_by_code=pool_by_code,
        config=strategy_config,
        trade_plan_config=trade_plan_config,
        snapshot_id=snapshot_id,
        strategy_commit=commit,
        strategy_config_hash=strategy_hash,
        trade_plan_config_hash=trade_plan_hash,
        outcome_config_hash=outcome_hash,
        snapshot_created_at=snapshot.created_at,
        sample_size=min(audit_sample_size, len(bars_for_audit)),
    )
    timing["audit_seconds"] = perf_counter() - audit_started
    if not audit["passed"]:
        raise ValueError(f"causal replay audit mismatch: {audit['mismatches']}")

    stage_events = {
        label.value: [event for event in all_events if event.execution_label is label]
        for label in (
            ExecutionLabel.B1_READY,
            ExecutionLabel.B2_READY,
            ExecutionLabel.B2_CONFIRMED,
        )
    }
    structural_stage_stats = {
        stage: _stats(events) for stage, events in stage_events.items()
    }
    actionable_stage_stats = {
        stage: _stats(events, actionable_only=True)
        for stage, events in stage_events.items()
    }
    # Keep the historical stage_stats key as the primary/actionable view.
    stage_stats = actionable_stage_stats
    target_events = [
        event
        for event in all_events
        if event.execution_label in {
            ExecutionLabel.B1_READY,
            ExecutionLabel.B2_READY,
            ExecutionLabel.B2_CONFIRMED,
        }
    ]
    pattern_success: dict[str, dict[str, int]] = {}
    for horizon in outcome_config.forward_horizons:
        field = f"pattern_{horizon}d"
        counts = Counter(
            getattr(event, field).value
            for event in target_events
            if getattr(event, field) is not None
        )
        pattern_success[f"{horizon}d"] = dict(sorted(counts.items()))

    actionable_setup_quality_groups = _group_stats(
        target_events,
        lambda event: _group_bucket(event.setup_quality_score),
        actionable_only=True,
        expected_keys=QUALITY_GROUP_KEYS,
    )
    actionable_entry_quality_groups = _group_stats(
        target_events,
        lambda event: _group_bucket(event.entry_quality_score),
        actionable_only=True,
        expected_keys=QUALITY_GROUP_KEYS,
    )
    actionable_days_since_anchor_groups = _group_stats(
        target_events,
        lambda event: _days_bucket(event.days_since_anchor),
        actionable_only=True,
        expected_keys=DAYS_GROUP_KEYS,
    )
    structural_setup_quality_groups = _group_stats(
        target_events,
        lambda event: _group_bucket(event.setup_quality_score),
        expected_keys=QUALITY_GROUP_KEYS,
    )
    structural_entry_quality_groups = _group_stats(
        target_events,
        lambda event: _group_bucket(event.entry_quality_score),
        expected_keys=QUALITY_GROUP_KEYS,
    )
    structural_days_since_anchor_groups = _group_stats(
        target_events,
        lambda event: _days_bucket(event.days_since_anchor),
        expected_keys=DAYS_GROUP_KEYS,
    )

    status_started = perf_counter()
    provisional_dates = 0
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        # Canonical availability is the study universe; provisional-only days
        # are detected from snapshot rows without inventing sessions.
        snapshot_daily = metadata.snapshot_by_id(snapshot_id)
    if snapshot_daily is None:
        raise ValueError(f"unknown snapshot: {snapshot_id}")
    status_by_date: dict[date, set[str]] = defaultdict(set)
    for batch in pq.ParquetFile(daily_path).iter_batches(
        columns=["trade_date", "reconciliation_status"],
        batch_size=65536,
        use_threads=False,
    ):
        for row in batch.to_pylist():
            status_by_date[row["trade_date"]].add(
                str(row["reconciliation_status"])
            )
        del batch
    provisional_dates = sum(
        1
        for trade_date, values in status_by_date.items()
        if "CONFIRMED" not in values and values
        and start <= trade_date <= end
    )
    timing["status_scan_seconds"] = perf_counter() - status_started

    for metric in (
        "replay_seconds",
        "outcome_label_seconds",
        "audit_seconds",
        "summary_write_seconds",
    ):
        timing.setdefault(metric, 0.0)
    performance: dict[str, object] = {
        **timing,
        **counters,
        "codes_processed": code_count,
        "episodes_generated": len(all_events),
        "worker_count": worker_count,
        "python_architecture": os.uname().machine,
    }
    performance["total_seconds"] = perf_counter() - total_started
    audit_with_metrics = {
        "performance": performance,
    }

    summary = OutcomeStudySummary(
        dataset_mode=DATASET_MODE,
        snapshot_id=snapshot_id,
        start=start,
        end=end,
        confirmed_date_count=len(confirmed_dates),
        confirmed_code_count=code_count,
        provisional_only_date_count=provisional_dates,
        raw_signal_days=sum(raw_counts.values()),
        episode_count=len(all_events),
        b1_prep_episodes=sum(event.execution_label is ExecutionLabel.B1_PREP for event in all_events),
        stage_stats=stage_stats,
        actionable_stage_stats=actionable_stage_stats,
        structural_stage_stats=structural_stage_stats,
        actionable_setup_quality_groups=actionable_setup_quality_groups,
        actionable_entry_quality_groups=actionable_entry_quality_groups,
        actionable_days_since_anchor_groups=actionable_days_since_anchor_groups,
        structural_setup_quality_groups=structural_setup_quality_groups,
        structural_entry_quality_groups=structural_entry_quality_groups,
        structural_days_since_anchor_groups=structural_days_since_anchor_groups,
        # Legacy names are intentionally aliases of the primary actionable
        # cohort, never the mixed structural population.
        setup_quality_groups=actionable_setup_quality_groups,
        entry_quality_groups=actionable_entry_quality_groups,
        days_since_anchor_groups=actionable_days_since_anchor_groups,
        pattern_success=pattern_success,
        audit={
            **audit,
            **audit_with_metrics,
            "workers": worker_count,
            "future_bar_leakage": False,
            "future_pool_leakage": False,
            "future_state_leakage": False,
            "historical_vintage_authenticity": "UNAVAILABLE_FINAL_VINTAGE",
        },
        performance=performance,
        limitations=(
            "current final-vintage canonical data",
            "historical revision authenticity unavailable",
            "historical universe may contain survivorship / coverage bias",
            "daily OHLC ambiguity",
            "execution costs not modeled",
            "true A-share T+1 execution not modeled in Phase 2D.0",
            "provisional-only dates are excluded rather than interpolated",
        ),
        strategy_commit=commit,
        strategy_config_hash=strategy_hash,
        trade_plan_config_hash=trade_plan_hash,
        outcome_config_hash=outcome_hash,
    )
    run_id = f"outcome-{snapshot_id}-{start.isoformat()}-{end.isoformat()}-{outcome_hash[:12]}"
    output_dir = layout.root / "outcome-study" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    write_started = perf_counter()
    _write_episodes(output_dir / "episodes.parquet", all_events)
    (output_dir / "summary.md").write_text(
        _summary_markdown(summary), encoding="utf-8"
    )
    performance["summary_write_seconds"] = perf_counter() - write_started
    performance["total_seconds"] = perf_counter() - total_started
    summary = summary.model_copy(
        update={
            "performance": performance,
            "audit": {
                **summary.audit,
                "performance": performance,
            },
        }
    )
    (output_dir / "summary.json").write_text(
        summary.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "summary.md").write_text(
        _summary_markdown(summary), encoding="utf-8"
    )
    return summary


__all__ = ["run_outcome_study"]
