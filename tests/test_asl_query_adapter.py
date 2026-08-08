"""Phase 1C-Q1 tests: official ASL Query API -> V Flash candidate snapshot.

The official ``ashare_lake.query`` API is the production read boundary; the
physical-parquet adapter is LEGACY_MIGRATION_FALLBACK.  These tests run only
where ``ashare_lake`` is importable (the ASL environment).
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

try:
    from ashare_lake.query import load, resolve_config, scan  # noqa: F401

    HAS_ASL_QUERY = True
except ImportError:  # pragma: no cover - default CI env without ASL
    HAS_ASL_QUERY = False

pytestmark = pytest.mark.skipif(
    not HAS_ASL_QUERY, reason="ashare_lake query API unavailable"
)

from limit_pullback.warehouse.asl_adapter import (  # noqa: E402
    AslAdapterError,
    load_asl_daily_slice,
)
from limit_pullback.warehouse.asl_query_adapter import (  # noqa: E402
    query_asof_scope,
    query_daily_facts,
)
from limit_pullback.warehouse.asl_snapshot import (  # noqa: E402
    build_asl_candidate_snapshot,
)
from limit_pullback.warehouse.layout import WarehouseLayout  # noqa: E402
from limit_pullback.warehouse.metadata import WarehouseMetadata  # noqa: E402
from limit_pullback.warehouse.snapshot import (  # noqa: E402
    read_snapshot_daily,
    read_snapshot_pool,
)
from limit_pullback.warehouse.validate import data_validate  # noqa: E402

AS_OF = date(2026, 6, 15)
START = date(2026, 6, 11)
CODES = ["000001", "000010", "000524", "605198"]

_FETCHED = datetime(2026, 8, 7, 2, 0, tzinfo=timezone.utc)


def _write(path: Path, rows: list[dict]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _build_lake(root: Path) -> None:
    """Synthetic ASL lake with FULL dataset schemas (query API validates)."""

    _write(
        root / "curated" / "instruments" / "part-merged.parquet",
        [
            {"symbol": "000001.SZ", "name": "平安银行", "exchange": "SZ", "asset_type": "stock",
             "list_date": None, "delist_date": None, "prev_symbol": None,
             "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED},
            {"symbol": "000010.SZ", "name": "美丽生态", "exchange": "SZ", "asset_type": "stock",
             "list_date": None, "delist_date": None, "prev_symbol": None,
             "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED},
            {"symbol": "000524.SZ", "name": "岭南控股", "exchange": "SZ", "asset_type": "stock",
             "list_date": None, "delist_date": None, "prev_symbol": None,
             "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED},
            {"symbol": "300750.SZ", "name": "宁德时代", "exchange": "SZ", "asset_type": "stock",
             "list_date": None, "delist_date": None, "prev_symbol": None,
             "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED},
            {"symbol": "605198.SH", "name": "德力西", "exchange": "SH", "asset_type": "stock",
             "list_date": None, "delist_date": None, "prev_symbol": None,
             "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED},
            {"symbol": "600000.SH", "name": "浦发银行", "exchange": "SH", "asset_type": "stock",
             "list_date": date(1995, 1, 1), "delist_date": date(2026, 6, 1), "prev_symbol": None,
             "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED},
            {"symbol": "600001.SH", "name": "新上市", "exchange": "SH", "asset_type": "stock",
             "list_date": date(2026, 6, 20), "delist_date": None, "prev_symbol": None,
             "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED},
            {"symbol": "600002.SH", "name": "停牌", "exchange": "SH", "asset_type": "stock",
             "list_date": date(2000, 1, 1), "delist_date": None, "prev_symbol": None,
             "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED},
            {"symbol": "600003.SH", "name": "零量", "exchange": "SH", "asset_type": "stock",
             "list_date": date(2000, 1, 1), "delist_date": None, "prev_symbol": None,
             "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED},
        ],
    )
    _write(
        root / "curated" / "trading_calendar" / "trade_date=2026" / "part-merged.parquet",
        [
            {"trade_date": day, "is_trading": day in (date(2026, 6, 11), date(2026, 6, 12), date(2026, 6, 15)),
             "source": "exchange_calendar", "data_version": "v1", "fetched_at": _FETCHED}
            for day in [
                date(2026, 6, 11), date(2026, 6, 12),
                date(2026, 6, 13), date(2026, 6, 14), date(2026, 6, 15),
            ]
        ],
    )
    bars = {
        "000001.SZ": [
            {"trade_date": date(2026, 6, 11), "open": 11.30, "high": 11.40, "low": 11.20, "close": 11.30, "volume": 100000, "amount": 1129999.5},
            {"trade_date": date(2026, 6, 12), "open": 11.00, "high": 11.25, "low": 10.88, "close": 11.24, "volume": 200000, "amount": 2222222.25},
            {"trade_date": date(2026, 6, 15), "open": 11.21, "high": 11.21, "low": 10.98, "close": 11.06, "volume": 150000, "amount": 1650000.0},
        ],
        "000010.SZ": [
            {"trade_date": date(2026, 6, 11), "open": 2.00, "high": 2.01, "low": 1.99, "close": 2.00, "volume": 50000, "amount": 100000.0},
            {"trade_date": date(2026, 6, 12), "open": 2.00, "high": 2.06, "low": 2.00, "close": 2.05, "volume": 60000, "amount": 122000.0},
            {"trade_date": date(2026, 6, 15), "open": 2.05, "high": 2.10, "low": 2.04, "close": 2.10, "volume": 70000, "amount": 145000.0},
        ],
        "000524.SZ": [
            {"trade_date": date(2026, 6, 11), "open": 9.00, "high": 9.10, "low": 8.95, "close": 9.00, "volume": 80000, "amount": 720000.0},
            {"trade_date": date(2026, 6, 12), "open": 9.00, "high": 9.05, "low": 8.95, "close": 9.00, "volume": 0, "amount": 0.0},
            {"trade_date": date(2026, 6, 15), "open": 9.10, "high": 9.25, "low": 9.05, "close": 9.20, "volume": 90000, "amount": 825000.0},
        ],
        "605198.SH": [
            {"trade_date": date(2026, 6, 11), "open": 49.9, "high": 50.1, "low": 49.8, "close": 50.0, "volume": 20000, "amount": 1000000.0},
            {"trade_date": date(2026, 6, 12), "open": 50.0, "high": 50.5, "low": 49.8, "close": 50.2, "volume": 30000, "amount": 1500000.0},
            {"trade_date": date(2026, 6, 15), "open": 50.2, "high": 50.6, "low": 50.0, "close": 50.4, "volume": 35000, "amount": 1760000.0},
        ],
        "300750.SZ": [
            {"trade_date": date(2026, 6, 11), "open": 200.0, "high": 205.0, "low": 199.0, "close": 204.0, "volume": 1000000, "amount": 2.03e8},
            {"trade_date": date(2026, 6, 12), "open": 203.0, "high": 206.0, "low": 201.0, "close": 205.0, "volume": 1100000, "amount": 2.25e8},
            {"trade_date": date(2026, 6, 15), "open": 205.0, "high": 207.0, "low": 203.0, "close": 204.5, "volume": 900000, "amount": 1.84e8},
        ],
        "600002.SH": [
            {"trade_date": date(2026, 6, 11), "open": 5.0, "high": 5.1, "low": 4.9, "close": 5.0, "volume": 10000, "amount": 50000.0},
            {"trade_date": date(2026, 6, 12), "open": 5.0, "high": 5.0, "low": 4.8, "close": 4.9, "volume": 10000, "amount": 49000.0},
        ],
        "600003.SH": [
            {"trade_date": date(2026, 6, 11), "open": 6.0, "high": 6.1, "low": 5.9, "close": 6.0, "volume": 10000, "amount": 60000.0},
            {"trade_date": date(2026, 6, 12), "open": 6.0, "high": 6.2, "low": 5.9, "close": 6.1, "volume": 10000, "amount": 61000.0},
            {"trade_date": date(2026, 6, 15), "open": 6.1, "high": 6.1, "low": 6.0, "close": 6.0, "volume": 0, "amount": 0.0},
        ],
    }
    by_date: dict[date, list[dict]] = {}
    for symbol, rows in bars.items():
        for row in rows:
            by_date.setdefault(row["trade_date"], []).append(
                {
                    "symbol": symbol,
                    "trade_date": row["trade_date"],
                    "open": row["open"], "high": row["high"], "low": row["low"],
                    "close": row["close"], "volume": row["volume"], "amount": row["amount"],
                    "source": "tdx_protocol", "data_version": "v2", "fetched_at": _FETCHED,
                }
            )
    for trade_date, rows in sorted(by_date.items()):
        _write(
            root / "curated" / "daily_bars" / f"trade_date={trade_date.isoformat()}" / "part-merged.parquet",
            rows,
        )
    _write(
        root / "curated" / "trading_status" / "trade_date=2026-06" / "part-merged.parquet",
        [
            {"symbol": "000010.SZ", "trade_date": date(2026, 6, 12), "is_trading": True, "status": "st", "source": "baostock", "data_version": "v1", "fetched_at": _FETCHED},
            {"symbol": "000010.SZ", "trade_date": date(2026, 6, 15), "is_trading": True, "status": "*st", "source": "baostock", "data_version": "v1", "fetched_at": _FETCHED},
            {"symbol": "000524.SZ", "trade_date": date(2026, 6, 12), "is_trading": False, "status": "suspended", "source": "derived_bar_gap", "data_version": "v1", "fetched_at": _FETCHED},
        ],
    )


def _query_rows(lake: Path, codes=CODES) -> list:
    slices = list(
        query_daily_facts(lake, as_of=AS_OF, start=START, codes=codes)
    )
    return [row for slice_ in slices for row in slice_.rows]


def _layout(tmp_path: Path) -> WarehouseLayout:
    layout = WarehouseLayout(tmp_path / "data")
    layout.ensure_dirs()
    return layout


# --- A: official query API only, no physical parquet reads ----------------

def test_query_adapter_never_reads_physical_parquet(tmp_path, monkeypatch):
    """A: the query build path never calls the physical parquet reader or
    opens curated parquet files directly."""

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("physical parquet read must not happen")

    monkeypatch.setattr(
        "limit_pullback.warehouse.asl_snapshot.load_asl_daily_slice", _forbidden
    )
    import pyarrow.parquet as pq

    monkeypatch.setattr(pq.ParquetFile, "read", _forbidden)
    lake = tmp_path / "lake"
    _build_lake(lake)
    layout = _layout(tmp_path)
    snapshot = build_asl_candidate_snapshot(
        layout=layout, asl_root=lake, as_of=AS_OF, codes=CODES, start=START,
    )
    assert snapshot.status == "CURRENT"


# --- B: symbol normalization ----------------------------------------------

def test_symbol_normalization(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    rows = _query_rows(lake, ["000001"])
    assert rows
    assert all(row.code == "000001" for row in rows)


# --- C: sequential preclose with predecessor before START -----------------

def test_predecessor_before_start(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    # Add a real predecessor bar the day before START (2026-06-10).
    _write(
        lake / "curated" / "daily_bars" / "trade_date=2026-06-10" / "part-merged.parquet",
        [
            {"symbol": "000001.SZ", "trade_date": date(2026, 6, 10),
             "open": 11.1, "high": 11.3, "low": 11.05, "close": 11.25,
             "volume": 90000, "amount": 1012500.0,
             "source": "tdx_protocol", "data_version": "v2", "fetched_at": _FETCHED},
        ],
    )
    rows = {r.trade_date: r for r in _query_rows(lake, ["000001"])}
    assert rows[date(2026, 6, 11)].preclose == Decimal("11.2500")
    assert rows[date(2026, 6, 12)].preclose == Decimal("11.3000")


# --- D: IPO day MISSING_PRECLOSE ------------------------------------------

def test_ipo_day_missing_preclose(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    _write(
        lake / "curated" / "instruments" / "part-merged.parquet",
        [
            {"symbol": "600004.SH", "name": "新股", "exchange": "SH", "asset_type": "stock",
             "list_date": date(2026, 6, 15), "delist_date": None, "prev_symbol": None,
             "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED},
        ],
        # append to the existing instruments file
    ) if False else None
    # simpler: build a dedicated single-code lake
    import pyarrow.parquet as pq
    import pyarrow as pa

    inst_path = lake / "curated" / "instruments" / "part-merged.parquet"
    table = pq.ParquetFile(inst_path).read()
    rows = table.to_pylist()
    rows.append(
        {"symbol": "600004.SH", "name": "新股", "exchange": "SH", "asset_type": "stock",
         "list_date": date(2026, 6, 15), "delist_date": None, "prev_symbol": None,
         "source": "tdx_protocol", "data_version": "v1", "fetched_at": _FETCHED}
    )
    pq.write_table(pa.Table.from_pylist(rows), inst_path)
    _write(
        lake / "curated" / "daily_bars" / "trade_date=2026-06-15" / "part-ipo.parquet",
        [
            {"symbol": "600004.SH", "trade_date": date(2026, 6, 15),
             "open": 10.0, "high": 11.0, "low": 9.9, "close": 10.5,
             "volume": 500000, "amount": 5200000.0,
             "source": "tdx_protocol", "data_version": "v2", "fetched_at": _FETCHED},
        ],
    )
    rows_out = _query_rows(lake, ["600004"])
    assert len(rows_out) == 1
    assert rows_out[0].row_status == "MISSING_PRECLOSE"
    assert rows_out[0].preclose is None


# --- E/F: PIT status trust unchanged; ST bars stay in history -------------

def test_pit_status_semantics_and_st_history_kept(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    rows = {r.code: r for r in _query_rows(lake, CODES)}
    # 000010 trusted historical ST on 6/12 and 6/15.
    assert rows["000010"].is_st is True
    # The ST-dated bars are STILL in history (not dropped).
    by_code = {}
    for row in _query_rows(lake, CODES):
        by_code.setdefault(row.code, {})[row.trade_date] = row
    assert date(2026, 6, 12) in by_code["000010"]
    assert by_code["000010"][date(2026, 6, 12)].is_st is True
    # 000524's derived_bar_gap suspension day has a zero-volume bar marked
    # non-trading; the other days are trading.
    assert by_code["000524"][date(2026, 6, 12)].trade_status is False
    assert by_code["000524"][date(2026, 6, 15)].trade_status is True


# --- G/H: missing-session gap guard ---------------------------------------

def test_unexplained_missing_session_raises(tmp_path):
    """H: 600002 has no 6/15 bar and no trusted status -> MISSING_REQUIRED_BAR."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    with pytest.raises(AslAdapterError) as excinfo:
        _query_rows(lake, ["600002"])
    assert "MISSING_REQUIRED_BAR:600002:2026-06-15" in str(excinfo.value)


