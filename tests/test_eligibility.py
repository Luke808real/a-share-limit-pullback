"""Main-board non-ST universe eligibility tests (V2) — offline.

Eligibility is a MASK on evaluation output, NEVER a price-history deletion:
the strategy always runs on the complete real ASL bar series; ST dates are
never removed from indicator history.  ST status unknown fails closed.
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
    classify_rows_evidence,
    eligibility_for_date,
    is_asof_strategy_eligible,
    is_mainboard_instrument,
    mask_timeline_dates,
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


def _row(day, code="600519", is_st=False, trade_status=True, trust="EASTMONEY_SAME_DAY"):
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
        "asl_status_trust": trust,
    }


def test_mainboard_trusted_non_st_eligible():
    """Normal main-board stock with a trusted explicit non-ST status ->
    ELIGIBLE."""

    inst = _instrument()
    row = _row(APRIL_DAYS[0], is_st=False, trust="EASTMONEY_SAME_DAY")
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, row) == "ELIGIBLE"
    assert is_asof_strategy_eligible("600519", APRIL_DAYS[0], inst, row) == "ELIGIBLE"
    inst2 = _instrument(code="000001", exchange="SZ")
    assert eligibility_for_date("000001", APRIL_DAYS[0], inst2, _row(APRIL_DAYS[0], code="000001")) == "ELIGIBLE"


def test_st_excluded():
    inst = _instrument()
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], is_st=True)) == "EXCLUDED_ST"


def test_star_st_excluded():
    """*ST maps to status st in the ASL contract; the exclusion flag is a
    trusted is_st=True (regardless of st/*st spelling)."""

    inst = _instrument()
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], is_st=True)) == "EXCLUDED_ST"


def test_suspended_excluded():
    inst = _instrument()
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], trade_status=False)) == "EXCLUDED_SUSPENDED"
    # No bar at all that date -> suspended.
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, None) == "EXCLUDED_SUSPENDED"


def test_st_unknown_fails_closed():
    """is_st=None (no trusted status evidence) is EXCLUDED_STATUS_UNKNOWN —
    never guessed non-ST."""

    inst = _instrument()
    assert (
        eligibility_for_date("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], is_st=None, trust=None))
        == "EXCLUDED_STATUS_UNKNOWN"
    )
    assert (
        is_asof_strategy_eligible("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], is_st=None, trust=None))
        == "EXCLUDED_STATUS_UNKNOWN"
    )


def test_chinext_excluded():
    inst = _instrument(code="300750", exchange="SZ")
    assert is_mainboard_instrument(inst) is False
    assert eligibility_for_date("300750", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], code="300750")) == "EXCLUDED_NON_MAINBOARD"


def test_star_market_excluded():
    inst = _instrument(code="688981", exchange="SH")
    assert is_mainboard_instrument(inst) is False
    assert eligibility_for_date("688981", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], code="688981")) == "EXCLUDED_NON_MAINBOARD"


def test_etf_and_bj_excluded():
    inst = _instrument(code="510050", exchange="SH", asset_type="etf")
    assert eligibility_for_date("510050", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], code="510050")) == "EXCLUDED_NON_MAINBOARD"
    inst2 = _instrument(code="920001", exchange="BJ")
    assert eligibility_for_date("920001", APRIL_DAYS[0], inst2, _row(APRIL_DAYS[0], code="920001")) == "EXCLUDED_NON_MAINBOARD"


def test_not_listed_excluded():
    inst = _instrument(list_date=date(2026, 8, 7))
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0])) == "EXCLUDED_NOT_LISTED"
    inst2 = _instrument(delist_date=date(2026, 1, 1))
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst2, _row(APRIL_DAYS[0])) == "EXCLUDED_NOT_LISTED"


def test_full_history_intact_with_st_date():
    """The strategy history keeps the COMPLETE bar series even when one
    historical date is ST: no synthetic price gap is created."""

    inst = _instrument()
    st_day = APRIL_DAYS[3]
    rows = [
        _row(day, is_st=True if day == st_day else False)
        for day in APRIL_DAYS
    ]
    # Strategy input is the full unmodified series: an item exists for the
    # ST date (the engine still evaluated it; anchor rejection is the
    # production engine's own rule, not a deletion here).
    items, _ = build_timeline(rows, CONFIG, WINDOW_START, AS_OF)
    item_dates = {item.trade_date for item in items}
    assert st_day in item_dates
    assert len(item_dates) == len(APRIL_DAYS)


def test_st_date_not_emitted_as_candidate():
    """The eligibility mask removes the ST date from the user-facing output;
    the ST date can never surface as a candidate."""

    inst = _instrument()
    st_day = APRIL_DAYS[3]
    rows = [
        _row(day, is_st=True if day == st_day else False)
        for day in APRIL_DAYS
    ]
    rows_by_date = {row["trade_date"]: row for row in rows}
    items, _ = build_timeline(rows, CONFIG, WINDOW_START, AS_OF)
    masked = mask_timeline_dates(items, {"600519": inst}, rows_by_date, "600519")
    masked_dates = {item.trade_date for item in masked}
    assert st_day not in masked_dates
    assert APRIL_DAYS[4] in masked_dates


def test_later_normal_date_evaluated_with_real_history():
    """A later trusted non-ST date IS evaluated, using the real unmodified
    historical bar series (including the earlier ST bar as history)."""

    inst = _instrument()
    st_day = APRIL_DAYS[3]
    later = APRIL_DAYS[7]
    rows = [
        _row(day, is_st=True if day == st_day else False)
        for day in APRIL_DAYS
    ]
    rows_by_date = {row["trade_date"]: row for row in rows}
    items, _ = build_timeline(rows, CONFIG, WINDOW_START, AS_OF)
    masked = mask_timeline_dates(items, {"600519": inst}, rows_by_date, "600519")
    masked_by_date = {item.trade_date: item for item in masked}
    assert later in masked_by_date
    assert strategy_signature(masked_by_date[later])[0] in (
        "NORMAL", "LIMIT_ANCHOR", "WATCH_PULLBACK", "B1_READY", "B2_READY", "B2_CONFIRMED", "INVALID",
    )


def test_classify_rows_evidence_is_not_history():
    """classify_rows_evidence is an exclusion AUDIT, not a strategy input
    builder: eligible/excluded classification never shortens the bar series."""

    inst = _instrument()
    st_day = APRIL_DAYS[2]
    rows = [_row(day, is_st=True if day == st_day else False) for day in APRIL_DAYS]
    eligible, exclusions = classify_rows_evidence(rows, {"600519": inst})
    assert len(eligible) + len(exclusions) == len(rows)
    assert any(e["date"] == st_day.isoformat() and e["reason"] == "EXCLUDED_ST" for e in exclusions)
    # The strategy still consumes the full series.
    items, _ = build_timeline(rows, CONFIG, WINDOW_START, AS_OF)
    assert len(items) == len(APRIL_DAYS)


def test_mainboard_prefix_contract_frozen():
    assert FROZEN_MAINBOARD_PREFIXES == ("000", "001", "002", "003", "600", "601", "603", "605")
    for code in ("000001", "001979", "002594", "003816", "600519", "601318", "603288", "605117"):
        inst = _instrument(code=code, exchange="SH" if code.startswith("6") else "SZ")
        assert is_mainboard_instrument(inst) is True
