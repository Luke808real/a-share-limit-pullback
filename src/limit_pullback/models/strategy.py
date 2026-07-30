"""Pure-strategy calculation result models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import Field, computed_field, model_validator

from limit_pullback.models.base import (
    DecimalValue,
    FrozenDomainModel,
    NonNegativeDecimal,
    PositiveDecimal,
    RatioDecimal,
)
from limit_pullback.models.enums import PatternType, ScoreProfile
from limit_pullback.models.market import LimitUpRecord
from limit_pullback.models.signal import AnchorSnapshot


class ContinuousPricePoint(FrozenDomainModel):
    trade_date: date
    code: str = Field(pattern=r"^\d{6}$")
    raw_close: PositiveDecimal
    continuous_close: PositiveDecimal


class KlineMetrics(FrozenDomainModel):
    body_share: RatioDecimal
    close_location: RatioDecimal
    upper_shadow_share: RatioDecimal
    lower_shadow_share: RatioDecimal
    amplitude: NonNegativeDecimal
    is_bullish: bool
    is_bearish: bool
    is_doji: bool
    is_small_body: bool
    is_long_bearish: bool
    has_long_lower_shadow: bool


class IndicatorPoint(FrozenDomainModel):
    trade_date: date
    code: str = Field(pattern=r"^\d{6}$")
    continuous_close: PositiveDecimal
    continuous_mas: dict[int, DecimalValue | None]
    raw_equivalent_mas: dict[int, DecimalValue | None]
    ma_compression: DecimalValue | None
    position_120: DecimalValue | None
    kline: KlineMetrics


class AnchorEvaluation(FrozenDomainModel):
    snapshot: AnchorSnapshot
    profile: ScoreProfile
    limit_price: PositiveDecimal
    is_limit_close: bool
    is_one_word: bool
    is_t_word: bool
    is_first_board: bool
    recent_limit_count: int = Field(ge=0)
    recent_limits_non_consecutive: bool
    seal_before_cutoff: bool | None
    pool_record: LimitUpRecord | None = None


class PriceLevelCandidate(FrozenDomainModel):
    source: str = Field(min_length=1)
    value: PositiveDecimal


class PriceCluster(FrozenDomainModel):
    low: PositiveDecimal
    high: PositiveDecimal
    center: PositiveDecimal
    sources: tuple[str, ...]

    @model_validator(mode="after")
    def validate_cluster(self) -> "PriceCluster":
        if not self.sources:
            raise ValueError("price cluster requires sources")
        if not self.low <= self.center <= self.high:
            raise ValueError("cluster center must be inside range")
        return self


class ConditionScore(FrozenDomainModel):
    matched: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_condition_ids(self) -> "ConditionScore":
        groups = tuple(map(set, (self.matched, self.failed, self.unavailable)))
        if any(len(group) != len(values) for group, values in zip(
            groups, (self.matched, self.failed, self.unavailable), strict=True
        )):
            raise ValueError("condition identifiers must be unique")
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("condition groups must be disjoint")
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


class PatternEvaluation(FrozenDomainModel):
    air_refuel: ConditionScore
    bearish_pullback: ConditionScore
    matched_patterns: frozenset[PatternType] = frozenset()
    primary_pattern: PatternType | None = None
    pattern_scores: dict[PatternType, DecimalValue] = Field(default_factory=dict)
    primary_pattern_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_pattern_selection(self) -> "PatternEvaluation":
        if self.matched_patterns and self.primary_pattern is None:
            raise ValueError("matched patterns require one primary_pattern")
        if not self.matched_patterns and self.primary_pattern is not None:
            raise ValueError("primary_pattern requires at least one matched pattern")
        if (
            self.primary_pattern is not None
            and self.primary_pattern not in self.matched_patterns
        ):
            raise ValueError("primary_pattern must be a matched pattern")
        if not self.matched_patterns.issubset(self.pattern_scores):
            raise ValueError("every matched pattern requires a pattern score")
        if any(score < 0 or score > 100 for score in self.pattern_scores.values()):
            raise ValueError("pattern scores must be between 0 and 100")
        return self
