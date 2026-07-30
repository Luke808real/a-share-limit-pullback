"""Point-in-time continuous prices and deterministic indicators."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from limit_pullback.models.config import IndicatorsConfig
from limit_pullback.models.market import DailyBar
from limit_pullback.models.strategy import (
    ContinuousPricePoint,
    IndicatorPoint,
    KlineMetrics,
)


ZERO = Decimal("0")
ONE = Decimal("1")


def _ordered_bars(
    bars: Sequence[DailyBar],
    as_of: date | None = None,
) -> tuple[DailyBar, ...]:
    selected = tuple(
        bar for bar in bars if as_of is None or bar.trade_date <= as_of
    )
    if not selected:
        return ()
    codes = {bar.code for bar in selected}
    if len(codes) != 1:
        raise ValueError("indicator functions require bars for exactly one code")
    ordered = tuple(sorted(selected, key=lambda bar: bar.trade_date))
    dates = tuple(bar.trade_date for bar in ordered)
    if len(set(dates)) != len(dates):
        raise ValueError("daily bars contain duplicate trade dates")
    return ordered


def build_continuous_prices(
    bars: Sequence[DailyBar],
    as_of: date | None = None,
) -> tuple[ContinuousPricePoint, ...]:
    """Build a close/preclose chain using no observations after ``as_of``."""

    ordered = _ordered_bars(bars, as_of)
    if not ordered:
        return ()
    points: list[ContinuousPricePoint] = []
    continuous_close = ordered[0].close
    points.append(
        ContinuousPricePoint(
            trade_date=ordered[0].trade_date,
            code=ordered[0].code,
            raw_close=ordered[0].close,
            continuous_close=continuous_close,
        )
    )
    for bar in ordered[1:]:
        continuous_close = continuous_close * bar.close / bar.preclose
        points.append(
            ContinuousPricePoint(
                trade_date=bar.trade_date,
                code=bar.code,
                raw_close=bar.close,
                continuous_close=continuous_close,
            )
        )
    return tuple(points)


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("mean requires at least one value")
    return sum(values, ZERO) / Decimal(len(values))


def calculate_kline_metrics(
    bar: DailyBar,
    config: IndicatorsConfig,
) -> KlineMetrics:
    price_range = bar.high - bar.low
    if price_range == ZERO:
        body_share = ZERO
        close_location = ONE
        upper_shadow_share = ZERO
        lower_shadow_share = ZERO
        amplitude = ZERO
    else:
        body_share = abs(bar.close - bar.open) / price_range
        close_location = (bar.close - bar.low) / price_range
        upper_shadow_share = (
            bar.high - max(bar.open, bar.close)
        ) / price_range
        lower_shadow_share = (
            min(bar.open, bar.close) - bar.low
        ) / price_range
        amplitude = price_range / bar.preclose
    return KlineMetrics(
        body_share=body_share,
        close_location=close_location,
        upper_shadow_share=upper_shadow_share,
        lower_shadow_share=lower_shadow_share,
        amplitude=amplitude,
        is_bullish=bar.close > bar.open,
        is_bearish=bar.close < bar.open,
        is_doji=body_share <= config.kline.doji_body_share_max,
        is_small_body=body_share <= config.kline.small_body_share_max,
        is_long_bearish=(
            bar.close < bar.open
            and body_share >= config.kline.long_body_share_min
        ),
        has_long_lower_shadow=(
            lower_shadow_share >= config.kline.long_shadow_share_min
        ),
    )


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
