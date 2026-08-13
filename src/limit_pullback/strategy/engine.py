"""Compatibility shim for the setup state engine (REF-R5 R5.2).

The engine implementation now lives in `limit_pullback.state.engine` and its
helpers in `limit_pullback.state.engine_helpers`. This module re-exports the
same names so existing callers and monkeypatch seams keep working.

`evaluate_strategy` is resolved lazily through PEP 562 `__getattr__`, which
breaks the import cycle between `state.engine` and the strategy package.
"""

from __future__ import annotations

from limit_pullback.state.engine_helpers import (
    ACTIONABLE,
    ONE,
    ZERO,
    _as_cluster,
    _as_s1_cluster,
    _conditions,
    _entry_quality_score,
    _entry_room,
    _evaluate_b1,
    _evaluate_b2_confirmation,
    _evaluate_event_flags,
    _evaluate_invalid_reasons,
    _expected_b2_trigger,
    _mean,
    _platform_b2_trigger,
    _quantize_price,
    _risk_reward,
    make_setup_id,
)
from limit_pullback.strategy.structure import (
    cluster_price_candidates,
    detect_anchor,
    generate_resistance_candidates,
    generate_support_candidates,
    select_resistance_levels,
    select_support_cluster,
)

__all__ = [
    "ACTIONABLE",
    "ONE",
    "ZERO",
    "_as_cluster",
    "_as_s1_cluster",
    "_conditions",
    "_entry_quality_score",
    "_entry_room",
    "_evaluate_b1",
    "_evaluate_b2_confirmation",
    "_evaluate_event_flags",
    "_evaluate_invalid_reasons",
    "_expected_b2_trigger",
    "_mean",
    "_platform_b2_trigger",
    "_quantize_price",
    "_risk_reward",
    "cluster_price_candidates",
    "detect_anchor",
    "evaluate_strategy",
    "generate_resistance_candidates",
    "generate_support_candidates",
    "make_setup_id",
    "select_resistance_levels",
    "select_support_cluster",
]


def __getattr__(name: str):
    if name == "evaluate_strategy":
        from limit_pullback.state.engine import evaluate_strategy

        return evaluate_strategy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
