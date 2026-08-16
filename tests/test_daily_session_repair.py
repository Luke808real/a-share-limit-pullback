"""Bounded daily-session repair pipeline — targeted offline tests.

Proves the fail-closed contract of ``repair_daily_sessions``:

* the repair fetches ONLY the explicit repair dates from TUSHARE and never
  calls the AKSHARE/BAOSTOCK fetchers (parent raw rows are reused read-only);
* a partial TUSHARE batch (consensus codes not covered) is blocked — per
  date, not as a cross-date union;
* a missing parent AKSHARE/BAOSTOCK population on any repair date is blocked;
* a successful repair publishes a RESEARCH_READY snapshot composed of base
  daily minus repair dates plus repaired rows, with pool rows unchanged;
* snapshot provenance is the union of base + verified parent + new TUSHARE
  source hashes, and tampered parent files fail closed;
* the repair snapshot as_of is frozen to the base snapshot as_of;
* the base snapshot and parent run lineage are untouched;
* the run identity is deterministic and a completed repair is always reused
  (no force_finalize in-place rewrite path);
* the composed snapshot has no duplicate (code, trade_date) keys;
* a repair date with zero CONFIRMED rows fails closed;
* per-date audit numbers (TS_N/AK_N/BS_N/CONSENSUS_N/...) are reported.
"""

from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.pipeline import (
    PipelineError,
    _repair_snapshot_for_run,
    _run_id,
    bootstrap,
    repair_daily_sessions,
)
from limit_pullback.warehouse.snapshot import (
    read_snapshot_daily,
    read_snapshot_pool,
)
from tests.warehouse_fakes import FakeProviderSet, daily_row

DAY = date(2026, 7, 31)
D20 = date(2026, 7, 20)
D21 = date(2026, 7, 21)
D22 = date(2026, 7, 22)
D23 = date(2026, 7, 23)
D24 = date(2026, 7, 24)
CALENDAR = [D20, D21, D22, D23, D24]
REPAIR_DATES = [D22, D24]
NON_REPAIR = [D20, D21, D23]
CODES = ("600000", "600001")
POLICY = "phase-2c2a-r1"


def _layout(tmp_path) -> WarehouseLayout:
    return WarehouseLayout(tmp_path / "data")


def _rows_for(codes: tuple[str, ...], days: list[date]) -> list[dict]:
    rows = []
    for code in codes:
        for day in days:
            rows.append(daily_row(code, day.isoformat()))
    return rows


def _base_bootstrap(
    layout: WarehouseLayout,
    *,
    codes: tuple[str, ...] = CODES,
    pool: list[dict] | None = None,
    tushare_missing_days: list[date] | None = None,
    akshare_days: list[date] | None = None,
    baostock_days: list[date] | None = None,
) -> tuple[str, str]:
    """Build the parent run + base snapshot.

    Mirrors the real July failure shape: TUSHARE has NO rows on the repair
    dates (so those sessions are PROVISIONAL from AKSHARE/BAOSTOCK only),
    while AKSHARE/BAOSTOCK cover the full window (override per provider when
    modeling a missing parent provider).
    """
    missing = set(tushare_missing_days or REPAIR_DATES)
    tushare_days = [d for d in CALENDAR if d not in missing]
    fake = FakeProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(codes, tushare_days),
        akshare_daily=_rows_for(codes, akshare_days or CALENDAR),
        baostock_daily=_rows_for(codes, baostock_days or CALENDAR),
        pool=pool or [],
    )
    result = bootstrap(
        layout=layout,
        start=CALENDAR[0],
        end=CALENDAR[-1],
        codes=codes,
        provider_set=fake,
        today=DAY,
    )
    return result.run_id, result.snapshot_id


