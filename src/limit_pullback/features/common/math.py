"""Pure feature math: PIT continuous prices and kline ratio facts.

REF-R4/R4.2: only policy-free calculations live here. Threshold-classified
kline flags and the indicator pipeline (which composes kline policy) live in
the strategy glue layer and are imported by `strategy/math.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from limit_pullback.models.market import DailyBar
from limit_pullback.models.strategy import (
    ContinuousPricePoint,
)
from pydantic import BaseModel, ConfigDict


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


class KlineRatios(BaseModel):
    """Policy-free kline shape facts for one daily bar."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    body_share: Decimal
    close_location: Decimal
    upper_shadow_share: Decimal
    lower_shadow_share: Decimal
    amplitude: Decimal
    is_bullish: bool
    is_bearish: bool


def calculate_kline_ratios(bar: DailyBar) -> KlineRatios:
    """Kline shape ratios as pure facts; no thresholds involved."""

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
    return KlineRatios(
        body_share=body_share,
        close_location=close_location,
        upper_shadow_share=upper_shadow_share,
        lower_shadow_share=lower_shadow_share,
        amplitude=amplitude,
        is_bullish=bar.close > bar.open,
        is_bearish=bar.close < bar.open,
    )
