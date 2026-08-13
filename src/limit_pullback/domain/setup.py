"""Setup identity and stage vocabulary (REF-R2)."""

from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from limit_pullback.models.base import DomainModel
from limit_pullback.models.enums import EventFlag, SetupStage

# Product vocabulary -> frozen runtime stage. SECOND_LAUNCH is deliberately
# absent: it is an outcome/event, not a SetupStage.
PRODUCT_TO_RUNTIME_STAGE: dict[str, SetupStage] = {
    "T0": SetupStage.LIMIT_ANCHOR,
    "PULLBACK": SetupStage.WATCH_PULLBACK,
    "B1": SetupStage.B1_READY,
    "B2_READY": SetupStage.B2_READY,
    "B2_CONFIRMED": SetupStage.B2_CONFIRMED,
}


class SetupIdentity(DomainModel):
    """Identity of one setup created by one valid anchor.

    A new valid anchor creates a new SetupIdentity; it never overwrites an old
    setup. This contract formalizes the existing `code:YYYYMMDD:...` setup_id
    vocabulary and is not consumed by runtime paths yet.
    """

    setup_id: str = Field(min_length=1)
    symbol: str = Field(min_length=6, max_length=6)
    anchor_date: date
    anchor_event_id: str | None = None
    created_as_of: date
    strategy_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_symbol_prefix(self) -> SetupIdentity:
        if not self.setup_id.startswith(f"{self.symbol}:"):
            raise ValueError("setup_id must start with '<symbol>:'")
        return self


__all__ = [
    "EventFlag",
    "PRODUCT_TO_RUNTIME_STAGE",
    "SetupIdentity",
    "SetupStage",
]
