from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.pipeline import bootstrap
from limit_pullback.warehouse.snapshot import read_snapshot_daily
from limit_pullback.warehouse.tushare_provider import CapabilityUnavailable
from tests.test_screen import _chain_rows, _weekdays
from tests.warehouse_fakes import FakeProviderSet, daily_row


def test_heartbeat_file_is_written(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    day = date(2026, 7, 30)
    fake = FakeProviderSet(
        calendar=[day],
        tushare_daily=[daily_row("603318", day.isoformat())],
        akshare_daily=[daily_row("603318", day.isoformat())],
    )
    result = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=["603318"],
        provider_set=fake,
        today=day,
    )
    heartbeat_path = layout.root / ".bootstrap_heartbeat.json"
    assert heartbeat_path.exists()
    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == result.run_id
    assert payload["phase"] in {"", "akshare-daily", "baostock-daily"}


def test_rate_limited_failures_are_deferred(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    day = date(2026, 7, 30)

    class RateLimitedTushare(FakeProviderSet):
        def fetch_tushare_daily(self, requested, start, end):
            raise CapabilityUnavailable(
                "daily_bars",
                "UNAVAILABLE_PROVIDER",
                error_code="RATE_LIMITED",
                detail="rate limited",
            )

    fake = RateLimitedTushare(
        calendar=[day],
        akshare_daily=[daily_row("603318", day.isoformat())],
    )
    result = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=["603318"],
        provider_set=fake,
        today=day,
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        deferred = metadata.deferred_failures(result.run_id)
        assert deferred
        assert all(item["retry_at"] is not None for item in deferred)
        pending = metadata.pending_failures(result.run_id)
        assert not any(item["code"] == "603318" for item in pending)
        counts = metadata.failure_status_counts(result.run_id)
        assert counts.get("DEFERRED_RATE_LIMIT", 0) >= 1


def test_aux_backfill_uses_separate_run_and_publishes_research_ready(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    day = date(2026, 7, 30)
    tushare = daily_row("603318", day.isoformat())
    akshare = dict(tushare)
    fake = FakeProviderSet(
        calendar=[day],
        tushare_daily=[tushare],
        akshare_daily=[akshare],
        daily_basic=[
            {
                "code": "603318",
                "trade_date": day,
                "turnover_rate": Decimal("2.5"),
                "volume_ratio": None,
                "pe": None,
                "pb": None,
                "total_mv": None,
                "circ_mv": None,
            }
        ],
        adj_factor=[
            {"code": "603318", "trade_date": day, "adj_factor": Decimal("1.1")}
        ],
        suspension=[],
        price_limits=[
            {"code": "603318", "trade_date": day, "up_limit": Decimal("11.0"), "down_limit": Decimal("9.0")}
        ],
    )
    core = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=["603318"],
        provider_set=fake,
        today=day,
    )
    assert core.snapshot_id is not None
    backfill = bootstrap(
        layout=layout,
        start=day - timedelta(days=7),
        end=day,
        codes=["603318"],
        provider_set=fake,
        today=day,
        aux_backfill=True,
    )
    assert backfill.run_id != core.run_id
    assert backfill.snapshot_id != core.snapshot_id
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(backfill.snapshot_id)
        assert snapshot.status == "RESEARCH_READY"
        core_snapshot = metadata.snapshot_by_id(core.snapshot_id)
        assert core_snapshot.status == "CURRENT"


def test_preclose_unconfirmed_released_after_aux_backfill(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    day = date(2026, 7, 30)
    tushare = daily_row("603318", day.isoformat(), preclose="8.89", close="10.20")
    tushare["pct_change"] = Decimal(
        str(((Decimal("10.20") - Decimal("8.89")) / Decimal("8.89") * 100).quantize(Decimal("0.01")))
    )
    akshare = dict(tushare)
    akshare["preclose"] = Decimal("9.31")
    fake_core = FakeProviderSet(
        calendar=[day],
        tushare_daily=[tushare],
        akshare_daily=[akshare],
    )
    core = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=["603318"],
        provider_set=fake_core,
        today=day,
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        rows = metadata._connection.execute(
            "SELECT count(*) FROM quarantine_records WHERE reason = 'PRECLOSE_DIVERGENCE_UNCONFIRMED'"
        ).fetchone()
        assert rows[0] >= 1

    fake_backfill = FakeProviderSet(
        calendar=[day],
        tushare_daily=[tushare],
        akshare_daily=[akshare],
        adj_factor=[
            {"code": "603318", "trade_date": day, "adj_factor": Decimal("1.1")},
            {
                "code": "603318",
                "trade_date": day - timedelta(days=1),
                "adj_factor": Decimal("1.0"),
            },
        ],
    )
    backfill = bootstrap(
        layout=layout,
        start=day - timedelta(days=7),
        end=day,
        codes=["603318"],
        provider_set=fake_backfill,
        today=day,
        aux_backfill=True,
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        resolved = metadata._connection.execute(
            """
            SELECT count(*) FROM quarantine_records
            WHERE reason = 'RESOLVED_CORPORATE_ACTION'
            """
        ).fetchone()
        assert resolved[0] >= 1
        snapshot = metadata.snapshot_by_id(backfill.snapshot_id)
        rows = read_snapshot_daily(layout, snapshot)
        assert rows and any(row["code"] == "603318" for row in rows)
        marked = metadata._connection.execute(
            """
            SELECT count(*) FROM reconciliation_results
            WHERE snapshot_id = ?
              AND code = '603318'
              AND notes LIKE '%CORPORATE_ACTION_PRECLOSE_DIVERGENCE%'
            """,
            [backfill.snapshot_id],
        ).fetchone()
        assert marked[0] >= 1


def test_stock_basic_coverage_includes_delisted_in_window():
    from limit_pullback.warehouse.fetch import (
        main_board_universe,
        stock_coverage,
    )

    start = date(2024, 1, 1)
    end = date(2026, 7, 31)
    rows = [
        {"code": "600000", "list_date": date(1999, 1, 1), "delist_date": None},
        {"code": "600001", "list_date": date(1998, 1, 1), "delist_date": date(2025, 3, 1)},
        {"code": "600002", "list_date": date(2020, 1, 1), "delist_date": date(2023, 12, 31)},
        {"code": "688001", "list_date": date(2020, 1, 1), "delist_date": None},
        {"code": "300001", "list_date": date(2010, 1, 1), "delist_date": None},
    ]
    universe = main_board_universe(rows, start, end)
    assert "600001" in universe  # delisted inside the window
    assert "600002" not in universe  # delisted before the window
    coverage = stock_coverage(rows, start, end)
    assert coverage["delisted_in_window"] == 1
    assert coverage["covered_in_window"] == 2
