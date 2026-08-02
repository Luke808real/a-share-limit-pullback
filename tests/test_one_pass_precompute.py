from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from limit_pullback.config import load_strategy_config
from limit_pullback.models.market import DailyBar
from limit_pullback.strategy.math import calculate_indicators


def _bar(index: int) -> DailyBar:
    day = date(2024, 1, 2) + timedelta(days=index)
    return DailyBar(
        trade_date=day,
        code="000001",
        open=Decimal("10.00"),
        high=Decimal("10.50"),
        low=Decimal("9.50"),
        close=Decimal("10.00"),
        preclose=Decimal("10.00"),
        volume=Decimal("1000"),
        amount=Decimal("10000"),
        trade_status=True,
        is_st=False,
        source="fixture",
        fetched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def test_full_series_point_equals_prefix_point_at_boundaries():
    bars = [_bar(index) for index in range(260)]
    config = load_strategy_config("config/strategy.yaml").indicators
    full = calculate_indicators(bars, config)
    for index in (0, 4, 9, 19, 29, 119, 249, 259):
        prefix = calculate_indicators(bars[: index + 1], config)[-1]
        point = full[index]
        assert point.trade_date == prefix.trade_date
        assert point.continuous_close == prefix.continuous_close
        assert point.continuous_mas == prefix.continuous_mas
        assert point.raw_equivalent_mas == prefix.raw_equivalent_mas
        assert point.ma_compression == prefix.ma_compression
        assert point.position_120 == prefix.position_120
        assert point.kline == prefix.kline
