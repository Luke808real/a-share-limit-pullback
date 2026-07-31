"""Structured models for screen runs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import Field, field_validator

from limit_pullback.models.base import DomainModel, require_aware_datetime


class ScreenRunResult(DomainModel):
    run_id: str
    kind: str
    as_of: date
    start: date | None = None
    snapshot_id: str
    strategy_commit: str
    config_hash: str
    output_hash: str
    universe_size: int = Field(ge=0)
    codes: tuple[str, ...] = ()
    rows_count: int = Field(ge=0)
    status_counts: dict[str, int] = {}
    new_anchor_count: int = Field(ge=0)
    active_setup_count: int = Field(ge=0)
    entry_candidate_count: int = Field(ge=0)
    quality_rejection_count: int = Field(ge=0)
    verify_replay: bool = False
    verify_replay_matched: bool | None = None
    reused: bool = False
    output_path: str | None = None
    state_path: str | None = None
    notes: tuple[str, ...] = ()


class ScreenState(DomainModel):
    code: str = Field(pattern=r"^\d{6}$")
    last_processed_date: date
    signal_json: str
    setup_id: str | None = None
    snapshot_id: str
    bars_prefix_hash: str
    processed_at: datetime

    @field_validator("processed_at")
    @classmethod
    def validate_processed_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "processed_at")


class ScreenRunManifest(DomainModel):
    run_id: str
    kind: str
    as_of: date
    start: date | None = None
    snapshot_id: str
    strategy_commit: str
    config_hash: str
    dataset_snapshot_id: str
    output_hash: str
    rows_count: int = Field(ge=0)
    created_at: datetime
    status_counts: dict[str, int] = {}
    verify_replay_matched: bool | None = None

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "created_at")