def test_trusted_suspension_authorizes_missing_session(tmp_path):
    """G: a derived_bar_gap suspension row authorizes the absent session."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    import pyarrow as pa
    import pyarrow.parquet as pq

    status_path = lake / "curated" / "trading_status" / "trade_date=2026-06" / "part-merged.parquet"
    table = pq.ParquetFile(status_path).read()
    rows = table.to_pylist()
    rows.append(
        {"symbol": "600002.SH", "trade_date": date(2026, 6, 15),
         "is_trading": False, "status": "suspended", "source": "derived_bar_gap",
         "data_version": "v1", "fetched_at": _FETCHED}
    )
    pq.write_table(pa.Table.from_pylist(rows), status_path)
    slices = list(query_daily_facts(lake, as_of=AS_OF, start=START, codes=["600002"]))
    assert any(
        item.reason == "SUSPENDED_BY_STATUS"
        for slice_ in slices
        for item in slice_.missing_required_bars
    )
    valid = [r for slice_ in slices for r in slice_.rows if r.row_status == "VALID_ROW"]
    # 6/11 is the first row (no predecessor) -> MISSING_PRECLOSE; only 6/12
    # is VALID, and the 6/15 session is authorized as suspended.
    assert {r.trade_date for r in valid} == {date(2026, 6, 12)}


# --- I: AS_OF scope semantics ----------------------------------------------

def test_query_asof_scope(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    scope = set(query_asof_scope(lake, AS_OF))
    assert scope == {"000001", "000010", "000524", "605198"}
    assert "300750" not in scope
    assert "600000" not in scope  # delisted before AS_OF
    assert "600001" not in scope  # listed after AS_OF
    assert "600002" not in scope  # no AS_OF bar
    assert "600003" not in scope  # zero-volume AS_OF bar


# --- J: query facts == physical facts on the synthetic lake ---------------

def _normalize(rows) -> list[tuple]:
    out = []
    for row in sorted(rows, key=lambda r: (r.code, r.trade_date)):
        out.append(
            (
                row.code, row.trade_date,
                str(row.open), str(row.high), str(row.low), str(row.close),
                str(row.preclose), str(row.volume), str(row.amount),
                str(row.pct_change), row.trade_status, row.is_st,
            )
        )
    return out


def test_query_facts_equal_physical_facts(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    query_rows = [
        row
        for row in _query_rows(lake, CODES)
        if row.row_status == "VALID_ROW"
    ]
    physical = load_asl_daily_slice(
        lake, as_of=AS_OF, start=START, codes=CODES
    )
    physical_rows = [
        row for row in physical.rows if row.row_status == "VALID_ROW"
    ]
    assert _normalize(query_rows) == _normalize(physical_rows)


# --- K: candidate snapshot through the QUERY path --------------------------

def test_query_candidate_snapshot_contract(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    layout = _layout(tmp_path)
    snapshot = build_asl_candidate_snapshot(
        layout=layout, asl_root=lake, as_of=AS_OF, codes=CODES, start=START,
    )
    assert snapshot.status == "CURRENT"
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(snapshot.snapshot_id)
        rows = read_snapshot_daily(layout, stored)
        pool = read_snapshot_pool(layout, stored)
    assert rows
    assert {row["selected_provider"] for row in rows} == {"ASL"}
    assert {row["reconciliation_status"] for row in rows} == {"CONFIRMED"}
    assert all(row["turnover_rate"] is None for row in rows)
    assert pool == []
    result = data_validate(layout, snapshot_id=snapshot.snapshot_id)
    assert result.valid is True
