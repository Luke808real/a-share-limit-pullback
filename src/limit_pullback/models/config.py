"""Pydantic schema for config/strategy.yaml."""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from limit_pullback.models.base import (
    DecimalValue,
    DomainModel,
    NonNegativeDecimal,
    PositiveDecimal,
    RatioDecimal,
)
from limit_pullback.models.enums import ScoreProfile


class UniverseConfig(DomainModel):
    exchanges: tuple[Literal["SH", "SZ"], ...]
    boards: tuple[Literal["MAIN"], ...]
    minimum_listing_trade_days: int = Field(ge=1)
    exclude_st: bool
    require_active_trade: bool


class PriceSystemConfig(DomainModel):
    raw_price_uses: tuple[str, ...]
    continuous_seed: Literal["FIRST_VALID_CLOSE"]
    continuous_return_numerator: Literal["close"]
    continuous_return_denominator: Literal["preclose"]
    reject_invalid_preclose: bool


class AnchorConfig(DomainModel):
    limit_rate: RatioDecimal
    price_tick: PositiveDecimal
    lookback_trade_days: int = Field(ge=1)
    recent_limit_window: int = Field(ge=1)
    recent_limit_count_min: int = Field(ge=0)
    recent_limit_count_max: int = Field(ge=1)
    first_seal_cutoff: time
    require_non_consecutive: bool
    require_first_board: bool
    require_positive_volume: bool
    require_positive_amount: bool
    limit_price_tolerance: PositiveDecimal

    @model_validator(mode="after")
    def validate_limit_count_range(self) -> "AnchorConfig":
        if self.recent_limit_count_min > self.recent_limit_count_max:
            raise ValueError("recent limit count range is reversed")
        return self


class PositionThresholds(DomainModel):
    high_score_max: RatioDecimal
    medium_score_max: RatioDecimal
    low_score_max: RatioDecimal

    @model_validator(mode="after")
    def validate_order(self) -> "PositionThresholds":
        if not (
            self.high_score_max < self.medium_score_max < self.low_score_max
        ):
            raise ValueError("position thresholds must be strictly increasing")
        return self


class MaCompressionThresholds(DomainModel):
    high_max: RatioDecimal
    good_max: RatioDecimal
    normal_max: RatioDecimal

    @model_validator(mode="after")
    def validate_order(self) -> "MaCompressionThresholds":
        if not self.high_max < self.good_max < self.normal_max:
            raise ValueError("MA compression thresholds must be strictly increasing")
        return self


class IndicatorsConfig(DomainModel):
    moving_average_windows: tuple[int, ...]
    position_window: int = Field(ge=1)
    position_thresholds: PositionThresholds
    ma_compression_thresholds: MaCompressionThresholds
    kline: "KlineConfig"

    @model_validator(mode="after")
    def validate_windows(self) -> "IndicatorsConfig":
        if not self.moving_average_windows:
            raise ValueError("at least one moving-average window is required")
        if any(window <= 0 for window in self.moving_average_windows):
            raise ValueError("moving-average windows must be positive")
        if len(set(self.moving_average_windows)) != len(
            self.moving_average_windows
        ):
            raise ValueError("moving-average windows must be unique")
        return self


class KlineConfig(DomainModel):
    doji_body_share_max: RatioDecimal
    small_body_share_max: RatioDecimal
    long_body_share_min: RatioDecimal
    long_shadow_share_min: RatioDecimal

    @model_validator(mode="after")
    def validate_body_thresholds(self) -> "KlineConfig":
        if not (
            self.doji_body_share_max
            <= self.small_body_share_max
            < self.long_body_share_min
        ):
            raise ValueError("K-line body thresholds are inconsistent")
        return self


class AirRefuelConfig(DomainModel):
    minimum_close_to_anchor: PositiveDecimal
    current_close_to_anchor_minimum: PositiveDecimal
    recent_volume_days: int = Field(ge=1)
    recent_volume_to_anchor_maximum: PositiveDecimal
    amplitude_contraction_maximum: PositiveDecimal
    ma_distance_maximum: RatioDecimal


class BearishPullbackConfig(DomainModel):
    require_bearish_bar: bool
    support_touch_tolerance: RatioDecimal
    volume_contraction_maximum: PositiveDecimal


class PatternsConfig(DomainModel):
    minimum_condition_ratio: RatioDecimal
    air_refuel: AirRefuelConfig
    bearish_pullback: BearishPullbackConfig


class SupportConfig(DomainModel):
    cluster_distance: RatioDecimal
    invalid_buffer: RatioDecimal
    max_above_reference_close: RatioDecimal = Field(le=Decimal("0.005"))
    platform_lookback_days: int = Field(ge=1)
    moving_average_sources: tuple[int, ...]
    prefer_anchor_or_ma10: bool


class ResistanceConfig(DomainModel):
    cluster_distance: RatioDecimal
    left_high_lookback_days: int = Field(ge=1)
    recent_high_lookback_days: int = Field(ge=1)
    long_recent_high_lookback_days: int = Field(ge=1)
    first_post_anchor_window_days: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_windows(self) -> "ResistanceConfig":
        if self.long_recent_high_lookback_days < self.recent_high_lookback_days:
            raise ValueError(
                "long resistance lookback cannot be shorter than recent lookback"
            )
        return self


