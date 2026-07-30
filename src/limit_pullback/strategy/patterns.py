"""Weighted, missing-aware pullback pattern evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import PatternType
from limit_pullback.models.market import DailyBar
from limit_pullback.models.strategy import (
    AnchorEvaluation,
    ConditionScore,
    IndicatorPoint,
    PatternEvaluation,
    PriceCluster,
)


ZERO = Decimal("0")
ONE = Decimal("1")


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, ZERO) / Decimal(len(values))


def _condition_score(
    conditions: dict[str, bool | None],
) -> ConditionScore:
    return ConditionScore(
        matched=tuple(sorted(
            name for name, result in conditions.items() if result is True
        )),
        failed=tuple(sorted(
            name for name, result in conditions.items() if result is False
        )),
        unavailable=tuple(sorted(
            name for name, result in conditions.items() if result is None
        )),
    )


def evaluate_patterns(
    bars: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    anchor: AnchorEvaluation,
    support: PriceCluster | None,
    as_of: date,
    config: StrategyConfig,
) -> PatternEvaluation:
    ordered = tuple(sorted(
        (bar for bar in bars if bar.trade_date <= as_of),
        key=lambda bar: bar.trade_date,
    ))
    by_date = {point.trade_date: point for point in indicators}
    anchor_bar = next(
        bar for bar in ordered if bar.trade_date == anchor.snapshot.anchor_date
    )
    current = ordered[-1]
    current_indicator = by_date[current.trade_date]
    post_anchor = tuple(
        bar for bar in ordered if bar.trade_date > anchor.snapshot.anchor_date
    )
    recent_volume_days = config.patterns.air_refuel.recent_volume_days

    if len(post_anchor) >= 4:
        amplitudes = tuple(by_date[bar.trade_date].kline.amplitude for bar in post_anchor)
        midpoint = len(amplitudes) // 2
        amplitude_contraction = (
            _mean(amplitudes[midpoint:])
            <= _mean(amplitudes[:midpoint])
            * config.patterns.air_refuel.amplitude_contraction_maximum
        )
    else:
        amplitude_contraction = None

    if len(post_anchor) >= recent_volume_days:
        recent_average_volume = _mean(tuple(
            bar.volume for bar in post_anchor[-recent_volume_days:]
        ))
        air_volume_contraction = (
            recent_average_volume
            <= anchor_bar.volume
            * config.patterns.air_refuel.recent_volume_to_anchor_maximum
        )
    else:
        air_volume_contraction = None

    short_mas = tuple(
        value
        for window in (5, 10)
        if (value := current_indicator.raw_equivalent_mas.get(window)) is not None
    )
    near_short_ma = (
        current.close
        >= min(short_mas)
        * (ONE - config.patterns.air_refuel.ma_distance_maximum)
        if short_mas
        else None
    )

    air_conditions = {
        "post_anchor_close_floor": (
            min(bar.close for bar in post_anchor)
            >= anchor.snapshot.anchor_price
            * config.patterns.air_refuel.minimum_close_to_anchor
            if post_anchor
            else None
        ),
        "current_above_anchor": (
            current.close
            >= anchor.snapshot.anchor_price
            * config.patterns.air_refuel.current_close_to_anchor_minimum
        ),
        "amplitude_contraction": amplitude_contraction,
        "volume_contraction": air_volume_contraction,
        "near_short_ma": near_short_ma,
    }
    air_score = _condition_score(air_conditions)

    bearish_exists = (
        any(bar.close < bar.open for bar in post_anchor)
        if post_anchor
        else None
    )
    support_touch = (
        any(
            bar.low
            <= support.high
            * (ONE + config.patterns.bearish_pullback.support_touch_tolerance)
            and bar.high
            >= support.low
            * (ONE - config.patterns.bearish_pullback.support_touch_tolerance)
            for bar in post_anchor
        )
        if support is not None and post_anchor
        else None
    )
    if post_anchor:
        pullback_average_volume = _mean(tuple(bar.volume for bar in post_anchor))
        bearish_volume_contraction = (
            pullback_average_volume
            <= anchor_bar.volume
            * config.patterns.bearish_pullback.volume_contraction_maximum
        )
    else:
        bearish_volume_contraction = None
    no_volume_break = (
        not any(
            bar.close
            < support.low * (ONE - config.support.invalid_buffer)
            and bar.volume >= anchor_bar.volume
            for bar in post_anchor
        )
        if support is not None and post_anchor
        else None
    )
    kline = current_indicator.kline
    stabilization = (
        kline.is_doji
        or kline.has_long_lower_shadow
        or (kline.is_bullish and kline.is_small_body)
        or (
            kline.is_bearish
            and kline.is_small_body
            and current.volume < anchor_bar.volume
        )
    )
    bearish_score = _condition_score(
        {
            "bearish_bar_exists": bearish_exists,
            "support_touch": support_touch,
            "volume_contraction": bearish_volume_contraction,
            "no_volume_break": no_volume_break,
            "stabilization": stabilization,
        }
    )

    threshold = config.patterns.minimum_condition_ratio
    patterns: set[PatternType] = set()
    if (
        air_score.available_count > 0
        and air_score.match_ratio >= threshold
    ):
        patterns.add(PatternType.AIR_REFUEL)
    if (
        bearish_score.available_count > 0
        and bearish_score.match_ratio >= threshold
    ):
        patterns.add(PatternType.BEARISH_PULLBACK)
    return PatternEvaluation(
        air_refuel=air_score,
        bearish_pullback=bearish_score,
        patterns=frozenset(patterns),
    )
