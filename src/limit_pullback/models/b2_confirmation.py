"""Typed models for the B2_CONFIRMATION_V01 research layer.

This layer sits on top of the frozen B1/B2 lifecycle. It adds confirmation
features, a 0-100 diagnostic score, a level label, and two deterministic
rankings. It never rewrites ``setup_stage`` or any frozen transition.
"""

from __future__ import annotations

from datetime import date, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import Field, model_validator

from limit_pullback.models.base import (
    DecimalValue,
    DomainModel,
    FrozenDomainModel,
    NonNegativeDecimal,
    PositiveDecimal,
)
from limit_pullback.models.enums import B2ConfirmationLevel, SetupStage, VwapSource


class IntradayBar(FrozenDomainModel):
    """Minimal typed intraday bar used only for PIT-safe VWAP construction."""

    trade_date: date
    code: str = Field(pattern=r"^\d{6}$")
    time: time
    price: PositiveDecimal
    volume: NonNegativeDecimal
    amount: NonNegativeDecimal
    volume_unit: Literal["SHARES", "LOTS", "UNKNOWN"] = "SHARES"
    amount_unit: Literal["CNY", "UNKNOWN"] = "CNY"


class B2ConfirmationFeatures(FrozenDomainModel):
    """Point-in-time feature snapshot for one code on one session D."""

    trade_date: date
    code: str = Field(pattern=r"^\d{6}$")
    t0_date: date
    t0_quality: Literal["A", "B", "C", "D"]
    days_after_anchor: int = Field(ge=0)
    day_return_pct: DecimalValue | None = None
    intraday_max_return_pct: DecimalValue | None = None
    b2_return_zone: bool | None = None
    b2_intraday_attack: bool | None = None
    vwap: DecimalValue | None = None
    vwap_source: VwapSource = VwapSource.UNKNOWN
    close_above_vwap: bool | None = None
    close_to_vwap_pct: DecimalValue | None = None
    close_above_ma5: bool | None = None
    ma5_gt_ma10: bool | None = None
    ma5_gt_ma20: bool | None = None
    short_ma_bullish: bool | None = None
    ma5: DecimalValue | None = None
    ma10: DecimalValue | None = None
    ma20: DecimalValue | None = None
    turnover_rate: DecimalValue | None = None
    turnover_active: bool | None = None
    touched_below_ma5_7d: bool | None = None
    touched_below_ma10_7d: bool | None = None
    touched_below_ma18_7d: bool | None = None
    washout_depth_score: DecimalValue | None = None
    limit_up_count_7d: int | None = Field(default=None, ge=0)
    prev_day_not_limit_up: bool | None = None
    return_20d_pct: DecimalValue | None = None
    circulating_market_cap: DecimalValue | None = None
    market_cap_source_date: date | None = None
    pullback_volume_ratio: DecimalValue | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "B2ConfirmationFeatures":
        if self.t0_date > self.trade_date:
            raise ValueError("t0_date cannot be after trade_date")
        return self


class B2ConfirmationEvaluation(FrozenDomainModel):
    """Score + level + diagnostics for one code/session."""

    trade_date: date
    code: str = Field(pattern=r"^\d{6}$")
    setup_stage: SetupStage
    features: B2ConfirmationFeatures
    structure_score: NonNegativeDecimal
    launch_score: NonNegativeDecimal
    b2_confirm_score: NonNegativeDecimal = Field(le=Decimal("100"))
    available_max_score: PositiveDecimal = Field(le=Decimal("100"))
    normalized_score: DecimalValue | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("100"),
    )
    level: B2ConfirmationLevel
    hard_fail: bool
    hard_fail_reason: str | None = None
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    structure_components: dict[str, NonNegativeDecimal]
    launch_components: dict[str, NonNegativeDecimal]
    missing_components: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_evaluation(self) -> "B2ConfirmationEvaluation":
        if (
            self.structure_score + self.launch_score
            != self.b2_confirm_score
        ):
            raise ValueError(
                "b2_confirm_score must equal structure plus launch scores"
            )
        if self.normalized_score is not None:
            expected = (
                self.b2_confirm_score
                / self.available_max_score
                * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if self.normalized_score != expected:
                raise ValueError("normalized_score must derive from score/max")
        if self.hard_fail:
            if self.level is not B2ConfirmationLevel.NONE:
                raise ValueError("hard-failed evaluation must be level NONE")
            if not self.hard_fail_reason:
                raise ValueError("hard-failed evaluation requires a reason")
        else:
            if self.hard_fail_reason is not None:
                raise ValueError("non-failed evaluation cannot carry a fail reason")
        if self.level is not B2ConfirmationLevel.NONE and self.hard_fail:
            raise ValueError("level must be NONE when hard_fail is true")
        if not self.reasons or any(not reason for reason in self.reasons):
            raise ValueError("evaluation requires at least one reason")
        return self


class B1SetupRankRow(FrozenDomainModel):
    """Deterministic B1 latent/watch ranking row."""

    code: str = Field(pattern=r"^\d{6}$")
    name: str = ""
    t0_date: date
    t0_quality: Literal["A", "B", "C", "D"]
    pullback_days: int = Field(ge=0)
    b1_zone_low: DecimalValue | None = None
    b1_zone_high: DecimalValue | None = None
    support_low: DecimalValue | None = None
    support_high: DecimalValue | None = None
    pullback_volume_ratio: DecimalValue | None = None
    b1_score: NonNegativeDecimal = Field(le=Decimal("100"))
    current_stage: SetupStage


class B2LaunchRankRow(FrozenDomainModel):
    """Deterministic B2 launch ranking row."""

    code: str = Field(pattern=r"^\d{6}$")
    name: str = ""
    t0_date: date
    t0_quality: Literal["A", "B", "C", "D"]
    pullback_days: int = Field(ge=0)
    day_return_pct: DecimalValue | None = None
    intraday_max_return_pct: DecimalValue | None = None
    close_above_vwap: bool | None = None
    turnover_rate: DecimalValue | None = None
    ma5: DecimalValue | None = None
    ma10: DecimalValue | None = None
    ma20: DecimalValue | None = None
    pullback_volume_ratio: DecimalValue | None = None
    b2_confirm_score: NonNegativeDecimal = Field(le=Decimal("100"))
    structure_score: NonNegativeDecimal = Field(le=Decimal("100"))
    b2_confirm_level: B2ConfirmationLevel
    current_stage: SetupStage
