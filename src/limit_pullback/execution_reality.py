"""Phase 2D.1A T+1 / GAP execution-reality relabeling.

This module consumes the corrected, frozen Phase 2D.0 episodes and canonical
daily bars only.  It does not call ``evaluate_strategy`` and does not change
the frozen signal, fill, or outcome fields.  The implementation is a daily-bar
execution model for ordinary A-share T+1 selling.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import json
from math import floor
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from limit_pullback.models.enums import ExecutionLabel, FillType, OutcomeStatus
from limit_pullback.models.execution_reality import (
    ExecutionRealityEpisode,
    ExecutionRealitySummary,
)
from limit_pullback.models.market import DailyBar
from limit_pullback.outcome import (
    _iter_confirmed_code_bars,
    _load_frozen_episodes,
    _load_snapshot,
    _snapshot_file,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.parquet import sha256_file


CORRECTED_EPISODES_SHA256 = (
    "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
)
MAX_HOLDING_SESSIONS = 10
FRICTION_BPS = (0, 10, 20, 30)
ZERO = Decimal("0")
ONE = Decimal("1")
BPS_QUANTUM = Decimal("0.0001")
R_QUANTUM = Decimal("0.0001")

ACTIONABLE_LABELS = frozenset(
    {
        ExecutionLabel.B1_READY,
        ExecutionLabel.B2_READY,
        ExecutionLabel.B2_CONFIRMED,
    }
)

STATUS_NO_FILL = "NO_FILL"
STATUS_NON_ACTIONABLE = "NON_ACTIONABLE"
STATUS_RESOLVED = "RESOLVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_CENSORED = "CENSORED"
STATUS_INVALID_PLAN = "INVALID_PLAN"

FILL_DAY_STOP_NONE = "NONE"
FILL_DAY_STOP_T1_BLOCKED = "STOP_TRIGGERED_T1_BLOCKED"
FILL_DAY_STOP_AMBIGUOUS = "AMBIGUOUS_FILL_DAY_STOP_ORDER"
FILL_DAY_TARGET_NONE = "NONE"
FILL_DAY_TARGET_MISSED = "MISSED_SAME_DAY_TARGET_T1"
FILL_DAY_TARGET_ORDER_UNKNOWN = "FILL_DAY_TARGET_ORDER_UNKNOWN"
PRICE_LIMIT_NOT_MODELED = "PRICE_LIMIT_EXECUTION_NOT_MODELED"
PRICE_LIMIT_MODELED = "MODELED"
PRICE_LIMIT_LOCKED = "LOCKED_LIMIT_DOWN_NO_EXIT"


@dataclass(frozen=True)
class _Exit:
    status: str
    exit_type: str | None = None
    exit_date: date | None = None
    exit_price: Decimal | None = None
    holding_sessions: int | None = None


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(R_QUANTUM, rounding=ROUND_HALF_UP)


def _quantize_pct(value: Decimal) -> Decimal:
    return value.quantize(BPS_QUANTUM, rounding=ROUND_HALF_UP)


def _as_decimal(value: object) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _is_filled(event) -> bool:
    return event.fill_status.value == "FILLED" and event.fill_date is not None and event.fill_price is not None


def _is_target_exit(exit_type: str | None) -> bool:
    return exit_type in {"TARGET", "GAP_TARGET"}


def _is_stop_exit(exit_type: str | None) -> bool:
    return exit_type in {
        "STOP",
        "GAP_STOP",
        "STOP_FIRST",
        "STOP_TRIGGERED_T1_BLOCKED",
    }


def _status_from_original_fill(event) -> str:
    if not event.is_entry_candidate:
        return STATUS_NON_ACTIONABLE
    if event.fill_status.value == "CENSORED":
        return STATUS_CENSORED
    return STATUS_NO_FILL


def _empty_derived(event, *, status: str) -> ExecutionRealityEpisode:
    """Build a no-fill row while retaining every frozen field verbatim."""

    return ExecutionRealityEpisode.model_validate(
        {
            **event.model_dump(mode="python"),
            "strict_execution_status": status,
            "conservative_execution_status": status,
            "price_limit_execution_status": PRICE_LIMIT_NOT_MODELED,
        }
    )


def _fill_day_states(event, fill_bar: DailyBar) -> tuple[str, str]:
    if event.fill_type in {FillType.OPEN_FILL, FillType.BREAKOUT_GAP_FILL}:
        stop_state = (
            FILL_DAY_STOP_T1_BLOCKED
            if fill_bar.low <= event.invalid_price
            else FILL_DAY_STOP_NONE
        )
    else:
        stop_state = (
            FILL_DAY_STOP_AMBIGUOUS
            if fill_bar.low <= event.invalid_price
            else FILL_DAY_STOP_NONE
        )
    if fill_bar.high < event.s1_price:
        target_state = FILL_DAY_TARGET_NONE
    elif event.fill_type is FillType.INTRADAY_TOUCH_FILL:
        # Daily OHLC cannot establish whether an intraday-touch fill happened
        # before or after a same-day target high.  Keep this informational
        # state separate from the known post-entry cases.
        target_state = FILL_DAY_TARGET_ORDER_UNKNOWN
    else:
        target_state = FILL_DAY_TARGET_MISSED
    return stop_state, target_state


def _terminal_for_window(
    *,
    bars: Sequence[DailyBar],
    fill_index: int,
    end_index: int,
) -> _Exit:
    available = end_index - fill_index
    if available < MAX_HOLDING_SESSIONS:
        return _Exit(STATUS_CENSORED, holding_sessions=available or None)
    return _Exit(STATUS_TIMEOUT, holding_sessions=MAX_HOLDING_SESSIONS)


def _down_limit_for(
    price_limits: Mapping[date, object] | None,
    bar: DailyBar,
) -> Decimal | None:
    if price_limits is None:
        return None
    value = price_limits.get(bar.trade_date)
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = value.get("down_limit")
    else:
        value = getattr(value, "down_limit", value)
    return _as_decimal(value)


def _is_locked_limit_down(
    bar: DailyBar,
    price_limits: Mapping[date, object] | None,
) -> bool:
    down_limit = _down_limit_for(price_limits, bar)
    return (
        down_limit is not None
        and bar.open == down_limit
        and bar.high == down_limit
        and bar.low == down_limit
        and bar.close == down_limit
    )


def _resolve_execution(
    event,
    bars: Sequence[DailyBar],
    *,
    fill_index: int,
    fill_day_stop_state: str,
    price_limits: Mapping[date, object] | None = None,
) -> tuple[_Exit, _Exit, date | None, int | None, str]:
    """Return strict, conservative, first sell date and holding sessions."""

    end_index = min(len(bars), fill_index + MAX_HOLDING_SESSIONS)
    sell_index = fill_index + 1
    sell_date = bars[sell_index].trade_date if sell_index < len(bars) else None

    price_limit_status = PRICE_LIMIT_NOT_MODELED if price_limits is None else PRICE_LIMIT_MODELED
    if sell_index >= end_index:
        terminal = _terminal_for_window(
            bars=bars,
            fill_index=fill_index,
            end_index=end_index,
        )
        if fill_day_stop_state == FILL_DAY_STOP_AMBIGUOUS:
            return _Exit(STATUS_AMBIGUOUS, holding_sessions=terminal.holding_sessions), terminal, sell_date, terminal.holding_sessions, price_limit_status
        return terminal, terminal, sell_date, terminal.holding_sessions, price_limit_status

    if fill_day_stop_state == FILL_DAY_STOP_T1_BLOCKED:
        for index in range(sell_index, end_index):
            next_bar = bars[index]
            if _is_locked_limit_down(next_bar, price_limits):
                price_limit_status = PRICE_LIMIT_LOCKED
                continue
            holding = index - fill_index + 1
            exit_value = _Exit(
                STATUS_RESOLVED,
                "STOP_TRIGGERED_T1_BLOCKED",
                next_bar.trade_date,
                next_bar.open,
                holding,
            )
            return exit_value, exit_value, sell_date, holding, price_limit_status
        terminal = _terminal_for_window(bars=bars, fill_index=fill_index, end_index=end_index)
        return terminal, terminal, sell_date, terminal.holding_sessions, price_limit_status

    if fill_day_stop_state == FILL_DAY_STOP_AMBIGUOUS:
        for index in range(sell_index, end_index):
            next_bar = bars[index]
            if _is_locked_limit_down(next_bar, price_limits):
                price_limit_status = PRICE_LIMIT_LOCKED
                continue
            holding = index - fill_index + 1
            conservative = _Exit(
                STATUS_RESOLVED,
                "STOP_TRIGGERED_T1_BLOCKED",
                next_bar.trade_date,
                next_bar.open,
                holding,
            )
            strict = _Exit(STATUS_AMBIGUOUS, holding_sessions=holding)
            return strict, conservative, sell_date, holding, price_limit_status
        terminal = _terminal_for_window(bars=bars, fill_index=fill_index, end_index=end_index)
        return _Exit(STATUS_AMBIGUOUS, holding_sessions=terminal.holding_sessions), terminal, sell_date, terminal.holding_sessions, price_limit_status

    for index in range(sell_index, end_index):
        bar = bars[index]
        holding = index - fill_index + 1
        if _is_locked_limit_down(bar, price_limits):
            price_limit_status = PRICE_LIMIT_LOCKED
            continue
        if bar.open <= event.invalid_price:
            result = _Exit(STATUS_RESOLVED, "GAP_STOP", bar.trade_date, bar.open, holding)
            return result, result, sell_date, holding, price_limit_status
        if bar.open >= event.s1_price:
            result = _Exit(STATUS_RESOLVED, "GAP_TARGET", bar.trade_date, event.s1_price, holding)
            return result, result, sell_date, holding, price_limit_status
        hit_invalid = bar.low <= event.invalid_price
        hit_target = bar.high >= event.s1_price
        if hit_invalid and hit_target:
            strict = _Exit(STATUS_AMBIGUOUS, holding_sessions=holding)
            conservative = _Exit(
                STATUS_RESOLVED,
                "STOP_FIRST",
                bar.trade_date,
                event.invalid_price,
                holding,
            )
            return strict, conservative, sell_date, holding, price_limit_status
        if hit_invalid:
            result = _Exit(STATUS_RESOLVED, "STOP", bar.trade_date, event.invalid_price, holding)
            return result, result, sell_date, holding, price_limit_status
        if hit_target:
            result = _Exit(STATUS_RESOLVED, "TARGET", bar.trade_date, event.s1_price, holding)
            return result, result, sell_date, holding, price_limit_status

    terminal = _terminal_for_window(
        bars=bars,
        fill_index=fill_index,
        end_index=end_index,
    )
    return terminal, terminal, sell_date, terminal.holding_sessions, price_limit_status


def _return_values(
    *,
    fill_price: Decimal,
    risk_abs: Decimal,
    exit_value: _Exit,
) -> tuple[Decimal | None, Decimal | None]:
    if exit_value.status != STATUS_RESOLVED or exit_value.exit_price is None:
        return None, None
    gross_pct = _quantize_pct(exit_value.exit_price / fill_price - ONE)
    gross_r = _quantize((exit_value.exit_price - fill_price) / risk_abs)
    return gross_pct, gross_r


def _friction_values(
    *,
    gross_pct: Decimal | None,
    risk_pct: Decimal,
) -> dict[str, Decimal | None]:
    values: dict[str, Decimal | None] = {}
    for bp in FRICTION_BPS:
        net_pct = (
            _quantize_pct(gross_pct - Decimal(bp) / Decimal("10000"))
            if gross_pct is not None
            else None
        )
        net_r = _quantize(net_pct / risk_pct) if net_pct is not None else None
        values[f"net_return_pct_{bp}bp"] = net_pct
        values[f"net_execution_R_{bp}bp"] = net_r
    return values


def _update_frozen_row(event, row: ExecutionRealityEpisode) -> None:
    before = event.model_dump(mode="python")
    after = row.model_dump(mode="python")
    for field in type(event).model_fields:
        if before[field] != after[field]:
            raise AssertionError(
                f"frozen field changed during execution relabel: {event.code}:{event.signal_date}:{field}"
            )
    if row.frozen_event_hash != event.frozen_event_hash:
        raise AssertionError("frozen_event_hash changed during execution relabel")


def relabel_execution_episode(
    event,
    bars: Sequence[DailyBar],
    *,
    price_limits: Mapping[date, object] | None = None,
) -> ExecutionRealityEpisode:
    """Apply T+1 execution semantics to one frozen episode."""

    if not event.is_entry_candidate or not _is_filled(event):
        row = _empty_derived(event, status=_status_from_original_fill(event))
        _update_frozen_row(event, row)
        return row

    fill_price = event.fill_price
    invalid = event.invalid_price
    s1 = event.s1_price
    if fill_price is None or invalid is None or s1 is None or fill_price <= invalid:
        row = _empty_derived(event, status=STATUS_INVALID_PLAN)
        _update_frozen_row(event, row)
        return row

    index_by_date = {bar.trade_date: index for index, bar in enumerate(bars)}
    fill_index = index_by_date.get(event.fill_date)
    if fill_index is None:
        row = _empty_derived(event, status=STATUS_CENSORED)
        _update_frozen_row(event, row)
        return row

    fill_bar = bars[fill_index]
    stop_state, target_state = _fill_day_states(event, fill_bar)
    strict, conservative, sell_date, holding, price_limit_status = _resolve_execution(
        event,
        bars,
        fill_index=fill_index,
        fill_day_stop_state=stop_state,
        price_limits=price_limits,
    )
    risk_abs = fill_price - invalid
    risk_pct = _quantize_pct(risk_abs / fill_price)
    strict_pct, strict_r = _return_values(
        fill_price=fill_price,
        risk_abs=risk_abs,
        exit_value=strict,
    )
    conservative_pct, conservative_r = _return_values(
        fill_price=fill_price,
        risk_abs=risk_abs,
        exit_value=conservative,
    )
    strict_friction = _friction_values(gross_pct=strict_pct, risk_pct=risk_pct)
    conservative_friction = _friction_values(
        gross_pct=conservative_pct,
        risk_pct=risk_pct,
    )
    payload = {
        **event.model_dump(mode="python"),
        "entry_price_theoretical": fill_price,
        "planned_risk_abs": risk_abs,
        "planned_risk_pct": risk_pct,
        "fill_day_stop_state": stop_state,
        "fill_day_target_state": target_state,
        "sell_eligible_date": sell_date,
        "execution_exit_type": strict.exit_type,
        "execution_exit_date": strict.exit_date,
        "execution_exit_price": strict.exit_price,
        "gross_return_pct": strict_pct,
        "gross_execution_R": strict_r,
        **strict_friction,
        "conservative_execution_exit_type": conservative.exit_type,
        "conservative_execution_exit_date": conservative.exit_date,
        "conservative_execution_exit_price": conservative.exit_price,
        "conservative_gross_return_pct": conservative_pct,
        "conservative_gross_execution_R": conservative_r,
        **{
            f"conservative_{key}": value
            for key, value in conservative_friction.items()
        },
        "holding_sessions": holding,
        "strict_execution_status": strict.status,
        "conservative_execution_status": conservative.status,
        "price_limit_execution_status": price_limit_status,
    }
    row = ExecutionRealityEpisode.model_validate(payload)
    _update_frozen_row(event, row)
    return row


def _percentile(values: Sequence[Decimal], fraction: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return _quantize(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - Decimal(lower)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * weight
    return _quantize(value)


def _mean(values: Iterable[Decimal]) -> Decimal | None:
    values = list(values)
    return _quantize(sum(values, ZERO) / Decimal(len(values))) if values else None


def _metric_values(rows: Sequence[ExecutionRealityEpisode], field: str) -> list[Decimal]:
    return [value for row in rows if (value := getattr(row, field)) is not None]


def _stats(rows: Sequence[ExecutionRealityEpisode]) -> dict[str, object]:
    filled = [row for row in rows if row.fill_status.value == "FILLED"]
    strict_resolved = [row for row in filled if row.strict_execution_status == STATUS_RESOLVED]
    conservative_resolved = [row for row in filled if row.conservative_execution_status == STATUS_RESOLVED]
    strict_r = _metric_values(strict_resolved, "gross_execution_R")
    conservative_r = _metric_values(conservative_resolved, "conservative_gross_execution_R")
    strict_wins = [row for row in strict_resolved if _is_target_exit(row.execution_exit_type)]
    conservative_wins = [row for row in conservative_resolved if _is_target_exit(row.conservative_execution_exit_type)]
    strict_losses = [row for row in strict_resolved if _is_stop_exit(row.execution_exit_type)]
    conservative_losses = [row for row in conservative_resolved if _is_stop_exit(row.conservative_execution_exit_type)]
    # ``GAP_STOP`` is reserved for a sell-eligible session opening below the
    # invalid price.  Fill-day T+1-blocked stops and order ambiguity are
    # reported separately and must not inflate the gap-stop rate.
    gap_stops = [row for row in filled if row.execution_exit_type == "GAP_STOP"]

    def rate(numerator: int, denominator: int) -> Decimal:
        return _quantize_pct(Decimal(numerator) / Decimal(denominator)) if denominator else ZERO

    result: dict[str, object] = {
        "episodes": len(rows),
        "filled": len(filled),
        "strict_resolved": len(strict_resolved),
        "conservative_resolved": len(conservative_resolved),
        "strict_win_rate": rate(len(strict_wins), len(strict_resolved)),
        "conservative_win_rate": rate(len(conservative_wins), len(conservative_resolved)),
        "gross_E_R": _mean(strict_r),
        "strict_gross_E_R": _mean(strict_r),
        "conservative_gross_E_R": _mean(conservative_r),
        "10bp_E_R": _mean(_metric_values(strict_resolved, "net_execution_R_10bp")),
        "20bp_E_R": _mean(_metric_values(strict_resolved, "net_execution_R_20bp")),
        "30bp_E_R": _mean(_metric_values(strict_resolved, "net_execution_R_30bp")),
        "strict_10bp_E_R": _mean(_metric_values(strict_resolved, "net_execution_R_10bp")),
        "strict_20bp_E_R": _mean(_metric_values(strict_resolved, "net_execution_R_20bp")),
        "strict_30bp_E_R": _mean(_metric_values(strict_resolved, "net_execution_R_30bp")),
        "conservative_10bp_E_R": _mean(_metric_values(conservative_resolved, "conservative_net_execution_R_10bp")),
        "conservative_20bp_E_R": _mean(_metric_values(conservative_resolved, "conservative_net_execution_R_20bp")),
        "conservative_30bp_E_R": _mean(_metric_values(conservative_resolved, "conservative_net_execution_R_30bp")),
        "average_win_R": _mean(_metric_values(strict_wins, "gross_execution_R")),
        "average_loss_R": _mean(_metric_values(strict_losses, "gross_execution_R")),
        "conservative_average_win_R": _mean(_metric_values(conservative_wins, "conservative_gross_execution_R")),
        "conservative_average_loss_R": _mean(_metric_values(conservative_losses, "conservative_gross_execution_R")),
        "median_R": _percentile(strict_r, Decimal("0.50")),
        "p10_R": _percentile(strict_r, Decimal("0.10")),
        "p90_R": _percentile(strict_r, Decimal("0.90")),
        "p99_R": _percentile(strict_r, Decimal("0.99")),
        "conservative_median_R": _percentile(conservative_r, Decimal("0.50")),
        "conservative_p10_R": _percentile(conservative_r, Decimal("0.10")),
        "conservative_p90_R": _percentile(conservative_r, Decimal("0.90")),
        "conservative_p99_R": _percentile(conservative_r, Decimal("0.99")),
        "gap_stop_count": len(gap_stops),
        "gap_stop_rate": rate(len(gap_stops), len(filled)),
        "loss_R_lt_minus_1": sum(value < Decimal("-1") for value in strict_r),
        "loss_R_lt_minus_2": sum(value < Decimal("-2") for value in strict_r),
        "loss_R_lt_minus_3": sum(value < Decimal("-3") for value in strict_r),
        "conservative_loss_R_lt_minus_1": sum(value < Decimal("-1") for value in conservative_r),
        "conservative_loss_R_lt_minus_2": sum(value < Decimal("-2") for value in conservative_r),
        "conservative_loss_R_lt_minus_3": sum(value < Decimal("-3") for value in conservative_r),
        "MISSED_SAME_DAY_TARGET_T1": sum(row.fill_day_target_state == FILL_DAY_TARGET_MISSED for row in filled),
        "FILL_DAY_TARGET_ORDER_UNKNOWN": sum(row.fill_day_target_state == FILL_DAY_TARGET_ORDER_UNKNOWN for row in filled),
        "STOP_TRIGGERED_T1_BLOCKED": sum(row.fill_day_stop_state == FILL_DAY_STOP_T1_BLOCKED for row in filled),
        "AMBIGUOUS_FILL_DAY_STOP_ORDER": sum(row.fill_day_stop_state == FILL_DAY_STOP_AMBIGUOUS for row in filled),
        "TIMEOUT": sum(row.strict_execution_status == STATUS_TIMEOUT for row in filled),
        "CENSORED": sum(row.strict_execution_status == STATUS_CENSORED for row in filled),
        "AMBIGUOUS": sum(row.strict_execution_status == STATUS_AMBIGUOUS for row in filled),
    }
    return result


def _cohort_rows(rows: Sequence[ExecutionRealityEpisode], name: str) -> list[ExecutionRealityEpisode]:
    if name == "B1_READY_ALL":
        return [row for row in rows if row.is_entry_candidate and row.execution_label is ExecutionLabel.B1_READY]
    if name == "B1_READY_SETUP_GE_80":
        return [row for row in _cohort_rows(rows, "B1_READY_ALL") if row.setup_quality_score >= Decimal("80")]
    if name == "B1_READY_ENTRY_GE_80":
        return [row for row in _cohort_rows(rows, "B1_READY_ALL") if row.entry_quality_score is not None and row.entry_quality_score >= Decimal("80")]
    if name == "B2_READY_ALL":
        return [row for row in rows if row.is_entry_candidate and row.execution_label is ExecutionLabel.B2_READY]
    if name == "B2_READY_BREAKOUT_GAP_FILL":
        return [row for row in _cohort_rows(rows, "B2_READY_ALL") if row.fill_type is FillType.BREAKOUT_GAP_FILL]
    if name == "B2_READY_BREAKOUT_TRIGGER_FILL":
        return [row for row in _cohort_rows(rows, "B2_READY_ALL") if row.fill_type is FillType.BREAKOUT_TRIGGER_FILL]
    if name == "B2_CONFIRMED_ALL":
        return [row for row in rows if row.is_entry_candidate and row.execution_label is ExecutionLabel.B2_CONFIRMED]
    raise KeyError(name)


def _tail_summary(rows: Sequence[ExecutionRealityEpisode], name: str) -> dict[str, object]:
    cohort = _cohort_rows(rows, name)
    original_winners = [row for row in cohort if row.outcome is OutcomeStatus.WIN_S1]
    known_post_entry = [
        row
        for row in original_winners
        if row.fill_day_target_state == FILL_DAY_TARGET_MISSED
    ]
    target_order_unknown = [
        row
        for row in original_winners
        if row.fill_day_target_state == FILL_DAY_TARGET_ORDER_UNKNOWN
    ]
    touched = known_post_entry
    final = {
        "WIN": sum(row.strict_execution_status == STATUS_RESOLVED and _is_target_exit(row.execution_exit_type) for row in touched),
        "LOSS": sum(row.strict_execution_status == STATUS_RESOLVED and _is_stop_exit(row.execution_exit_type) for row in touched),
        "TIMEOUT": sum(row.strict_execution_status == STATUS_TIMEOUT for row in touched),
        "AMBIGUOUS": sum(row.strict_execution_status == STATUS_AMBIGUOUS for row in touched),
        "CENSORED": sum(row.strict_execution_status == STATUS_CENSORED for row in touched),
    }
    large = [row for row in original_winners if row.r_multiple is not None and row.r_multiple >= Decimal("10")]
    final_gross = _metric_values(large, "gross_execution_R")
    final_10bp = _metric_values(large, "net_execution_R_10bp")
    return {
        "original_WIN_count": len(original_winners),
        "KNOWN_POST_ENTRY_FILL_DAY_TARGET": len(known_post_entry),
        "TARGET_ORDER_UNKNOWN": len(target_order_unknown),
        "known_post_entry_fill_day_target_share": _quantize_pct(Decimal(len(known_post_entry)) / Decimal(len(original_winners))) if original_winners else ZERO,
        "target_order_unknown_share": _quantize_pct(Decimal(len(target_order_unknown)) / Decimal(len(original_winners))) if original_winners else ZERO,
        "fill_day_target_touched_count": len(touched),
        "fill_day_target_touched_share": _quantize_pct(Decimal(len(touched)) / Decimal(len(original_winners))) if original_winners else ZERO,
        "fill_day_target_touched_definition": "KNOWN_POST_ENTRY_FILL_DAY_TARGET only; TARGET_ORDER_UNKNOWN is excluded",
        "share_denominator": "original_WIN_count",
        "fill_day_target_final_status": final,
        "original_R_ge_10_winner_count": len(large),
        "original_R_ge_10_T1_gross_mean_R": _mean(final_gross),
        "original_R_ge_10_T1_gross_median_R": _percentile(final_gross, Decimal("0.50")),
        "original_R_ge_10_T1_10bp_mean_R": _mean(final_10bp),
    }


def _comparison(stats: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    baselines = {
        "B1_READY_SETUP_GE_80": {"phase_2d0_theoretical_gross_E_R": Decimal("0.1557")},
        "B1_READY_ENTRY_GE_80": {"phase_2d0_theoretical_gross_E_R": Decimal("0.1686")},
        "B2_READY_BREAKOUT_GAP_FILL": {
            "phase_2d0_theoretical_strict_E_R": Decimal("0.0399"),
            "phase_2d0_theoretical_conservative_E_R": Decimal("0.0321"),
        },
    }
    output: dict[str, dict[str, object]] = {}
    for name, baseline in baselines.items():
        current = stats[name]
        output[name] = {
            **baseline,
            "t1_gross_E_R": current["strict_gross_E_R"],
            "t1_10bp_E_R": current["strict_10bp_E_R"],
            "t1_20bp_E_R": current["strict_20bp_E_R"],
            "t1_30bp_E_R": current["strict_30bp_E_R"],
            "t1_conservative_gross_E_R": current["conservative_gross_E_R"],
            "t1_conservative_10bp_E_R": current["conservative_10bp_E_R"],
            "t1_conservative_20bp_E_R": current["conservative_20bp_E_R"],
            "t1_conservative_30bp_E_R": current["conservative_30bp_E_R"],
        }
    return output


def _b2_trigger_ambiguity(rows: Sequence[ExecutionRealityEpisode]) -> dict[str, object]:
    source = [
        row
        for row in rows
        if row.is_entry_candidate
        and row.execution_label is ExecutionLabel.B2_READY
        and row.fill_type is FillType.BREAKOUT_TRIGGER_FILL
        and row.outcome is OutcomeStatus.AMBIGUOUS_INTRADAY
    ]
    return {
        "original_ambiguous": len(source),
        "RESOLVED_BY_T1_MODEL": sum(row.strict_execution_status == STATUS_RESOLVED for row in source),
        "STILL_ORDER_AMBIGUOUS": sum(row.strict_execution_status == STATUS_AMBIGUOUS for row in source),
        "TIMEOUT": sum(row.strict_execution_status == STATUS_TIMEOUT for row in source),
        "CENSORED": sum(row.strict_execution_status == STATUS_CENSORED for row in source),
        "unique_codes": len({row.code for row in source}),
    }


def _write_episodes(path: Path, rows: Sequence[ExecutionRealityEpisode]) -> None:
    serialized = [row.model_dump(mode="json") for row in rows]
    if not serialized:
        table = pa.table({"code": pa.array([], type=pa.string())})
    else:
        keys = tuple(serialized[0])
        normalized = {
            key: [
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (list, dict))
                else value
                for value in (row.get(key) for row in serialized)
            ]
            for key in keys
        }
        table = pa.Table.from_pydict(normalized)
    pq.write_table(table, path, compression="zstd")


def _json_ready(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _render_markdown(summary: ExecutionRealitySummary) -> str:
    payload = json.dumps(
        _json_ready(summary.model_dump(mode="python")),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return "\n".join(
        [
            "PHASE 2D.1A EXECUTION REALITY CHECK",
            "",
            "T+1 DAILY-BAR MODEL",
            "",
            "NOT STRATEGY OPTIMIZATION",
            "",
            "NOT PORTFOLIO BACKTEST",
            "",
            "## Summary JSON",
            "",
            "```",
            payload,
            "```",
            "",
        ]
    )


def run_execution_reality_check(
    *,
    layout: WarehouseLayout,
    snapshot_id: str,
    episodes_path: Path,
    output_dir: Path | None = None,
    expected_sha256: str = CORRECTED_EPISODES_SHA256,
) -> dict[str, object]:
    """Create the immutable-derived Phase 2D.1A artifact."""

    started = perf_counter()
    actual_sha256 = sha256_file(episodes_path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"episodes artifact hash mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    episodes = _load_frozen_episodes(episodes_path)
    snapshot = _load_snapshot(layout, snapshot_id)
    daily_path = _snapshot_file(layout, snapshot, "daily_bars")
    by_code: dict[str, list] = defaultdict(list)
    for event in episodes:
        by_code[event.code].append(event)

    derived: list[ExecutionRealityEpisode] = []
    seen_codes: set[str] = set()
    for code, bars in _iter_confirmed_code_bars(daily_path):
        events = by_code.get(code)
        if not events:
            continue
        seen_codes.add(code)
        for event in events:
            derived.append(relabel_execution_episode(event, bars))
    for code in sorted(set(by_code) - seen_codes):
        for event in by_code[code]:
            derived.append(_empty_derived(event, status=STATUS_CENSORED))

    derived.sort(key=lambda row: (row.code, row.signal_date, row.execution_label.value, row.setup_id))
    if len(derived) != len(episodes):
        raise AssertionError("execution relabel changed episode count")

    cohort_names = (
        "B1_READY_ALL",
        "B1_READY_SETUP_GE_80",
        "B1_READY_ENTRY_GE_80",
        "B2_READY_ALL",
        "B2_READY_BREAKOUT_GAP_FILL",
        "B2_READY_BREAKOUT_TRIGGER_FILL",
        "B2_CONFIRMED_ALL",
    )
    cohort_stats = {name: _stats(_cohort_rows(derived, name)) for name in cohort_names}
    summary = ExecutionRealitySummary(
        snapshot_id=snapshot_id,
        source_episodes_sha256=actual_sha256,
        episode_count=len(derived),
        code_count=len({row.code for row in derived}),
        max_holding_sessions=MAX_HOLDING_SESSIONS,
        evaluate_strategy_calls=0,
        price_limit_execution_model=PRICE_LIMIT_NOT_MODELED,
        cohorts=cohort_stats,
        comparison_2d0=_comparison(cohort_stats),
        b1_tail={
            "B1_READY_SETUP_GE_80": _tail_summary(derived, "B1_READY_SETUP_GE_80"),
            "B1_READY_ENTRY_GE_80": _tail_summary(derived, "B1_READY_ENTRY_GE_80"),
        },
        b2_trigger_ambiguity=_b2_trigger_ambiguity(derived),
        performance={
            "analysis_seconds": perf_counter() - started,
            "evaluate_strategy_calls": 0,
            "derived_rows": len(derived),
        },
    )
    destination = output_dir or episodes_path.parent / "execution-reality"
    destination.mkdir(parents=True, exist_ok=True)
    episodes_output = destination / "execution_episodes.parquet"
    summary_json = destination / "summary.json"
    summary_md = destination / "summary.md"
    _write_episodes(episodes_output, derived)
    summary_json.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    summary_md.write_text(_render_markdown(summary), encoding="utf-8")
    return {
        "episodes_path": str(episodes_output),
        "summary_json": str(summary_json),
        "summary_md": str(summary_md),
        "summary": summary,
        "performance": summary.performance,
    }


__all__ = [
    "CORRECTED_EPISODES_SHA256",
    "ExecutionRealityEpisode",
    "ExecutionRealitySummary",
    "FILL_DAY_TARGET_ORDER_UNKNOWN",
    "relabel_execution_episode",
    "run_execution_reality_check",
]
