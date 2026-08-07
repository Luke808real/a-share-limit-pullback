"""Main-board non-ST universe eligibility tests (offline).

Universe contract (frozen): SH/SZ MAINBOARD NORMAL A-SHARES ONLY, with ST as
an exclusion flag applied BEFORE screen_code.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "research" / "asl_phase1b")
)

from limit_pullback.config import load_strategy_config  # noqa: E402
from eligibility import (  # noqa: E402
    FROZEN_MAINBOARD_PREFIXES,
    filter_eligible_rows,
    is_mainboard_instrument,
    is_strategy_eligible,
)
from shadow import build_timeline, strategy_signature  # noqa: E402
from shadow import WINDOW_START, AS_OF  # noqa: E402

CONFIG = load_strategy_config("config/strategy.yaml")

APRIL_DAYS = [
    date(2026, 4, 1),
    date(2026, 4, 2),
    date(2026, 4, 3),
    date(2026, 4, 6),
    date(2026, 4, 7),
    date(2026, 4, 8),
    date(2026, 4, 9),
    date(2026, 4, 10),
]


def _instrument(code="600519", exchange="SH", asset_type="stock",
                list_date=date(2010, 1, 1), delist_date=None):
    return {
        "symbol": f"{code}.{exchange}",
        "exchange": exchange,
        "asset_type": asset_type,
        "list_date": list_date,
        "delist_date": delist_date,
    }


def _row(day, code="600519", is_st=None, trade_status=True):
    return {
        "trade_date": day,
        "code": code,
        "open": "10.00",
        "high": "10.00",
        "low": "10.00",
        "close": "10.00",
        "preclose": "10.00",
        "volume": "100000",
        "amount": "1000000.00",
        "trade_status": trade_status,
        "is_st": is_st,
        "asl_status_trust": None,
    }


def test_mainboard_normal_trading_stock_eligible():
    inst = _instrument()
    assert is_strategy_eligible("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0])) == "ELIGIBLE"
    inst2 = _instrument(code="000001", exchange="SZ")
    assert is_strategy_eligible("000001", APRIL_DAYS[0], inst2, _row(APRIL_DAYS[0], code="000001")) == "ELIGIBLE"


def test_st_excluded_before_screen_code():
    inst = _instrument()
    row = _row(APRIL_DAYS[0], is_st=True)
    assert is_strategy_eligible("600519", APRIL_DAYS[0], inst, row) == "EXCLUDED_ST"
    # ST rows are filtered out BEFORE screen_code: no timeline item exists
    # for the excluded date.
    rows = [
        _row(day, is_st=True if day == APRIL_DAYS[3] else None)
        for day in APRIL_DAYS
    ]
    eligible, exclusions = filter_eligible_rows(rows, {"600519": inst})
    assert len(eligible) == len(APRIL_DAYS) - 1
    assert any(
        e["date"] == APRIL_DAYS[3].isoformat() and e["reason"] == "EXCLUDED_ST"
        for e in exclusions
    )
    items, _ = build_timeline(eligible, CONFIG, WINDOW_START, AS_OF)
    dates = {item.trade_date for item in items}
    assert APRIL_DAYS[3] not in dates
    assert APRIL_DAYS[4] in dates


def test_star_st_excluded():
    """*ST maps to status st in the ASL contract; the exclusion flag is a
    trusted is_st=True (regardless of the st/*st spelling)."""

    inst = _instrument()
    assert is_strategy_eligible("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], is_st=True)) == "EXCLUDED_ST"


def test_suspended_excluded():
    inst = _instrument()
    row = _row(APRIL_DAYS[0], trade_status=False)
    assert is_strategy_eligible("600519", APRIL_DAYS[0], inst, row) == "EXCLUDED_SUSPENDED"


def test_chinext_excluded():
    inst = _instrument(code="300750", exchange="SZ")
    assert is_mainboard_instrument(inst) is False
    assert is_strategy_eligible("300750", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], code="300750")) == "EXCLUDED_NON_MAINBOARD"


def test_star_market_excluded():
    inst = _instrument(code="688981", exchange="SH")
    assert is_mainboard_instrument(inst) is False
    assert is_strategy_eligible("688981", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], code="688981")) == "EXCLUDED_NON_MAINBOARD"


def test_etf_excluded():
    inst = _instrument(code="510050", exchange="SH", asset_type="etf")
    assert is_strategy_eligible("510050", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], code="510050")) == "EXCLUDED_NON_MAINBOARD"


def test_bj_excluded():
    inst = _instrument(code="920001", exchange="BJ")
    assert is_strategy_eligible("920001", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], code="920001")) == "EXCLUDED_NON_MAINBOARD"


def test_unknown_st_never_excludes():
    """is_st=None (no trusted ASL status fact) is NOT an ST exclusion."""

    inst = _instrument()
    assert is_strategy_eligible("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], is_st=None)) == "ELIGIBLE"


def test_not_listed_excluded():
    inst = _instrument(list_date=date(2026, 8, 7))
    assert is_strategy_eligible("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0])) == "EXCLUDED_NOT_LISTED"
    inst2 = _instrument(delist_date=date(2026, 1, 1))
    assert is_strategy_eligible("600519", APRIL_DAYS[0], inst2, _row(APRIL_DAYS[0])) == "EXCLUDED_NOT_LISTED"


def test_historical_st_date_excluded_normal_date_eligible():
    """Same stock: the historical ST date is excluded, the historical normal
    date stays eligible (ST is per-date, not per-code)."""

    inst = _instrument()
    st_day = APRIL_DAYS[2]
    rows = [_row(day, is_st=True if day == st_day else None) for day in APRIL_DAYS]
    eligible, exclusions = filter_eligible_rows(rows, {"600519": inst})
    assert len(eligible) == len(APRIL_DAYS) - 1
    assert all(e["date"] != APRIL_DAYS[0].isoformat() for e in exclusions)
    assert any(e["date"] == st_day.isoformat() for e in exclusions)
    items, _ = build_timeline(eligible, CONFIG, WINDOW_START, AS_OF)
    dates = {item.trade_date for item in items}
    assert st_day not in dates
    assert APRIL_DAYS[0] in dates


def test_precedence_non_mainboard_over_status():
    """A ChiNext code with an ST flag is EXCLUDED_NON_MAINBOARD (structural
    checks first), never evaluated as an ST stock."""

    inst = _instrument(code="300750", exchange="SZ")
    assert (
        is_strategy_eligible("300750", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], is_st=True))
        == "EXCLUDED_NON_MAINBOARD"
    )


def test_mainboard_prefix_contract_frozen():
    assert FROZEN_MAINBOARD_PREFIXES == ("000", "001", "002", "003", "600", "601", "603", "605")
    for code in ("000001", "001979", "002594", "003816", "600519", "601318", "603288", "605117"):
        inst = _instrument(code=code, exchange="SH" if code.startswith("6") else "SZ")
        assert is_mainboard_instrument(inst) is True
