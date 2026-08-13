"""Pure strategy calculation engine.

REF-R5 R5.2: `evaluate_strategy` is resolved lazily through PEP 562 so the
strategy package no longer participates in the import cycle with
`limit_pullback.state.engine`; the rest of the public surface stays eager.
"""

from limit_pullback.strategy.engine import make_setup_id
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


def __getattr__(name: str):
    if name == "evaluate_strategy":
        from limit_pullback.strategy.engine import evaluate_strategy

        return evaluate_strategy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
