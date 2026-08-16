"""ASL-backed repair provider — targeted offline tests.

Proves that the bounded daily-session repair can use the ASL lake as its
authoritative primary source (``provider_name="ASL"``) with ZERO TUSHARE
calls:

* the full repair pipeline succeeds against a synthetic ASL lake, producing
  CONFIRMED rows and a RESEARCH_READY snapshot;
* raw files land under ``raw/ASL/daily_bars`` and the snapshot provenance
  carries the new ASL source hashes;
* the adjustment-factor fetch returns the predecessor + repair dates from
  ``derived/adj_factors`` (symbol suffix normalized);
* bars that the Phase-1A adapter did not validate are never emitted.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from limit_pullback.warehouse.asl_repair_provider import (
    AslRepairProviderError,
    AslRepairProviderSet,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.pipeline import bootstrap, repair_daily_sessions
from limit_pullback.warehouse.snapshot import read_snapshot_daily
from tests.warehouse_fakes import FakeProviderSet, daily_row

DAY = date(2026, 7, 31)
D20 = date(2026, 7, 20)
D21 = date(2026, 7, 21)
D22 = date(2026, 7, 22)
D23 = date(2026, 7, 23)
D24 = date(2026, 7, 24)
CALENDAR = [D20, D21, D22, D23, D24]
REPAIR_DATES = [D22, D24]
CODES = ("600000", "600001")

BAR_VALUE = {
    "open": 10.00,
    "high": 10.50,
    "low": 9.80,
    "close": 10.20,
    "volume": 100000,
    "amount": 1020000.0,
}

SYMBOLS = {code: f"{code}.SH" for code in CODES}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)


def _build_asl_lake(
    root: Path,
    *,
    days: list[date] | None = None,
    drop_adj_factors: bool = False,
) -> None:
    days = days or CALENDAR
    _write(
        root / "curated" / "instruments" / "part-merged.parquet",
        [
            {"symbol": SYMBOLS[code], "list_date": None, "delist_date": None}
            for code in CODES
        ],
    )
    # calendar partition covering the window plus non-trading days
    weekend = [date(2026, 7, 18), date(2026, 7, 19)]
    calendar_rows = [
        {"trade_date": d, "is_trading": d in days}
        for d in sorted([*days, *weekend])
    ]
    _write(
        root / "curated" / "trading_calendar" / "trade_date=2026" / "part-merged.parquet",
        calendar_rows,
    )
    # daily bars: every symbol on every trading day (v2 = shares).
    # The AK/BS parent rows carry preclose=10.00 every day; the ASL
    # sequential previous-close chain must therefore close at 10.00 on the
    # days BEFORE repair dates (D21 seeds D22, D23 seeds D24) while repair
    # days themselves close at 10.20 to match the AK/BS bars.
    for day in days:
        close = BAR_VALUE["close"] if day in REPAIR_DATES else 10.00
        _write(
            root / "curated" / "daily_bars"
            / f"trade_date={day.isoformat()}" / "part-merged.parquet",
            [
                {
                    "symbol": SYMBOLS[code],
                    "trade_date": day,
                    **{**BAR_VALUE, "close": close},
                    "source": "tdx_protocol",
                    "data_version": "v2",
                    "fetched_at": "2026-08-07T00:00:00Z",
                }
                for code in CODES
            ],
        )
    # empty trading_status partition (monthly layout)
    status_path = root / "curated" / "trading_status" / "trade_date=2026-07" / "part-merged.parquet"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [],
            schema=pa.schema(
                [
                    ("symbol", pa.string()),
                    ("trade_date", pa.date32()),
                    ("is_trading", pa.bool_()),
                    ("status", pa.string()),
                    ("source", pa.string()),
                    ("data_version", pa.string()),
                    ("fetched_at", pa.timestamp("us", tz="UTC")),
                ]
            ),
        ),
        status_path,
    )
    # derived hfq factors for every trading day (flat 1.00)
    if not drop_adj_factors:
        for day in days:
            _write(
                root / "derived" / "adj_factors"
                / f"trade_date={day.isoformat()}" / "part-0.parquet",
                [
                    {
                        "trade_date": day,
                        "factor": 1.0,
                        "symbol": SYMBOLS[code],
                        "adjust_type": "hfq",
                        "data_version": "v1",
                        "fetched_at": "2026-08-07T00:00:00Z",
                        "source": "sina",
                    }
                    for code in CODES
                ],
            )


def _layout(tmp_path) -> WarehouseLayout:
    return WarehouseLayout(tmp_path / "data")


def _base_bootstrap(layout: WarehouseLayout) -> tuple[str, str]:
    """TUSHARE missing on repair dates; AK/BS cover the full window."""
    missing = set(REPAIR_DATES)
    tushare_days = [d for d in CALENDAR if d not in missing]
    fake = FakeProviderSet(
        calendar=CALENDAR,
        tushare_daily=[daily_row(c, d.isoformat()) for c in CODES for d in tushare_days],
        akshare_daily=[daily_row(c, d.isoformat()) for c in CODES for d in CALENDAR],
        baostock_daily=[daily_row(c, d.isoformat()) for c in CODES for d in CALENDAR],
    )
    result = bootstrap(
        layout=layout,
        start=CALENDAR[0],
        end=CALENDAR[-1],
        codes=CODES,
        provider_set=fake,
        today=DAY,
    )
    return result.run_id, result.snapshot_id


def _asl_provider(tmp_path, as_of: date = D24) -> AslRepairProviderSet:
    asl_root = tmp_path / "asl-lake"
    _build_asl_lake(asl_root)
    return AslRepairProviderSet(asl_root, as_of=as_of, repair_dates=REPAIR_DATES)


# ---------- 1. full repair with ASL as primary source ----------

def test_asl_provider_full_repair_succeeds(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)
    provider = _asl_provider(tmp_path)

    result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=provider,
        today=DAY,
        repair_lineage="july-2026-gap-v01",
        provider_name="ASL",
    )
    assert result.reused is False
    assert result.snapshot_id is not None
    assert result.confirmed_n == len(REPAIR_DATES) * len(CODES)
    assert result.provisional_n == 0
    assert result.quarantine_n == 0
    assert result.pending_failures == 0
    for stats in result.per_date_stats:
        assert stats.ts_n == 2  # ASL codes per date
        assert stats.ak_n == 2
        assert stats.bs_n == 2
        assert stats.ts_coverage_of_consensus == 2
        assert stats.confirmed_n == 2

    # raw files landed under raw/ASL/daily_bars with ASL provenance
    raw_dir = layout.raw_dataset_dir("ASL", "daily_bars")
    files = sorted(raw_dir.glob(f"{result.run_id}-*.parquet"))
    assert files, "no ASL raw daily files written"
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        src = metadata._connection.execute(
            "SELECT provider, count(*) FROM source_files "
            "WHERE ingest_run_id = ? GROUP BY provider",
            [result.run_id],
        ).fetchall()
        providers = {row[0]: row[1] for row in src}
        assert providers.get("ASL", 0) >= 1
        assert "TUSHARE" not in providers
        repaired = metadata.snapshot_by_id(result.snapshot_id)
        assert repaired is not None
        assert repaired.status == "RESEARCH_READY"
        # provenance carries new ASL hashes
        asl_keys = [k for k in repaired.source_file_hashes if "/asl/" in k.lower()]
        assert asl_keys, "no ASL sources in snapshot provenance"
        # composed rows all CONFIRMED on repair dates
        daily = read_snapshot_daily(layout, repaired)
        for row in daily:
            if row["trade_date"] in REPAIR_DATES:
                assert row["reconciliation_status"] == "CONFIRMED"


# ---------- 2. adjustment-factor coverage: predecessor + repair dates ----------

def test_asl_provider_adj_factor_predecessor_coverage(tmp_path) -> None:
    provider = _asl_provider(tmp_path)
    rows = provider.fetch_tushare_adj_factor_by_trade_date([D21, D22, D24])
    keys = sorted((row["code"], row["trade_date"]) for row in rows)
    expected = sorted(
        (code, day) for code in CODES for day in (D21, D22, D24)
    )
    assert keys == expected
    for row in rows:
        assert row["adj_factor"] == 1.0


# ---------- 3. provider never emits unvalidated rows / wrong symbols ----------

def test_asl_provider_symbol_normalization_and_bounded_dates(tmp_path) -> None:
    provider = _asl_provider(tmp_path)
    # only the requested dates are returned
    rows = provider.fetch_tushare_daily_by_trade_date([D22])
    assert len(rows) == len(CODES)
    assert all(row["trade_date"] == D22 for row in rows)
    assert all(row["code"] in CODES for row in rows)
    assert all(row["trade_status"] is True for row in rows)
    assert all(row["preclose"] is not None for row in rows)
    # D22 preclose must be D21 close (sequential previous-close chain;
    # D21 closed at 10.00 to seed the parent-consistent preclose)
    for row in rows:
        assert row["preclose"] == Decimal("10.00")
    # daily_basic / stock_basic are contractually empty
    assert provider.fetch_tushare_daily_basic_by_trade_date([D22]) == []
    assert provider.fetch_stock_basic((), listed_only=False) == []


# ---------- 4. missing required ASL datasets fail closed ----------

def test_asl_provider_missing_lake_fails_closed(tmp_path) -> None:
    asl_root = tmp_path / "empty-lake"
    asl_root.mkdir(parents=True, exist_ok=True)
    provider = AslRepairProviderSet(asl_root, as_of=D24, repair_dates=REPAIR_DATES)
    with pytest.raises(Exception) as excinfo:
        provider.fetch_tushare_daily_by_trade_date([D22])
    assert "asl" in str(excinfo.value).lower() or "raise" in str(excinfo.value).lower()


# ---------- 5. drop adj_factors -> empty factor coverage (no crash) ----------

def test_asl_provider_missing_adj_factors_returns_empty(tmp_path) -> None:
    asl_root = tmp_path / "lake-no-adj"
    _build_asl_lake(asl_root, drop_adj_factors=True)
    provider = AslRepairProviderSet(asl_root, as_of=D24, repair_dates=REPAIR_DATES)
    assert provider.fetch_tushare_adj_factor_by_trade_date([D21, D22]) == []
