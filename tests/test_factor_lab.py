"""Offline tests for the factor_lab PIT factors (catalog F01-F21 batch 1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from limit_pullback import factor_lab as fl
from tests.synthetic_data import base_setup_bars, business_dates, make_bar


def _series(closes: list[str], volumes: list[str]) -> list:
    """Build one-code bars; closes[i] with preclose = closes[i-1] (first 10.00)."""
    days = business_dates(date(2026, 1, 5), len(closes))
    bars = []
    preclose = Decimal("10.00")
    for day, close_s, vol_s in zip(days, closes, volumes, strict=True):
        close = Decimal(close_s)
        bars.append(
            make_bar(
                day,
                open_price=close_s,
                high=str(close + Decimal("0.10")),
                low=str(close - Decimal("0.10")),
                close=close_s,
                preclose=str(preclose),
                volume=vol_s,
            )
        )
        preclose = close
    return bars


def test_t0_position_60_exact() -> None:
    bars = _series(
        ["10.00", "9.00", "11.00", "10.50", "12.00"],
        ["100", "100", "100", "100", "500"],
    )
    anchor = bars[-1].trade_date
    # window before T0 highs/lows: lows 9.90, 8.90, 10.90, 10.40; highs 10.10, 9.10, 11.10, 10.60
    # low_min = 8.90, high_max = 11.10
    # (12.00 - 8.90) / (11.10 - 8.90) = 3.10 / 2.20
    assert fl.t0_position_60(bars, anchor) == Decimal("3.10") / Decimal("2.20")


def test_t0_position_insufficient_history_is_none() -> None:
    bars = _series(["10.00", "11.00"], ["100", "500"])
    # anchor = first bar -> no prior window at all
    assert fl.t0_position_60(bars, bars[0].trade_date) is None


def test_dist_from_120d_high_pct_exact() -> None:
    bars = _series(
        ["10.00", "13.00", "11.00", "10.00"],
        ["100", "100", "100", "500"],
    )
    anchor = bars[-1].trade_date
    # max high in window = 13.10 (high of the 13.00 bar), T0 close 10.00
    # (13.10 - 10.00) / 13.10
    expected = (Decimal("13.10") - Decimal("10.00")) / Decimal("13.10")
    assert fl.dist_from_120d_high_pct(bars, anchor) == expected


def test_t0_volume_and_turnover() -> None:
    bars = _series(
        ["10.00", "10.00", "10.00", "11.00"],
        ["100", "100", "100", "500"],
    )
    anchor = bars[-1].trade_date
    assert fl.t0_volume_vs_20d_mean(bars, anchor) == Decimal("5")
    assert fl.t0_turnover(bars, anchor) == Decimal("0.03")  # make_bar default


def test_pullback_depth_and_trough_index() -> None:
    bars = _series(
        ["10.00", "10.00", "9.50", "9.80", "9.60"],
        ["100", "80", "60", "70", "65"],
    )
    anchor = bars[1].trade_date
    as_of = bars[-1].trade_date
    # after T0 closes: 9.50, 9.80, 9.60 -> min 9.50 at T+1
    assert fl.pullback_depth_pct(bars, anchor, as_of) == (Decimal("10.00") - Decimal("9.50")) / Decimal("10.00")
    assert fl.pullback_trough_index(bars, anchor, as_of) == 1
    assert fl.pullback_min_volume_ratio(bars, anchor, as_of) == Decimal("60") / Decimal("80")
    assert fl.t1_volume_ratio(bars, anchor, as_of) == Decimal("60") / Decimal("80")


def test_pit_cutoff_no_future_leak() -> None:
    bars = _series(
        ["10.00", "10.00", "9.50", "9.20", "9.80"],
        ["100", "80", "60", "55", "70"],
    )
    anchor = bars[1].trade_date
    early = fl.pullback_depth_pct(bars, anchor, bars[2].trade_date)
    late = fl.pullback_depth_pct(bars, anchor, bars[-1].trade_date)
    assert early == (Decimal("10.00") - Decimal("9.50")) / Decimal("10.00")
    assert late == (Decimal("10.00") - Decimal("9.20")) / Decimal("10.00")
    assert early != late  # future bars must not leak into the earlier as_of


def test_anchor_missing_raises() -> None:
    bars = _series(["10.00", "11.00"], ["100", "500"])
    with pytest.raises(ValueError):
        fl.t0_position_60(bars, date(2030, 1, 1))


def test_b2_volume_ratio_exact() -> None:
    bars = _series(
        ["10.00", "10.00", "9.80", "9.60", "10.50"],
        ["100", "80", "60", "70", "300"],
    )
    anchor = bars[1].trade_date
    b2_date = bars[-1].trade_date
    # pullback vols before B2: 60, 70 -> mean 65; 300 / 65
    assert fl.b2_volume_vs_pullback_mean(bars, anchor, b2_date) == Decimal("300") / Decimal("65")


def test_b2_next_day_back_under_platform() -> None:
    bars = _series(
        ["10.00", "10.00", "9.80", "10.50", "10.20"],
        ["100", "80", "60", "300", "150"],
    )
    anchor = bars[1].trade_date
    b2_date = bars[3].trade_date
    assert fl.b2_next_day_back_under_platform(
        bars, anchor, b2_date, Decimal("10.30")
    ) is True
    assert fl.b2_next_day_back_under_platform(
        bars, anchor, b2_date, Decimal("10.10")
    ) is False


def test_f23_zero_events() -> None:
    bars = _series(
        ["10.00", "10.20", "10.40"],
        ["100", "90", "80"],
    )
    anchor = bars[0].trade_date
    as_of = bars[-1].trade_date
    # rising closes, falling volume -> no down-volume session
    assert fl.pullback_down_volume_count(bars, anchor, as_of) == 0


def test_f23_exactly_one_event() -> None:
    bars = _series(
        ["10.00", "9.80", "9.90", "10.10"],
        ["100", "150", "140", "130"],
    )
    anchor = bars[0].trade_date
    as_of = bars[-1].trade_date
    # T+1: close down and volume up -> event; T+2/T+3 closes up -> not events
    assert fl.pullback_down_volume_count(bars, anchor, as_of) == 1


def test_f23_multiple_events() -> None:
    bars = _series(
        ["10.00", "9.70", "9.50", "9.80"],
        ["100", "120", "130", "110"],
    )
    anchor = bars[0].trade_date
    as_of = bars[-1].trade_date
    # T+1 and T+2 both close down with volume up -> 2 events; T+3 close up
    assert fl.pullback_down_volume_count(bars, anchor, as_of) == 2


def test_f23_price_down_volume_not_up_no_event() -> None:
    bars = _series(
        ["10.00", "9.80", "9.60"],
        ["100", "90", "80"],
    )
    anchor = bars[0].trade_date
    as_of = bars[-1].trade_date
    # closes fall but volume also falls -> no event
    assert fl.pullback_down_volume_count(bars, anchor, as_of) == 0


def test_f23_volume_up_price_not_down_no_event() -> None:
    bars = _series(
        ["10.00", "10.10", "10.20"],
        ["100", "150", "160"],
    )
    anchor = bars[0].trade_date
    as_of = bars[-1].trade_date
    # volume rises but closes rise -> no event
    assert fl.pullback_down_volume_count(bars, anchor, as_of) == 0


def test_f23_pit_cutoff_no_future_leak() -> None:
    bars = _series(
        ["10.00", "9.80", "9.50", "9.90"],
        ["100", "150", "160", "140"],
    )
    anchor = bars[0].trade_date
    # events at T+1 and T+2; the later as_of must not leak into the earlier one
    early = fl.pullback_down_volume_count(bars, anchor, bars[1].trade_date)
    late = fl.pullback_down_volume_count(bars, anchor, bars[-1].trade_date)
    assert early == 1
    assert late == 2
    assert early != late
    # as_of == anchor -> no visible session after T0
    assert fl.pullback_down_volume_count(bars, anchor, anchor) is None


def _ma_series(closes: list[str]) -> list:
    """10 flat 10.00 sessions (indices 0..9), then the given tail."""
    return _series(["10.00"] * 10 + closes, ["100"] * (10 + len(closes)))


def test_ma10_touch_hold() -> None:
    bars = _ma_series(["10.00"])
    anchor = bars[9].trade_date
    as_of = bars[10].trade_date
    # MA10(day10) = 10.00; low 9.90 <= 10.00 <= close 10.00
    assert fl.ma10_touch_hold(bars, anchor, as_of) is True
    assert fl.ma10_close_break(bars, anchor, as_of) is False
    assert fl.ma10_reclaim_within_3d(bars, anchor, as_of) is False


def test_ma10_close_break() -> None:
    bars = _ma_series(["9.50"])
    anchor = bars[9].trade_date
    as_of = bars[10].trade_date
    # MA10(day10) = 9.95; close 9.50 < 9.95
    assert fl.ma10_close_break(bars, anchor, as_of) is True
    # low 9.40 <= 9.95 but close 9.50 < 9.95 -> no touch+hold
    assert fl.ma10_touch_hold(bars, anchor, as_of) is False
    # break at the last visible day -> no reclaim within the window
    assert fl.ma10_reclaim_within_3d(bars, anchor, as_of) is False


def test_ma10_reclaim_within_3d() -> None:
    bars = _ma_series(["9.40", "10.10"])
    anchor = bars[9].trade_date
    as_of = bars[11].trade_date
    # day10: close 9.40 < MA10 9.94 (break); day11: MA10 9.95, close 10.10
    # >= 9.95 -> reclaim 1 visible session after the first break
    assert fl.ma10_reclaim_within_3d(bars, anchor, as_of) is True


def test_ma10_reclaim_after_3_not_counted() -> None:
    bars = _ma_series(["9.40", "9.30", "9.20", "9.10", "10.20"])
    anchor = bars[9].trade_date
    as_of = bars[14].trade_date
    # first break at day10; days 11-13 stay below MA10; day14 reclaim is
    # the 4th visible session after the first break -> not counted
    assert fl.ma10_reclaim_within_3d(bars, anchor, as_of) is False


def test_ma10_insufficient_history_none() -> None:
    bars = _series(["10.00"] * 6, ["100"] * 6)
    anchor = bars[0].trade_date
    as_of = bars[5].trade_date
    # every visible day has fewer than 10 sessions of history -> MA10
    # undefined -> no events can be evaluated
    assert fl.ma10_touch_hold(bars, anchor, as_of) is None
    assert fl.ma10_close_break(bars, anchor, as_of) is None
    assert fl.ma10_reclaim_within_3d(bars, anchor, as_of) is None


def test_ma10_future_reclaim_no_leak() -> None:
    bars = _ma_series(["9.40", "10.10"])
    anchor = bars[9].trade_date
    early = fl.ma10_reclaim_within_3d(bars, anchor, bars[10].trade_date)
    late = fl.ma10_reclaim_within_3d(bars, anchor, bars[11].trade_date)
    assert early is False
    assert late is True
    assert early != late


def test_ma10_second_break_does_not_reset_window() -> None:
    bars = _ma_series(["9.40", "9.30", "9.20", "9.10", "9.05", "9.90"])
    anchor = bars[9].trade_date
    as_of = bars[15].trade_date
    # first break at day10 (close 9.40 < MA10 9.94); days 11-13 stay below
    # MA10 -> no reclaim within 3 sessions; day14 is a later (second)
    # break; day15 closes back above MA10 (reclaim within 3 sessions of
    # the second break). The window stays anchored to the FIRST break, so
    # E03 must still be False.
    assert fl.ma10_close_break(bars, anchor, as_of) is True
    assert fl.ma10_reclaim_within_3d(bars, anchor, as_of) is False


def test_ma10_fail_closed() -> None:
    # duplicate trade dates -> ValueError
    day = business_dates(date(2026, 1, 5), 1)[0]
    dup = [
        make_bar(
            day, open_price="10.00", high="10.10", low="9.90",
            close="10.00", preclose="9.90", volume="100",
        ),
        make_bar(
            day, open_price="10.00", high="10.10", low="9.90",
            close="10.00", preclose="9.90", volume="100",
        ),
    ]
    with pytest.raises(ValueError):
        fl.ma10_close_break(dup, day, day)
    # multi-code bars -> ValueError
    day1, day2 = business_dates(date(2026, 1, 5), 2)
    multi = [
        make_bar(
            day1, code="600000", open_price="10.00", high="10.10",
            low="9.90", close="10.00", preclose="9.90", volume="100",
        ),
        make_bar(
            day2, code="000001", open_price="10.00", high="10.10",
            low="9.90", close="10.00", preclose="9.90", volume="100",
        ),
    ]
    with pytest.raises(ValueError):
        fl.ma10_touch_hold(multi, day1, day2)
    # missing anchor -> ValueError
    bars = _series(["10.00"] * 10, ["100"] * 10)
    with pytest.raises(ValueError):
        fl.ma10_close_break(bars, date(2030, 1, 1), bars[-1].trade_date)


def _zone_bars(t0_open: str, t0_close: str, post: list[tuple[str, str]]) -> list:
    """T0 anchor (fixed high/low around body) + post days as (low, close)."""
    days = business_dates(date(2026, 2, 2), 1 + len(post))
    t0_high = max(Decimal(t0_open), Decimal(t0_close)) + Decimal("0.05")
    t0_low = min(Decimal(t0_open), Decimal(t0_close)) - Decimal("0.05")
    bars = [
        make_bar(
            days[0],
            open_price=t0_open,
            high=str(t0_high),
            low=str(t0_low),
            close=t0_close,
            preclose="10.00",
            volume="1000",
        )
    ]
    for day, (low_s, close_s) in zip(days[1:], post, strict=True):
        bars.append(
            make_bar(
                day,
                open_price=close_s,
                high=str(Decimal(close_s) + Decimal("0.05")),
                low=low_s,
                close=close_s,
                preclose="10.00",
                volume="500",
            )
        )
    return bars


# --- E04: T0 body touch ---


def test_e04_touch_into_t0_body_true() -> None:
    bars = _zone_bars("10.00", "11.00", [("10.50", "10.80")])
    assert fl.t0_body_touch(bars, bars[0].trade_date, bars[-1].trade_date) is True


def test_e04_low_below_body_is_break_not_touch() -> None:
    bars = _zone_bars("10.00", "11.00", [("9.90", "10.20")])
    assert fl.t0_body_touch(bars, bars[0].trade_date, bars[-1].trade_date) is False


def test_e04_low_above_body_no_contact() -> None:
    bars = _zone_bars("10.00", "11.00", [("11.10", "11.30")])
    assert fl.t0_body_touch(bars, bars[0].trade_date, bars[-1].trade_date) is False


def test_e04_degenerate_body_requires_exact_low() -> None:
    bars = _zone_bars("11.00", "11.00", [("11.00", "11.20")])
    assert fl.t0_body_touch(bars, bars[0].trade_date, bars[-1].trade_date) is True
    bars = _zone_bars("11.00", "11.00", [("10.99", "11.20")])
    assert fl.t0_body_touch(bars, bars[0].trade_date, bars[-1].trade_date) is False


def test_e04_pit_cutoff_no_future_leak() -> None:
    bars = _zone_bars("10.00", "11.00", [("9.90", "10.20"), ("10.50", "10.80")])
    anchor = bars[0].trade_date
    assert fl.t0_body_touch(bars, anchor, bars[1].trade_date) is False
    assert fl.t0_body_touch(bars, anchor, bars[2].trade_date) is True


def test_e04_no_post_anchor_bar_is_none() -> None:
    bars = _zone_bars("10.00", "11.00", [])
    assert fl.t0_body_touch(bars, bars[0].trade_date, bars[0].trade_date) is None


def test_e04_fail_closed() -> None:
    bars = _zone_bars("10.00", "11.00", [("10.50", "10.80")])
    anchor = bars[0].trade_date
    with pytest.raises(ValueError):
        fl.t0_body_touch(bars, date(2030, 1, 1), bars[-1].trade_date)
    multi = bars + [
        make_bar(
            bars[-1].trade_date,
            code="600001",
            open_price="10.80",
            high="10.85",
            low="10.50",
            close="10.80",
            preclose="10.00",
            volume="500",
        )
    ]
    with pytest.raises(ValueError):
        fl.t0_body_touch(multi, anchor, bars[-1].trade_date)
    duplicated = bars + [bars[-1]]
    with pytest.raises(ValueError):
        fl.t0_body_touch(duplicated, anchor, bars[-1].trade_date)


# --- E05: frozen platform support touch ---


def test_e05_low_inside_frozen_zone_true() -> None:
    bars = _zone_bars("10.00", "11.00", [("10.40", "10.80")])
    anchor = bars[0].trade_date
    assert (
        fl.platform_support_touch(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        is True
    )


def test_e05_low_below_zone_is_break_not_touch() -> None:
    bars = _zone_bars("10.00", "11.00", [("10.10", "10.30")])
    anchor = bars[0].trade_date
    assert (
        fl.platform_support_touch(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        is False
    )


def test_e05_low_above_zone_no_contact() -> None:
    bars = _zone_bars("10.00", "11.00", [("10.70", "10.90")])
    anchor = bars[0].trade_date
    assert (
        fl.platform_support_touch(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        is False
    )


def test_e05_degenerate_zone_requires_exact_low() -> None:
    zone = Decimal("10.40")
    bars = _zone_bars("10.00", "11.00", [("10.40", "10.80")])
    anchor = bars[0].trade_date
    assert (
        fl.platform_support_touch(bars, anchor, bars[-1].trade_date, zone, zone)
        is True
    )
    bars = _zone_bars("10.00", "11.00", [("10.39", "10.80")])
    assert (
        fl.platform_support_touch(bars, anchor, bars[-1].trade_date, zone, zone)
        is False
    )


def test_e05_pit_cutoff_no_future_leak() -> None:
    bars = _zone_bars("10.00", "11.00", [("10.70", "10.90"), ("10.40", "10.80")])
    anchor = bars[0].trade_date
    args = (Decimal("10.20"), Decimal("10.60"))
    assert (
        fl.platform_support_touch(bars, anchor, bars[1].trade_date, *args) is False
    )
    assert (
        fl.platform_support_touch(bars, anchor, bars[2].trade_date, *args) is True
    )


def test_e05_no_post_anchor_bar_is_none() -> None:
    bars = _zone_bars("10.00", "11.00", [])
    assert (
        fl.platform_support_touch(
            bars,
            bars[0].trade_date,
            bars[0].trade_date,
            Decimal("10.20"),
            Decimal("10.60"),
        )
        is None
    )


def test_e05_invalid_frozen_zone_fail_closed() -> None:
    bars = _zone_bars("10.00", "11.00", [("10.40", "10.80")])
    anchor = bars[0].trade_date
    with pytest.raises(ValueError):
        fl.platform_support_touch(
            bars, anchor, bars[-1].trade_date, Decimal("10.60"), Decimal("10.20")
        )
    with pytest.raises(ValueError):
        fl.platform_support_touch(
            bars, anchor, bars[-1].trade_date, Decimal("0"), Decimal("10.60")
        )
    with pytest.raises(ValueError):
        fl.platform_support_touch(
            bars, date(2030, 1, 1), bars[-1].trade_date,
            Decimal("10.20"), Decimal("10.60"),
        )
