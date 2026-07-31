"""Provider-owned request and response models."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import Field, field_validator, model_validator

from limit_pullback.models.base import (
    DecimalValue,
    DomainModel,
    NonNegativeDecimal,
    PositiveDecimal,
    require_aware_datetime,
)
from limit_pullback.models.enums import DataQuality


class DailyBar(DomainModel):
    trade_date: date
    code: str = Field(pattern=r"^\d{6}$")
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
    source: str = Field(min_length=1)
    fetched_at: datetime

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "fetched_at")

    @model_validator(mode="after")
    def validate_ohlc(self) -> "DailyBar":
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high is below another OHLC value")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low is above another OHLC value")
        return self


class LimitUpRecord(DomainModel):
    trade_date: date
    code: str = Field(pattern=r"^\d{6}$")
    name: str = Field(min_length=1)
    limit_price: PositiveDecimal
    first_seal_time: time | None = None
    last_seal_time: time | None = None
    open_count: int | None = Field(default=None, ge=0)
    consecutive_count: int | None = Field(default=None, ge=1)
    turnover_rate: DecimalValue | None = None
    float_market_cap: DecimalValue | None = None
    total_market_cap: DecimalValue | None = None
    industry: str | None = None
    source: str = Field(min_length=1)
    fetched_at: datetime

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "fetched_at")


class DailyBarsRequest(DomainModel):
    codes: tuple[str, ...]
    start_date: date
    end_date: date
    adjust_type: Literal["raw"] = "raw"

    @field_validator("codes")
    @classmethod
    def validate_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one code is required")
        if any(len(code) != 6 or not code.isdigit() for code in value):
            raise ValueError("codes must contain six digits")
        if len(set(value)) != len(value):
            raise ValueError("codes must be unique")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "DailyBarsRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class LimitUpPoolRequest(DomainModel):
    trade_date: date
    codes: tuple[str, ...] = ()

    @field_validator("codes")
    @classmethod
    def validate_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(len(code) != 6 or not code.isdigit() for code in value):
            raise ValueError("codes must contain six digits")
        if len(set(value)) != len(value):
            raise ValueError("codes must be unique")
        return value


class DailyBarsResult(DomainModel):
    bars: tuple[DailyBar, ...]
    quality: DataQuality
    quality_flags: tuple[str, ...] = ()
    fetched_at: datetime

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "fetched_at")


class LimitUpPoolResult(DomainModel):
    trade_date: date
    records: tuple[LimitUpRecord, ...]
    quality: DataQuality
    quality_flags: tuple[str, ...] = ()
    fetched_at: datetime

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        return require_aware_datetime(value, "fetched_at")
