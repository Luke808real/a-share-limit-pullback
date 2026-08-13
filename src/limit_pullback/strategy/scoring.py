"""Compatibility shim for the ranking policy moved to selection (REF-R6).

The frozen FULL/PRICE_ONLY score construction now lives in
`limit_pullback.selection.ranking`; this module re-exports the same objects.
"""

from limit_pullback.selection.ranking import (
    ONE,
    ZERO,
    _fractional_score,
    build_score,
)

__all__ = ["ONE", "ZERO", "_fractional_score", "build_score"]