class B1Config(DomainModel):
    days_after_anchor_min: int = Field(ge=1)
    days_after_anchor_max: int = Field(ge=1)
    optimal_days_min: int = Field(ge=1)
    optimal_days_max: int = Field(ge=1)
    close_to_anchor_min: PositiveDecimal
    close_to_anchor_max: PositiveDecimal
    volume_to_anchor_max: PositiveDecimal
    recent_volume_days: int = Field(ge=1)
    recent_volume_to_post_anchor_max: PositiveDecimal
    minimum_condition_ratio: RatioDecimal
    # Execution-layer observation thresholds. These do not participate in
    # StrategySignal B1 structure qualification.
    prep_support_distance_max: RatioDecimal
    prep_volume_to_anchor_max: PositiveDecimal
    prep_volume_to_post_anchor_max: PositiveDecimal

    @model_validator(mode="after")
    def validate_ranges(self) -> "B1Config":
        if self.days_after_anchor_min > self.days_after_anchor_max:
            raise ValueError("B1 anchor-day range is reversed")
        if self.optimal_days_min > self.optimal_days_max:
            raise ValueError("B1 optimal-day range is reversed")
        if not (
            self.days_after_anchor_min
            <= self.optimal_days_min
            <= self.optimal_days_max
            <= self.days_after_anchor_max
        ):
            raise ValueError("B1 optimal range must be inside the full range")
        if self.close_to_anchor_min > self.close_to_anchor_max:
            raise ValueError("B1 close-to-anchor range is reversed")
        return self


class B2Config(DomainModel):
    daily_return_min: DecimalValue
    daily_return_max: DecimalValue
    close_location_min: RatioDecimal
    volume_expansion_min: PositiveDecimal
    volume_expansion_max: PositiveDecimal
    trigger_buffer: NonNegativeDecimal
    platform_lookback_days: int = Field(ge=1)
    skip_gap_open: NonNegativeDecimal
    minimum_condition_ratio: RatioDecimal

    @model_validator(mode="after")
    def validate_ranges(self) -> "B2Config":
        if self.daily_return_min > self.daily_return_max:
            raise ValueError("B2 return range is reversed")
        if self.volume_expansion_min > self.volume_expansion_max:
            raise ValueError("B2 volume range is reversed")
        return self


class EntryRoomConfig(DomainModel):
    thin_headroom_max: RatioDecimal
    sufficient_headroom_min: RatioDecimal
    minimum_risk_reward: PositiveDecimal

    @model_validator(mode="after")
    def validate_boundary(self) -> "EntryRoomConfig":
        if self.thin_headroom_max != self.sufficient_headroom_min:
            raise ValueError(
                "entry-room THIN and SUFFICIENT boundaries must be identical"
            )
        return self


class S2Config(DomainModel):
    close_off_high_min: RatioDecimal
    upper_shadow_share_min: RatioDecimal
    volume_to_ma5_min: PositiveDecimal
    minimum_condition_ratio: RatioDecimal


class SupportWarningConfig(DomainModel):
    close_to_support_low_max: RatioDecimal
    close_to_invalid_max: RatioDecimal
    abnormal_volume_ratio_min: PositiveDecimal
    volume_lookback_days: int = Field(ge=1)
    consecutive_test_days: int = Field(ge=2)
    test_distance_max: RatioDecimal


class EventsConfig(DomainModel):
    near_s1_distance: RatioDecimal
    s1_breakout_close_buffer: NonNegativeDecimal
    support_warning: SupportWarningConfig
    s2: S2Config


class InvalidationConfig(DomainModel):
    support_break_buffer: RatioDecimal
    volume_expansion_min: PositiveDecimal
    consecutive_distribution_days: int = Field(ge=1)
    recovery_days: int = Field(ge=1)
    invalid_price_may_loosen: Literal[False]


class ScoreProfileConfig(DomainModel):
    profile_max_score: PositiveDecimal
    rule_max_scores: dict[str, PositiveDecimal]

    @model_validator(mode="after")
    def validate_profile_total(self) -> "ScoreProfileConfig":
        if not self.rule_max_scores:
            raise ValueError("score profile must contain at least one rule")
        if sum(self.rule_max_scores.values(), Decimal("0")) != self.profile_max_score:
            raise ValueError("profile_max_score must equal the sum of rule maxima")
        return self


class ScoringConfig(DomainModel):
    normalized_score_quantum: DecimalValue
    profiles: dict[ScoreProfile, ScoreProfileConfig]

    @model_validator(mode="after")
    def validate_profiles(self) -> "ScoringConfig":
        if self.normalized_score_quantum != Decimal("0.01"):
            raise ValueError("normalized_score_quantum must be exactly 0.01")
        if set(self.profiles) != set(ScoreProfile):
            raise ValueError("FULL and PRICE_ONLY score profiles are both required")
        return self


class QualityConfig(DomainModel):
    missing_score_flag_prefix: Literal["MISSING_SCORE_FIELD:"]
    invalid_preclose_flag: str = Field(min_length=1)
    inferred_anchor_flag: str = Field(min_length=1)
    minimum_score_coverage: RatioDecimal


class StrategyConfig(DomainModel):
    strategy_version: str = Field(min_length=1)
    universe: UniverseConfig
    price_system: PriceSystemConfig
    anchor: AnchorConfig
    indicators: IndicatorsConfig
    patterns: PatternsConfig
    support: SupportConfig
    resistance: ResistanceConfig
    b1: B1Config
    b2: B2Config
    entry_room: EntryRoomConfig
    events: EventsConfig
    invalidation: InvalidationConfig
    scoring: ScoringConfig
    quality: QualityConfig
