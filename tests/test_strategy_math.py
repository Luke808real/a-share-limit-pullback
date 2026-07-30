from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal

from limit_pullback.config import load_strategy_config
from limit_pullback.models.market import DailyBar
from limit_pullback.strategy.math import (
    build_continuous_prices,
    calculate_indicators,
)
from tests.synthetic_data import base_setup_bars


def test_point_in_time_continuous_price_handles_corporate_action(project_root):
    fixture = project_root / "tests" / "fixtures" / "synthetic_bars.csv"
    with fixture.open(encoding="utf-8", newline="") as stream:
        bars = tuple(DailyBar.model_validate(row) for row in csv.DictReader(stream))

    points = build_continuous_prices(bars)
    assert tuple(point.continuous_close for point in points) == (
        Decimal("10.00"),
        Decimal("11.00"),
        Decimal("11.00"),
        Decimal("11.10"),
    )


def test_indicators_use_continuous_prices_and_decimal(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    bars = base_setup_bars()
    indicators = calculate_indicators(bars, config.indicators)
    before_anchor = indicators[-2]

    assert before_anchor.position_120 is not None
    assert before_anchor.position_120 < Decimal("0.35")
    assert before_anchor.ma_compression is not None
    assert isinstance(before_anchor.ma_compression, Decimal)
    assert before_anchor.raw_equivalent_mas[20] is not None
    assert isinstance(before_anchor.kline.body_share, Decimal)


def test_indicator_result_ignores_future_rows(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    bars = base_setup_bars()
    as_of = bars[-2].trade_date
    original = calculate_indicators(bars, config.indicators, as_of)
    future = bars[-1].model_copy(
        update={
            "trade_date": date(2099, 1, 1),
            "close": Decimal("999"),
            "high": Decimal("999"),
            "open": Decimal("999"),
            "low": Decimal("999"),
        }
    )

    assert calculate_indicators((*bars, future), config.indicators, as_of) == original
