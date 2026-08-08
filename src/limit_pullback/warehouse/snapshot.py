"""Immutable dataset snapshots and point-in-time resolution."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

import pyarrow as pa

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import (
    SnapshotRecord,
    is_snapshot_formally_usable,
)
from limit_pullback.warehouse.parquet import (
    canonical_daily_schema,
    canonical_limit_up_pool_schema,
    quantize_row,
    sha256_file,
    write_json_atomic,
    write_rows_atomic,
    write_table_atomic,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class SnapshotUsabilityError(ValueError):
    """Typed fail-closed error for formal snapshot/state consumption.

    ``code`` is machine-readable and stable so CLI wrappers and tests can
    assert on the exact guard that fired without matching free-text messages.
    """

    def __init__(
        self,
        *,
        code: str,
        snapshot_id: str,
        snapshot_status: str,
        as_of: date,
        detail: str,
    ) -> None:
        self.code = code
        self.snapshot_id = snapshot_id
        self.snapshot_status = snapshot_status
        self.as_of = as_of
        super().__init__(
            f"{code}: snapshot={snapshot_id} "
            f"status={snapshot_status} as_of={as_of.isoformat()} {detail}"
        )


class FormalPointerError(RuntimeError):
    """Formal screen-ready pointer is missing or points to an unusable snapshot."""

    def __init__(
        self,
        *,
        code: str,
        snapshot_id: str | None = None,
        snapshot_status: str | None = None,
        detail: str = "",
    ) -> None:
        self.code = code
        self.snapshot_id = snapshot_id
        self.snapshot_status = snapshot_status
        message = code
        if snapshot_id:
            message += (
                f": snapshot={snapshot_id}"
                + (
                    f" status={snapshot_status}"
                    if snapshot_status
                    else ""
                )
            )
        if detail:
            message += f" {detail}"
        super().__init__(message)


def resolve_formal_screen_ready_snapshot(
    metadata,
) -> SnapshotRecord:
    """Resolve the single formal pointer; fail closed when absent/invalid."""

    pointer = metadata.get_formal_pointer()
    if pointer is None:
        raise FormalPointerError(
            code="FORMAL_POINTER_MISSING",
            detail="no formal SCREEN_READY pointer has been promoted",
        )
    snapshot = metadata.snapshot_by_id(pointer[0])
    if snapshot is None:
        raise FormalPointerError(
            code="FORMAL_POINTER_INVALID",
            snapshot_id=pointer[0],
            detail="pointer references an unknown snapshot",
        )
    if not is_snapshot_formally_usable(snapshot.status):
        raise FormalPointerError(
            code="FORMAL_POINTER_INVALID",
            snapshot_id=snapshot.snapshot_id,
            snapshot_status=snapshot.status,
            detail="pointer references a non-SCREEN_READY snapshot",
        )
    return snapshot


def require_formally_usable_snapshot(
    snapshot: SnapshotRecord,
    *,
    allow_unusable_snapshot_for_forensics: bool = False,
) -> SnapshotRecord:
    """Enforce the shared formal-usability predicate for one snapshot.

    Formal production consumption requires ``SCREEN_READY``.  Explicit
    forensic/research reads may opt in by passing
    ``allow_unusable_snapshot_for_forensics=True``; ordinary research
    workflows therefore still fail closed by default.
    """

    if is_snapshot_formally_usable(snapshot.status):
        return snapshot
    if allow_unusable_snapshot_for_forensics:
        return snapshot
    raise SnapshotUsabilityError(
        code="SNAPSHOT_NOT_SCREEN_READY",
        snapshot_id=snapshot.snapshot_id,
        snapshot_status=snapshot.status,
        as_of=snapshot.as_of,
        detail="formal consumers require status=SCREEN_READY",
    )


def snapshot_status_map(layout: WarehouseLayout) -> dict[str, tuple[str, date]]:
    """Return {snapshot_id: (status, as_of)} for every published snapshot.

    Small metadata table; used to guard persisted states without opening the
    metadata store once per state file.
    """

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        rows = metadata._connection.execute(
            "SELECT snapshot_id, status, as_of FROM dataset_snapshots"
        ).fetchall()
    return {
        str(row[0]): (str(row[1]), row[2])
        for row in rows
    }


def require_state_snapshot_usable(
    status_by_snapshot: dict[str, tuple[str, date]],
    *,
    snapshot_id: str,
    as_of: date | None = None,
) -> None:
    """Fail closed when a persisted state references a non-SCREEN_READY snapshot."""

    entry = status_by_snapshot.get(snapshot_id)
    if entry is None:
        raise SnapshotUsabilityError(
            code="STATE_BOUND_TO_UNKNOWN_SNAPSHOT",
            snapshot_id=snapshot_id,
            snapshot_status="UNKNOWN",
            as_of=as_of or date.min,
            detail="persisted state references a snapshot missing from metadata",
        )
    resolved_status, snapshot_as_of = entry
    if is_snapshot_formally_usable(resolved_status):
        return
    raise SnapshotUsabilityError(
        code="STATE_BOUND_TO_UNUSABLE_SNAPSHOT",
        snapshot_id=snapshot_id,
        snapshot_status=resolved_status,
        as_of=snapshot_as_of or as_of or date.min,
        detail="persisted state is bound to a non-SCREEN_READY snapshot",
    )


def forward_preflight(
    layout: WarehouseLayout,
    snapshot_id: str | None = None,
) -> SnapshotRecord:
    """Fail-closed snapshot usability gate for the Forward runner.

    PR-A deliberately stops before any minute-data read: this only validates
    that the candidate/source snapshot is SCREEN_READY (or an explicit safe
    read).  It never silently falls back to an older SCREEN_READY snapshot.
    """

    if not layout.duckdb_path.exists():
        raise ValueError("no dataset snapshot published")
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = (
            metadata.snapshot_by_id(snapshot_id)
            if snapshot_id is not None
            else metadata.latest_snapshot()
        )
        if snapshot is None:
            raise ValueError(
                f"unknown snapshot: {snapshot_id}" if snapshot_id else "no dataset snapshot published"
            )
        try:
            require_formally_usable_snapshot(snapshot)
        except SnapshotUsabilityError as exc:
            if snapshot_id is None:
                raise SnapshotUsabilityError(
                    code="LATEST_SNAPSHOT_NOT_SCREEN_READY",
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_status=snapshot.status,
                    as_of=snapshot.as_of,
                    detail="Forward requires an explicit SCREEN_READY snapshot",
                ) from exc
            raise
    return snapshot


def _write_row_chunks_atomic(
    row_chunks: Iterable[Sequence[Mapping[str, Any]]],
    schema: pa.Schema,
    path: Path,
) -> int:
    """Write bounded row chunks into ONE atomic parquet file.

    Uses ``pyarrow.parquet.ParquetWriter`` over a temporary file: each chunk
    is quantized with the shared ``quantize_row`` semantics, written, then
    released before the next chunk (bounded construction).  On success the
    temp file is fsynced and atomically replaced; on ANY exception the
    writer is closed safely and the temp file removed — no partial final
    parquet is ever exposed.  Returns the total row count.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid4().hex}")
    writer: pa.parquet.ParquetWriter | None = None
    row_count = 0
    try:
        writer = pa.parquet.ParquetWriter(temporary, schema, compression="zstd")
        for chunk in row_chunks:
            quantized = [quantize_row(dict(row), schema) for row in chunk]
            if not quantized:
                continue
            table = pa.Table.from_pylist(quantized, schema=schema)
            writer.write_table(table)
            row_count += len(quantized)
            del table, quantized
        writer.close()
        writer = None
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
        return row_count
    except BaseException:
        if writer is not None:
            try:
                writer.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        temporary.unlink(missing_ok=True)
        raise


