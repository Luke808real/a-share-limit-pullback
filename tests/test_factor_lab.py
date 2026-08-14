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
