"""Indicator pipeline glue: composes pure features with kline policy.

The MA/compression/position facts are pure feature math; the per-bar kline
flags embed frozen policy thresholds. This module is the strategy-side glue
that `strategy/math.py` exposes to existing callers.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from limit_pullback.features.common.math import (
    ZERO,
    _mean,
    _ordered_bars,
    build_continuous_prices,
)
from limit_pullback.models.config import IndicatorsConfig
from limit_pullback.models.market import DailyBar
from limit_pullback.models.strategy import IndicatorPoint
from limit_pullback.strategy.kline_policy import calculate_kline_metrics


def calculate_indicators(
    bars: Sequence[DailyBar],
    config: IndicatorsConfig,
    as_of: date | None = None,
) -> tuple[IndicatorPoint, ...]:
    ordered = _ordered_bars(bars, as_of)
    continuous = build_continuous_prices(ordered)
    values = tuple(point.continuous_close for point in continuous)
    output: list[IndicatorPoint] = []

    for index, (bar, point) in enumerate(zip(ordered, continuous, strict=True)):
        continuous_mas: dict[int, Decimal | None] = {}
        raw_mas: dict[int, Decimal | None] = {}
        for window in config.moving_average_windows:
            if index + 1 < window:
                continuous_mas[window] = None
                raw_mas[window] = None
                continue
            ma = _mean(values[index - window + 1 : index + 1])
            continuous_mas[window] = ma
            raw_mas[window] = ma * bar.close / point.continuous_close

        compression_mas = tuple(
            continuous_mas.get(window) for window in (5, 10, 20)
        )
        if all(value is not None for value in compression_mas):
            resolved = tuple(
                value for value in compression_mas if value is not None
            )
            ma_compression = (max(resolved) - min(resolved)) / point.continuous_close
        else:
            ma_compression = None

        position_window = config.position_window
        if index + 1 < position_window:
            position = None
        else:
            position_values = values[index - position_window + 1 : index + 1]
            rolling_low = min(position_values)
            rolling_high = max(position_values)
            if rolling_high == rolling_low:
                position = ZERO
            else:
                position = (
                    point.continuous_close - rolling_low
                ) / (rolling_high - rolling_low)

        output.append(
            IndicatorPoint(
                trade_date=bar.trade_date,
                code=bar.code,
                continuous_close=point.continuous_close,
                continuous_mas=continuous_mas,
                raw_equivalent_mas=raw_mas,
                ma_compression=ma_compression,
                position_120=position,
                kline=calculate_kline_metrics(bar, config),
            )
        )
    return tuple(output)


__all__ = ["calculate_indicators"]
