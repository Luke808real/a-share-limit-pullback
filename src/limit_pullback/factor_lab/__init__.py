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


def _ma10(ordered: tuple[DailyBar, ...]) -> dict[date, Decimal | None]:
    """MA10(D) = mean close of the last 10 visible sessions ending at D
    inclusive. None when fewer than 10 sessions exist through D (that day
    contributes no event). Computed only from the series as passed."""
    out: dict[date, Decimal | None] = {}
    for i, bar in enumerate(ordered):
        if i < 9:
            out[bar.trade_date] = None
        else:
            out[bar.trade_date] = _mean(b.close for b in ordered[i - 9 : i + 1])
    return out


def ma10_touch_hold(bars, anchor_date: date, as_of: date) -> bool | None:
    """E01_MA10_TOUCH_HOLD: exists D in (anchor_date, as_of] with
    low(D) <= MA10(D) and close(D) >= MA10(D).

    None when no post-anchor session is visible at as_of, or no visible
    session has a defined MA10 (fewer than 10 sessions through that day).
    PIT: never reads beyond as_of. Duplicate dates / multi-code / missing
    anchor fail closed (ValueError)."""
    ordered = _ordered(bars)
    _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    ma = _ma10(ordered)
    evaluated = False
    for bar in after:
        m = ma[bar.trade_date]
        if m is None:
            continue
        evaluated = True
        if bar.low <= m <= bar.close:
            return True
    return False if evaluated else None


def ma10_close_break(bars, anchor_date: date, as_of: date) -> bool | None:
    """E02_MA10_CLOSE_BREAK: exists D in (anchor_date, as_of] with
    close(D) < MA10(D).

    None when no post-anchor session is visible at as_of, or no visible
    session has a defined MA10. PIT: never reads beyond as_of. Duplicate
    dates / multi-code / missing anchor fail closed (ValueError)."""
    ordered = _ordered(bars)
    _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    ma = _ma10(ordered)
    evaluated = False
    for bar in after:
        m = ma[bar.trade_date]
        if m is None:
            continue
        evaluated = True
        if bar.close < m:
            return True
    return False if evaluated else None


def ma10_reclaim_within_3d(bars, anchor_date: date, as_of: date) -> bool | None:
    """E03_MA10_RECLAIM_3D: after the FIRST close-break day D2 in
    (anchor_date, as_of], there exists a visible session D' with
    D2 < D' <= as_of, at most 3 visible sessions after D2, with
    close(D') >= MA10(D'). Sessions with undefined MA10 are skipped (they
    neither break nor reclaim).

    Frozen anchoring choice: the 3-session window counts from the FIRST
    E02 day in the window; later break days do not reset the window.
    None when no post-anchor session is visible or no visible session has
    a defined MA10; False when a defined-MA10 session exists but no break
    occurred, or when no reclaim occurs within 3 sessions; True on
    reclaim. PIT: never reads beyond as_of. Duplicate dates / multi-code /
    missing anchor fail closed (ValueError)."""
    ordered = _ordered(bars)
    _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    ma = _ma10(ordered)
    evaluated = False
    break_idx: int | None = None
    for idx, bar in enumerate(after):
        m = ma[bar.trade_date]
        if m is None:
            continue
        evaluated = True
        if bar.close < m:
            break_idx = idx
            break
    if break_idx is None:
        return False if evaluated else None
    for candidate in after[break_idx + 1 : break_idx + 4]:
        m = ma[candidate.trade_date]
        if m is None:
            continue
        if candidate.close >= m:
            return True
    return False


def t0_body_touch(bars, anchor_date: date, as_of: date) -> bool | None:
    """E04_T0_BODY_TOUCH: exists D in (anchor_date, as_of] with
    min(open(T0), close(T0)) <= low(D) <= max(open(T0), close(T0)).

    T0 is the anchor bar itself and must be visible in bars. The T0 body
    zone is [min(open, close), max(open, close)] (catalog E04): a low that
    enters the zone is a touch, a low strictly below the zone is a break
    through the body (not an E04 touch), a low strictly above is no
    contact. A degenerate body (open == close) reduces the zone to a
    single price and requires an exact low.

    None when no post-anchor session is visible at as_of. PIT: never reads
    beyond as_of. Duplicate dates / multi-code / missing anchor fail
    closed (ValueError)."""
    ordered = _ordered(bars)
    anchor = _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    body_low = min(anchor.open, anchor.close)
    body_high = max(anchor.open, anchor.close)
    return any(body_low <= bar.low <= body_high for bar in after)


def platform_support_touch(
    bars,
    anchor_date: date,
    as_of: date,
    support_low: Decimal | None,
    support_high: Decimal | None,
) -> bool | None:
    """E05_PLATFORM_SUPPORT_TOUCH: exists D in (anchor_date, as_of] with
    low(D) <= support_high and high(D) >= support_low (frozen contract:
    the candle range intersects the frozen support zone).

    support_low / support_high are FROZEN inputs: they must come from the
    frozen SupportSnapshot of the frozen engine (frozen states /
    episodes support_low/support_high columns). This function never
    recomputes a platform; it only tests daily-bar ranges against the
    frozen zone (catalog E05 frozen definition, restored by audit fix v01).

    A candle whose range intersects the closed zone [support_low,
    support_high] is a touch — including a low below support_low when
    high >= support_low. A degenerate zone (support_low == support_high)
    requires the candle range to cover that single price. Missing frozen
    support (either bound is None) yields None: an episode whose support
    never reached its freeze point carries no platform and therefore no
    touch answer. Non-positive or reversed frozen zone fails closed
    (ValueError).

    None when no post-anchor session is visible at as_of. PIT: never reads
    beyond as_of. Duplicate dates / multi-code / missing anchor fail
    closed (ValueError)."""
    if support_low is None or support_high is None:
        return None
    if support_low <= ZERO or support_high <= ZERO:
        raise ValueError("frozen support zone requires positive prices")
    if support_low > support_high:
        raise ValueError("frozen support zone is reversed")
    ordered = _ordered(bars)
    _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    return any(bar.low <= support_high and bar.high >= support_low for bar in after)


