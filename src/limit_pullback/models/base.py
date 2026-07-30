"""Shared strict domain types."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise TypeError("float is forbidden; provide Decimal or a decimal string")
    return value


DecimalValue = Annotated[Decimal, BeforeValidator(_reject_float)]
NonNegativeDecimal = Annotated[DecimalValue, Field(ge=Decimal("0"))]
PositiveDecimal = Annotated[DecimalValue, Field(gt=Decimal("0"))]
RatioDecimal = Annotated[
    DecimalValue,
    Field(ge=Decimal("0"), le=Decimal("1")),
]


class DomainModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class FrozenDomainModel(DomainModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit timezone")
    return value
