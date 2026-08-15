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


def test_e05_candle_intersects_zone_low_below_true() -> None:
    # 冻结合同：K 线区间与冻结区间相交即触及 —— low 低于 support_low 但
    # high >= support_low 仍算触及（Sol 审计示例：low=10.10, high=10.40,
    # zone=[10.20, 10.60] → True）。
    bars = _zone_bars("10.00", "11.00", [("10.10", "10.40")])
    anchor = bars[0].trade_date
    assert (
        fl.platform_support_touch(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        is True
    )


def test_e05_bar_fully_below_zone_false() -> None:
    # 整根 K 线在冻结区间之下（high < support_low）→ 不相交 → False
    bars = _zone_bars("10.00", "11.00", [("10.00", "10.10")])
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


def test_e05_degenerate_zone_requires_range_cover_price() -> None:
    # 退化区间（support_low == support_high）：K 线区间覆盖该单点价格
    zone = Decimal("10.40")
    bars = _zone_bars("10.00", "11.00", [("10.40", "10.80")])
    anchor = bars[0].trade_date
    assert (
        fl.platform_support_touch(bars, anchor, bars[-1].trade_date, zone, zone)
        is True
    )
    # low 低于单点但 high 覆盖单点 → 相交 → True
    bars = _zone_bars("10.00", "11.00", [("10.39", "10.80")])
    assert (
        fl.platform_support_touch(bars, anchor, bars[-1].trade_date, zone, zone)
        is True
    )
    # 区间整体在单点上方 → False
    bars = _zone_bars("10.00", "11.00", [("10.41", "10.80")])
    assert (
        fl.platform_support_touch(bars, anchor, bars[-1].trade_date, zone, zone)
        is False
    )


def test_e05_missing_support_returns_none() -> None:
    # 冻结样本中 support 缺失（未到冻结时点）→ None，不抛 TypeError
    bars = _zone_bars("10.00", "11.00", [("10.40", "10.80")])
    anchor = bars[0].trade_date
    assert (
        fl.platform_support_touch(
            bars, anchor, bars[-1].trade_date, None, Decimal("10.60")
        )
        is None
    )
    assert (
        fl.platform_support_touch(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), None
        )
        is None
    )
    assert (
        fl.platform_support_touch(
            bars, anchor, bars[-1].trade_date, None, None
        )
        is None
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


# --- F18: support confluence (audit fix v01: max daily depth 0-3, frozen activation) ---


def _f18_series(pre_close: str, post: list[tuple[str, str, str]], n_pre: int = 12, t0_close: str = "11.00") -> list:
    """F18 helper: n_pre pre-anchor days closing at pre_close, T0 anchor
    (open 10.00 / close t0_close, body zone [min(10.00,t0_close),
    max(10.00,t0_close)]), then post days as (low, high, close). MA10 at a
    post day = mean of the last 10 closes ending at that day (includes the
    T0 close)."""
    days = business_dates(date(2026, 2, 2), n_pre + 1 + len(post))
    bars = []
    p = Decimal(pre_close)
    for day in days[:n_pre]:
        bars.append(make_bar(
            day,
            open_price=pre_close,
            high=str(p + Decimal("0.05")),
            low=str(p - Decimal("0.05")),
            close=pre_close,
            preclose="10.00",
            volume="1000",
        ))
    anchor = days[n_pre]
    bars.append(make_bar(
        anchor,
        open_price="10.00",
        high="11.05",
        low="9.95",
        close=t0_close,
        preclose=pre_close,
        volume="1000",
    ))
    for day, (low_s, high_s, close_s) in zip(days[n_pre + 1:], post, strict=True):
        bars.append(make_bar(
            day,
            open_price=close_s,
            high=high_s,
            low=low_s,
            close=close_s,
            preclose="10.00",
            volume="500",
        ))
    return bars


def test_f18_max_depth_three_all_intersect() -> None:
    # E01/E04/E05 激活全成立且 MA10∈实体∩平台 → 三重共振 3
    # m=(10.50+11.00+8×10.40)/10=10.47
    bars = _f18_series("10.40", [("10.10", "10.80", "10.50")])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        == 3
    )


def test_f18_all_active_no_common_intersection_depth_two() -> None:
    # Sol 裁决用例：三区间同日全 active，但 MA10=11.45∉实体∉平台
    # （公共交集为空）→ 2，不允许 3
    bars = _f18_series("11.50", [("10.50", "11.80", "11.50")])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        == 2
    )


def test_f18_ma_body_pair_depth_two() -> None:
    # MA10∈实体 且 MA+实体 激活、平台未激活 → 2
    bars = _f18_series("10.40", [("10.20", "10.80", "10.50")])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(
            bars, anchor, bars[-1].trade_date, Decimal("11.20"), Decimal("11.60")
        )
        == 2
    )


def test_f18_ma_plat_pair_depth_two() -> None:
    # MA10∈平台 且 MA+平台 激活、实体未激活（low 跌破实体下沿）→ 2
    bars = _f18_series("10.40", [("9.90", "10.80", "10.50")])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        == 2
    )


def test_f18_body_plat_pair_depth_two() -> None:
    # Blocker 2 明确用例：BODY+PLATFORM 同日 active 且两区间重叠，
    # MA 不构成共同交集（close<MA10 且 m∉平台）→ 2
    # m=(11.30+11.00+8×11.50)/10=11.43，close 11.30 < m → MA 不激活
    bars = _f18_series("11.50", [("10.50", "11.80", "11.30")])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        == 2
    )


