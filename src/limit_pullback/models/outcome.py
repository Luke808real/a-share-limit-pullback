"""Research-only models for the Phase 2D.0 signal outcome study."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from limit_pullback.models.base import DecimalValue, DomainModel, PositiveDecimal
from limit_pullback.models.enums import (
    EntryRoomState,
    ExecutionLabel,
    FillStatus,
    OutcomeStatus,
    PatternOutcome,
    PatternType,
    SetupStage,
)


class OutcomeStudyConfig(DomainModel):
    """Independent research configuration; never merged into strategy.yaml."""

    forward_horizons: tuple[int, ...] = (1, 3, 5, 10)
    max_holding_sessions: int = Field(default=10, ge=1)

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "OutcomeStudyConfig":
        config = cls.model_validate(payload)
        if tuple(sorted(set(config.forward_horizons))) != config.forward_horizons:
            raise ValueError("forward_horizons must be sorted and unique")
        if config.max_holding_sessions < max(config.forward_horizons):
            raise ValueError("max_holding_sessions must cover all horizons")
        return config


class OutcomeEpisode(DomainModel):
    """One frozen first-entry episode plus its future-only outcome labels."""

    code: str = Field(pattern=r"^\d{6}$")
    setup_id: str = Field(min_length=1)
    execution_label: ExecutionLabel
    setup_stage: SetupStage
    signal_date: date
    anchor_date: date | None = None
    anchor_price: PositiveDecimal | None = None
    support_low: PositiveDecimal | None = None
    support_high: PositiveDecimal | None = None
    support_center: PositiveDecimal | None = None
    b2_trigger_price: PositiveDecimal | None = None

    setup_quality_score: DecimalValue
    entry_quality_score: DecimalValue | None = None
    days_since_anchor: int | None = Field(default=None, ge=0)
    entry_room_state: EntryRoomState | None = None
    is_entry_candidate: bool = False

    preferred_entry: PositiveDecimal | None = None
    buy_zone_low: PositiveDecimal | None = None
    buy_zone_high: PositiveDecimal | None = None
    invalid_price: PositiveDecimal | None = None
    s1_price: PositiveDecimal | None = None
    entry_reference_price: PositiveDecimal | None = None

    next_trade_date: date | None = None
    fill_status: FillStatus
    fill_date: date | None = None
    fill_price: PositiveDecimal | None = None
    outcome: OutcomeStatus
    resolution_date: date | None = None
    exit_price: PositiveDecimal | None = None
    r_multiple: DecimalValue | None = None
    conservative_r_multiple: DecimalValue | None = None
    mfe_pct: DecimalValue | None = None
    mae_pct: DecimalValue | None = None
    holding_sessions_to_resolution: int | None = Field(default=None, ge=1)
    future_sessions_available: int = Field(ge=0)
    eligibility_reason: str | None = None

    pattern_1d: PatternOutcome | None = None
    pattern_3d: PatternOutcome | None = None
    pattern_5d: PatternOutcome | None = None
    pattern_10d: PatternOutcome | None = None

    prep_conversion_1d: bool | None = None
    prep_conversion_3d: bool | None = None
    prep_conversion_5d: bool | None = None
    prep_mfe_1d: DecimalValue | None = None
    prep_mfe_3d: DecimalValue | None = None
    prep_mfe_5d: DecimalValue | None = None
    prep_mae_1d: DecimalValue | None = None
    prep_mae_3d: DecimalValue | None = None
    prep_mae_5d: DecimalValue | None = None

    raw_signal_days: int = Field(default=1, ge=1)
    data_quality: str
    quality_flags: tuple[str, ...] = ()

    snapshot_id: str = Field(min_length=1)
    snapshot_created_at: datetime | None = None
    strategy_commit: str = Field(min_length=1)
    strategy_config_hash: str = Field(min_length=1)
    trade_plan_config_hash: str = Field(min_length=1)
    outcome_config_hash: str = Field(min_length=1)
    frozen_event_hash: str = Field(min_length=1)


class OutcomeStats(DomainModel):
    episodes: int = Field(ge=0)
    raw_signal_days: int = Field(ge=0)
    eligible: int = Field(ge=0)
    no_fill: int = Field(ge=0)
    cancel_gap_invalid: int = Field(ge=0)
    filled: int = Field(ge=0)
    resolved: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    timeout: int = Field(ge=0)
    censored: int = Field(ge=0)
    fill_rate: DecimalValue
    strict_win_rate: DecimalValue
    conservative_win_rate: DecimalValue
    average_win_r: DecimalValue | None = None
    average_loss_r: DecimalValue | None = None
    average_r: DecimalValue | None = None
    expectancy_r: DecimalValue | None = None
    median_r: DecimalValue | None = None
    median_mfe: DecimalValue | None = None
    median_mae: DecimalValue | None = None
    median_holding_sessions: DecimalValue | None = None


class OutcomeStudySummary(DomainModel):
    dataset_mode: str = "FINAL_VINTAGE_CAUSAL"
    snapshot_id: str = Field(min_length=1)
    start: date
    end: date
    confirmed_date_count: int = Field(ge=0)
    confirmed_code_count: int = Field(ge=0)
    provisional_only_date_count: int = Field(ge=0)
    raw_signal_days: int = Field(ge=0)
    episode_count: int = Field(ge=0)
    b1_prep_episodes: int = Field(ge=0)
    stage_stats: dict[str, OutcomeStats]
    setup_quality_groups: dict[str, OutcomeStats] = {}
    entry_quality_groups: dict[str, OutcomeStats] = {}
    days_since_anchor_groups: dict[str, OutcomeStats] = {}
    pattern_success: dict[str, dict[str, int]] = {}
    audit: dict[str, object] = {}
    limitations: tuple[str, ...] = ()
    strategy_commit: str = Field(min_length=1)
    strategy_config_hash: str = Field(min_length=1)
    trade_plan_config_hash: str = Field(min_length=1)
    outcome_config_hash: str = Field(min_length=1)


__all__ = [
    "OutcomeEpisode",
    "OutcomeStats",
    "OutcomeStudyConfig",
    "OutcomeStudySummary",
]
