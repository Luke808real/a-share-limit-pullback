"""Main-board non-ST universe eligibility tests (V3) — offline.

ST is a POSITIVE EXCLUSION SET: a trusted ST/*ST fact excludes; a missing
per-stock status row is NORMAL and never excludes.  Fail-closed applies at
DATASET level (ST_DATA_NOT_READY blocks publishing the screen).  Eligibility
is a MASK, never a price-history deletion.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "research" / "asl_phase1b")
)

import pyarrow as pa
import pyarrow.parquet as pq

from limit_pullback.config import load_strategy_config  # noqa: E402
from eligibility import (  # noqa: E402
    FROZEN_MAINBOARD_PREFIXES,
    classify_rows_evidence,
    eligibility_for_date,
    is_asof_strategy_eligible,
    is_mainboard_instrument,
    mask_timeline_dates,
    screen_gate,
    st_exclusion_ready,
)
from shadow import build_timeline  # noqa: E402
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


def _row(day, code="600519", is_st=None, trade_status=True, trust=None):
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


def test_normal_mainboard_absent_status_row_eligible():
    """An ordinary main-board stock with NO individual status row is
    ELIGIBLE (positive exclusion set; dataset readiness is separate)."""

    inst = _instrument()
    row = _row(APRIL_DAYS[0], is_st=None, trust=None)
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, row) == "ELIGIBLE"
    assert is_asof_strategy_eligible("600519", APRIL_DAYS[0], inst, row) == "ELIGIBLE"
    inst2 = _instrument(code="000001", exchange="SZ")
    assert eligibility_for_date("000001", APRIL_DAYS[0], inst2, _row(APRIL_DAYS[0], code="000001")) == "ELIGIBLE"


def test_trusted_st_member_excluded():
    """A code-date in the trusted ST exclusion set (Baostock ST fact) is
    EXCLUDED_ST."""

    inst = _instrument()
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], is_st=True)) == "EXCLUDED_ST"


def test_suspended_no_bar_excluded():
    inst = _instrument()
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], trade_status=False)) == "EXCLUDED_SUSPENDED"
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, None) == "EXCLUDED_SUSPENDED"


def test_suspended_takes_precedence_over_st():
    """Suspended (no trading bar / non-trading session) is checked before
    the ST exclusion set."""

    inst = _instrument()
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], is_st=True, trade_status=False)) == "EXCLUDED_SUSPENDED"


def test_st_dataset_not_ready_gate_fails_closed(tmp_path):
    """Dataset-level fail-closed: without a ready ST exclusion dataset the
    screen gate is ST_DATA_NOT_READY, never published."""

    # Missing dataset entirely.
    lake = tmp_path / "lake"
    assert st_exclusion_ready(lake, AS_OF) is False
    assert screen_gate(lake, AS_OF) == "ST_DATA_NOT_READY"

    # Dataset present but no trusted ST exclusion row for AS_OF.
    status_root = lake / "curated" / "trading_status" / "trade_date=2026-08"
    status_root.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": pa.array(["600519.SH"], type=pa.large_string()),
                "trade_date": pa.array([AS_OF], type=pa.date32()),
                "is_trading": pa.array([True], type=pa.bool_()),
                "status": pa.array(["st"], type=pa.large_string()),
                "source": pa.array(["derived_bar_gap"], type=pa.large_string()),
                "data_version": pa.array(["v1"], type=pa.large_string()),
                "fetched_at": pa.array(
                    [datetime(2026, 8, 7, 2, 0, tzinfo=timezone.utc)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
            }
        ),
        status_root / "part-merged.parquet",
    )
    assert st_exclusion_ready(lake, AS_OF) is False
    assert screen_gate(lake, AS_OF) == "ST_DATA_NOT_READY"

    # A trusted baostock ST exclusion row for AS_OF makes the dataset ready.
    pq.write_table(
        pa.table(
            {
                "symbol": pa.array(["000826.SZ"], type=pa.large_string()),
                "trade_date": pa.array([AS_OF], type=pa.date32()),
                "is_trading": pa.array([True], type=pa.bool_()),
                "status": pa.array(["st"], type=pa.large_string()),
                "source": pa.array(["baostock"], type=pa.large_string()),
                "data_version": pa.array(["v1"], type=pa.large_string()),
                "fetched_at": pa.array(
                    [datetime(2026, 8, 7, 2, 0, tzinfo=timezone.utc)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
            }
        ),
        status_root / "part-baostock.parquet",
    )
    assert st_exclusion_ready(lake, AS_OF) is True
    assert screen_gate(lake, AS_OF) == "READY"


def test_chinext_star_etf_excluded():
    inst = _instrument(code="300750", exchange="SZ")
    assert is_mainboard_instrument(inst) is False
    assert eligibility_for_date("300750", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0], code="300750")) == "EXCLUDED_NON_MAINBOARD"
    inst2 = _instrument(code="688981", exchange="SH")
    assert eligibility_for_date("688981", APRIL_DAYS[0], inst2, _row(APRIL_DAYS[0], code="688981")) == "EXCLUDED_NON_MAINBOARD"
    inst3 = _instrument(code="510050", exchange="SH", asset_type="etf")
    assert eligibility_for_date("510050", APRIL_DAYS[0], inst3, _row(APRIL_DAYS[0], code="510050")) == "EXCLUDED_NON_MAINBOARD"
    inst4 = _instrument(code="920001", exchange="BJ")
    assert eligibility_for_date("920001", APRIL_DAYS[0], inst4, _row(APRIL_DAYS[0], code="920001")) == "EXCLUDED_NON_MAINBOARD"


def test_not_listed_excluded():
    inst = _instrument(list_date=date(2026, 8, 7))
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, _row(APRIL_DAYS[0])) == "EXCLUDED_NOT_LISTED"
    inst2 = _instrument(delist_date=date(2026, 1, 1))
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst2, _row(APRIL_DAYS[0])) == "EXCLUDED_NOT_LISTED"


def test_full_history_remains_unchanged():
    """The strategy history keeps the COMPLETE bar series even with an ST
    date: no synthetic price gap is created (item exists for the ST date)."""

    inst = _instrument()
    st_day = APRIL_DAYS[3]
    rows = [
        _row(day, is_st=True if day == st_day else None)
        for day in APRIL_DAYS
    ]
    items, _ = build_timeline(rows, CONFIG, WINDOW_START, AS_OF)
    item_dates = {item.trade_date for item in items}
    assert st_day in item_dates
    assert len(item_dates) == len(APRIL_DAYS)


def test_st_date_masked_from_candidates():
    """The eligibility mask removes the ST date from user-facing output."""

    inst = _instrument()
    st_day = APRIL_DAYS[3]
    rows = [
        _row(day, is_st=True if day == st_day else None)
        for day in APRIL_DAYS
    ]
    rows_by_date = {row["trade_date"]: row for row in rows}
    items, _ = build_timeline(rows, CONFIG, WINDOW_START, AS_OF)
    masked = mask_timeline_dates(items, {"600519": inst}, rows_by_date, "600519")
    masked_dates = {item.trade_date for item in masked}
    assert st_day not in masked_dates
    assert APRIL_DAYS[4] in masked_dates


def test_later_normal_date_remains_evaluable():
    """A later ordinary date (no status row, not in the ST exclusion set) is
    evaluated using the real unmodified historical series."""

    inst = _instrument()
    st_day = APRIL_DAYS[3]
    later = APRIL_DAYS[7]
    rows = [
        _row(day, is_st=True if day == st_day else None)
        for day in APRIL_DAYS
    ]
    rows_by_date = {row["trade_date"]: row for row in rows}
    items, _ = build_timeline(rows, CONFIG, WINDOW_START, AS_OF)
    masked = mask_timeline_dates(items, {"600519": inst}, rows_by_date, "600519")
    masked_by_date = {item.trade_date: item for item in masked}
    assert later in masked_by_date
    assert eligibility_for_date("600519", later, inst, rows_by_date[later]) == "ELIGIBLE"


def test_classify_rows_evidence_audit_only():
    inst = _instrument()
    st_day = APRIL_DAYS[2]
    rows = [_row(day, is_st=True if day == st_day else None) for day in APRIL_DAYS]
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
