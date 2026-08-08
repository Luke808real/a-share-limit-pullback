"""DuckDB metadata store for warehouse runs, files, snapshots and audits."""

from __future__ import annotations

import json
from contextlib import contextmanager
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

    def __init__(
        self,
        duckdb_path: str | Path,
        read_only: bool = False,
        profile=None,
    ) -> None:
        self.duckdb_path = Path(duckdb_path)
        if read_only:
            self._connection = duckdb.connect(str(self.duckdb_path), read_only=True)
        else:
            self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = duckdb.connect(str(self.duckdb_path))
        if not read_only:
            self.init_schema()
            if profile is not None:
                from limit_pullback.resources import apply_duckdb_settings

                temp_dir = self.duckdb_path.parent / "tmp" / "duckdb"
                temp_dir.mkdir(parents=True, exist_ok=True)
                apply_duckdb_settings(
                    self._connection,
                    profile,
                    str(temp_dir),
                )

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
            CREATE TABLE IF NOT EXISTS snapshot_governance_records (
                record_id VARCHAR PRIMARY KEY,
                snapshot_id VARCHAR NOT NULL,
                status_from VARCHAR NOT NULL,
                status_to VARCHAR NOT NULL,
                reason VARCHAR NOT NULL,
                audit_report_sha256 VARCHAR,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot_validation_records (
                snapshot_id VARCHAR PRIMARY KEY,
                report_hash VARCHAR NOT NULL,
                report_path VARCHAR,
                validation_status VARCHAR NOT NULL,
                validated_at TIMESTAMPTZ NOT NULL,
                validator_version VARCHAR NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot_promotion_records (
                snapshot_id VARCHAR PRIMARY KEY,
                from_state VARCHAR NOT NULL,
                to_state VARCHAR NOT NULL,
                validation_report_hash VARCHAR NOT NULL,
                input_artifact_hashes VARCHAR NOT NULL,
                code_commit VARCHAR,
                strategy_version VARCHAR,
                universe_contract VARCHAR,
                promoted_at TIMESTAMPTZ NOT NULL,
                promotion_reason VARCHAR NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS formal_screen_ready_pointer (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                snapshot_id VARCHAR NOT NULL,
                validation_report_hash VARCHAR,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS state_generations (
                generation_id VARCHAR PRIMARY KEY,
                snapshot_id VARCHAR NOT NULL,
                snapshot_content_hash VARCHAR NOT NULL,
                snapshot_validation_hash VARCHAR,
                universe_contract_version VARCHAR NOT NULL,
                universe_hash VARCHAR NOT NULL,
                strategy_version VARCHAR NOT NULL,
                strategy_config_hash VARCHAR NOT NULL,
                strategy_code_commit VARCHAR,
                as_of DATE NOT NULL,
                status VARCHAR NOT NULL,
                state_semantic_root_hash VARCHAR NOT NULL,
                compact_output_hash VARCHAR NOT NULL,
                verification_hash VARCHAR NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS state_generation_promotion_records (
                generation_id VARCHAR PRIMARY KEY,
                snapshot_id VARCHAR NOT NULL,
                snapshot_hash VARCHAR NOT NULL,
                universe_contract VARCHAR NOT NULL,
                universe_hash VARCHAR NOT NULL,
                strategy_version VARCHAR NOT NULL,
                strategy_config_hash VARCHAR NOT NULL,
                code_commit VARCHAR,
                state_semantic_root_hash VARCHAR NOT NULL,
                compact_output_hash VARCHAR NOT NULL,
                verification_hash VARCHAR NOT NULL,
                from_state VARCHAR NOT NULL,
                to_state VARCHAR NOT NULL,
                promoted_at TIMESTAMPTZ NOT NULL,
                promotion_reason VARCHAR NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS formal_state_generation_pointer (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generation_id VARCHAR NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot_validation_correction_records (
                record_id VARCHAR PRIMARY KEY,
                snapshot_id VARCHAR NOT NULL,
                original_validation_hash VARCHAR NOT NULL,
                correction_type VARCHAR NOT NULL,
                old_summary VARCHAR NOT NULL,
                corrected_summary VARCHAR NOT NULL,
                snapshot_bytes_affected BOOLEAN NOT NULL,
                publication_eligibility_changed BOOLEAN NOT NULL,
                reason VARCHAR NOT NULL,
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
                retry_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            ALTER TABLE ingest_failures ADD COLUMN IF NOT EXISTS retry_at TIMESTAMPTZ
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

    def set_snapshot_status(
        self,
        *,
        snapshot_id: str,
        status: str,
        reason: str,
        record_id: str | None = None,
        audit_report_sha256: str | None = None,
        created_at: datetime | None = None,
    ) -> tuple[str, str]:
        """Auditable snapshot status transition (e.g. quarantine).

        Persists a governance record describing the transition; the original
        canonical parquet/manifest bytes are never touched here.
        """

        from uuid import uuid4

        rows = self._connection.execute(
            "SELECT status FROM dataset_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchall()
        if not rows:
            raise ValueError(f"unknown snapshot: {snapshot_id}")
        status_from = str(rows[0][0])
        if status_from == status:
            return status_from, status
        created = created_at or datetime.now(timezone.utc)
        rid = record_id or f"gov-{snapshot_id}-{uuid4().hex[:12]}"
        self._connection.execute(
            "UPDATE dataset_snapshots SET status = ? WHERE snapshot_id = ?",
            [status, snapshot_id],
        )
        self._connection.execute(
            """
            INSERT INTO snapshot_governance_records (
                record_id, snapshot_id, status_from, status_to,
                reason, audit_report_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                rid,
                snapshot_id,
                status_from,
                status,
                reason,
                audit_report_sha256,
                _utc(created),
            ],
        )
        return status_from, status

    @contextmanager
    def promotion_transaction(self):
        """Explicit DuckDB transaction for atomic promotion visibility."""

        self._connection.execute("BEGIN TRANSACTION")
        try:
            yield self
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        self._connection.execute("COMMIT")

    def get_formal_pointer(self) -> tuple[str, str | None] | None:
        if not self._table_exists("formal_screen_ready_pointer"):
            return None
        rows = self._connection.execute(
            """
            SELECT snapshot_id, validation_report_hash
            FROM formal_screen_ready_pointer
            WHERE id = 1
            """
        ).fetchall()
        if not rows:
            return None
        return str(rows[0][0]), (
            str(rows[0][1]) if rows[0][1] is not None else None
        )

    def _table_exists(self, name: str) -> bool:
        rows = self._connection.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = ?
            """,
            [name],
        ).fetchall()
        return bool(rows)

    def resolve_formal_snapshot(self) -> SnapshotRecord | None:
        pointer = self.get_formal_pointer()
        if pointer is None:
            return None
        return self.snapshot_by_id(pointer[0])

    def set_formal_pointer(
        self,
        *,
        snapshot_id: str,
        validation_report_hash: str | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        now = updated_at or datetime.now(timezone.utc)
        self._connection.execute(
            """
            INSERT INTO formal_screen_ready_pointer (
                id, snapshot_id, validation_report_hash, updated_at
            ) VALUES (1, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                snapshot_id = excluded.snapshot_id,
                validation_report_hash = excluded.validation_report_hash,
                updated_at = excluded.updated_at
            """,
            [snapshot_id, validation_report_hash, _utc(now)],
        )

    def get_formal_state_pointer(self) -> str | None:
        if not self._table_exists("formal_state_generation_pointer"):
            return None
        rows = self._connection.execute(
            """
            SELECT generation_id FROM formal_state_generation_pointer
            WHERE id = 1
            """
        ).fetchall()
        return str(rows[0][0]) if rows else None

    def set_formal_state_pointer(
        self,
        *,
        generation_id: str,
        updated_at: datetime | None = None,
    ) -> None:
        now = updated_at or datetime.now(timezone.utc)
        self._connection.execute(
            """
            INSERT INTO formal_state_generation_pointer (
                id, generation_id, updated_at
            ) VALUES (1, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                generation_id = excluded.generation_id,
                updated_at = excluded.updated_at
            """,
            [generation_id, _utc(now)],
        )

    def insert_state_generation(
        self,
        *,
        generation_id: str,
        snapshot_id: str,
        snapshot_content_hash: str,
        snapshot_validation_hash: str | None,
        universe_contract_version: str,
        universe_hash: str,
        strategy_version: str,
        strategy_config_hash: str,
        strategy_code_commit: str | None,
        as_of: date,
        status: str,
        state_semantic_root_hash: str,
        compact_output_hash: str,
        verification_hash: str,
        created_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO state_generations (
                generation_id, snapshot_id, snapshot_content_hash,
                snapshot_validation_hash, universe_contract_version,
                universe_hash, strategy_version, strategy_config_hash,
                strategy_code_commit, as_of, status, state_semantic_root_hash,
                compact_output_hash, verification_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (generation_id) DO UPDATE SET
                status = excluded.status,
                state_semantic_root_hash = excluded.state_semantic_root_hash,
                compact_output_hash = excluded.compact_output_hash,
                verification_hash = excluded.verification_hash
            """,
            [
                generation_id,
                snapshot_id,
                snapshot_content_hash,
                snapshot_validation_hash,
                universe_contract_version,
                universe_hash,
                strategy_version,
                strategy_config_hash,
                strategy_code_commit,
                as_of,
                status,
                state_semantic_root_hash,
                compact_output_hash,
                verification_hash,
                _utc(created_at),
            ],
        )

    def update_state_generation_status(
        self,
        *,
        generation_id: str,
        status: str,
    ) -> None:
        self._connection.execute(
            "UPDATE state_generations SET status = ? WHERE generation_id = ?",
            [status, generation_id],
        )

    def state_generation_by_id(self, generation_id: str) -> dict[str, Any] | None:
        if not self._table_exists("state_generations"):
            return None
        rows = self._connection.execute(
            """
            SELECT generation_id, snapshot_id, snapshot_content_hash,
                   snapshot_validation_hash, universe_contract_version,
                   universe_hash, strategy_version, strategy_config_hash,
                   strategy_code_commit, as_of, status,
                   state_semantic_root_hash, compact_output_hash,
                   verification_hash, created_at
            FROM state_generations WHERE generation_id = ?
            """,
            [generation_id],
        ).fetchall()
        if not rows:
            return None
        row = rows[0]
        return {
            "generation_id": str(row[0]),
            "snapshot_id": str(row[1]),
            "snapshot_content_hash": str(row[2]),
            "snapshot_validation_hash": (
                str(row[3]) if row[3] is not None else None
            ),
            "universe_contract_version": str(row[4]),
            "universe_hash": str(row[5]),
            "strategy_version": str(row[6]),
            "strategy_config_hash": str(row[7]),
            "strategy_code_commit": (
                str(row[8]) if row[8] is not None else None
            ),
            "as_of": row[9],
            "status": str(row[10]),
            "state_semantic_root_hash": str(row[11]),
            "compact_output_hash": str(row[12]),
            "verification_hash": str(row[13]),
            "created_at": row[14],
        }

    def insert_state_generation_promotion(
        self,
        *,
        generation_id: str,
        snapshot_id: str,
        snapshot_hash: str,
        universe_contract: str,
        universe_hash: str,
        strategy_version: str,
        strategy_config_hash: str,
        code_commit: str | None,
        state_semantic_root_hash: str,
        compact_output_hash: str,
        verification_hash: str,
        from_state: str,
        to_state: str,
        promoted_at: datetime,
        promotion_reason: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO state_generation_promotion_records (
                generation_id, snapshot_id, snapshot_hash, universe_contract,
                universe_hash, strategy_version, strategy_config_hash,
                code_commit, state_semantic_root_hash, compact_output_hash,
                verification_hash, from_state, to_state, promoted_at,
                promotion_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (generation_id) DO UPDATE SET
                from_state = excluded.from_state,
                to_state = excluded.to_state,
                verification_hash = excluded.verification_hash
            """,
            [
                generation_id,
                snapshot_id,
                snapshot_hash,
                universe_contract,
                universe_hash,
                strategy_version,
                strategy_config_hash,
                code_commit,
                state_semantic_root_hash,
                compact_output_hash,
                verification_hash,
                from_state,
                to_state,
                _utc(promoted_at),
                promotion_reason,
            ],
        )

    def insert_snapshot_validation_correction(
        self,
        *,
        record_id: str,
        snapshot_id: str,
        original_validation_hash: str,
        correction_type: str,
        old_summary: dict[str, Any],
        corrected_summary: dict[str, Any],
        snapshot_bytes_affected: bool,
        publication_eligibility_changed: bool,
        reason: str,
        created_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO snapshot_validation_correction_records (
                record_id, snapshot_id, original_validation_hash,
                correction_type, old_summary, corrected_summary,
                snapshot_bytes_affected, publication_eligibility_changed,
                reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (record_id) DO UPDATE SET
                corrected_summary = excluded.corrected_summary,
                reason = excluded.reason
            """,
            [
                record_id,
                snapshot_id,
                original_validation_hash,
                correction_type,
                json.dumps(old_summary, sort_keys=True, default=str),
                json.dumps(corrected_summary, sort_keys=True, default=str),
                bool(snapshot_bytes_affected),
                bool(publication_eligibility_changed),
                reason,
                _utc(created_at),
            ],
        )

    def insert_snapshot_validation(
        self,
        *,
        snapshot_id: str,
        report_hash: str,
        report_path: str | None,
        validation_status: str,
        validated_at: datetime,
        validator_version: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO snapshot_validation_records (
                snapshot_id, report_hash, report_path, validation_status,
                validated_at, validator_version
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (snapshot_id) DO UPDATE SET
                report_hash = excluded.report_hash,
                report_path = excluded.report_path,
                validation_status = excluded.validation_status,
                validated_at = excluded.validated_at,
                validator_version = excluded.validator_version
            """,
            [
                snapshot_id,
                report_hash,
                report_path,
                validation_status,
                _utc(validated_at),
                validator_version,
            ],
        )

    def insert_snapshot_promotion(
        self,
        *,
        snapshot_id: str,
        from_state: str,
        to_state: str,
        validation_report_hash: str,
        input_artifact_hashes: dict[str, str],
        code_commit: str | None,
        strategy_version: str | None,
        universe_contract: str | None,
        promoted_at: datetime,
        promotion_reason: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO snapshot_promotion_records (
                snapshot_id, from_state, to_state, validation_report_hash,
                input_artifact_hashes, code_commit, strategy_version,
                universe_contract, promoted_at, promotion_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (snapshot_id) DO UPDATE SET
                from_state = excluded.from_state,
                to_state = excluded.to_state,
                validation_report_hash = excluded.validation_report_hash,
                input_artifact_hashes = excluded.input_artifact_hashes,
                code_commit = excluded.code_commit,
                strategy_version = excluded.strategy_version,
                universe_contract = excluded.universe_contract,
                promoted_at = excluded.promoted_at,
                promotion_reason = excluded.promotion_reason
            """,
            [
                snapshot_id,
                from_state,
                to_state,
                validation_report_hash,
                json.dumps(input_artifact_hashes, sort_keys=True),
                code_commit,
                strategy_version,
                universe_contract,
                _utc(promoted_at),
                promotion_reason,
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

    def latest_screen_ready_snapshot(self) -> SnapshotRecord | None:
        """Newest snapshot explicitly promoted to SCREEN_READY.

        This is the ONLY sanctioned "usable latest" selector for formal
        consumers.  It never falls back to CURRENT: if the newest snapshot is
        not formally usable, callers receive None and must fail closed rather
        than silently selecting an older snapshot.
        """

        from limit_pullback.warehouse.models import SCREEN_READY_STATUS

        rows = self._connection.execute(
            """
            SELECT * FROM dataset_snapshots
            WHERE status = ?
            ORDER BY as_of DESC, created_at DESC
            LIMIT 1
            """,
            [SCREEN_READY_STATUS],
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
        retry_at=None,
        created_at: datetime,
        updated_at: datetime | None = None,
    ) -> None:
        if isinstance(retry_at, (int, float)):
            retry_at = datetime.fromtimestamp(retry_at, tz=timezone.utc)
        self._connection.execute(
            """
            INSERT INTO ingest_failures (
                failure_id, run_id, provider, dataset, code, trade_date,
                error, retry_count, status, retry_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (failure_id) DO UPDATE SET
                error = excluded.error,
                retry_count = excluded.retry_count,
                status = excluded.status,
                retry_at = excluded.retry_at,
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
                retry_at,
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

    def deferred_failures(self, run_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT provider, dataset, code, trade_date, error, retry_count, retry_at
            FROM ingest_failures
            WHERE run_id = ? AND status = 'DEFERRED_RATE_LIMIT'
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
                "retry_at": row[6],
            }
            for row in rows
        ]

    def failure_status_counts(self, run_id: str) -> dict[str, int]:
        rows = self._connection.execute(
            "SELECT status, count(*) FROM ingest_failures WHERE run_id = ? GROUP BY status",
            [run_id],
        ).fetchall()
        return {str(status): int(count) for status, count in rows}

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
