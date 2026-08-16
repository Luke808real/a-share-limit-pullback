"""Tushare bulk daily coverage fail-closed — targeted tests.

Covers the silent-empty-as-success defect found in the July 2026 session
coverage audit:
  1. bulk fetch returns D1,D3 for requested [D1,D2,D3]
     -> D1/D3 COMPLETED, D2 NOT completed, D2 PENDING failure
  2. whole bulk batch returns [] -> no requested date completed, every
     requested date failure
  3. resume: already-good dates skipped, missing D2 remains retryable
  4. pipeline: missing TUSHARE daily expected session -> no create_snapshot,
     run NOT COMPLETED
  5. pipeline: historical COMPLETED run with coverage hole -> reuse fails
     closed (COMPLETED_RUN_DAILY_COVERAGE_INVALID)
  6. aux dataset empty result -> existing behavior unchanged
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from limit_pullback.warehouse.fetch import FetchContext, fetch_rows
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.pipeline import (
    PipelineError,
    _tushare_daily_missing_sessions,
    bootstrap,
)
from tests.warehouse_fakes import FakeProviderSet, daily_row


def _layout(tmp_path) -> WarehouseLayout:
    return WarehouseLayout(tmp_path / "data")


def _clock() -> datetime:
    return datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


D1 = date(2026, 7, 9)
D2 = date(2026, 7, 10)
D3 = date(2026, 7, 13)


def _daily(code: str, day: date) -> dict:
    return daily_row(code, day.isoformat())


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _fetch_attempt(layout, run_id, bulk_fn, dates):
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        ctx = FetchContext(
            layout=layout,
            metadata=metadata,
            run_id=run_id,
            clock=_clock,
            versions={"TUSHARE": "test"},
            batch_rows=20000,
            retries=0,
            backoff_seconds=0.0,
        )
        fetch_rows(
            ctx,
            provider="TUSHARE",
            dataset="daily_bars",
            items=dates,
            bulk_fn=bulk_fn,
            use_bulk=True,
            item_is_date=True,
            require_date_presence=True,
            batch_size=20,
            return_rows=False,
        )
        completed = metadata.completed_progress_codes(run_id=run_id, provider="TUSHARE", dataset="daily_bars")
        failures = metadata.pending_failures(run_id)
        return completed, failures


# ---------- 1. partial batch completion ----------

def test_partial_bulk_batch_marks_only_present_dates_completed(tmp_path) -> None:
    layout = _layout(tmp_path)
    rows = [_daily("600000", D1), _daily("600000", D3)]  # D2 missing

    def bulk(dates):
        wanted = set(dates)
        return [r for r in rows if r["trade_date"] in wanted]

    completed, failures = _fetch_attempt(layout, "run-partial", bulk, [D1, D2, D3])
    assert f"DATE:{D1.isoformat()}" in completed
    assert f"DATE:{D3.isoformat()}" in completed
    assert f"DATE:{D2.isoformat()}" not in completed  # the core contract
    def _as_date2(v):
        return v if isinstance(v, date) else date.fromisoformat(str(v))
    d2_failures = [f for f in failures if f.get("trade_date") is not None and _as_date2(f.get("trade_date")) == D2]
    assert d2_failures
    assert all(f["error"] == "EMPTY_BULK_DATE_RESULT" for f in d2_failures)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        rows = metadata._connection.execute(
            "SELECT status FROM ingest_failures WHERE run_id = ? AND trade_date = ?",
            ["run-partial", D2.isoformat()],
        ).fetchall()
        assert rows
        assert all(row[0] == "PENDING" for row in rows)


# ---------- 2. whole batch empty ----------

def test_empty_bulk_batch_fails_every_requested_date(tmp_path) -> None:
    layout = _layout(tmp_path)

    def bulk(dates):  # noqa: ARG001
        return []

    completed, failures = _fetch_attempt(layout, "run-empty", bulk, [D1, D2, D3])
    assert not completed  # nothing completed
    def _as_date(v):
        return v if isinstance(v, date) else date.fromisoformat(str(v))
    assert {_as_date(f["trade_date"]) for f in failures} == {D1, D2, D3}
    assert all(f["error"] == "EMPTY_BULK_DATE_RESULT" for f in failures)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        rows = metadata._connection.execute(
            "SELECT status FROM ingest_failures WHERE run_id = ?", ["run-empty"]
        ).fetchall()
        assert rows
        assert all(row[0] == "PENDING" for row in rows)


# ---------- 3. resume ----------

def test_resume_skips_good_dates_and_retries_missing(tmp_path) -> None:
    layout = _layout(tmp_path)
    run_id = "run-resume"
    rows_all = [_daily("600000", D1), _daily("600000", D2), _daily("600000", D3)]

    def bulk_partial(dates):
        wanted = set(dates)
        return [r for r in rows_all if r["trade_date"] in wanted and r["trade_date"] != D2]

    def bulk_full(dates):
        wanted = set(dates)
        return [r for r in rows_all if r["trade_date"] in wanted]

    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.begin_ingest_run(
            run_id=run_id, kind="bootstrap",
            started_at=_clock(),
            start_date=D1, end_date=D3, codes=(), config_json="{}",
        )
    completed1, failures1 = _fetch_attempt(layout, run_id, bulk_partial, [D1, D2, D3])
    assert f"DATE:{D2.isoformat()}" not in completed1
    assert len([f for f in failures1 if _as_date(f["trade_date"]) == D2]) == 1

    # second attempt: D1/D3 already completed -> skipped; D2 retried
    completed2, failures2 = _fetch_attempt(layout, run_id, bulk_full, [D1, D2, D3])
    assert f"DATE:{D2.isoformat()}" in completed2
    # no remaining PENDING failure for D2 (record resolved by _mark)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        rows = metadata._connection.execute(
            "SELECT status FROM ingest_failures WHERE run_id = ? AND trade_date = ?",
            [run_id, D2.isoformat()],
        ).fetchall()
        assert rows
        assert all(row[0] == "RESOLVED" for row in rows)


# ---------- 4. pre-snapshot coverage gate (pipeline) ----------

def test_missing_tushare_daily_session_blocks_snapshot(tmp_path) -> None:
    layout = _layout(tmp_path)
    days = [D1, D2, D3]
    codes = tuple(f"600{i:03d}" for i in range(250))
    rows = [daily_row(code, day.isoformat()) for code in codes for day in days]
    pool = [
        {
            "code": code,
            "trade_date": D3,
            "name": "n",
            "limit_price": daily_row(code, D3.isoformat())["close"],
            "first_seal_time": None,
            "last_seal_time": None,
            "open_count": 0,
            "consecutive_count": 1,
            "turnover_rate": None,
            "float_market_cap": None,
            "total_market_cap": None,
            "industry": "x",
        }
        for code in codes
    ]

    class GapFake(FakeProviderSet):
        def fetch_tushare_daily_by_trade_date(self, dates):
            wanted = set(dates)
            return [
                dict(row)
                for row in self.tushare_daily
                if row["trade_date"] in wanted and row["trade_date"] != D2
            ]

    fake = GapFake(
        calendar=days,
        tushare_daily=rows,
        akshare_daily=rows,
        baostock_daily=rows,
        pool=pool,
    )
    with pytest.raises(PipelineError, match="missing 1 TUSHARE daily sessions"):
        bootstrap(
            layout=layout,
            start=days[0],
            end=days[-1],
            codes=codes,
            provider_set=fake,
            today=days[-1],
            bulk_threshold=200,
        )
    # no COMPLETED ingest run
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        runs = metadata._connection.execute(
            "SELECT status FROM ingest_runs"
        ).fetchall()
        assert runs
        assert all(row[0] != "COMPLETED" for row in runs)


# ---------- 5. completed-run reuse gate (pipeline) ----------

def test_completed_run_reuse_blocked_on_coverage_hole(tmp_path) -> None:
    layout = _layout(tmp_path)
    days = [D1, D2, D3]
    codes = tuple(f"600{i:03d}" for i in range(250))
    rows = [daily_row(code, day.isoformat()) for code in codes for day in days]
    pool = [
        {
            "code": code,
            "trade_date": D3,
            "name": "n",
            "limit_price": daily_row(code, D3.isoformat())["close"],
            "first_seal_time": None,
            "last_seal_time": None,
            "open_count": 0,
            "consecutive_count": 1,
            "turnover_rate": None,
            "float_market_cap": None,
            "total_market_cap": None,
            "industry": "x",
        }
        for code in codes
    ]
    fake = FakeProviderSet(
        calendar=days,
        tushare_daily=rows,
        akshare_daily=rows,
        baostock_daily=rows,
        pool=pool,
    )
    first = bootstrap(
        layout=layout,
        start=days[0],
        end=days[-1],
        codes=codes,
        provider_set=fake,
        today=days[-1],
        bulk_threshold=200,
    )
    assert first.reused is False
    assert first.snapshot_id is not None
    assert first.pending_failures == 0

    # simulate a historical COMPLETED run whose TUSHARE daily raw files now
    # lack one requested session (the silent-empty scenario retroactively)
    missing = _tushare_daily_missing_sessions(layout, first.run_id, days)
    assert missing == []
    import pyarrow as pa
    import pyarrow.parquet as pq
    from pathlib import Path
    tushare_dir = layout.raw_dataset_dir("TUSHARE", "daily_bars")
    for path in sorted(tushare_dir.glob(f"{first.run_id}-*.parquet")):
        table = pq.read_table(path)
        df = table.to_pandas()
        df = df[df["trade_date"].astype(str) != D2.isoformat()]
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path)

    # reuse must fail closed instead of returning the old snapshot
    with pytest.raises(PipelineError, match="TUSHARE daily session coverage hole"):
        bootstrap(
            layout=layout,
            start=days[0],
            end=days[-1],
            codes=codes,
            provider_set=fake,
            today=days[-1],
            bulk_threshold=200,
        )


# ---------- 6. aux empty result unchanged ----------

def test_aux_empty_result_keeps_existing_semantics(tmp_path) -> None:
    layout = _layout(tmp_path)
    days = [D1, D2, D3]
    codes = tuple(f"600{i:03d}" for i in range(250))
    rows = [daily_row(code, day.isoformat()) for code in codes for day in days]
    pool = [
        {
            "code": code,
            "trade_date": D3,
            "name": "n",
            "limit_price": daily_row(code, D3.isoformat())["close"],
            "first_seal_time": None,
            "last_seal_time": None,
            "open_count": 0,
            "consecutive_count": 1,
            "turnover_rate": None,
            "float_market_cap": None,
            "total_market_cap": None,
            "industry": "x",
        }
        for code in codes
    ]

    class EmptyAuxFake(FakeProviderSet):
        def fetch_tushare_suspension(self, requested, start, end):
            return []  # legitimately empty aux dataset

        def fetch_tushare_suspension_by_trade_date(self, dates):
            return []

    fake = EmptyAuxFake(
        calendar=days,
        tushare_daily=rows,
        akshare_daily=rows,
        baostock_daily=rows,
        pool=pool,
    )
    result = bootstrap(
        layout=layout,
        start=days[0],
        end=days[-1],
        codes=codes,
        provider_set=fake,
        today=days[-1],
        bulk_threshold=200,
    )
    assert result.snapshot_id is not None
    assert result.pending_failures == 0
