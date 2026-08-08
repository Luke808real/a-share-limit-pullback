"""STATE_READER_CORRECTNESS: contiguity-safe canonical daily reader."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from limit_pullback.screen.canonical import iter_canonical_code_bars
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.models import SnapshotRecord
from limit_pullback.warehouse.parquet import (
    canonical_daily_schema,
    sha256_file,
    write_rows_atomic,
)


def _row(code, day, close, *, status="CONFIRMED"):
    value = Decimal(str(close))
    return {
        "code": code,
        "trade_date": day,
        "open": value,
        "high": value + Decimal("0.01"),
        "low": value - Decimal("0.01"),
        "close": value,
        "preclose": value - Decimal("0.10"),
        "volume": Decimal("1000"),
        "amount": Decimal("10000"),
        "turnover_rate": None,
        "pct_change": None,
        "trade_status": True,
        "is_st": False,
        "selected_provider": "TEST",
        "reconciliation_status": status,
        "source_row_hash": f"{code}-{day.isoformat()}",
        "dataset_snapshot_id": "snap-reader-test",
    }


def _snapshot(layout: WarehouseLayout, daily_path: Path) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_id="snap-reader-test",
        created_at=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        as_of=date(2026, 8, 5),
        provider_versions={"TEST": "1.0"},
        source_file_hashes={},
        canonical_file_hashes={
            f"canonical/daily_bars/snap-reader-test.parquet": sha256_file(
                daily_path
            )
        },
        reconciliation_policy_version="test-r1",
        status="SCREEN_READY",
        manifest_path=str(layout.manifests_dir / "snap-reader-test.json"),
    )


def test_split_code_blocks_yield_merged_sorted_once(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    layout.ensure_dirs()
    path = layout.canonical_daily_dir / "snap-reader-test.parquet"
    a_hist = [_row("000001", date(2026, 7, 29), 10.0)]
    b_hist = [_row("000002", date(2026, 7, 30), 20.0)]
    a_append = [
        _row("000001", date(2026, 8, 3), 11.0),
        _row("000001", date(2026, 8, 5), 12.0),
    ]
    b_append = [_row("000002", date(2026, 8, 4), 21.0)]
    write_rows_atomic(
        [*a_hist, *b_hist, *a_append, *b_append],
        canonical_daily_schema(),
        path,
    )
    snapshot = _snapshot(layout, path)
    groups = list(
        iter_canonical_code_bars(
            layout,
            snapshot,
            as_of=date(2026, 8, 5),
        )
    )
    by_code = {code: bars for code, bars in groups}
    assert list(by_code) == ["000001", "000002"]
    assert len(groups) == 2
    assert [bar.trade_date for bar in by_code["000001"]] == [
        date(2026, 7, 29),
        date(2026, 8, 3),
        date(2026, 8, 5),
    ]
    assert [bar.trade_date for bar in by_code["000002"]] == [
        date(2026, 7, 30),
        date(2026, 8, 4),
    ]


def test_duplicate_identical_row_deduped(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    layout.ensure_dirs()
    path = layout.canonical_daily_dir / "snap-reader-test.parquet"
    row = _row("000001", date(2026, 8, 3), 11.0)
    write_rows_atomic(
        [row, dict(row)],
        canonical_daily_schema(),
        path,
    )
    snapshot = _snapshot(layout, path)
    groups = list(iter_canonical_code_bars(layout, snapshot))
    assert len(groups) == 1
    assert len(groups[0][1]) == 1


def test_conflicting_duplicate_fails_closed(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    layout.ensure_dirs()
    path = layout.canonical_daily_dir / "snap-reader-test.parquet"
    row_a = _row("000001", date(2026, 8, 3), 11.0)
    row_b = _row("000001", date(2026, 8, 3), 11.5)
    write_rows_atomic(
        [row_a, row_b],
        canonical_daily_schema(),
        path,
    )
    snapshot = _snapshot(layout, path)
    with pytest.raises(ValueError) as exc_info:
        list(iter_canonical_code_bars(layout, snapshot))
    assert "DUPLICATE_CANONICAL_ROW_CONFLICT" in str(exc_info.value)
