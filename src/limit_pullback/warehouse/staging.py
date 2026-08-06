"""ADR-008 staging service: TDX+Tencent daily catch-up, fail-closed.

This service owns the formal pipeline boundary:

    provider adapters -> typed rows -> sequential preclose -> whole-row
    reconciliation -> existing continuity validator -> STAGED candidate

It never publishes a production snapshot.  Outputs live under
``<data-root>/tmp/staging/adr008/<run_id>/`` with a portable manifest and no
absolute machine paths.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from limit_pullback.providers.errors import (
    ProviderError,
    ProviderMalformedRowError,
    ProviderUnexpectedError,
)
from limit_pullback.providers.tdx_daily import (
    PROVIDER_NAME as TDX_PROVIDER,
    normalize_tdx_daily_row,
)
from limit_pullback.providers.tencent_daily import (
    PROVIDER_NAME as TENCENT_PROVIDER,
    normalize_tencent_daily_row,
)
from limit_pullback.warehouse.adr008_reconcile import reconcile_adr008_rows
from limit_pullback.warehouse.continuity import (
    MISSING_PREDECESSOR,
    OK as PRECLOSE_OK,
    build_sequential_preclose,
    previous_close_index,
)
from limit_pullback.warehouse.failure_registry import ProviderFailureRegistry
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import sha256_file, write_rows_atomic
from limit_pullback.warehouse.reconciliation import (
    CONFIRMED,
    CONFLICTED,
    INCOMPLETE,
    PROVISIONAL,
    ReconciliationPolicy,
)
from limit_pullback.warehouse.snapshot import require_formally_usable_snapshot
from limit_pullback.warehouse.validate import preclose_continuity_issues

STAGING_ROOT_REL = Path("tmp") / "staging" / "adr008"
PRICE = pa.decimal128(18, 4)
AMOUNT = pa.decimal128(38, 8)
RATE = pa.decimal128(28, 10)


def staging_candidate_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("code", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("open", PRICE, nullable=True),
            pa.field("high", PRICE, nullable=True),
            pa.field("low", PRICE, nullable=True),
            pa.field("close", PRICE, nullable=True),
            pa.field("preclose", PRICE, nullable=True),
            pa.field("volume", AMOUNT, nullable=True),
            pa.field("amount", AMOUNT, nullable=True),
            pa.field("pct_change", RATE, nullable=True),
            pa.field("selected_provider", pa.string(), nullable=True),
            pa.field("confirmation_provider", pa.string(), nullable=True),
            pa.field("selected_source_hash", pa.string(), nullable=True),
            pa.field("confirmation_source_hash", pa.string(), nullable=True),
            pa.field("reconciliation_status", pa.string(), nullable=False),
            pa.field("preclose_status", pa.string(), nullable=False),
            pa.field("continuity_status", pa.string(), nullable=False),
            pa.field("reconciliation_detail", pa.string(), nullable=True),
            pa.field("price_domain", pa.string(), nullable=False),
            pa.field("volume_unit", pa.string(), nullable=True),
            pa.field("amount_unit", pa.string(), nullable=False),
            pa.field("tencent_volume_unit", pa.string(), nullable=True),
            pa.field("corporate_action_status", pa.string(), nullable=False),
            pa.field("ingest_run_id", pa.string(), nullable=False),
            pa.field("tdx_source_uri", pa.string(), nullable=True),
            pa.field("tencent_source_uri", pa.string(), nullable=True),
        ]
    )


@dataclass(frozen=True)
class Adr008StagingResult:
    run_id: str
    staging_dir: Path
    manifest_path: Path
    candidate_path: Path
    failure_registry_path: Path
    base_snapshot_id: str
    requested_code_n: int
    tdx_success_n: int
    tdx_failure_n: int
    tencent_success_n: int
    tencent_failure_n: int
    confirmed_n: int
    provisional_n: int
    incomplete_n: int
    conflicted_n: int
    preclose_continuity_mismatch_n: int
    unclassified_failure_n: int
    staging_canonical_hash: str
    publish_eligible: bool
    stage_status: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_seed_previous_closes(
    layout: WarehouseLayout,
    snapshot,
) -> dict[str, Decimal]:
    """Last CONFIRMED close per code in the seed snapshot (as_of frontier)."""

    daily_rel = next(
        (
            key
            for key in snapshot.canonical_file_hashes
            if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
        ),
        None,
    )
    if daily_rel is None:
        raise ValueError("seed snapshot has no daily bars")
    path = layout.root / daily_rel
    pf = pq.ParquetFile(path)
    previous: dict[str, Decimal] = {}
    for batch in pf.iter_batches(
        columns=["code", "trade_date", "close", "reconciliation_status"],
        batch_size=65536,
        use_threads=False,
    ):
        mask = pc.equal(
            batch["reconciliation_status"],
            pa.scalar("CONFIRMED"),
        )
        mask = pc.and_(
            mask,
            pc.less_equal(batch["trade_date"], pa.scalar(snapshot.as_of)),
        )
        for row in batch.filter(mask).to_pylist():
            code = str(row["code"])
            previous[code] = Decimal(str(row["close"]))
    return previous


def _normalize_provider_rows(
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    provider: str,
    registry: ProviderFailureRegistry,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in raw_rows:
        try:
            if provider == TDX_PROVIDER:
                row = normalize_tdx_daily_row(
                    raw,
                    provider_server="staging-artifact",
                    run_id=registry.run_id,
                )
            else:
                row = normalize_tencent_daily_row(
                    raw,
                    run_id=registry.run_id,
                )
        except ProviderMalformedRowError as exc:
            registry.record(
                provider=provider,
                error=exc,
                code=str(raw.get("code")),
                final_status="MALFORMED",
            )
            continue
        except Exception as exc:
            registry.record(
                provider=provider,
                error=ProviderUnexpectedError.wrap(
                    exc,
                    provider=provider,
                    run_id=registry.run_id,
                ),
                code=str(raw.get("code")),
                final_status="UNEXPECTED",
            )
            continue
        normalized.append(row)
    return normalized


def _content_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    non_content_fields = {"fetched_at", "ingest_run_id"}
    payload = [
        {
            key: (
                value.isoformat()
                if isinstance(value, (date, datetime))
                else str(value)
                if isinstance(value, Decimal)
                else value
            )
            for key, value in sorted(row.items())
            if key not in non_content_fields
        }
        for row in rows
    ]
    return _sha256_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    )


def staged_candidate_content_hash(
    rows: Sequence[Mapping[str, Any]],
) -> str:
    """Public deterministic content hash for a PR-B staged candidate."""

    return _content_hash(rows)


def run_adr008_staging(
    layout: WarehouseLayout,
    *,
    run_id: str,
    seed_snapshot_id: str,
    sessions: Sequence[date],
    tdx_raw_rows: Sequence[Mapping[str, Any]],
    tencent_raw_rows: Sequence[Mapping[str, Any]],
    tdx_artifact_path: Path | None = None,
    tencent_artifact_path: Path | None = None,
    policy: ReconciliationPolicy | None = None,
    clock=None,
) -> Adr008StagingResult:
    """Run one staged ADR-008 reconstruction; never publishes a snapshot."""

    policy = policy or ReconciliationPolicy()
    registry = ProviderFailureRegistry(run_id=run_id)
    if not layout.duckdb_path.exists():
        raise ValueError("no dataset metadata published")
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        seed = metadata.snapshot_by_id(seed_snapshot_id)
    if seed is None:
        raise ValueError(f"unknown seed snapshot: {seed_snapshot_id}")
    require_formally_usable_snapshot(seed)

    ordered_sessions = tuple(sorted(set(sessions)))
    if not ordered_sessions:
        raise ValueError("sessions must not be empty")
    seed_closes = load_seed_previous_closes(layout, seed)

    tdx_rows = _normalize_provider_rows(
        tdx_raw_rows,
        provider=TDX_PROVIDER,
        registry=registry,
    )
    tencent_rows = _normalize_provider_rows(
        tencent_raw_rows,
        provider=TENCENT_PROVIDER,
        registry=registry,
    )
    tdx_success = {
        (row["code"], row["trade_date"]) for row in tdx_rows
    }
    tencent_success = {
        (row["code"], row["trade_date"]) for row in tencent_rows
    }

    requested_codes = sorted(
        set(seed_closes)
        | {key[0] for key in tdx_success}
        | {key[0] for key in tencent_success}
    )
    requested_universe_hash = _sha256_text("|".join(requested_codes))

    rows_by_key = {
        (row["code"], row["trade_date"]): row for row in tdx_rows
    }
    staged = build_sequential_preclose(
        rows_by_key,
        seed_previous_close=seed_closes,
        ordered_sessions=ordered_sessions,
    )
    reconciled = reconcile_adr008_rows(
        list(staged.values()),
        tencent_rows,
        policy=policy,
    )
    reconciled_by_key = {
        (row["code"], row["trade_date"]): row for row in reconciled
    }

    # Build complete rows over the requested universe (INCOMPLETE fill-ins).
    complete: list[dict[str, Any]] = []
    latest_close: dict[str, Decimal] = dict(seed_closes)
    for session in ordered_sessions:
        for code in requested_codes:
            key = (code, session)
            row = reconciled_by_key.get(key)
            if row is None:
                row = {
                    "code": code,
                    "trade_date": session,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": None,
                    "preclose": latest_close.get(code),
                    "volume": None,
                    "amount": None,
                    "pct_change": None,
                    "selected_provider": None,
                    "confirmation_provider": None,
                    "selected_source_hash": None,
                    "confirmation_source_hash": None,
                    "reconciliation_status": INCOMPLETE,
                    "preclose_status": (
                        PRECLOSE_OK
                        if code in latest_close
                        else MISSING_PREDECESSOR
                    ),
                    "continuity_status": "NOT_CHECKED",
                    "reconciliation_detail": "both_providers_missing",
                    "price_domain": "RAW_UNADJUSTED",
                    "volume_unit": "SHARES",
                    "amount_unit": "CNY",
                    "tencent_volume_unit": None,
                    "corporate_action_status": "UNKNOWN",
                    "ingest_run_id": run_id,
                    "tdx_source_uri": None,
                    "tencent_source_uri": None,
                }
            row.setdefault("volume_unit", "SHARES")
            row.setdefault("amount_unit", "CNY")
            row.setdefault("corporate_action_status", "UNKNOWN")
            row.setdefault("ingest_run_id", run_id)
            row.setdefault("tdx_source_uri", None)
            row.setdefault("tencent_source_uri", None)
            if row.get("preclose_status") == MISSING_PREDECESSOR:
                row["reconciliation_status"] = INCOMPLETE
            if row["reconciliation_status"] == INCOMPLETE:
                row["continuity_status"] = "NOT_CHECKED"
            complete.append(row)
            close = row.get("close")
            if close is not None:
                latest_close[code] = Decimal(str(close))

    # Mandatory existing-validator continuity gate.
    prev_index = previous_close_index(
        rows_by_key,
        seed_previous_close=seed_closes,
        ordered_sessions=ordered_sessions,
    )
    continuity_rows = [
        row
        for row in complete
        if row.get("preclose") is not None
        and row.get("close") is not None
    ]
    continuity_issues = preclose_continuity_issues(
        continuity_rows,
        previous_close_index=prev_index,
        provider_label="TDX",
    )
    mismatch_keys: set[tuple[str, date]] = set()
    for issue in continuity_issues:
        parts = issue.detail.split(" ", 2)
        if len(parts) >= 2:
            mismatch_keys.add((parts[0], date.fromisoformat(parts[1])))
    for row in continuity_rows:
        row["continuity_status"] = (
            "MISMATCH"
            if (row["code"], row["trade_date"]) in mismatch_keys
            else "OK"
        )
    mismatch_count = len(mismatch_keys)
    complete.sort(key=lambda row: (row["code"], row["trade_date"]))
    counts: dict[str, int] = {}
    for row in complete:
        counts[row["reconciliation_status"]] = (
            counts.get(row["reconciliation_status"], 0) + 1
        )

    staging_dir = layout.root / STAGING_ROOT_REL / run_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = staging_dir / "canonical_candidate.parquet"
    failure_registry_path = staging_dir / "failures.jsonl"
    manifest_path = staging_dir / "manifest.json"

    write_rows_atomic(complete, staging_candidate_schema(), candidate_path)
    registry.path = failure_registry_path
    registry.write()

    content_hash = _content_hash(complete)
    source_artifacts: dict[str, dict[str, Any]] = {}
    for provider, path in (
        (TDX_PROVIDER, tdx_artifact_path),
        (TENCENT_PROVIDER, tencent_artifact_path),
    ):
        if path is None:
            continue
        resolved = Path(path).expanduser().resolve()
        relative = resolved.relative_to(layout.root)
        source_artifacts[provider] = {
            "logical_uri": f"raw://{provider.lower()}/{run_id}/{relative}",
            "relative_path": str(relative),
            "sha256": sha256_file(resolved),
        }

    unclassified = registry.unclassified_count()
    mismatch_n = mismatch_count
    publish_eligible = unclassified == 0 and mismatch_n == 0
    stage_status = (
        "VALIDATION_FAILED"
        if mismatch_n > 0
        else "FAILED"
        if unclassified > 0
        else "STAGED_OK"
    )

    manifest = {
        "run_id": run_id,
        "base_snapshot_id": seed_snapshot_id,
        "base_snapshot_status": seed.status,
        "date_from": ordered_sessions[0].isoformat(),
        "date_to": ordered_sessions[-1].isoformat(),
        "sessions": [day.isoformat() for day in ordered_sessions],
        "provider": {
            "daily_primary": "TDX",
            "daily_confirm": "TENCENT",
            "daily_audit": "BAOSTOCK",
        },
        "provider_adapter_versions": {
            "TDX": "v1",
            "TENCENT": "v1",
        },
        "source_artifacts": source_artifacts,
        "requested_universe_hash": requested_universe_hash,
        "requested_code_n": len(requested_codes),
        "row_counts": {
            "tdx_success_n": len(tdx_success),
            "tdx_failure_n": registry.count(provider=TDX_PROVIDER),
            "tencent_success_n": len(tencent_success),
            "tencent_failure_n": registry.count(provider=TENCENT_PROVIDER),
            "confirmed_n": counts.get(CONFIRMED, 0),
            "provisional_n": counts.get(PROVISIONAL, 0),
            "incomplete_n": counts.get(INCOMPLETE, 0),
            "conflicted_n": counts.get(CONFLICTED, 0),
            "preclose_continuity_mismatch_n": mismatch_n,
            "unclassified_failure_n": unclassified,
        },
        "reconciliation_policy": {
            "price_absolute": str(policy.price_absolute),
            "price_relative": str(policy.price_relative),
            "volume_relative": str(policy.volume_relative),
            "policy_version": policy.policy_version,
        },
        "continuity_validation": {
            "validator": "warehouse.validate.preclose_continuity_issues",
            "mismatch_n": mismatch_n,
        },
        "corporate_action_status_semantics": "UNKNOWN/AFFECTED/NOT_AFFECTED",
        "staging_canonical_hash": content_hash,
        "staging_candidate_path": str(
            candidate_path.relative_to(layout.root)
        ),
        "failure_registry_path": str(
            failure_registry_path.relative_to(layout.root)
        ),
        "PUBLISH_ELIGIBLE": publish_eligible,
        "STAGE_STATUS": stage_status,
        "production_snapshot_published": False,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return Adr008StagingResult(
        run_id=run_id,
        staging_dir=staging_dir,
        manifest_path=manifest_path,
        candidate_path=candidate_path,
        failure_registry_path=failure_registry_path,
        base_snapshot_id=seed_snapshot_id,
        requested_code_n=len(requested_codes),
        tdx_success_n=len(tdx_success),
        tdx_failure_n=registry.count(provider=TDX_PROVIDER),
        tencent_success_n=len(tencent_success),
        tencent_failure_n=registry.count(provider=TENCENT_PROVIDER),
        confirmed_n=counts.get(CONFIRMED, 0),
        provisional_n=counts.get(PROVISIONAL, 0),
        incomplete_n=counts.get(INCOMPLETE, 0),
        conflicted_n=counts.get(CONFLICTED, 0),
        preclose_continuity_mismatch_n=mismatch_n,
        unclassified_failure_n=unclassified,
        staging_canonical_hash=content_hash,
        publish_eligible=publish_eligible,
        stage_status=stage_status,
    )
