"""Run context vocabulary (REF-R2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from limit_pullback.models.base import DomainModel, require_aware_datetime


class RunContext(DomainModel):
    """Formal description of one strategy run (evidence input contract).

    This is the vocabulary of the RunManifest target; the runtime evidence
    layer adopts it incrementally in REF-R7. LIVE is vocabulary-only.
    """

    run_id: str = Field(min_length=1)
    runtime_mode: Literal["REPLAY", "DAILY", "LIVE"]
    as_of: date
    runtime_commit_sha: str | None = None
    strategy_version: str | None = None
    config_hash: str | None = None
    data_snapshot_id: str | None = None
    universe_id: str | None = None
    predecessor_generation_id: str | None = None
    engine_versions: dict[str, str] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: str | None = None

    @model_validator(mode="after")
    def _require_aware_datetimes(self) -> RunContext:
        if self.started_at is not None:
            require_aware_datetime(self.started_at, "started_at")
        if self.completed_at is not None:
            require_aware_datetime(self.completed_at, "completed_at")
        return self


__all__ = ["RunContext"]
