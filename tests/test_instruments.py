from __future__ import annotations

import pytest

from limit_pullback.instruments import (
    InstrumentCodeError,
    parse_instrument_code,
)
from limit_pullback.models.market import DailyBarsRequest


@pytest.mark.parametrize(
    ("code", "exchange", "baostock_code"),
    (
        ("000001", "SZ", "sz.000001"),
        ("001382", "SZ", "sz.001382"),
        ("002640", "SZ", "sz.002640"),
        ("003001", "SZ", "sz.003001"),
        ("600199", "SH", "sh.600199"),
        ("601001", "SH", "sh.601001"),
        ("603318", "SH", "sh.603318"),
        ("605001", "SH", "sh.605001"),
    ),
)
def test_supported_main_board_prefixes(
    code,
    exchange,
    baostock_code,
):
    instrument = parse_instrument_code(code)

    assert instrument.normalized_code == code
    assert instrument.exchange == exchange
    assert instrument.baostock_code == baostock_code
    assert instrument.board == "MAIN"


def test_leading_zero_is_preserved():
    instrument = parse_instrument_code("001382")

    assert instrument.normalized_code == "001382"
    assert instrument.baostock_code == "sz.001382"
    assert instrument.model_config["extra"] == "forbid"
    assert instrument.model_config["frozen"] is True


@pytest.mark.parametrize(
    "code",
    (
        "300001",
        "301001",
        "688001",
        "200001",
        "900001",
        "830001",
    ),
)
def test_non_main_board_prefixes_are_rejected(code):
    with pytest.raises(
        InstrumentCodeError,
        match=f"UNSUPPORTED_MARKET_BOARD:{code}",
    ):
        parse_instrument_code(code)


def test_length_and_numeric_errors_are_distinct():
    with pytest.raises(InstrumentCodeError, match="INVALID_CODE_LENGTH"):
        parse_instrument_code("12345")
    with pytest.raises(InstrumentCodeError, match="NON_NUMERIC_CODE"):
        parse_instrument_code("ABC123")


def test_provider_request_uses_the_shared_instrument_validator():
    with pytest.raises(ValueError, match="UNSUPPORTED_MARKET_BOARD"):
        DailyBarsRequest(
            codes=("300001",),
            start_date="2026-07-01",
            end_date="2026-07-30",
        )
