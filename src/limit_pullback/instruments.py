"""Strict instrument parsing for the supported A-share main-board scope."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field


Exchange = Literal["SH", "SZ"]
Board = Literal["MAIN"]

MAIN_BOARD_PREFIX_TO_EXCHANGE: Final = MappingProxyType(
    {
        "000": "SZ",
        "001": "SZ",
        "002": "SZ",
        "003": "SZ",
        "600": "SH",
        "601": "SH",
        "603": "SH",
        "605": "SH",
    }
)


class InstrumentCodeError(ValueError):
    """A code is malformed or outside the frozen main-board scope."""


class InstrumentCode(BaseModel):
    """Immutable normalized result; construction stays behind the parser."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    normalized_code: str = Field(pattern=r"^\d{6}$")
    exchange: Exchange
    baostock_code: str = Field(pattern=r"^(sh|sz)\.\d{6}$")
    board: Board


def parse_instrument_code(value: str) -> InstrumentCode:
    """Parse one exact six-digit Shanghai/Shenzhen main-board code."""

    if not isinstance(value, str):
        raise InstrumentCodeError(
            "INVALID_CODE_TYPE: stock code must be a six-digit string"
        )
    if len(value) != 6:
        raise InstrumentCodeError(
            f"INVALID_CODE_LENGTH: expected 6 characters, got {len(value)}"
        )
    if not value.isascii() or not value.isdecimal():
        raise InstrumentCodeError(
            "NON_NUMERIC_CODE: stock code must contain six ASCII digits"
        )
    exchange = MAIN_BOARD_PREFIX_TO_EXCHANGE.get(value[:3])
    if exchange is None:
        raise InstrumentCodeError(f"UNSUPPORTED_MARKET_BOARD:{value}")
    return InstrumentCode(
        normalized_code=value,
        exchange=exchange,
        baostock_code=f"{exchange.lower()}.{value}",
        board="MAIN",
    )
