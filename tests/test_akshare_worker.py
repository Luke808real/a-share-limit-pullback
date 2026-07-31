from __future__ import annotations

from datetime import date

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.pipeline import bootstrap
from tests.warehouse_fakes import FakeProviderSet, daily_row


def test_isolated_worker_crash_records_failures_and_continues(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    days = [date(2026, 7, 29), date(2026, 7, 30)]
    codes = ("600000", "600001", "600002", "600003")
    all_rows = [daily_row(code, day.isoformat()) for code in codes for day in days]
    fake = FakeProviderSet(
        calendar=days,
        tushare_daily=list(all_rows),
        akshare_daily=list(all_rows),
    )
    crash_codes = {"600001", "600002"}

    def fake_runner(*, mode, codes=None, dates=None, start=None, end=None):
        if mode == "pool":
            return []
        requested = set(codes or ())
        if mode == "daily" and requested & crash_codes:
            return None  # simulated native crash of the worker
        wanted = set(codes or ())
        return [
            dict(row)
            for row in fake.akshare_daily
            if row["code"] in wanted
        ]

    result = bootstrap(
        layout=layout,
        start=days[0],
        end=days[-1],
        codes=codes,
        provider_set=fake,
        today=days[-1],
        akshare_worker_runner=fake_runner,
    )
    assert result.snapshot_id is not None
    assert result.failure_count >= 2
    assert result.pending_failures >= 2
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        failures = metadata.pending_failures(result.run_id)
        failed_codes = {
            item["code"] for item in failures if item["provider"] == "AKSHARE"
        }
        assert {"600001", "600002"} <= failed_codes

    # Re-run with the worker recovered: only the crashed codes are retried
    # and the failures become RESOLVED.
    recovered = bootstrap(
        layout=layout,
        start=days[0],
        end=days[-1],
        codes=codes,
        provider_set=fake,
        today=days[-1],
        akshare_worker_runner=lambda **kwargs: [
            dict(row)
            for row in fake.akshare_daily
            if kwargs.get("mode") == "daily"
            and row["code"] in set(kwargs.get("codes") or ())
        ],
    )
    assert recovered.pending_failures == 0
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        rows = metadata._connection.execute(
            "SELECT status FROM ingest_failures WHERE run_id = ?",
            [result.run_id],
        ).fetchall()
        assert rows
        assert all(row[0] == "RESOLVED" for row in rows)
