"""REF-R2 domain vocabulary package.

This package formalizes the stable public vocabulary of the strategy system
(what things are called and what they mean) without business calculation.

Extraction rule for REF-R2:
- re-exports point only at `limit_pullback.models.*` (the existing domain-ish
  vocabulary) so no new behavior or schema is introduced;
- the warehouse/provider layers stay outside this package until REF-R3 moves
  the canonical data contract behind a proper data boundary;
- new additive contracts (SetupIdentity, FeatureRecord, RunContext,
  DataProvenance) are documentation-grade formalizations of existing
  vocabulary and are not consumed by runtime paths yet.
"""

from limit_pullback.domain.features import (
    FeatureAvailability,
    FeatureRecord,
)
from limit_pullback.domain.market import DailyBar, LimitUpRecord
from limit_pullback.domain.provenance import DataProvenance
from limit_pullback.domain.run import RunContext
from limit_pullback.domain.setup import (
    PRODUCT_TO_RUNTIME_STAGE,
    SetupIdentity,
)
from limit_pullback.domain.state import (
    AnchorSnapshot,
    B2TriggerSnapshot,
    InvalidPriceSnapshot,
    Lifecycle,
    S1Snapshot,
    SupportSnapshot,
)

__all__ = [
    "AnchorSnapshot",
    "B2TriggerSnapshot",
    "DailyBar",
    "DataProvenance",
    "FeatureAvailability",
    "FeatureRecord",
    "InvalidPriceSnapshot",
    "Lifecycle",
    "LimitUpRecord",
    "PRODUCT_TO_RUNTIME_STAGE",
    "RunContext",
    "S1Snapshot",
    "SetupIdentity",
    "SupportSnapshot",
]
