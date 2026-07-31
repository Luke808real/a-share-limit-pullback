"""DuckDB metadata store for warehouse runs, files, snapshots and audits."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import duckdb

from limit_pullback.warehouse.models import (
    IngestRunRecord,
    QuarantineRecord,
    ReconciliationRecord,
    SnapshotRecord,
    SourceFileRecord,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class WarehouseMetadata:
    """Owns the DuckDB file and exposes typed helpers."""

    def __init__(self, duckdb_path: str | Path, read_only: bool = False) -> None:
        self.duckdb_path = Path(duckdb_path)
        if read_only:
            self._connection = duckdb.connect(str(self.duckdb_path), read_only=True)
        else:
            self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = duckdb.connect(str(self.duckdb_path))
        if not read_only:
            self.init_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "WarehouseMetadata":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def init_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_capabilities (
                provider VARCHAR NOT NULL,
                capability VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                error_code VARCHAR,
                detail VARCHAR,
                checked_at TIMESTAMPTZ NOT NULL,
                provider_version VARCHAR,
                PRIMARY KEY (provider, capability)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_runs (
                run_id VARCHAR PRIMARY KEY,
                kind VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                started_at TIMESTAMPTZ NOT NULL,
                finished_at TIMESTAMPTZ,
                start_date DATE,
                end_date DATE,
                codes VARCHAR[],
                config_json VARCHAR,
                error VARCHAR
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_snapshots (
                snapshot_id VARCHAR PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL,
                as_of DATE NOT NULL,
                provider_versions VARCHAR NOT NULL,
                source_file_hashes VARCHAR NOT NULL,
                canonical_file_hashes VARCHAR NOT NULL,
                reconciliation_policy_version VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                manifest_path VARCHAR
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS source_files (
                path VARCHAR PRIMARY KEY,
                provider VARCHAR NOT NULL,
                ingest_run_id VARCHAR NOT NULL,
                sha256 VARCHAR NOT NULL,
                row_count BIGINT NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reconciliation_results (
                reconciliation_id VARCHAR PRIMARY KEY,
                code VARCHAR NOT NULL,
                trade_date DATE NOT NULL,
                providers VARCHAR[] NOT NULL,
                status VARCHAR NOT NULL,
                selected_provider VARCHAR,
                notes VARCHAR,
                created_at TIMESTAMPTZ NOT NULL,
                snapshot_id VARCHAR
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS canonical_publications (
                snapshot_id VARCHAR NOT NULL,
                dataset VARCHAR NOT NULL,
                path VARCHAR NOT NULL,
                row_count BIGINT NOT NULL,
                published_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (snapshot_id, dataset)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quarantine_records (
                record_id VARCHAR PRIMARY KEY,
                code VARCHAR NOT NULL,
                trade_date DATE NOT NULL,
                providers VARCHAR[] NOT NULL,
                reason VARCHAR NOT NULL,
                payload VARCHAR NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_progress (
                run_id VARCHAR NOT NULL,
                provider VARCHAR NOT NULL,
                dataset VARCHAR NOT NULL,
                code VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                rows BIGINT NOT NULL DEFAULT 0,
                error VARCHAR,
                updated_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (run_id, provider, dataset, code)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_failures (
                failure_id VARCHAR PRIMARY KEY,
                run_id VARCHAR NOT NULL,
                provider VARCHAR NOT NULL,
                dataset VARCHAR NOT NULL,
                code VARCHAR,
                trade_date DATE,
                error VARCHAR,
                retry_count BIGINT NOT NULL DEFAULT 0,
                status VARCHAR NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )

    def record_capability(
        self,
        *,
        provider: str,
        capability: str,
        status: str,
        checked_at: datetime,
        provider_version: str | None = None,
        error_code: str | None = None,
        detail: str | None = None,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO provider_capabilities (
                provider, capability, status, error_code, detail,
                checked_at, provider_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (provider, capability) DO UPDATE SET
                status = excluded.status,
                error_code = excluded.error_code,
                detail = excluded.detail,
                checked_at = excluded.checked_at,
                provider_version = excluded.provider_version
            """,
            [
                provider,
                capability,
                status,
                error_code,
                detail,
                _utc(checked_at),
                provider_version,
            ],
        )

    def begin_ingest_run(
        self,
        *,
        run_id: str,
        kind: str,
        started_at: datetime,
        start_date: date | None,
        end_date: date | None,
        codes: tuple[str, ...],
        config_json: str | None = None,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO ingest_runs (
                run_id, kind, status, started_at, start_date, end_date,
                codes, config_json
            ) VALUES (?, ?, 'RUNNING', ?, ?, ?, ?, ?)
            ON CONFLICT (run_id) DO UPDATE SET
                kind = excluded.kind,
                status = 'RUNNING',
                started_at = excluded.started_at,
                start_date = excluded.start_date,
                end_date = excluded.end_date,
                codes = excluded.codes,
                config_json = excluded.config_json,
                error = NULL
            """,
            [
                run_id,
                kind,
                _utc(started_at),
                start_date,
                end_date,
                list(codes),
                config_json,
            ],
        )

    def get_ingest_run(self, run_id: str) -> IngestRunRecord | None:
        rows = self._connection.execute(
            "SELECT * FROM ingest_runs WHERE run_id = ?", [run_id]
        ).fetchall()
        if not rows:
            return None
        row = rows[0]
        return IngestRunRecord(
            run_id=row[0],
            kind=row[1],
            status=row[2],
            started_at=_aware(row[3]),
            finished_at=_aware(row[4]),
            start_date=row[5],
            end_date=row[6],
            codes=tuple(row[7] or ()),
            config_json=row[8],
            error=row[9],
        )

    def finish_ingest_run(
        self,
        *,
        run_id: str,
        status: str,
        finished_at: datetime,
        error: str | None = None,
    ) -> None:
        self._connection.execute(
            """
            UPDATE ingest_runs
            SET status = ?, finished_at = ?, error = ?
            WHERE run_id = ?
            """,
            [status, _utc(finished_at), error, run_id],
        )

    def insert_source_file(self, record: SourceFileRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO source_files (
                path, provider, ingest_run_id, sha256, row_count, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (path) DO UPDATE SET
                provider = excluded.provider,
                ingest_run_id = excluded.ingest_run_id,
                sha256 = excluded.sha256,
                row_count = excluded.row_count,
                recorded_at = excluded.recorded_at
            """,
            [
                record.path,
                record.provider,
                record.ingest_run_id,
                record.sha256,
                record.row_count,
                _utc(record.recorded_at),
            ],
        )

    def insert_snapshot(self, record: SnapshotRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO dataset_snapshots (
                snapshot_id, created_at, as_of, provider_versions,
                source_file_hashes, canonical_file_hashes,
                reconciliation_policy_version, status, manifest_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (snapshot_id) DO UPDATE SET
                created_at = excluded.created_at,
                as_of = excluded.as_of,
                provider_versions = excluded.provider_versions,
                source_file_hashes = excluded.source_file_hashes,
                canonical_file_hashes = excluded.canonical_file_hashes,
                reconciliation_policy_version = excluded.reconciliation_policy_version,
                status = excluded.status,
                manifest_path = excluded.manifest_path
            """,
            [
                record.snapshot_id,
                _utc(record.created_at),
                record.as_of,
                json.dumps(record.provider_versions, sort_keys=True),
                json.dumps(record.source_file_hashes, sort_keys=True),
                json.dumps(record.canonical_file_hashes, sort_keys=True),
                record.reconciliation_policy_version,
                record.status,
                record.manifest_path,
            ],
        )

    def insert_publication(
        self,
        *,
        snapshot_id: str,
        dataset: str,
        path: str,
        row_count: int,
        published_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO canonical_publications (
                snapshot_id, dataset, path, row_count, published_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (snapshot_id, dataset) DO UPDATE SET
                path = excluded.path,
                row_count = excluded.row_count,
                published_at = excluded.published_at
            """,
            [snapshot_id, dataset, path, row_count, _utc(published_at)],
        )

    def insert_reconciliation(self, record: ReconciliationRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO reconciliation_results (
                reconciliation_id, code, trade_date, providers, status,
                selected_provider, notes, created_at, snapshot_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (reconciliation_id) DO UPDATE SET
                code = excluded.code,
                trade_date = excluded.trade_date,
                providers = excluded.providers,
                status = excluded.status,
                selected_provider = excluded.selected_provider,
                notes = excluded.notes,
                created_at = excluded.created_at,
                snapshot_id = excluded.snapshot_id
            """,
            [
                record.reconciliation_id,
                record.code,
                record.trade_date,
                list(record.providers),
                record.status,
                record.selected_provider,
                record.notes,
                _utc(record.created_at),
                record.snapshot_id,
            ],
        )

    def insert_quarantine(self, record: QuarantineRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO quarantine_records (
                record_id, code, trade_date, providers, reason,
                payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (record_id) DO UPDATE SET
                code = excluded.code,
                trade_date = excluded.trade_date,
                providers = excluded.providers,
                reason = excluded.reason,
                payload = excluded.payload,
                created_at = excluded.created_at
            """,
            [
                record.record_id,
                record.code,
                record.trade_date,
                list(record.providers),
                record.reason,
                record.payload,
                _utc(record.created_at),
            ],
        )

    def latest_snapshot(self) -> SnapshotRecord | None:
        rows = self._connection.execute(
            """
            SELECT * FROM dataset_snapshots
            ORDER BY as_of DESC, created_at DESC
            LIMIT 1
            """
        ).fetchall()
        return self._snapshot_from_row(rows[0]) if rows else None

    def latest_snapshot_for(self, as_of: date) -> SnapshotRecord | None:
        rows = self._connection.execute(
            """
            SELECT * FROM dataset_snapshots
            WHERE as_of = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [as_of],
        ).fetchall()
        return self._snapshot_from_row(rows[0]) if rows else None

    def delete_source_files_for_run(self, run_id: str) -> None:
        self._connection.execute(
            "DELETE FROM source_files WHERE ingest_run_id = ?", [run_id]
        )

    def resolve_snapshot(self, as_of: date) -> SnapshotRecord | None:
        """Earliest publication for the newest frontier no later than as_of."""

        rows = self._connection.execute(
            """
            SELECT * FROM dataset_snapshots
            WHERE as_of <= ?
            ORDER BY as_of DESC, created_at ASC
            LIMIT 1
            """,
            [as_of],
        ).fetchall()
        return self._snapshot_from_row(rows[0]) if rows else None

    def snapshot_by_id(self, snapshot_id: str) -> SnapshotRecord | None:
        rows = self._connection.execute(
            "SELECT * FROM dataset_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchall()
        return self._snapshot_from_row(rows[0]) if rows else None

    @staticmethod
    def _snapshot_from_row(row: Any) -> SnapshotRecord:
        return SnapshotRecord(
            snapshot_id=row[0],
            created_at=_aware(row[1]),
            as_of=row[2],
            provider_versions=json.loads(row[3] or "{}"),
            source_file_hashes=json.loads(row[4] or "{}"),
            canonical_file_hashes=json.loads(row[5] or "{}"),
            reconciliation_policy_version=row[6],
            status=row[7],
            manifest_path=row[8],
        )

    def count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for status_value, count in self._connection.execute(
            "SELECT status, count(*) FROM reconciliation_results GROUP BY status"
        ).fetchall():
            counts[str(status_value)] = int(count)
        return counts

    def quarantine_count(self) -> int:
        row = self._connection.execute(
            "SELECT count(*) FROM quarantine_records"
        ).fetchone()
        return int(row[0]) if row else 0

    def upsert_progress(
        self,
        *,
        run_id: str,
        provider: str,
        dataset: str,
        code: str,
        status: str,
        rows: int = 0,
        error: str | None = None,
        updated_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO ingest_progress (
                run_id, provider, dataset, code, status, rows, error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (run_id, provider, dataset, code) DO UPDATE SET
                status = excluded.status,
                rows = excluded.rows,
                error = excluded.error,
                updated_at = excluded.updated_at
            """,
            [
                run_id,
                provider,
                dataset,
                code,
                status,
                rows,
                error,
                _utc(updated_at),
            ],
        )

    def progress_status(
        self,
        *,
        run_id: str,
        provider: str,
        dataset: str,
        code: str,
    ) -> str | None:
        rows = self._connection.execute(
            """
            SELECT status FROM ingest_progress
            WHERE run_id = ? AND provider = ? AND dataset = ? AND code = ?
            """,
            [run_id, provider, dataset, code],
        ).fetchall()
        return str(rows[0][0]) if rows else None

    def completed_progress_codes(
        self, *, run_id: str, provider: str, dataset: str
    ) -> set[str]:
        rows = self._connection.execute(
            """
            SELECT code FROM ingest_progress
            WHERE run_id = ? AND provider = ? AND dataset = ?
              AND status = 'COMPLETED'
            """,
            [run_id, provider, dataset],
        ).fetchall()
        return {str(row[0]) for row in rows}

    def record_failure(
        self,
        *,
        failure_id: str,
        run_id: str,
        provider: str,
        dataset: str,
        code: str | None,
        trade_date,
        error: str,
        retry_count: int = 0,
        status: str = "PENDING",
        created_at: datetime,
        updated_at: datetime | None = None,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO ingest_failures (
                failure_id, run_id, provider, dataset, code, trade_date,
                error, retry_count, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (failure_id) DO UPDATE SET
                error = excluded.error,
                retry_count = excluded.retry_count,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            [
                failure_id,
                run_id,
                provider,
                dataset,
                code,
                trade_date,
                error,
                retry_count,
                status,
                _utc(created_at),
                _utc(updated_at or created_at),
            ],
        )

    def pending_failures(self, run_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT provider, dataset, code, trade_date, error, retry_count
            FROM ingest_failures
            WHERE run_id = ? AND status = 'PENDING'
            ORDER BY provider, dataset, code, trade_date
            """,
            [run_id],
        ).fetchall()
        return [
            {
                "provider": row[0],
                "dataset": row[1],
                "code": row[2],
                "trade_date": row[3],
                "error": row[4],
                "retry_count": row[5],
            }
            for row in rows
        ]

    def failure_count(self, run_id: str) -> int:
        rows = self._connection.execute(
            "SELECT count(*) FROM ingest_failures WHERE run_id = ?",
            [run_id],
        ).fetchall()
        return int(rows[0][0]) if rows else 0

    def raw_max_date_by_provider(self, data_root: str) -> dict[str, date | None]:
        result: dict[str, date | None] = {}
        try:
            rows = self._connection.execute(
                """
                SELECT provider, max(trade_date)
                FROM read_parquet(?)
                GROUP BY provider
                """,
                [f"{data_root}/raw/*/daily_bars/*.parquet"],
            ).fetchall()
        except Exception:
            return result
        for provider, max_date in rows:
            result[str(provider)] = max_date
        return result