class RecordingProviderSet(FakeProviderSet):
    """FakeProviderSet that records which fetches the repair pipeline asks for."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.date_requests: list[list[date]] = []
        self.akshare_daily_calls = 0
        self.baostock_daily_calls = 0

    def fetch_tushare_daily_by_trade_date(self, dates: list[date]):
        self.date_requests.append(list(dates))
        return super().fetch_tushare_daily_by_trade_date(dates)

    def fetch_tushare_daily_basic_by_trade_date(self, dates: list[date]):
        self.date_requests.append(list(dates))
        return super().fetch_tushare_daily_basic_by_trade_date(dates)

    def fetch_tushare_adj_factor_by_trade_date(self, dates: list[date]):
        self.date_requests.append(list(dates))
        return super().fetch_tushare_adj_factor_by_trade_date(dates)

    def fetch_akshare_daily(self, codes, start, end):
        self.akshare_daily_calls += 1
        return super().fetch_akshare_daily(codes, start, end)

    def fetch_baostock_daily(self, codes, start, end):
        self.baostock_daily_calls += 1
        return super().fetch_baostock_daily(codes, start, end)


# ---------- 1. bounded fetch: repair dates only, no AK/BS fetcher calls ----------

def test_repair_fetch_is_bounded_to_repair_dates(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(CODES, REPAIR_DATES),
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=repair_provider,
        today=DAY,
        repair_lineage="july-2026-gap-v01",
    )
    assert result.reused is False
    assert result.snapshot_id is not None

    # every TUSHARE date request must be a subset of the repair dates
    requested = [d for batch in repair_provider.date_requests for d in batch]
    assert sorted(set(requested)) == REPAIR_DATES
    assert not any(d in NON_REPAIR for d in requested)
    # the repair never calls the AKSHARE/BAOSTOCK fetchers
    assert repair_provider.akshare_daily_calls == 0
    assert repair_provider.baostock_daily_calls == 0


# ---------- 2. partial TUSHARE batch blocked (consensus coverage gate) ----------

def test_repair_partial_tushare_batch_blocked(tmp_path) -> None:
    layout = _layout(tmp_path)
    codes = tuple(f"{600000 + i:06d}" for i in range(100))
    parent_run_id, base_snapshot_id = _base_bootstrap(layout, codes=codes)

    partial_codes = codes[:70]
    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(partial_codes, REPAIR_DATES),
        akshare_daily=_rows_for(codes, CALENDAR),
        baostock_daily=_rows_for(codes, CALENDAR),
    )
    with pytest.raises(PipelineError) as excinfo:
        repair_daily_sessions(
            layout=layout,
            base_snapshot_id=base_snapshot_id,
            parent_run_id=parent_run_id,
            repair_dates=REPAIR_DATES,
            provider_set=repair_provider,
            today=DAY,
            repair_lineage="july-2026-gap-v01",
        )
    assert excinfo.value.code == "REPAIR_TUSHARE_CONSENSUS_COVERAGE_INCOMPLETE"

    run_id = _run_id(
        "daily-session-repair",
        base_snapshot_id,
        parent_run_id,
        tuple(REPAIR_DATES),
        POLICY,
        "july-2026-gap-v01",
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        run = metadata.get_ingest_run(run_id)
        assert run is not None and run.status == "FAILED"
        assert _repair_snapshot_for_run(metadata, run_id) is None


# ---------- 3. successful composition ----------

def test_repair_successful_composition(tmp_path) -> None:
    layout = _layout(tmp_path)
    pool_rows = [
        {
            "code": CODES[0],
            "trade_date": day,
            "name": "TEST",
            "limit_price": Decimal("10.00"),
            "first_seal_time": "10:00:00",
            "last_seal_time": "14:00:00",
            "open_count": 1,
            "consecutive_count": 1,
            "turnover_rate": Decimal("1.00"),
            "float_market_cap": Decimal("1000000000"),
            "total_market_cap": Decimal("2000000000"),
            "industry": "TEST",
        }
        for day in CALENDAR
    ]
    parent_run_id, base_snapshot_id = _base_bootstrap(layout, pool=pool_rows)

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        base = metadata.snapshot_by_id(base_snapshot_id)
        assert base is not None
        base_daily = read_snapshot_daily(layout, base)
        base_pool = read_snapshot_pool(layout, base)
        base_by_key = {
            (str(row["code"]), row["trade_date"]): dict(row)
            for row in base_daily
        }
        base_repair_keys = {
            key for key in base_by_key if key[1] in REPAIR_DATES
        }
        # the modeled failure: base repair-date rows are PROVISIONAL only
        for key in base_repair_keys:
            assert base_by_key[key]["reconciliation_status"] == "PROVISIONAL"
        assert len(base_pool) == len(pool_rows)
        pool_before = [dict(row) for row in base_pool]

    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(CODES, REPAIR_DATES),
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=repair_provider,
        today=DAY,
        repair_lineage="july-2026-gap-v01",
    )
    assert result.reused is False
    assert result.base_row_n == len(base_daily)
    assert result.repaired_row_n == len(base_repair_keys)
    assert result.confirmed_n == len(base_repair_keys)
    assert result.provisional_n == 0
    assert result.quarantine_n == 0

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        repaired = metadata.snapshot_by_id(result.snapshot_id)
        assert repaired is not None
        assert repaired.status == "RESEARCH_READY"
        assert repaired.as_of == base.as_of

        new_daily = read_snapshot_daily(layout, repaired)
        new_pool = read_snapshot_pool(layout, repaired)
        new_by_key = {
            (str(row["code"]), row["trade_date"]): dict(row)
            for row in new_daily
        }

    # non-repair dates unchanged, byte-for-byte
    for key, row in base_by_key.items():
        if key[1] in REPAIR_DATES:
            continue
        new_row = new_by_key[key]
        for field, value in row.items():
            if field == "dataset_snapshot_id":
                continue
            assert new_row[field] == value, f"{key} field {field} changed"

    # repair dates replaced: PROVISIONAL -> CONFIRMED (TUSHARE selected)
    for key in base_repair_keys:
        new_row = new_by_key[key]
        assert new_row["reconciliation_status"] == "CONFIRMED"
        assert new_row["selected_provider"] == "TUSHARE"
        assert base_by_key[key]["selected_provider"] == "AKSHARE"

    # pool rows carried over unchanged (dataset_snapshot_id is re-stamped)
    def _strip_snapshot_id(rows: list[dict]) -> list[dict]:
        return [
            {k: v for k, v in dict(row).items() if k != "dataset_snapshot_id"}
            for row in rows
        ]

    assert _strip_snapshot_id(new_pool) == _strip_snapshot_id(pool_before)
    assert len(new_pool) == len(pool_before)
    # exact row-count composition: base - repair dates + repaired
    assert len(new_daily) == len(base_daily) - len(base_repair_keys) + result.repaired_row_n


# ---------- 4. old lineage untouched ----------

def test_repair_does_not_touch_base_or_parent_lineage(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        base = metadata.snapshot_by_id(base_snapshot_id)
        parent = metadata.get_ingest_run(parent_run_id)
        assert base is not None and parent is not None
        base_before = (
            base.status,
            base.as_of,
            base.created_at,
            dict(base.source_file_hashes),
            dict(base.canonical_file_hashes),
        )
        parent_before = (
            parent.status,
            parent.started_at,
            parent.finished_at,
            parent.error,
            parent.codes,
            parent.config_json,
        )

    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(CODES, REPAIR_DATES),
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=repair_provider,
        today=DAY,
        repair_lineage="july-2026-gap-v01",
    )

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        base_after = metadata.snapshot_by_id(base_snapshot_id)
        parent_after = metadata.get_ingest_run(parent_run_id)
        assert base_after is not None and parent_after is not None
        assert (
            base_after.status,
            base_after.as_of,
            base_after.created_at,
            dict(base_after.source_file_hashes),
            dict(base_after.canonical_file_hashes),
        ) == base_before
        assert (
            parent_after.status,
            parent_after.started_at,
            parent_after.finished_at,
            parent_after.error,
            parent_after.codes,
            parent_after.config_json,
        ) == parent_before


# ---------- 5. deterministic identity + completed-run reuse ----------

def test_repair_deterministic_and_reused(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    def run_repair() -> object:
        repair_provider = RecordingProviderSet(
            calendar=CALENDAR,
            tushare_daily=_rows_for(CODES, REPAIR_DATES),
            akshare_daily=_rows_for(CODES, CALENDAR),
            baostock_daily=_rows_for(CODES, CALENDAR),
        )
        return repair_daily_sessions(
            layout=layout,
            base_snapshot_id=base_snapshot_id,
            parent_run_id=parent_run_id,
            repair_dates=REPAIR_DATES,
            provider_set=repair_provider,
            today=DAY,
            repair_lineage="july-2026-gap-v01",
        )

    first = run_repair()
    second = run_repair()
    assert first.reused is False
    assert second.reused is True
    assert first.run_id == second.run_id
    assert first.snapshot_id == second.snapshot_id
    assert first.snapshot_id is not None
    # deterministic run identity per the documented expression
    expected = _run_id(
        "daily-session-repair",
        base_snapshot_id,
        parent_run_id,
        tuple(REPAIR_DATES),
        POLICY,
        "july-2026-gap-v01",
    )
    assert first.run_id == expected


# ---------- 6. no duplicate (code, trade_date) in the composed snapshot ----------

def test_repair_composed_snapshot_has_no_duplicate_keys(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(CODES, REPAIR_DATES),
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=repair_provider,
        today=DAY,
        repair_lineage="july-2026-gap-v01",
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        repaired = metadata.snapshot_by_id(result.snapshot_id)
        assert repaired is not None
        new_daily = read_snapshot_daily(layout, repaired)
    keys = [(str(row["code"]), row["trade_date"]) for row in new_daily]
    assert len(keys) == len(set(keys))
    # every repair-date key appears exactly once
    for code in CODES:
        for day in REPAIR_DATES:
            assert keys.count((code, day)) == 1


# ---------- 7. per-date CONFIRMED gate fails closed ----------

def test_repair_date_without_confirmed_row_fails_closed(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    # TUSHARE covers both codes on repair dates but with prices that CONFLICT
    # with the parent AKSHARE rows -> everything quarantines; no CONFIRMED row
    conflicting = [
        daily_row(code, day.isoformat(), open_price="90.00", high="95.00",
                  low="88.00", close="92.00", preclose="89.00")
        for code in CODES
        for day in REPAIR_DATES
    ]
    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=conflicting,
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    with pytest.raises(PipelineError) as excinfo:
        repair_daily_sessions(
            layout=layout,
            base_snapshot_id=base_snapshot_id,
            parent_run_id=parent_run_id,
            repair_dates=REPAIR_DATES,
            provider_set=repair_provider,
            today=DAY,
            repair_lineage="july-2026-gap-v01",
        )
    assert excinfo.value.code == "REPAIR_DATE_NO_CONFIRMED"


# ---------- 8. per-date breadth gate: cross-date union must NOT pass ----------

def test_repair_per_date_gap_fails_closed(tmp_path) -> None:
    """Regression for the union-gate hole: code X is missing from TUSHARE on
    D22 but present on D24. The old cross-date union gate passed (X existed
    somewhere); the frozen per-date contract must fail on D22."""
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    tushare_rows = _rows_for((CODES[0],), [D22]) + _rows_for(CODES, [D24])
    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=tushare_rows,
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    with pytest.raises(PipelineError) as excinfo:
        repair_daily_sessions(
            layout=layout,
            base_snapshot_id=base_snapshot_id,
            parent_run_id=parent_run_id,
            repair_dates=REPAIR_DATES,
            provider_set=repair_provider,
            today=DAY,
            repair_lineage="july-2026-gap-v01",
        )
    assert excinfo.value.code == "REPAIR_TUSHARE_CONSENSUS_COVERAGE_INCOMPLETE"
    assert D22.isoformat() in str(excinfo.value)

    run_id = _run_id(
        "daily-session-repair",
        base_snapshot_id,
        parent_run_id,
        tuple(REPAIR_DATES),
        POLICY,
        "july-2026-gap-v01",
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        run = metadata.get_ingest_run(run_id)
        assert run is not None and run.status == "FAILED"
        assert _repair_snapshot_for_run(metadata, run_id) is None


# ---------- 9. missing parent provider population blocked per date ----------

def test_repair_missing_parent_provider_date_coverage_fails_closed(tmp_path) -> None:
    """Blocker 2 regression: AKSHARE missing entirely on D24 (present on D22)
    must fail closed even though TUSHARE+AKSHARE could still confirm D22."""
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(
        layout, akshare_days=[D20, D21, D22, D23]
    )

    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(CODES, REPAIR_DATES),
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    with pytest.raises(PipelineError) as excinfo:
        repair_daily_sessions(
            layout=layout,
            base_snapshot_id=base_snapshot_id,
            parent_run_id=parent_run_id,
            repair_dates=REPAIR_DATES,
            provider_set=repair_provider,
            today=DAY,
            repair_lineage="july-2026-gap-v01",
        )
    assert excinfo.value.code == "REPAIR_PARENT_PROVIDER_DATE_COVERAGE_INCOMPLETE"
    assert D24.isoformat() in str(excinfo.value)


# ---------- 10. snapshot provenance union ----------

def test_repair_snapshot_provenance_is_union_of_all_sources(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        base = metadata.snapshot_by_id(base_snapshot_id)
        assert base is not None
        parent_files = metadata._connection.execute(
            "SELECT path, sha256 FROM source_files "
            "WHERE ingest_run_id = ? AND path LIKE '%/daily_bars/%'",
            [parent_run_id],
        ).fetchall()
        parent_hashes = {
            str(Path(path).relative_to(layout.root)): sha
            for path, sha in parent_files
        }

    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(CODES, REPAIR_DATES),
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=repair_provider,
        today=DAY,
        repair_lineage="july-2026-gap-v01",
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        repaired = metadata.snapshot_by_id(result.snapshot_id)
        assert repaired is not None
        hashes = dict(repaired.source_file_hashes)

    # union must contain every base source with the same digest
    for key, sha in base.source_file_hashes.items():
        assert hashes.get(key) == sha, f"base source {key} missing from provenance"
    # every verified parent AK/BS file must be traceable
    for key, sha in parent_hashes.items():
        assert hashes.get(key) == sha, f"parent source {key} missing from provenance"
    # new repair-run TUSHARE files must be present
    repair_keys = [
        key for key in hashes if f"/{result.run_id}-" in key
    ]
    assert any("/tushare/daily_bars/" in key.lower() for key in repair_keys)


# ---------- 11. tampered parent raw fails closed ----------

def test_repair_tampered_parent_raw_fails_closed(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        path_value = metadata._connection.execute(
            "SELECT path FROM source_files "
            "WHERE ingest_run_id = ? AND provider = 'AKSHARE' "
            "AND path LIKE '%/daily_bars/%' LIMIT 1",
            [parent_run_id],
        ).fetchone()[0]
    path = Path(path_value)
    path.write_bytes(path.read_bytes() + b"tampered")

    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(CODES, REPAIR_DATES),
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    with pytest.raises(PipelineError) as excinfo:
        repair_daily_sessions(
            layout=layout,
            base_snapshot_id=base_snapshot_id,
            parent_run_id=parent_run_id,
            repair_dates=REPAIR_DATES,
            provider_set=repair_provider,
            today=DAY,
            repair_lineage="july-2026-gap-v01",
        )
    assert excinfo.value.code == "REPAIR_PARENT_RAW_SHA_MISMATCH"


# ---------- 12. as_of frozen to base.as_of ----------

def test_repair_as_of_frozen_to_base(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        base = metadata.snapshot_by_id(base_snapshot_id)
        assert base is not None

    # repair date beyond base.as_of must fail closed before any side effect
    beyond = [D24, date(2026, 7, 25)]
    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(CODES, beyond),
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    with pytest.raises(PipelineError) as excinfo:
        repair_daily_sessions(
            layout=layout,
            base_snapshot_id=base_snapshot_id,
            parent_run_id=parent_run_id,
            repair_dates=beyond,
            provider_set=repair_provider,
            today=DAY,
            repair_lineage="july-2026-gap-v01",
        )
    assert excinfo.value.code == "REPAIR_DATE_BEYOND_BASE_AS_OF"

    # successful repair keeps as_of == base.as_of exactly
    repair_provider2 = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(CODES, REPAIR_DATES),
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=repair_provider2,
        today=DAY,
        repair_lineage="july-2026-gap-v02",
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        repaired = metadata.snapshot_by_id(result.snapshot_id)
        assert repaired is not None
        assert repaired.as_of == base.as_of


# ---------- 13. no force_finalize / as_of override surface ----------

def test_repair_api_has_no_force_finalize_or_as_of_override(tmp_path) -> None:
    parameters = inspect.signature(repair_daily_sessions).parameters
    assert "force_finalize" not in parameters
    assert "as_of" not in parameters


# ---------- 14. per-date audit numbers ----------

def test_repair_per_date_stats_reported(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    repair_provider = RecordingProviderSet(
        calendar=CALENDAR,
        tushare_daily=_rows_for(CODES, REPAIR_DATES),
        akshare_daily=_rows_for(CODES, CALENDAR),
        baostock_daily=_rows_for(CODES, CALENDAR),
    )
    result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=repair_provider,
        today=DAY,
        repair_lineage="july-2026-gap-v01",
    )
    assert [s.trade_date for s in result.per_date_stats] == REPAIR_DATES
    for stats in result.per_date_stats:
        assert stats.ts_n == 2
        assert stats.ak_n == 2
        assert stats.bs_n == 2
        assert stats.consensus_n == 2
        assert stats.ts_coverage_of_consensus == 2
        assert stats.base_row_n == 2
        assert stats.repaired_row_n == 2
        assert stats.confirmed_n == 2
        assert stats.provisional_n == 0
        assert stats.quarantine_n == 0
    # totals agree with the aggregate result fields
    assert sum(s.repaired_row_n for s in result.per_date_stats) == result.repaired_row_n
    assert sum(s.confirmed_n for s in result.per_date_stats) == result.confirmed_n
