"""Pure strategy calculation engine."""

from limit_pullback.strategy.engine import evaluate_strategy, make_setup_id
from limit_pullback.strategy.math import (
    build_continuous_prices,
    calculate_indicators,
)
from limit_pullback.strategy.structure import (
    cluster_price_candidates,
    detect_anchor,
    is_one_word_limit,
    is_t_word_limit,
)

__all__ = [
    "build_continuous_prices",
    "calculate_indicators",
    "cluster_price_candidates",
    "detect_anchor",
    "evaluate_strategy",
    "is_one_word_limit",
    "is_t_word_limit",
    "make_setup_id",
]
