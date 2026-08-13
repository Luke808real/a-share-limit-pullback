"""Kline threshold policy: classifies pure kline ratios with frozen config."""

from __future__ import annotations

from limit_pullback.features.common.math import KlineRatios, calculate_kline_ratios
from limit_pullback.models.config import IndicatorsConfig
from limit_pullback.models.market import DailyBar
from limit_pullback.models.strategy import KlineMetrics


def classify_kline_flags(
    ratios: KlineRatios,
    config: IndicatorsConfig,
) -> KlineMetrics:
    """Apply frozen kline thresholds to ratio facts (policy, not feature)."""

    return KlineMetrics(
        body_share=ratios.body_share,
        close_location=ratios.close_location,
        upper_shadow_share=ratios.upper_shadow_share,
        lower_shadow_share=ratios.lower_shadow_share,
        amplitude=ratios.amplitude,
        is_bullish=ratios.is_bullish,
        is_bearish=ratios.is_bearish,
        is_doji=ratios.body_share <= config.kline.doji_body_share_max,
        is_small_body=ratios.body_share <= config.kline.small_body_share_max,
        is_long_bearish=(
            ratios.is_bearish
            and ratios.body_share >= config.kline.long_body_share_min
        ),
        has_long_lower_shadow=(
            ratios.lower_shadow_share >= config.kline.long_shadow_share_min
        ),
    )


def calculate_kline_metrics(
    bar: DailyBar,
    config: IndicatorsConfig,
) -> KlineMetrics:
    """Composite: ratio facts + frozen threshold classification."""

    return classify_kline_flags(calculate_kline_ratios(bar), config)


__all__ = ["calculate_kline_metrics", "classify_kline_flags"]
