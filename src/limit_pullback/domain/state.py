"""Setup lifecycle and frozen snapshot vocabulary (REF-R2)."""

from limit_pullback.models.enums import SetupTerminationReason
from limit_pullback.models.signal import (
    AnchorSnapshot,
    B2TriggerSnapshot,
    InvalidPriceSnapshot,
    S1Snapshot,
    SupportSnapshot,
)

# The frozen lifecycle vocabulary already exists as SetupTerminationReason:
# ACTIVE / INVALIDATED / SUPERSEDED_BY_NEW_ANCHOR / EXPIRED. Alias, do not
# duplicate, so lifecycle and termination reasons can never diverge.
Lifecycle = SetupTerminationReason

__all__ = [
    "AnchorSnapshot",
    "B2TriggerSnapshot",
    "InvalidPriceSnapshot",
    "Lifecycle",
    "S1Snapshot",
    "SetupTerminationReason",
    "SupportSnapshot",
]
