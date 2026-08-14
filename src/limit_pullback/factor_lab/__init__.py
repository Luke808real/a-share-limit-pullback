"""factor_lab: research-layer PIT factors over canonical daily bars.

Pure functions only. Each factor reads daily bars for ONE code and returns a
Decimal or None (undefined: insufficient history / zero denominator). Bars
must be pre-truncated to as_of by the caller for point-in-time correctness.

This layer is RESEARCH ONLY: it never rewrites setup_stage, scores, or any
frozen semantics. Factor definitions live in
research/factor-lab/FACTOR_CATALOG.md (IDs F01-F23).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from limit_pullback.models.market import DailyBar

ZERO = Decimal("0")


def _ordered(bars) -> tuple[DailyBar, ...]:
    ordered = tuple(sorted(bars, key=lambda b: b.trade_date))
    codes = {bar.code for bar in ordered}
    if len(codes) != 1:
        raise ValueError("factors require bars for exactly one code")
    dates = [bar.trade_date for bar in ordered]
    if len(set(dates)) != len(dates):
        raise ValueError("daily bars contain duplicate trade dates")
    return ordered


def _by_date(ordered: tuple[DailyBar, ...]) -> dict[date, DailyBar]:
    return {bar.trade_date: bar for bar in ordered}


def _mean(values) -> Decimal | None:
    values = tuple(values)
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _window_before(
    ordered: tuple[DailyBar, ...],
    anchor_date: date,
    lookback: int,
) -> tuple[DailyBar, ...]:
    lo = anchor_date.toordinal() - lookback
    return tuple(
        bar
        for bar in ordered
        if bar.trade_date < anchor_date
        and bar.trade_date.toordinal() >= lo
    )


def _after(ordered: tuple[DailyBar, ...], anchor_date: date, as_of: date) -> tuple[DailyBar, ...]:
    return tuple(
        bar
        for bar in ordered
        if anchor_date < bar.trade_date <= as_of
    )


def _require_anchor(ordered: tuple[DailyBar, ...], anchor_date: date) -> DailyBar:
    by_date = _by_date(ordered)
    anchor = by_date.get(anchor_date)
    if anchor is None:
        raise ValueError(f"anchor bar missing: {anchor_date}")
    return anchor


def t0_position_60(bars, anchor_date: date) -> Decimal | None:
    """F01: (T0 close - min low) / (max high - min low) over the 60 sessions before T0."""
    ordered = _ordered(bars)
    anchor = _require_anchor(ordered, anchor_date)
    window = _window_before(ordered, anchor_date, 60)
    if not window:
        return None
    low_min = min(bar.low for bar in window)
    high_max = max(bar.high for bar in window)
    if high_max == low_min:
        return None
    return (anchor.close - low_min) / (high_max - low_min)


def dist_from_120d_high_pct(bars, anchor_date: date) -> Decimal | None:
    """F02: (max high over 120 sessions before T0 - T0 close) / max high."""
    ordered = _ordered(bars)
    anchor = _require_anchor(ordered, anchor_date)
    window = _window_before(ordered, anchor_date, 120)
    if not window:
        return None
    high_max = max(bar.high for bar in window)
    if high_max == ZERO:
        return None
    return (high_max - anchor.close) / high_max


def t0_turnover(bars, anchor_date: date) -> Decimal | None:
    """F06: turnover_rate on T0."""
    ordered = _ordered(bars)
    anchor = _require_anchor(ordered, anchor_date)
    return anchor.turnover_rate


def t0_volume_vs_20d_mean(bars, anchor_date: date) -> Decimal | None:
    """F07: vol(T0) / mean(vol, 20 sessions before T0)."""
    ordered = _ordered(bars)
    anchor = _require_anchor(ordered, anchor_date)
    window = _window_before(ordered, anchor_date, 20)
    mean_vol = _mean(bar.volume for bar in window)
    if mean_vol is None or mean_vol == ZERO:
        return None
    return anchor.volume / mean_vol


def pullback_depth_pct(bars, anchor_date: date, as_of: date) -> Decimal | None:
    """F09: (T0 close - min close after T0 through as_of) / T0 close."""
    ordered = _ordered(bars)
    anchor = _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    if anchor.close == ZERO:
        return None
    return (anchor.close - min(bar.close for bar in after)) / anchor.close


def pullback_trough_index(bars, anchor_date: date, as_of: date) -> int | None:
    """F11: 1-based index (T+1 = 1) of the lowest close after T0 through as_of."""
    ordered = _ordered(bars)
    _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    min_close = min(bar.close for bar in after)
    for index, bar in enumerate(after, start=1):
        if bar.close == min_close:
            return index
    return None


def pullback_min_volume_ratio(bars, anchor_date: date, as_of: date) -> Decimal | None:
    """F14: min(vol after T0 through as_of) / vol(T0)."""
    ordered = _ordered(bars)
    anchor = _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    if anchor.volume == ZERO:
        return None
    return min(bar.volume for bar in after) / anchor.volume


def t1_volume_ratio(bars, anchor_date: date, as_of: date) -> Decimal | None:
    """F16: vol(T+1) / vol(T0); None when T+1 is not yet visible at as_of."""
    ordered = _ordered(bars)
    anchor = _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    if anchor.volume == ZERO:
        return None
    return after[0].volume / anchor.volume


def b2_volume_vs_pullback_mean(bars, anchor_date: date, b2_date: date) -> Decimal | None:
    """F19: vol(B2 day) / mean(vol, T+1 .. day before B2)."""
    ordered = _ordered(bars)
    _require_anchor(ordered, anchor_date)
    by_date = _by_date(ordered)
    b2_bar = by_date.get(b2_date)
    if b2_bar is None:
        raise ValueError(f"b2 bar missing: {b2_date}")
    pullback = tuple(
        bar
        for bar in ordered
        if anchor_date < bar.trade_date < b2_date
    )
    mean_vol = _mean(bar.volume for bar in pullback)
    if mean_vol is None or mean_vol == ZERO:
        return None
    return b2_bar.volume / mean_vol


def b2_next_day_back_under_platform(
    bars,
    anchor_date: date,
    b2_date: date,
    platform_price: Decimal,
) -> bool | None:
    """F21: True when the first session after B2 closes below the platform."""
    ordered = _ordered(bars)
    _require_anchor(ordered, anchor_date)
    next_day = tuple(
        bar for bar in ordered if bar.trade_date > b2_date
    )
    if not next_day:
        return None
    return next_day[0].close < platform_price


def pullback_down_volume_count(bars, anchor_date: date, as_of: date) -> int | None:
    """F23: count of pullback sessions after T0 through as_of where
    close(i) < close(i-1) and volume(i) > volume(i-1); the previous session
    for the first visible day is T0 itself. None when no session after T0
    is visible at as_of. Duplicate dates / multi-code bars fail closed via
    _ordered/_require_anchor (ValueError)."""
    ordered = _ordered(bars)
    prev = _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    count = 0
    for bar in after:
        if bar.close < prev.close and bar.volume > prev.volume:
            count += 1
        prev = bar
    return count
