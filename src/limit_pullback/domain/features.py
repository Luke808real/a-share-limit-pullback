"""Feature vocabulary (REF-R2): facts, not policy."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import Field

from limit_pullback.models.base import DomainModel


class FeatureAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    SOURCE_MISSING = "SOURCE_MISSING"
    DATA_QUALITY_BLOCKED = "DATA_QUALITY_BLOCKED"
    INVALID_INPUT = "INVALID_INPUT"
    CENSORED = "CENSORED"
    NOT_YET_ELIGIBLE = "NOT_YET_ELIGIBLE"


class FeatureRecord(DomainModel):
    """One computed fact with explicit availability and provenance.

    A plain `None` value must never stand in for a missing feature; the
    availability enum and missing_reason carry that semantics explicitly.
    """

    feature_id: str = Field(min_length=1)
    feature_version: str = Field(min_length=1)
    symbol: str = Field(min_length=6, max_length=6)
    setup_id: str | None = None
    as_of: date
    value: Any | None = None
    unit: str | None = None
    availability: FeatureAvailability
    missing_reason: str | None = None
    input_window_start: date | None = None
    input_window_end: date | None = None
    data_snapshot_id: str | None = None
    calculation_version: str | None = None
    source_refs: tuple[str, ...] = ()


__all__ = ["FeatureAvailability", "FeatureRecord"]
