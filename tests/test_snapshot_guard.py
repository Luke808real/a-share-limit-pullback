from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import read_rows
from limit_pullback.warehouse.snapshot import create_snapshot


def test_create_snapshot_skips_canonical_rows_without_preclose(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    layout.ensure_dirs()
    now = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
    good = {
        "code": "603318",
        "trade_date": date(2026, 7, 30),
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9"),
        "close": Decimal("10.5"),
        "preclose": Decimal("10"),
        "volume": Decimal("1000"),
        "amount": Decimal("10000"),
        "turnover_rate": None,
        "pct_change": None,
        "trade_status": True,
        "is_st": None,
        "selected_provider": "TUSHARE",
        "reconciliation_status": "CONFIRMED",
        "source_row_hash": "h1",
    }
    missing = dict(good)
    missing["preclose"] = None
    missing["source_row_hash"] = "h2"
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        snapshot = create_snapshot(
            layout=layout,
            metadata=metadata,
            as_of=date(2026, 7, 30),
            provider_versions={"TUSHARE": "1.0"},
            daily_rows=[good, missing],
            pool_rows=[],
            source_file_hashes={},
            reconciliation_policy_version="phase-2c2b-r1",
            clock=lambda: now,
        )
        assert snapshot.snapshot_id is not None
    from limit_pullback.warehouse.snapshot import read_snapshot_daily

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(snapshot.snapshot_id)
        rows = read_snapshot_daily(layout, stored)
    assert len(rows) == 1
    assert rows[0]["code"] == "603318"
    assert rows[0]["preclose"] == Decimal("10.0000")
