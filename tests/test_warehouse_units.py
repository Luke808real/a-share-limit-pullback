from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from limit_pullback.warehouse.units import (
    normalize_akshare_daily,
    normalize_tushare_daily,
    normalize_tushare_daily_basic,
)


def test_tushare_daily_converts_lots_and_thousand_yuan_to_shares_and_yuan():
    row = normalize_tushare_daily(
        {
            "ts_code": "603318.SH",
            "trade_date": "20260730",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.2,
            "pre_close": 10.0,
            "vol": 1000.0,
            "amount": 1234.5,
            "pct_chg": 2.0,
        }
    )
    assert row["code"] == "603318"
    assert row["trade_date"] == date(2026, 7, 30)
    assert row["volume"] == Decimal("100000")
    assert row["amount"] == Decimal("1234500")
    assert row["pct_change"] == Decimal("2.0")


def test_akshare_daily_converts_lots_to_shares_and_keeps_yuan():
    row = normalize_akshare_daily(
        {
            "date": "2026-07-30",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.2,
            "volume": 100000.0,
            "amount": 1020000.0,
            "turnover": 0.154909,
        },
        code="603318",
    )
    assert row["volume"] == Decimal("100000")
    assert row["amount"] == Decimal("1020000")
    assert row["preclose"] is None
    assert row["turnover_rate"] == Decimal("15.4909")


def test_daily_basic_market_cap_converted_from_wan_to_yuan():
    row = normalize_tushare_daily_basic(
        {
            "ts_code": "000001.SZ",
            "trade_date": "20260730",
            "turnover_rate": 1.2,
            "volume_ratio": 0.9,
            "pe": 8.5,
            "pb": 1.1,
            "total_mv": 250000.0,
            "circ_mv": 200000.0,
        }
    )
    assert row["total_mv"] == Decimal("250000")
    assert row["circ_mv"] == Decimal("200000")


def test_no_float_leaks_into_normalized_rows():
    row = normalize_tushare_daily(
        {
            "ts_code": "002891.SZ",
            "trade_date": "20260728",
            "open": 10.1,
            "high": 10.3,
            "low": 9.9,
            "close": 10.2,
            "pre_close": 10.1,
            "vol": 500.0,
            "amount": 510.0,
            "pct_chg": 0.99,
        }
    )
    assert all(not isinstance(value, float) for value in row.values())
    assert all(
        isinstance(value, (Decimal, date, str, bool, type(None)))
        for value in row.values()
    )


def test_malformed_decimal_is_rejected():
    with pytest.raises(ValueError):
        normalize_tushare_daily(
            {
                "ts_code": "600199.SH",
                "trade_date": "20260728",
                "open": "abc",
                "high": "10.3",
                "low": "9.9",
                "close": "10.2",
                "pre_close": "10.1",
                "vol": "500",
                "amount": "510",
            }
        )
