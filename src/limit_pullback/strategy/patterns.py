"""Weighted, missing-aware pullback pattern evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

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
PATTERN_SCORE_QUANTUM = Decimal("0.01")
PATTERN_PRIORITY = (
    PatternType.BEARISH_PULLBACK,
    PatternType.AIR_REFUEL,
)


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


def select_primary_pattern(
    matched_patterns: set[PatternType] | frozenset[PatternType],
    pattern_scores: dict[PatternType, Decimal],
) -> PatternType | None:
    return next(
        iter(sorted(
            matched_patterns,
            key=lambda item: (
                -pattern_scores[item],
                PATTERN_PRIORITY.index(item),
            ),
        )),
        None,
    )


def explain_primary_pattern(
    matched_patterns: set[PatternType] | frozenset[PatternType],
    pattern_scores: dict[PatternType, Decimal],
    primary_pattern: PatternType | None,
) -> str:
    if primary_pattern is None:
        return "NO_PATTERN_REACHED_MINIMUM_RATIO"
    if len(matched_patterns) == 1:
        return f"ONLY_MATCHED_PATTERN:{primary_pattern.value}"
    top_score = pattern_scores[primary_pattern]
    tied = tuple(
        pattern
        for pattern in matched_patterns
        if pattern_scores[pattern] == top_score
    )
    if len(tied) > 1:
        return (
            f"TIE_BREAK_PRIORITY:{primary_pattern.value}:"
            "BEARISH_PULLBACK>AIR_REFUEL"
        )
    return f"HIGHEST_PATTERN_SCORE:{primary_pattern.value}:{top_score}"


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
    pattern_scores = {
        PatternType.AIR_REFUEL: (
            air_score.match_ratio * Decimal("100")
        ).quantize(PATTERN_SCORE_QUANTUM, rounding=ROUND_HALF_UP),
        PatternType.BEARISH_PULLBACK: (
            bearish_score.match_ratio * Decimal("100")
        ).quantize(PATTERN_SCORE_QUANTUM, rounding=ROUND_HALF_UP),
    }
    matched_patterns: set[PatternType] = set()
    if (
        air_score.available_count > 0
        and air_score.match_ratio >= threshold
    ):
        matched_patterns.add(PatternType.AIR_REFUEL)
    if (
        bearish_score.available_count > 0
        and bearish_score.match_ratio >= threshold
    ):
        matched_patterns.add(PatternType.BEARISH_PULLBACK)
    primary_pattern = select_primary_pattern(
        matched_patterns,
        pattern_scores,
    )
    return PatternEvaluation(
        air_refuel=air_score,
        bearish_pullback=bearish_score,
        matched_patterns=frozenset(matched_patterns),
        primary_pattern=primary_pattern,
        pattern_scores=pattern_scores,
        primary_pattern_reason=explain_primary_pattern(
            matched_patterns,
            pattern_scores,
            primary_pattern,
        ),
    )
