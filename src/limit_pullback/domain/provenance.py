"""Data provenance vocabulary (REF-R2)."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from limit_pullback.models.base import DomainModel


class DataProvenance(DomainModel):
    """Provenance block attached to a formal data snapshot."""

    data_provider_system: str = Field(min_length=1)
    data_snapshot_id: str = Field(min_length=1)
    data_as_of: date
    source_version: str | None = None
    adapter_version: str | None = None
    coverage: str | None = None
    quality_summary: str | None = None
    hash: str | None = None


__all__ = ["DataProvenance"]
