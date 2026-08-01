"""Immutable dataset snapshots and point-in-time resolution."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

import pyarrow as pa

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import SnapshotRecord
from limit_pullback.warehouse.parquet import (
    canonical_daily_schema,
    canonical_limit_up_pool_schema,
    sha256_file,
    write_json_atomic,
    write_rows_atomic,
    write_table_atomic,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_snapshot(
    *,
    layout: WarehouseLayout,
    metadata: WarehouseMetadata,
    as_of: date,
    provider_versions: Mapping[str, str],
    daily_rows: Sequence[Mapping[str, Any]],
    pool_rows: Sequence[Mapping[str, Any]],
    source_file_hashes: Mapping[str, str],
    reconciliation_policy_version: str,
    clock: Callable[[], datetime] = _now_utc,
    status: str = "CURRENT",
    daily_table=None,
) -> SnapshotRecord:
    """Publish a new immutable canonical snapshot."""

    created_at = clock()
    snapshot_id = f"snap-{as_of.isoformat()}-{uuid4().hex[:12]}"
    daily_path = layout.canonical_daily_dir / f"{snapshot_id}.parquet"
    pool_path = layout.canonical_pool_dir / f"{snapshot_id}.parquet"

    if daily_table is not None:
        if "dataset_snapshot_id" not in daily_table.column_names:
            daily_table = daily_table.append_column(
                pa.field("dataset_snapshot_id", pa.string()),
                pa.array([snapshot_id] * daily_table.num_rows),
            )
    else:
        daily_rows_with_id = [
            {**dict(row), "dataset_snapshot_id": snapshot_id}
            for row in daily_rows
            if row.get("preclose") is not None
        ]
    pool_rows_with_id = [
        {**dict(row), "dataset_snapshot_id": snapshot_id} for row in pool_rows
    ]
    if daily_table is not None:
        write_table_atomic(daily_table, daily_path)
    else:
        write_rows_atomic(daily_rows_with_id, canonical_daily_schema(), daily_path)
    write_rows_atomic(pool_rows_with_id, canonical_limit_up_pool_schema(), pool_path)

    def relative(path: Path) -> str:
        return str(path.relative_to(layout.root))

    canonical_file_hashes = {
        relative(daily_path): sha256_file(daily_path),
        relative(pool_path): sha256_file(pool_path),
    }
    manifest_path = layout.manifests_dir / f"{snapshot_id}.json"
    write_json_atomic(
        {
            "snapshot_id": snapshot_id,
            "created_at": created_at.isoformat(),
            "as_of": as_of.isoformat(),
            "provider_versions": dict(provider_versions),
            "source_file_hashes": dict(source_file_hashes),
            "canonical_file_hashes": canonical_file_hashes,
            "reconciliation_policy_version": reconciliation_policy_version,
            "status": status,
        },
        manifest_path,
    )
    record = SnapshotRecord(
        snapshot_id=snapshot_id,
        created_at=created_at,
        as_of=as_of,
        provider_versions=dict(provider_versions),
        source_file_hashes=dict(source_file_hashes),
        canonical_file_hashes=canonical_file_hashes,
        reconciliation_policy_version=reconciliation_policy_version,
        status=status,
        manifest_path=str(manifest_path),
    )
    metadata.insert_snapshot(record)
    metadata.insert_publication(
        snapshot_id=snapshot_id,
        dataset="daily_bars",
        path=relative(daily_path),
        row_count=(
            daily_table.num_rows
            if daily_table is not None
            else len(daily_rows_with_id)
        ),
        published_at=created_at,
    )
    metadata.insert_publication(
        snapshot_id=snapshot_id,
        dataset="limit_up_pool",
        path=relative(pool_path),
        row_count=len(pool_rows_with_id),
        published_at=created_at,
    )
    return record


def read_snapshot_daily(
    layout: WarehouseLayout, snapshot: SnapshotRecord
) -> list[dict[str, Any]]:
    from limit_pullback.warehouse.parquet import read_rows

    relative = snapshot.canonical_file_hashes
    daily_rel = next(
        (key for key in relative if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")),
        None,
    )
    if daily_rel is None:
        return []
    return read_rows(layout.root / daily_rel)


def read_snapshot_daily_table(layout: WarehouseLayout, snapshot: SnapshotRecord):
    """Columnar read of the canonical daily bars for one snapshot."""

    import pyarrow.parquet as pq

    relative = snapshot.canonical_file_hashes
    daily_rel = next(
        (
            key
            for key in relative
            if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
        ),
        None,
    )
    if daily_rel is None:
        return None
    return pq.read_table(layout.root / daily_rel)


def read_snapshot_pool(
    layout: WarehouseLayout, snapshot: SnapshotRecord
) -> list[dict[str, Any]]:
    from limit_pullback.warehouse.parquet import read_rows

    relative = snapshot.canonical_file_hashes
    pool_rel = next(
        (
            key
            for key in relative
            if key.endswith("/limit_up_pool/" + snapshot.snapshot_id + ".parquet")
        ),
        None,
    )
    if pool_rel is None:
        return []
    return read_rows(layout.root / pool_rel)
