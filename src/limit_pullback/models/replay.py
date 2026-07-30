"""Strict structured output for a single-stock in-memory timeline replay."""

from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from limit_pullback.models.base import (
    DecimalValue,
    DomainModel,
    PositiveDecimal,
)
from limit_pullback.models.enums import (
    DataQuality,
    EntryRoomState,
    EventFlag,
    PatternType,
    ScoreProfile,
    SetupStage,
    SetupTerminationReason,
)
from limit_pullback.models.inspect import DataSourceReport
from limit_pullback.models.signal import (
    AnchorSnapshot,
    B2TriggerSnapshot,
    ConditionSnapshot,
    InvalidPriceSnapshot,
    ResistanceCandidateSnapshot,
    ResistanceSnapshot,
    S1Snapshot,
    SupportSnapshot,
)


class ReplayTimelineItem(DomainModel):
    trade_date: date
    setup_id: str = Field(min_length=1)
    setup_stage: SetupStage
    event_flags: tuple[EventFlag, ...] = ()
    event_reasons: dict[EventFlag, tuple[str, ...]] = Field(default_factory=dict)
    matched_patterns: tuple[PatternType, ...] = ()
    primary_pattern: PatternType | None = None
    pattern_scores: dict[PatternType, DecimalValue] = Field(default_factory=dict)
    pattern_conditions: dict[PatternType, ConditionSnapshot] = Field(
        default_factory=dict
    )
    primary_pattern_reason: str | None = None
    b1_conditions: ConditionSnapshot | None = None
    b2_conditions: ConditionSnapshot | None = None
    score_profile: ScoreProfile
    normalized_score: DecimalValue
    is_entry_candidate: bool
    anchor_snapshot: AnchorSnapshot | None = None
    support_snapshot: SupportSnapshot | None = None
    invalid_price_snapshot: InvalidPriceSnapshot | None = None
    b2_trigger_snapshot: B2TriggerSnapshot | None = None
    expected_b2_trigger_price: PositiveDecimal | None = None
    resistance_candidates: tuple[ResistanceCandidateSnapshot, ...] = ()
    immediate_resistance: ResistanceSnapshot | None = None
    target_s1: S1Snapshot | None = None
    entry_reference_price: PositiveDecimal | None = None
    entry_headroom_pct: DecimalValue | None = None
    entry_room_state: EntryRoomState | None = None
    entry_room_reasons: tuple[str, ...] = ()
    initial_invalid_price: PositiveDecimal | None = None
    invalid_price: PositiveDecimal | None = None
    reasons: dict[str, str] = Field(default_factory=dict)
    risks: dict[str, str] = Field(default_factory=dict)
    invalidation_reasons: tuple[str, ...] = ()
    data_quality: DataQuality
    quality_flags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_explanations(self) -> "ReplayTimelineItem":
        if set(self.event_reasons) != set(self.event_flags):
            raise ValueError("timeline event reasons must match event flags")
        if set(self.pattern_scores) != set(self.pattern_conditions):
            raise ValueError("timeline pattern explanations must match scores")
        return self


class ReplayTransitionSummary(DomainModel):
    first_anchor_date: date | None = None
    first_b1_date: date | None = None
    first_b2_ready_date: date | None = None
    first_b2_confirmed_date: date | None = None
    first_near_s1_date: date | None = None
    first_s1_breakout_date: date | None = None
    first_s2_exhausted_date: date | None = None
    invalid_date: date | None = None


class SetupSummary(DomainModel):
    setup_id: str = Field(min_length=1)
    anchor_date: date
    score_profile: ScoreProfile
    data_quality: DataQuality
    first_b1_date: date | None = None
    first_b2_ready_date: date | None = None
    first_b2_confirmed_date: date | None = None
    first_near_s1_date: date | None = None
    first_s1_breakout_date: date | None = None
    first_s2_exhausted_date: date | None = None
    invalid_date: date | None = None
    final_stage: SetupStage
    closed_date: date | None = None
    termination_reason: SetupTerminationReason

    @model_validator(mode="after")
    def validate_termination(self) -> "SetupSummary":
        if self.termination_reason is SetupTerminationReason.ACTIVE:
            if self.closed_date is not None:
                raise ValueError("ACTIVE setup cannot have closed_date")
        elif self.closed_date is None:
            raise ValueError("terminated setup requires closed_date")
        if (
            self.termination_reason is SetupTerminationReason.INVALIDATED
            and self.closed_date != self.invalid_date
        ):
            raise ValueError(
                "INVALIDATED setup must close on its invalid_date"
            )
        return self


class ReplayOutput(DomainModel):
    code: str = Field(pattern=r"^\d{6}$")
    requested_start: date | None = None
    requested_as_of: date
    actual_first_bar_date: date
    actual_last_bar_date: date
    lookback_calendar_days: int = Field(ge=1)
    is_stale: bool
    daily_provider: str = Field(min_length=1)
    daily_provider_version: str = Field(min_length=1)
    limit_pool_provider: str = Field(min_length=1)
    limit_pool_provider_version: str = Field(min_length=1)
    used_limit_pool_dates: tuple[date, ...] = ()
    daily_data: DataSourceReport
    limit_pool_data: tuple[DataSourceReport, ...] = ()
    replay_data_quality: DataQuality
    current_setup_data_quality: DataQuality | None = None
    quality_flags: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    transitions: ReplayTransitionSummary
    current_setup_summary: SetupSummary | None = None
    setup_summaries: tuple[SetupSummary, ...] = ()
    timeline: tuple[ReplayTimelineItem, ...]

    @model_validator(mode="after")
    def validate_timeline(self) -> "ReplayOutput":
        if not self.timeline:
            raise ValueError("replay timeline cannot be empty")
        dates = tuple(item.trade_date for item in self.timeline)
        if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
            raise ValueError("replay timeline dates must be unique and ascending")
        if dates[-1] != self.actual_last_bar_date:
            raise ValueError("timeline must end on actual_last_bar_date")
        if self.actual_last_bar_date > self.requested_as_of:
            raise ValueError("actual_last_bar_date cannot exceed requested_as_of")
        if self.is_stale != (
            self.actual_last_bar_date < self.requested_as_of
        ):
            raise ValueError("is_stale does not match actual/requested dates")
        if self.is_stale and "STALE_DATA" not in self.quality_flags:
            raise ValueError("stale replay requires STALE_DATA quality flag")
        if (
            (self.current_setup_summary is None)
            != (self.current_setup_data_quality is None)
        ):
            raise ValueError(
                "current setup summary and quality must appear together"
            )
        if (
            self.current_setup_summary is not None
            and self.current_setup_summary.data_quality
            is not self.current_setup_data_quality
        ):
            raise ValueError("current setup quality must match its summary")
        return self