def _candle_intersects(bar, zone_low: Decimal, zone_high: Decimal) -> bool:
    """True when the candle range intersects the closed zone [zone_low, zone_high]
    (the frozen E05 platform activation predicate)."""
    return bar.low <= zone_high and bar.high >= zone_low


def support_confluence_max_count(
    bars,
    anchor_date: date,
    as_of: date,
    support_low: Decimal | None,
    support_high: Decimal | None,
) -> int | None:
    """F18_SUPPORT_CONFLUENCE (canonical name, audit fix v01): the maximum
    confluence depth over days D in (anchor_date, as_of]:
        F18 = max_D C(D),   C(D) in {0,1,2,3}
    where C(D) is the size of the largest subset of the three support
    zones that are day-level ACTIVE on D and have a non-empty common
    price intersection (no tolerance, no across-day accumulation).

    Frozen zones:
      Z_MA10(D)   = [MA10(D), MA10(D)]                (single price point)
      Z_BODY      = [min(open,close)(T0), max(open,close)(T0)]   (E04)
      Z_PLATFORM  = [support_low, support_high]       (E05 frozen values)

    Day-level activation REUSES the frozen per-factor predicates (never
    the range-intersection generalization):
      MA_ACTIVE(D)     = low(D) <= MA10(D) <= close(D)              (E01)
      BODY_ACTIVE(D)   = BODY_LOW <= low(D) <= BODY_HIGH            (E04)
      PLATFORM_ACTIVE(D) = low(D) <= support_high AND high(D) >=
                           support_low                              (E05)

    C(D) = 3 requires all three zones ACTIVE and
    Z_MA10 ∩ Z_BODY ∩ Z_PLATFORM ≠ ∅ (Z_MA10 is a point, so MA10(D) in
    Z_BODY and MA10(D) in Z_PLATFORM). C(D) = 2 requires some ACTIVE pair
    with non-empty zone intersection (BODY∩PLATFORM overlap, MA10(D) in
    Z_BODY, or MA10(D) in Z_PLATFORM). C(D) = 1 requires at least one
    ACTIVE zone; 0 otherwise.

    Days with undefined MA10 (fewer than 10 sessions through that day):
    the MA support is inactive that day, but BODY and PLATFORM still
    participate per their own contracts (a BODY+PLATFORM resonance on
    such a day yields C(D) = 2). Only when NO day in the window has a
    defined MA10 does the function return None. None also when no
    post-anchor session is visible at as_of. Missing frozen support
    (either bound None) returns None. Non-positive or reversed frozen
    zone fails closed.

    Validation precedence (frozen): structural bar integrity first
    (_ordered: multi-code / duplicate dates -> ValueError), then anchor
    presence (_require_anchor -> ValueError), then the observation
    window (_after: no post-anchor bar -> None), THEN missing frozen
    support -> None, then zone validity (non-positive / reversed ->
    ValueError)."""
    ordered = _ordered(bars)
    anchor = _require_anchor(ordered, anchor_date)
    after = _after(ordered, anchor_date, as_of)
    if not after:
        return None
    if support_low is None or support_high is None:
        return None
    if support_low <= ZERO or support_high <= ZERO:
        raise ValueError("frozen support zone requires positive prices")
    if support_low > support_high:
        raise ValueError("frozen support zone is reversed")
    t0_low = min(anchor.open, anchor.close)
    t0_high = max(anchor.open, anchor.close)
    ma = _ma10(ordered)
    best = 0
    has_ma10_day = False
    for bar in after:
        m = ma[bar.trade_date]
        body_active = t0_low <= bar.low <= t0_high
        plat_active = _candle_intersects(bar, support_low, support_high)
        if m is None:
            # MA support inactive today; BODY/PLATFORM still participate
            depth = 0
            if body_active and plat_active and t0_low <= support_high and support_low <= t0_high:
                depth = 2
            elif body_active or plat_active:
                depth = 1
            if depth > best:
                best = depth
            continue
        has_ma10_day = True
        ma_active = bar.low <= m <= bar.close
        if not (ma_active or body_active or plat_active):
            continue
        triple = (
            ma_active
            and body_active
            and plat_active
            and t0_low <= m <= t0_high
            and support_low <= m <= support_high
        )
        pair_body_plat = (
            body_active
            and plat_active
            and t0_low <= support_high
            and support_low <= t0_high
        )
        pair_ma_body = ma_active and body_active and t0_low <= m <= t0_high
        pair_ma_plat = ma_active and plat_active and support_low <= m <= support_high
        depth = 3 if triple else (2 if (pair_body_plat or pair_ma_body or pair_ma_plat) else 1)
        if depth > best:
            best = depth
    return best if has_ma10_day else None
