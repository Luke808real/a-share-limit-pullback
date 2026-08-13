"""REF-R4 feature package.

Features answer "what is the fact"; policy answers "is it good". This first
extraction slice moves the pure math and zero-copy view primitives verbatim
from `strategy/math.py` and `strategy/indicators.py` (target: features/common);
the legacy `strategy.*` modules become re-export shims.

Recorded coupling: `calculate_kline_metrics` still emits threshold-classified
flags (doji/small-body/long-shadow) using frozen strategy config values. The
ratio facts are feature-grade; the flag classification is policy-coupled and
is scheduled for policy extraction in a later round.
"""

from limit_pullback.features.common.math import (
    build_continuous_prices,
    calculate_kline_ratios,
)
from limit_pullback.features.common.math import KlineRatios
from limit_pullback.features.common.views import (
    IndicatorPrefixView,
    SequencePrefixView,
)

__all__ = [
    "IndicatorPrefixView",
    "KlineRatios",
    "SequencePrefixView",
    "build_continuous_prices",
    "calculate_kline_ratios",
]