def test_f18_across_day_no_accumulation() -> None:
    # 平台为窗口内固定冻结输入（10.20,10.60）：day1 实体+平台对（close<m，
    # MA 不激活 → 2），day2 MA+平台对（low 跌破实体下沿，实体不激活 → 2）；
    # 没有任何一天达到三重 → max=2，绝不允许跨日拼出 3
    bars = _f18_series("10.40", [("10.10", "10.80", "10.20"), ("9.90", "10.80", "10.50")])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        == 2
    )


def test_f18_no_overlap_depth_one() -> None:
    # 实体 [10.00,10.30] 与平台 [10.60,10.90] 不相交，MA10=10.48 不在两者内；
    # 三区间同日全激活但任何区间对无公共交集 → 1
    bars = _f18_series("10.50", [("10.10", "11.00", "10.50")], t0_close="10.30")
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(
            bars, anchor, bars[-1].trade_date, Decimal("10.60"), Decimal("10.90")
        )
        == 1
    )


def test_f18_boundary_closed_interval_and_degenerate_zones() -> None:
    # 闭合区间含端点 + 退化实体/退化平台单点精确命中 → 3
    bars = _f18_series("10.40", [("10.40", "10.80", "10.40")], t0_close="10.40")
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(
            bars, anchor, bars[-1].trade_date, Decimal("10.40"), Decimal("10.40")
        )
        == 3
    )


def test_f18_pit_cutoff_no_future_leak() -> None:
    # day1 仅实体激活（1），day2 三重（3）；as_of 截止 → 1 / 3
    bars = _f18_series("10.40", [("10.10", "10.50", "10.30"), ("10.10", "10.80", "10.50")])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(bars, anchor, bars[13].trade_date, Decimal("11.20"), Decimal("11.60"))
        == 1
    )
    assert (
        fl.support_confluence_max_count(bars, anchor, bars[14].trade_date, Decimal("10.20"), Decimal("10.60"))
        == 3
    )


def test_f18_missing_support_returns_none() -> None:
    bars = _f18_series("10.40", [("10.10", "10.80", "10.50")])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(bars, anchor, bars[-1].trade_date, None, Decimal("10.60"))
        is None
    )
    assert (
        fl.support_confluence_max_count(bars, anchor, bars[-1].trade_date, Decimal("10.20"), None)
        is None
    )


def test_f18_insufficient_ma10_returns_none() -> None:
    bars = _f18_series("10.40", [("10.10", "10.80", "10.50")], n_pre=5)
    anchor = bars[5].trade_date
    assert (
        fl.support_confluence_max_count(bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60"))
        is None
    )


def test_f18_no_post_anchor_bar_is_none() -> None:
    bars = _f18_series("10.40", [])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(bars, anchor, bars[12].trade_date, Decimal("10.20"), Decimal("10.60"))
        is None
    )


def test_f18_invalid_zone_fail_closed() -> None:
    bars = _f18_series("10.40", [("10.10", "10.80", "10.50")])
    anchor = bars[12].trade_date
    with pytest.raises(ValueError):
        fl.support_confluence_max_count(bars, anchor, bars[-1].trade_date, Decimal("10.60"), Decimal("10.20"))
    with pytest.raises(ValueError):
        fl.support_confluence_max_count(bars, anchor, bars[-1].trade_date, Decimal("0"), Decimal("10.60"))
    with pytest.raises(ValueError):
        fl.support_confluence_max_count(bars, date(2030, 1, 1), bars[-1].trade_date, Decimal("10.20"), Decimal("10.60"))


def test_f18_bad_bars_with_missing_support_fail_closed() -> None:
    # MALFORMED_BARS_PRECEDENCE：重复日期（结构坏 bar）+ support=None →
    # 结构校验优先，ValueError（不得被 missing 短路掩盖）
    bars = _f18_series("10.40", [("10.10", "10.80", "10.50")])
    bars = bars + [bars[-1]]
    anchor = bars[12].trade_date
    with pytest.raises(ValueError):
        fl.support_confluence_max_count(bars, anchor, bars[-1].trade_date, None, None)


def test_f18_missing_anchor_with_missing_support_fail_closed() -> None:
    # anchor 校验先于 missing support：anchor 缺失 + support=None →
    # ValueError
    bars = _f18_series("10.40", [("10.10", "10.80", "10.50")])
    with pytest.raises(ValueError):
        fl.support_confluence_max_count(
            bars, date(2030, 1, 1), bars[-1].trade_date, None, None
        )


def test_f18_e01_activation_requires_close_above_ma() -> None:
    # Blocker 3 回归：K 线穿过 MA10 价格但 close < MA10（close 10.20 < m 10.42）
    # → E01 激活为 False；若按错误的"区间相交"会算 3，冻结语义应为 2
    bars = _f18_series("10.40", [("10.10", "10.80", "10.20")])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        == 2
    )


def test_f18_e04_activation_requires_low_inside_body() -> None:
    # Blocker 3 回归：low 9.50 跌破实体下沿 10.00 → E04 激活为 False
    # （错误的区间相交会算实体激活 → 2；冻结语义应为 1）
    bars = _f18_series("10.40", [("9.50", "10.50", "10.30")])
    anchor = bars[12].trade_date
    assert (
        fl.support_confluence_max_count(
            bars, anchor, bars[-1].trade_date, Decimal("10.20"), Decimal("10.60")
        )
        == 1
    )
