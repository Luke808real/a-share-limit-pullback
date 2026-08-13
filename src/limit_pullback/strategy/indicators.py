"""Compatibility shim for the sequence views moved to features/common (REF-R4)."""

from limit_pullback.features.common.views import (
    IndicatorPrefixView,
    SequencePrefixView,
)

__all__ = ["IndicatorPrefixView", "SequencePrefixView"]
