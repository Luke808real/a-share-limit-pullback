"""Main-board non-ST universe eligibility tests (V3) — offline.

ST is a POSITIVE EXCLUSION SET: a trusted ST/*ST fact excludes; a missing
per-stock status row is NORMAL and never excludes.  Fail-closed applies at
DATASET level (ST_DATA_NOT_READY blocks publishing the screen).  Eligibility
is a MASK, never a price-history deletion.
"""

from __future__ import annotations

import json
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
    required_st_codes_for_asof,
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


def _write_marker(lake: Path, symbols: list[str]) -> None:
    """Official ASL ST-backfill completion evidence (resume marker)."""

    path = lake / "meta" / "state" / "trading_status_st_backfill.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"completed": symbols}), encoding="utf-8")


def _write_baostock_rows(lake: Path, symbols: list[str]) -> None:
    """A non-empty trading_status dataset with trusted ST rows (used to prove
    row presence NEVER establishes readiness)."""

    status_root = lake / "curated" / "trading_status" / "trade_date=2026-08"
    status_root.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": pa.array([f"{s}.SH" for s in symbols], type=pa.large_string()),
                "trade_date": pa.array([AS_OF] * len(symbols), type=pa.date32()),
                "is_trading": pa.array([True] * len(symbols), type=pa.bool_()),
                "status": pa.array(["st"] * len(symbols), type=pa.large_string()),
                "source": pa.array(["baostock"] * len(symbols), type=pa.large_string()),
                "data_version": pa.array(["v1"] * len(symbols), type=pa.large_string()),
                "fetched_at": pa.array(
                    [datetime(2026, 8, 7, 2, 0, tzinfo=timezone.utc)] * len(symbols),
                    type=pa.timestamp("us", tz="UTC"),
                ),
            }
        ),
        status_root / "part-merged.parquet",
    )


def test_nonempty_st_rows_incomplete_coverage_not_ready(tmp_path):
    """A non-empty ST exclusion set does NOT prove completeness: required
    coverage missing -> NOT_READY even though ST rows exist."""

    lake = tmp_path / "lake"
    _write_baostock_rows(lake, ["600519"])
    _write_marker(lake, ["600519.SH"])  # official completion: one symbol only
    required = ["600519", "601318"]
    assert st_exclusion_ready(lake, AS_OF, required) is False
    assert screen_gate(lake, AS_OF, required) == "ST_DATA_NOT_READY"


def test_targeted_scope_vs_larger_required_universe_not_ready(tmp_path):
    """A targeted 59-code completion cannot satisfy a larger required
    universe: NOT_READY."""

    lake = tmp_path / "lake"
    targeted = [f"0000{i:02d}.SZ" for i in range(1, 60)]
    _write_marker(lake, targeted)
    required = [f"0000{i:02d}" for i in range(1, 61)]  # 60 required codes
    assert st_exclusion_ready(lake, AS_OF, required) is False
    assert screen_gate(lake, AS_OF, required) == "ST_DATA_NOT_READY"


def test_complete_required_coverage_ready(tmp_path):
    lake = tmp_path / "lake"
    _write_marker(lake, ["600519.SH", "601318.SH"])
    required = ["600519", "601318"]
    assert st_exclusion_ready(lake, AS_OF, required) is True
    assert screen_gate(lake, AS_OF, required) == "READY"


def test_missing_or_failed_completion_evidence_not_ready(tmp_path):
    """Missing or malformed official completion evidence fails closed."""

    lake = tmp_path / "lake"
    assert st_exclusion_ready(lake, AS_OF, ["600519"]) is False
    marker = lake / "meta" / "state" / "trading_status_st_backfill.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{not json", encoding="utf-8")
    assert st_exclusion_ready(lake, AS_OF, ["600519"]) is False
    assert screen_gate(lake, AS_OF, ["600519"]) == "ST_DATA_NOT_READY"


def test_zero_st_rows_with_proven_scope_ready(tmp_path):
    """A day with ZERO ST stocks is READY when the official completion
    contract proves the fetch completed — completeness is independent of ST
    row count (no trading_status rows at all here)."""

    lake = tmp_path / "lake"
    _write_marker(lake, ["600519.SH", "601318.SH"])
    required = ["600519", "601318"]
    assert st_exclusion_ready(lake, AS_OF, required) is True
    assert screen_gate(lake, AS_OF, required) == "READY"


def _scope_instruments():
    """Synthetic instruments for the required-scope tests: one ordinary,
    one delisted, one not-yet-listed, one suspended, one non-main-board."""

    return {
        "600519": _instrument(code="600519", exchange="SH"),                          # ordinary
        "601318": _instrument(code="601318", exchange="SH"),                          # ordinary
        "600000": _instrument(code="600000", exchange="SH", delist_date=date(2026, 1, 1)),  # delisted
        "600001": _instrument(code="600001", exchange="SH", list_date=date(2026, 8, 7)),    # not yet listed
        "600002": _instrument(code="600002", exchange="SH"),                          # suspended (no bar)
        "300750": _instrument(code="300750", exchange="SZ"),                          # non-main-board
    }


def test_delisted_code_not_required_for_st_coverage():
    instruments = _scope_instruments()
    bars = {"600519": 100000, "601318": 100000, "600002": 0}
    required = required_st_codes_for_asof(instruments, bars, AS_OF)
    assert "600000" not in required  # delisted before AS_OF


def test_not_yet_listed_code_not_required():
    instruments = _scope_instruments()
    bars = {"600519": 100000, "601318": 100000}
    required = required_st_codes_for_asof(instruments, bars, AS_OF)
    assert "600001" not in required  # lists after AS_OF


def test_suspended_or_no_bar_code_not_required():
    instruments = _scope_instruments()
    bars = {"600519": 100000, "601318": 100000, "600002": 0}
    required = required_st_codes_for_asof(instruments, bars, AS_OF)
    assert "600002" not in required  # no valid trading bar


def test_listed_trading_mainboard_code_required():
    instruments = _scope_instruments()
    bars = {"600519": 100000, "601318": 100000, "600002": 0}
    required = required_st_codes_for_asof(instruments, bars, AS_OF)
    assert "600519" in required
    assert "601318" in required
    assert "300750" not in required  # non-main-board


def test_incomplete_required_set_not_ready(tmp_path):
    """Incomplete coverage of the REQUIRED scope -> ST_DATA_NOT_READY (a
    completed marker that omits required codes cannot publish the screen)."""

    lake = tmp_path / "lake"
    _write_marker(lake, ["600519.SH"])  # official completion: one symbol
    required = ["600519", "601318"]
    assert screen_gate(lake, AS_OF, required) == "ST_DATA_NOT_READY"


def test_complete_required_set_ready(tmp_path):
    lake = tmp_path / "lake"
    _write_marker(lake, ["600519.SH", "601318.SH"])
    required = ["600519", "601318"]
    assert screen_gate(lake, AS_OF, required) == "READY"


def test_per_stock_absent_status_row_remains_eligible():
    """Per-stock eligibility is separate from dataset readiness: an ordinary
    stock with no individual status row is still ELIGIBLE."""

    inst = _instrument()
    row = _row(APRIL_DAYS[0], is_st=None, trust=None)
    assert eligibility_for_date("600519", APRIL_DAYS[0], inst, row) == "ELIGIBLE"


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
