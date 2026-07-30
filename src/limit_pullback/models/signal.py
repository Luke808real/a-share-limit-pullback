"""Immutable snapshots and validated strategy signal output."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from pydantic import Field, computed_field, field_validator, model_validator

from limit_pullback.models.base import (
    DecimalValue,
    DomainModel,
    FrozenDomainModel,
    NonNegativeDecimal,
    PositiveDecimal,
    require_aware_datetime,
)
from limit_pullback.models.enums import (
    DataQuality,
    EventFlag,
    ReviewGroup,
    PatternType,
    ScoreProfile,
    SetupStage,
)


NORMALIZED_SCORE_QUANTUM = Decimal("0.01")
MISSING_SCORE_FLAG_PREFIX = "MISSING_SCORE_FIELD:"
ACTIONABLE_STAGES = frozenset(
    {
        SetupStage.B1_READY,
        SetupStage.B2_READY,
        SetupStage.B2_CONFIRMED,
    }
)


class AnchorSnapshot(FrozenDomainModel):
    anchor_date: date
    anchor_price: PositiveDecimal
    frozen_as_of: date
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dates(self) -> "AnchorSnapshot":
        if self.frozen_as_of < self.anchor_date:
            raise ValueError("anchor cannot be frozen before anchor_date")
        return self


class SupportSnapshot(FrozenDomainModel):
    support_low: PositiveDecimal
    support_high: PositiveDecimal
    support_center: PositiveDecimal
    sources: tuple[str, ...]
    frozen_as_of: date
    reference_low: PositiveDecimal | None = None

    @model_validator(mode="after")
    def validate_support(self) -> "SupportSnapshot":
        if not self.sources:
            raise ValueError("support snapshot requires at least one source")
        if not self.support_low <= self.support_center <= self.support_high:
            raise ValueError("support_center must be inside support range")
        return self


class B2TriggerSnapshot(FrozenDomainModel):
    trigger_price: PositiveDecimal
    frozen_as_of: date
    eligible_from: date
    sources: tuple[str, ...]

    @model_validator(mode="after")
    def validate_timing(self) -> "B2TriggerSnapshot":
        if self.eligible_from <= self.frozen_as_of:
            raise ValueError("eligible_from must be later than frozen_as_of")
        if not self.sources:
            raise ValueError("B2 trigger snapshot requires at least one source")
        return self


class S1Snapshot(FrozenDomainModel):
    s1_low: PositiveDecimal
    s1_high: PositiveDecimal
    sources: tuple[str, ...]
    frozen_as_of: date

    @model_validator(mode="after")
    def validate_s1(self) -> "S1Snapshot":
        if self.s1_low > self.s1_high:
            raise ValueError("S1 range is reversed")
        if not self.sources:
            raise ValueError("S1 snapshot requires at least one source")
        return self


class ScoreBreakdown(FrozenDomainModel):
    profile: ScoreProfile
    profile_max_score: PositiveDecimal
    component_scores: dict[str, NonNegativeDecimal]
    component_max_scores: dict[str, PositiveDecimal]
    unavailable_rules: tuple[str, ...] = ()
    reasons: dict[str, str] = Field(default_factory=dict)
    risks: dict[str, str] = Field(default_factory=dict)
    quality_flags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_components(self) -> "ScoreBreakdown":
        score_keys = set(self.component_scores)
        max_keys = set(self.component_max_scores)
        if score_keys != max_keys:
            raise ValueError("component score keys must match component maximum keys")
        if not score_keys:
            raise ValueError("at least one available score component is required")
        for rule_id, score in self.component_scores.items():
            if score > self.component_max_scores[rule_id]:
                raise ValueError(f"score exceeds maximum for rule {rule_id!r}")
        if self.available_max_score > self.profile_max_score:
            raise ValueError("available maximum exceeds profile maximum")

        unavailable = set(self.unavailable_rules)
        if len(unavailable) != len(self.unavailable_rules):
            raise ValueError("unavailable_rules must be unique")
        if unavailable & max_keys:
            raise ValueError("unavailable rules cannot be included in available scores")
        if unavailable & set(self.reasons):
            raise ValueError("unavailable rules cannot form positive reasons")
        if unavailable & set(self.risks):
            raise ValueError("unavailable rules cannot form negative reasons")
        required_flags = {
            f"{MISSING_SCORE_FLAG_PREFIX}{rule_id}" for rule_id in unavailable
        }
        if not required_flags.issubset(set(self.quality_flags)):
            raise ValueError("every unavailable rule requires a missing-score quality flag")
        return self

    @computed_field(return_type=Decimal)
    @property
    def available_score(self) -> Decimal:
        return sum(self.component_scores.values(), Decimal("0"))

    @computed_field(return_type=Decimal)
    @property
    def available_max_score(self) -> Decimal:
        return sum(self.component_max_scores.values(), Decimal("0"))

    @computed_field(return_type=Decimal)
    @property
    def normalized_score(self) -> Decimal:
        return (
            self.available_score
            / self.available_max_score
            * Decimal("100")
        ).quantize(NORMALIZED_SCORE_QUANTUM, rounding=ROUND_HALF_UP)


class StrategySignal(DomainModel):
    strategy_version: str = Field(min_length=1)
    setup_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._:-]+$")
    trade_date: date
    code: str = Field(pattern=r"^\d{6}$")
    generated_at: datetime
    setup_stage: SetupStage
    patterns: frozenset[PatternType] = frozenset()
    event_flags: frozenset[EventFlag] = frozenset()
    review_group: ReviewGroup = ReviewGroup.STANDARD
    data_quality: DataQuality
    quality_flags: tuple[str, ...] = ()
    score: ScoreBreakdown
    anchor: AnchorSnapshot | None = None
    support: SupportSnapshot | None = None
    initial_invalid_price: PositiveDecimal | None = None
    invalid_price: PositiveDecimal | None = None
    b2_trigger: B2TriggerSnapshot | None = None
    s1: S1Snapshot | None = None
    risk_reward_ratio: DecimalValue | None = None

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "generated_at")

    @model_validator(mode="after")
    def validate_signal_invariants(self) -> "StrategySignal":
        snapshots = tuple(
            snapshot
            for snapshot in (self.anchor, self.support, self.b2_trigger, self.s1)
            if snapshot is not None
        )
        if any(snapshot.frozen_as_of > self.trade_date for snapshot in snapshots):
            raise ValueError("snapshots cannot be frozen after trade_date")
        if self.anchor is not None and self.anchor.anchor_date > self.trade_date:
            raise ValueError("anchor_date cannot be after trade_date")

        invalid_pair = (self.initial_invalid_price, self.invalid_price)
        if (invalid_pair[0] is None) != (invalid_pair[1] is None):
            raise ValueError("initial and current invalid prices must appear together")
        if (
            self.initial_invalid_price is not None
            and self.invalid_price is not None
            and self.invalid_price < self.initial_invalid_price
        ):
            raise ValueError("invalid_price cannot loosen below initial_invalid_price")

        if self.setup_stage in ACTIONABLE_STAGES:
            if self.anchor is None or self.support is None:
                raise ValueError("actionable setup requires anchor and support snapshots")
            if self.initial_invalid_price is None:
                raise ValueError("actionable setup requires frozen invalid price")

        if self.setup_stage in {SetupStage.B2_READY, SetupStage.B2_CONFIRMED}:
            if self.b2_trigger is None:
                raise ValueError("B2 setup requires a frozen B2 trigger")

        if self.setup_stage is SetupStage.B2_CONFIRMED:
            assert self.b2_trigger is not None
            if self.b2_trigger.frozen_as_of >= self.trade_date:
                raise ValueError("B2 trigger must be frozen before confirmation date")
            if self.b2_trigger.eligible_from > self.trade_date:
                raise ValueError("B2 trigger is not eligible on confirmation date")

        if self.review_group is ReviewGroup.OPEN_SPACE:
            if self.s1 is not None:
                raise ValueError("OPEN_SPACE cannot contain an S1 snapshot")
            if self.risk_reward_ratio is not None:
                raise ValueError("OPEN_SPACE risk_reward_ratio must be null")
        elif self.s1 is not None and self.review_group is not ReviewGroup.STANDARD:
            raise ValueError("an S1 snapshot belongs to STANDARD review")

        if (
            self.setup_stage in ACTIONABLE_STAGES
            and self.s1 is None
            and self.review_group is not ReviewGroup.OPEN_SPACE
        ):
            raise ValueError("actionable setup without S1 must be OPEN_SPACE")

        if self.risk_reward_ratio is not None:
            if self.risk_reward_ratio < Decimal("0"):
                raise ValueError("risk_reward_ratio cannot be negative")
            if self.s1 is None:
                raise ValueError("risk_reward_ratio requires an S1 snapshot")
        return self