def create_snapshot(
    *,
    layout: WarehouseLayout,
    metadata: WarehouseMetadata,
    as_of: date,
    provider_versions: Mapping[str, str],
    daily_rows: Sequence[Mapping[str, Any]] | None = None,
    pool_rows: Sequence[Mapping[str, Any]],
    source_file_hashes: Mapping[str, str],
    reconciliation_policy_version: str,
    clock: Callable[[], datetime] = _now_utc,
    status: str = "CURRENT",
    daily_table=None,
    daily_row_chunks: Iterable[Sequence[Mapping[str, Any]]] | None = None,
) -> SnapshotRecord:
    """Publish a new immutable canonical snapshot.

    ``daily_row_chunks`` accepts bounded row chunks (lazy iterable) written
    into ONE atomic daily parquet with the SAME snapshot id per row.
    ``daily_rows`` / ``daily_table`` paths remain unchanged for existing
    callers.
    """

    created_at = clock()
    snapshot_id = f"snap-{as_of.isoformat()}-{uuid4().hex[:12]}"
    daily_path = layout.canonical_daily_dir / f"{snapshot_id}.parquet"
    pool_path = layout.canonical_pool_dir / f"{snapshot_id}.parquet"

    daily_row_count: int | None = None
    if daily_row_chunks is not None:
        def _chunks_with_id():
            for chunk in daily_row_chunks:
                yield [
                    {**dict(row), "dataset_snapshot_id": snapshot_id}
                    for row in chunk
                    if row.get("preclose") is not None
                ]

        daily_row_count = _write_row_chunks_atomic(
            _chunks_with_id(), canonical_daily_schema(), daily_path
        )
    elif daily_table is not None:
        if "dataset_snapshot_id" not in daily_table.column_names:
            daily_table = daily_table.append_column(
                pa.field("dataset_snapshot_id", pa.string()),
                pa.array([snapshot_id] * daily_table.num_rows),
            )
    else:
        if daily_rows is None:
            raise ValueError(
                "create_snapshot requires daily_rows, daily_table, or "
                "daily_row_chunks"
            )
        daily_rows_with_id = [
            {**dict(row), "dataset_snapshot_id": snapshot_id}
            for row in daily_rows
            if row.get("preclose") is not None
        ]
    pool_rows_with_id = [
        {**dict(row), "dataset_snapshot_id": snapshot_id} for row in pool_rows
    ]
    if daily_row_chunks is not None:
        pass  # daily parquet already written atomically above
    elif daily_table is not None:
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
            daily_row_count
            if daily_row_count is not None
            else (
                daily_table.num_rows
                if daily_table is not None
                else len(daily_rows_with_id)
            )
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
