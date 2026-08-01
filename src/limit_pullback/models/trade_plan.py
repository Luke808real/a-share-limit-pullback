"""Small post-close execution plan models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import Field, model_validator

from limit_pullback.models.base import DecimalValue, DomainModel, PositiveDecimal
from limit_pullback.models.enums import (
    DataQuality,
    EntryRoomState,
    ExecutionLabel,
    SetupStage,
)


class TradePlan(DomainModel):
    """Execution-layer output; it never changes StrategySignal lifecycle."""

    code: str = Field(pattern=r"^\d{6}$")
    plan_date: date
    for_trade_date: date
    setup_stage: SetupStage
    execution_label: ExecutionLabel
    anchor_date: date | None = None
    anchor_price: PositiveDecimal | None = None
    buy_zone_low: PositiveDecimal | None = None
    buy_zone_high: PositiveDecimal | None = None
    preferred_entry: PositiveDecimal | None = None
    trigger_price: PositiveDecimal | None = None
    support_price: PositiveDecimal | None = None
    invalid_price: PositiveDecimal | None = None
    s1_price: PositiveDecimal | None = None
    s2_price: PositiveDecimal | None = None
    entry_room_state: EntryRoomState | None = None
    risk_pct: DecimalValue | None = None
    reward_pct: DecimalValue | None = None
    rr: DecimalValue | None = None
    setup_quality_score: DecimalValue
    entry_quality_score: DecimalValue | None = None
    data_quality: DataQuality
    quality_flags: tuple[str, ...] = ()
    is_actionable: bool
    cancel_conditions: tuple[str, ...] = ()
    snapshot_id: str = Field(min_length=1)
    strategy_commit: str = Field(min_length=1)
    config_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan(self) -> "TradePlan":
        if self.for_trade_date <= self.plan_date:
            raise ValueError("for_trade_date must be after plan_date")
        if (
            self.buy_zone_low is not None
            and self.buy_zone_high is not None
            and self.buy_zone_low > self.buy_zone_high
        ):
            raise ValueError("buy zone is reversed")
        if self.execution_label is ExecutionLabel.B1_PREP and self.setup_stage not in {
            SetupStage.WATCH_PULLBACK,
            SetupStage.B1_READY,
        }:
            raise ValueError("B1_PREP requires WATCH_PULLBACK or B1_READY")
        if self.is_actionable and self.execution_label is ExecutionLabel.WATCH_ONLY:
            raise ValueError("WATCH_ONLY cannot be actionable")
        if self.is_actionable and self.data_quality is DataQuality.UNUSABLE:
            raise ValueError("UNUSABLE data cannot produce an actionable plan")
        if self.rr is not None and self.rr < Decimal("0"):
            raise ValueError("rr cannot be negative")
        return self


class TradePlanOutput(DomainModel):
    """Latest cross-section and aggregate rejection counts."""

    plan_date: date
    for_trade_date: date
    snapshot_id: str = Field(min_length=1)
    strategy_commit: str = Field(min_length=1)
    config_hash: str = Field(min_length=1)
    universe: int = Field(ge=0)
    watch_count: int = Field(ge=0)
    b1_prep_count: int = Field(ge=0)
    b1_ready_count: int = Field(ge=0)
    b2_ready_count: int = Field(ge=0)
    b2_confirmed_count: int = Field(ge=0)
    actionable_count: int = Field(ge=0)
    entry_room_none_reject_count: int = Field(ge=0)
    invalid_reject_count: int = Field(ge=0)
    reject_counts: dict[str, int] = Field(default_factory=dict)
    plans: tuple[TradePlan, ...] = ()
    top_candidates: tuple[TradePlan, ...] = ()

    @model_validator(mode="after")
    def validate_counts(self) -> "TradePlanOutput":
        if self.actionable_count != sum(plan.is_actionable for plan in self.plans):
            raise ValueError("actionable_count must match output plans")
        if len(self.top_candidates) > 20:
            raise ValueError("top_candidates cannot exceed 20")
        return self
