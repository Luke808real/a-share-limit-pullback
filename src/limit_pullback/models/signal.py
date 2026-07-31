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
    RatioDecimal,
    require_aware_datetime,
)
from limit_pullback.models.enums import (
    DataQuality,
    EntryRoomState,
    EventFlag,
    ReviewGroup,
    PatternType,
    ScoreProfile,
    SetupStage,
)


NORMALIZED_SCORE_QUANTUM = Decimal("0.01")
MISSING_SCORE_FLAG_PREFIX = "MISSING_SCORE_FIELD:"
ENTRY_CANDIDATE_STAGES = frozenset(
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
    eligible_from: date
    reference_close: PositiveDecimal
    max_above_reference_close: RatioDecimal = Field(le=Decimal("0.005"))
    reference_low: PositiveDecimal | None = None

    @model_validator(mode="after")
    def validate_support(self) -> "SupportSnapshot":
        if not self.sources:
            raise ValueError("support snapshot requires at least one source")
        if not self.support_low <= self.support_center <= self.support_high:
            raise ValueError("support_center must be inside support range")
        if self.eligible_from <= self.frozen_as_of:
            raise ValueError("eligible_from must be later than frozen_as_of")
        if (
            self.support_center
            > self.reference_close
            * (Decimal("1") + self.max_above_reference_close)
        ):
            raise ValueError(
                "support_center is too far above the freezing reference close"
            )
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
    eligible_from: date

    @model_validator(mode="after")
    def validate_s1(self) -> "S1Snapshot":
        if self.s1_low > self.s1_high:
            raise ValueError("S1 range is reversed")
        if not self.sources:
            raise ValueError("S1 snapshot requires at least one source")
        if self.eligible_from <= self.frozen_as_of:
            raise ValueError("eligible_from must be later than frozen_as_of")
        return self


class ResistanceSnapshot(FrozenDomainModel):
    resistance_low: PositiveDecimal
    resistance_high: PositiveDecimal
    sources: tuple[str, ...]
    frozen_as_of: date
    eligible_from: date

    @model_validator(mode="after")
    def validate_resistance(self) -> "ResistanceSnapshot":
        if self.resistance_low > self.resistance_high:
            raise ValueError("resistance range is reversed")
        if not self.sources:
            raise ValueError("resistance snapshot requires at least one source")
        if self.eligible_from <= self.frozen_as_of:
            raise ValueError("eligible_from must be later than frozen_as_of")
        return self


class ResistanceClusterSnapshot(FrozenDomainModel):
    low: PositiveDecimal
    high: PositiveDecimal
    center: PositiveDecimal
    sources: tuple[str, ...]

    @model_validator(mode="after")
    def validate_cluster(self) -> "ResistanceClusterSnapshot":
        if not self.low <= self.center <= self.high:
            raise ValueError("resistance cluster center must be inside its range")
        if not self.sources:
            raise ValueError("resistance cluster requires sources")
        return self


class ResistanceCandidateSnapshot(FrozenDomainModel):
    source: str = Field(min_length=1)
    price: PositiveDecimal
    cluster: ResistanceClusterSnapshot
    excluded_reason: str | None = None
    selected_reason: str | None = None

    @model_validator(mode="after")
    def validate_candidate(self) -> "ResistanceCandidateSnapshot":
        if self.source not in self.cluster.sources:
            raise ValueError("candidate source must be present in its cluster")
        if not self.cluster.low <= self.price <= self.cluster.high:
            raise ValueError("candidate price must be inside its cluster")
        return self


class InvalidPriceSnapshot(FrozenDomainModel):
    initial_invalid_price: PositiveDecimal
    invalid_price: PositiveDecimal
    frozen_as_of: date
    eligible_from: date

    @model_validator(mode="after")
    def validate_invalid_price(self) -> "InvalidPriceSnapshot":
        if self.invalid_price < self.initial_invalid_price:
            raise ValueError("invalid_price cannot loosen below initial_invalid_price")
        if self.eligible_from <= self.frozen_as_of:
            raise ValueError("eligible_from must be later than frozen_as_of")
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


class ConditionSnapshot(FrozenDomainModel):
    matched: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_conditions(self) -> "ConditionSnapshot":
        groups = tuple(map(set, (self.matched, self.failed, self.unavailable)))
        values = (self.matched, self.failed, self.unavailable)
        if any(
            len(group) != len(items)
            for group, items in zip(groups, values, strict=True)
        ):
            raise ValueError("pattern condition identifiers must be unique")
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("pattern condition groups must be disjoint")
        return self

    @computed_field(return_type=int)
    @property
    def available_count(self) -> int:
        return len(self.matched) + len(self.failed)

    @computed_field(return_type=Decimal)
    @property
    def match_ratio(self) -> Decimal:
        if self.available_count == 0:
            return Decimal("0")
        return Decimal(len(self.matched)) / Decimal(self.available_count)


class StrategySignal(DomainModel):
    strategy_version: str = Field(min_length=1)
    setup_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._:-]+$")
    trade_date: date
    code: str = Field(pattern=r"^\d{6}$")
    generated_at: datetime
    setup_stage: SetupStage
    matched_patterns: frozenset[PatternType] = frozenset()
    primary_pattern: PatternType | None = None
    pattern_scores: dict[PatternType, DecimalValue] = Field(default_factory=dict)
    pattern_conditions: dict[PatternType, ConditionSnapshot] = Field(
        default_factory=dict
    )
    primary_pattern_reason: str | None = None
    b1_conditions: ConditionSnapshot | None = None
    b2_conditions: ConditionSnapshot | None = None
    event_flags: frozenset[EventFlag] = frozenset()
    event_reasons: dict[EventFlag, tuple[str, ...]] = Field(default_factory=dict)
    review_group: ReviewGroup = ReviewGroup.STANDARD
    data_quality: DataQuality
    quality_flags: tuple[str, ...] = ()
    score: ScoreBreakdown
    anchor: AnchorSnapshot | None = None
    support: SupportSnapshot | None = None
    invalid_price_snapshot: InvalidPriceSnapshot | None = None
    initial_invalid_price: PositiveDecimal | None = None
    invalid_price: PositiveDecimal | None = None
    b2_trigger: B2TriggerSnapshot | None = None
    expected_b2_trigger_price: PositiveDecimal | None = None
    resistance_candidates: tuple[ResistanceCandidateSnapshot, ...] = ()
    immediate_resistance: ResistanceSnapshot | None = None
    target_s1: S1Snapshot | None = None
    entry_reference_price: PositiveDecimal | None = None
    entry_headroom_pct: DecimalValue | None = None
    entry_room_state: EntryRoomState | None = None
    entry_room_reasons: tuple[str, ...] = ()
    risk_reward_ratio: DecimalValue | None = None
    entry_quality_score: DecimalValue | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("100"),
    )
    invalidation_reasons: tuple[str, ...] = ()

    @computed_field(return_type=Decimal)
    @property
    def setup_quality_score(self) -> Decimal:
        return self.score.normalized_score

    @computed_field(return_type=bool)
    @property
    def is_entry_candidate(self) -> bool:
        return (
            self.setup_stage in ENTRY_CANDIDATE_STAGES
            and self.data_quality is not DataQuality.UNUSABLE
            and EventFlag.S2_EXHAUSTED not in self.event_flags
            and EventFlag.S1_BREAKOUT not in self.event_flags
            and self.entry_room_state is not EntryRoomState.NONE
        )

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "generated_at")

    @model_validator(mode="after")
    def validate_signal_invariants(self) -> "StrategySignal":
        if self.matched_patterns and self.primary_pattern is None:
            raise ValueError("matched patterns require one primary_pattern")
        if not self.matched_patterns and self.primary_pattern is not None:
            raise ValueError("primary_pattern requires matched_patterns")
        if (
            self.primary_pattern is not None
            and self.primary_pattern not in self.matched_patterns
        ):
            raise ValueError("primary_pattern must be a matched pattern")
        if not self.matched_patterns.issubset(self.pattern_scores):
            raise ValueError("matched patterns require corresponding pattern scores")
        if set(self.pattern_scores) != set(self.pattern_conditions):
            raise ValueError(
                "pattern scores and condition explanations require identical keys"
            )
        if bool(self.pattern_scores) != bool(self.primary_pattern_reason):
            raise ValueError(
                "pattern evaluations require one primary selection reason"
            )
        if set(self.event_reasons) != set(self.event_flags):
            raise ValueError("every event flag requires exactly one reason list")
        if any(not reasons for reasons in self.event_reasons.values()):
            raise ValueError("event reason lists cannot be empty")
        if any(
            len(reasons) != len(set(reasons))
            for reasons in self.event_reasons.values()
        ):
            raise ValueError("event reasons must be unique")

        snapshots = tuple(
            snapshot
            for snapshot in (
                self.anchor,
                self.support,
                self.invalid_price_snapshot,
                self.b2_trigger,
                self.immediate_resistance,
                self.target_s1,
            )
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
        if self.invalid_price_snapshot is None:
            if self.initial_invalid_price is not None:
                raise ValueError("invalid prices require an invalid price snapshot")
        else:
            if self.initial_invalid_price is None:
                raise ValueError("invalid price snapshot requires output prices")
            if (
                self.invalid_price_snapshot.initial_invalid_price
                != self.initial_invalid_price
                or self.invalid_price_snapshot.invalid_price != self.invalid_price
            ):
                raise ValueError("invalid prices must match the frozen snapshot")

        if self.setup_stage in ENTRY_CANDIDATE_STAGES:
            if self.anchor is None or self.support is None:
                raise ValueError(
                    "entry-candidate stage requires anchor and support snapshots"
                )
            if self.initial_invalid_price is None:
                raise ValueError(
                    "entry-candidate stage requires frozen invalid price"
                )
            if self.invalid_price_snapshot is None:
                raise ValueError(
                    "entry-candidate stage requires invalid price snapshot"
                )

        if self.setup_stage in {SetupStage.B2_READY, SetupStage.B2_CONFIRMED}:
            if self.b2_trigger is None:
                raise ValueError("B2 setup requires a frozen B2 trigger")

        if self.setup_stage is SetupStage.B2_CONFIRMED:
            assert self.b2_trigger is not None
            if self.b2_trigger.frozen_as_of >= self.trade_date:
                raise ValueError("B2 trigger must be frozen before confirmation date")
            if self.b2_trigger.eligible_from > self.trade_date:
                raise ValueError("B2 trigger is not eligible on confirmation date")

        if self.setup_stage is SetupStage.LIMIT_ANCHOR:
            if any(
                snapshot is not None
                for snapshot in (
                    self.support,
                    self.invalid_price_snapshot,
                    self.b2_trigger,
                    self.immediate_resistance,
                    self.target_s1,
                )
            ):
                raise ValueError("LIMIT_ANCHOR may only freeze the anchor snapshot")
            if self.event_flags:
                raise ValueError("LIMIT_ANCHOR cannot emit structure events")

        if EventFlag.SUPPORT_WARNING in self.event_flags:
            if (
                self.support is None
                or self.support.eligible_from > self.trade_date
            ):
                raise ValueError(
                    "SUPPORT_WARNING requires an eligible support snapshot"
                )
        s1_events = {
            EventFlag.NEAR_S1,
            EventFlag.S1_BREAKOUT,
            EventFlag.S2_EXHAUSTED,
        }
        if self.event_flags & s1_events:
            if (
                self.target_s1 is None
                or self.target_s1.eligible_from > self.trade_date
            ):
                raise ValueError("S1 events require an eligible S1 snapshot")

        if self.review_group is ReviewGroup.OPEN_SPACE:
            if self.target_s1 is not None:
                raise ValueError("OPEN_SPACE cannot contain an S1 snapshot")
            if self.risk_reward_ratio is not None:
                raise ValueError("OPEN_SPACE risk_reward_ratio must be null")
        elif (
            self.target_s1 is not None
            and self.review_group is not ReviewGroup.STANDARD
        ):
            raise ValueError("an S1 snapshot belongs to STANDARD review")

        if (
            self.setup_stage in ENTRY_CANDIDATE_STAGES
            and self.target_s1 is None
            and self.review_group is not ReviewGroup.OPEN_SPACE
        ):
            raise ValueError("actionable setup without S1 must be OPEN_SPACE")

        if self.setup_stage in ENTRY_CANDIDATE_STAGES:
            if (
                self.entry_reference_price is None
                or self.entry_room_state is None
                or not self.entry_room_reasons
            ):
                raise ValueError(
                    "entry stages require complete entry-room output"
                )
            if self.target_s1 is None:
                if (
                    self.entry_room_state is not EntryRoomState.OPEN_SPACE
                    or self.entry_headroom_pct is not None
                ):
                    raise ValueError(
                        "missing target S1 requires OPEN_SPACE without headroom"
                    )
            else:
                expected_headroom = (
                    self.target_s1.s1_low - self.entry_reference_price
                ) / self.entry_reference_price
                if self.entry_headroom_pct != expected_headroom:
                    raise ValueError(
                        "entry_headroom_pct must be derived from target S1"
                    )
                if (
                    expected_headroom <= 0
                    and self.entry_room_state is not EntryRoomState.NONE
                ):
                    raise ValueError(
                        "non-positive target headroom requires NONE"
                    )
                if (
                    expected_headroom > 0
                    and self.entry_room_state
                    not in {EntryRoomState.THIN, EntryRoomState.SUFFICIENT}
                ):
                    raise ValueError(
                        "positive target headroom requires THIN or SUFFICIENT"
                    )
        elif any(
            value is not None
            for value in (
                self.entry_reference_price,
                self.entry_headroom_pct,
                self.entry_room_state,
            )
        ) or self.entry_room_reasons:
            raise ValueError(
                "entry-room output is only valid for B1/B2 stages"
            )

        if self.expected_b2_trigger_price is not None:
            if self.target_s1 is not None and (
                self.target_s1.s1_low <= self.expected_b2_trigger_price
            ):
                raise ValueError(
                    "target S1 must be above expected B2 trigger"
                )
        if self.resistance_candidates and self.support is None:
            raise ValueError(
                "resistance candidate audit requires a support snapshot"
            )

        if self.risk_reward_ratio is not None:
            if self.risk_reward_ratio < Decimal("0"):
                raise ValueError("risk_reward_ratio cannot be negative")
            if self.target_s1 is None:
                raise ValueError("risk_reward_ratio requires an S1 snapshot")
        if self.setup_stage in ENTRY_CANDIDATE_STAGES:
            if self.entry_quality_score is None:
                raise ValueError(
                    "entry stages require an entry_quality_score"
                )
            if not self.is_entry_candidate and self.entry_quality_score != 0:
                raise ValueError(
                    "disqualified entry stage requires zero entry_quality_score"
                )
        elif self.entry_quality_score is not None:
            raise ValueError(
                "entry_quality_score is only valid for B1/B2 stages"
            )
        if self.setup_stage is SetupStage.INVALID:
            if not self.invalidation_reasons:
                raise ValueError("INVALID requires explicit invalidation reasons")
            if (
                self.support is None
                or self.invalid_price_snapshot is None
                or self.support.eligible_from > self.trade_date
                or self.invalid_price_snapshot.eligible_from > self.trade_date
            ):
                raise ValueError(
                    "INVALID requires eligible support and invalid snapshots"
                )
        elif self.invalidation_reasons:
            raise ValueError("invalidation reasons are only valid for INVALID")
        return self
