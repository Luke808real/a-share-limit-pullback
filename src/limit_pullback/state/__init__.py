"""REF-R5 state engine package.

Home of the single setup state engine: transition helpers live in
`state/engine_helpers.py` and the orchestration entry `evaluate_strategy` in
`state/engine.py`. `strategy/engine.py` remains a compatibility shim.
"""

from limit_pullback.state.engine_helpers import (
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

__all__ = [
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
    "make_setup_id",
]
