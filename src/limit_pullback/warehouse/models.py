"""Structured models for warehouse commands and metadata."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator

from limit_pullback.models.base import (
    DecimalValue,
    DomainModel,
    NonNegativeDecimal,
    PositiveDecimal,
    require_aware_datetime,
)

ProbeStatus = Literal[
    "AVAILABLE",
    "UNAVAILABLE_PERMISSION",
    "UNAVAILABLE_PROVIDER",
    "MALFORMED_RESPONSE",
]

ReconciliationStatus = Literal[
    "PROVISIONAL",
    "CONFIRMED",
    "CONFIRMED_SINGLE_SOURCE",
    "INCOMPLETE",
    "CONFLICTED",
    "QUARANTINED",
]


class ProbeCapability(DomainModel):
    capability: str
    status: ProbeStatus
    error_code: str | None = None
    detail: str | None = None


class ProbeResult(DomainModel):
    provider: str
    provider_version: str | None = None
    capabilities: tuple[ProbeCapability, ...]
    overall: ProbeStatus


class SnapshotRecord(DomainModel):
    snapshot_id: str
    created_at: datetime
    as_of: date
    provider_versions: dict[str, str]
    source_file_hashes: dict[str, str]
    canonical_file_hashes: dict[str, str]
    reconciliation_policy_version: str
    status: str = "CURRENT"
    manifest_path: str | None = None

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "created_at")


class IngestRunRecord(DomainModel):
    run_id: str
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    codes: tuple[str, ...] = ()
    config_json: str | None = None
    error: str | None = None

    @field_validator("started_at")
    @classmethod
    def validate_started_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "started_at")

    @field_validator("finished_at")
    @classmethod
    def validate_finished_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_aware_datetime(value, "finished_at")


class SourceFileRecord(DomainModel):
    path: str
    provider: str
    ingest_run_id: str
    sha256: str
    row_count: int = Field(ge=0)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "recorded_at")


class ReconciliationRecord(DomainModel):
    reconciliation_id: str
    code: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    providers: tuple[str, ...]
    status: ReconciliationStatus
    selected_provider: str | None = None
    notes: str | None = None
    created_at: datetime
    snapshot_id: str | None = None

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "created_at")


class QuarantineRecord(DomainModel):
    record_id: str
    code: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    providers: tuple[str, ...]
    reason: str
    payload: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "created_at")


class CanonicalDailyBar(DomainModel):
    code: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    preclose: PositiveDecimal
    volume: NonNegativeDecimal
    amount: NonNegativeDecimal
    turnover_rate: DecimalValue | None = None
    pct_change: DecimalValue | None = None
    trade_status: bool = True
    is_st: bool | None = None
    selected_provider: str
    reconciliation_status: ReconciliationStatus
    source_row_hash: str
    dataset_snapshot_id: str


class CanonicalLimitUpRecord(DomainModel):
    code: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    name: str
    limit_price: PositiveDecimal
    first_seal_time: time | None = None
    last_seal_time: time | None = None
    open_count: int | None = Field(default=None, ge=0)
    consecutive_count: int | None = Field(default=None, ge=1)
    turnover_rate: DecimalValue | None = None
    float_market_cap: DecimalValue | None = None
    total_market_cap: DecimalValue | None = None
    industry: str | None = None
    selected_provider: str
    reconciliation_status: ReconciliationStatus
    source_row_hash: str
    dataset_snapshot_id: str


class DataStatusOutput(DomainModel):
    latest_requested_date: date | None = None
    latest_available_date_by_provider: dict[str, date | None] = {}
    latest_canonical_date: date | None = None
    reconciliation_status: dict[str, int] = {}
    lagging_providers: tuple[str, ...] = ()
    conflicted_rows: int = 0
    quarantined_rows: int = 0
    dataset_snapshot_id: str | None = None


class ValidationIssue(DomainModel):
    check: str
    severity: Literal["error", "warning"]
    detail: str


class ValidationResult(DomainModel):
    valid: bool
    snapshot_id: str | None = None
    issues: tuple[ValidationIssue, ...] = ()


class BootstrapResult(DomainModel):
    run_id: str
    kind: str = "bootstrap"
    snapshot_id: str | None = None
    start_date: date
    end_date: date
    codes: tuple[str, ...]
    raw_files: tuple[SourceFileRecord, ...] = ()
    canonical_daily_rows: int = 0
    canonical_pool_rows: int = 0
    reconciliation_rows: int = 0
    quarantine_rows: int = 0
    reused: bool = False
    notes: tuple[str, ...] = ()
    failure_count: int = 0
    pending_failures: int = 0
    metrics: dict[str, Any] = {}


class UpdateResult(DomainModel):
    run_id: str
    kind: str = "update"
    snapshot_id: str | None = None
    as_of: date
    previous_snapshot_id: str | None = None
    codes: tuple[str, ...]
    new_trade_dates: tuple[date, ...] = ()
    raw_files: tuple[SourceFileRecord, ...] = ()
    canonical_daily_rows: int = 0
    canonical_pool_rows: int = 0
    reconciliation_rows: int = 0
    quarantine_rows: int = 0
    reused: bool = False
    notes: tuple[str, ...] = ()
