"""Structured, in-memory output for the stage-2A single-stock command."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, field_validator

from limit_pullback.models.base import DomainModel, require_aware_datetime
from limit_pullback.models.enums import DataQuality
from limit_pullback.models.signal import StrategySignal


class DataSourceReport(DomainModel):
    provider: str = Field(min_length=1)
    requested_start: date
    requested_end: date
    fetched_at: datetime | None = None
    quality: DataQuality
    record_count: int = Field(ge=0)
    quality_flags: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_aware_datetime(value, "fetched_at")


class InspectOutput(DomainModel):
    code: str = Field(pattern=r"^\d{6}$")
    as_of: date
    days: int = Field(ge=1)
    generated_at: datetime
    daily_data: DataSourceReport
    limit_up_pool_data: DataSourceReport
    signal: StrategySignal

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "generated_at")
