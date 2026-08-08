"""PR-E: staged state generation -> verify -> atomic ACTIVE promotion.

Generation lifecycle: STAGED -> VERIFIED -> ACTIVE / REJECTED.  Formal state
consumers resolve only the explicit ``formal_state_generation_pointer``; there
is no latest-directory scan and no fallback to the legacy contaminated root.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from limit_pullback.models.enums import SetupStage
from limit_pullback.models.signal import StrategySignal
from limit_pullback.screen.models import ScreenState
from limit_pullback.coverage import (
    STATE_COVERED_THROUGH_AS_OF,
    state_is_covered_through,
)
from limit_pullback.screen.runner import (
    ScreenFailpointError,
    run_screen,
)
from limit_pullback.universe import (
    Phase2d0Universe,
    PHASE2D0_UNIVERSE_CONTRACT_VERSION,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import sha256_file, write_json_atomic

STAGED = "STAGED"
VERIFIED = "VERIFIED"
ACTIVE = "ACTIVE"
REJECTED = "REJECTED"
PROMOTION_REASON = (
    "FULL_REBUILD_FROM_CORRECTED_SCREEN_READY_SNAPSHOT_AFTER_QUARANTINE"
)
DECISION_USE_STATUS = "BLOCKED_STRATEGY_SEMANTIC_REVIEW"
DECISION_USE_REASON = "B2_CONFIRMED_LIFECYCLE_UNRESOLVED"


class StateGenerationError(RuntimeError):
    pass


class StatePointerError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        generation_id: str | None = None,
        detail: str = "",
    ) -> None:
        self.code = code
        self.generation_id = generation_id
        message = code
        if generation_id:
            message += f": generation={generation_id}"
        if detail:
            message += f" {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class StateGenerationResult:
    generation_id: str
    status: str
    generation_root: Path
    state_semantic_root_hash: str
    compact_output_hash: str
    verification_hash: str
    state_n: int
    setup_counts: dict[str, int]
    last_processed_20260805_n: int
    compact_output_row_n: int
    compact_roundtrip_hash_match: bool
    pointer_before: str | None
    pointer_after: str | None
    idempotent: bool
    build_wall_seconds: float
    peak_rss_bytes: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _git_head() -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


SET_LIKE_SIGNAL_FIELDS = (
    "matched_patterns",
    "event_flags",
    "quality_flags",
    "unavailable_rules",
)


def normalize_signal_payload(signal: dict[str, Any]) -> dict[str, Any]:
    """Order/derived-metadata normalization for set-like signal fields."""

    normalized = {
        key: value
        for key, value in signal.items()
        if key != "generated_at"
    }
    for key in SET_LIKE_SIGNAL_FIELDS:
        value = normalized.get(key)
        if isinstance(value, list):
            normalized[key] = sorted(value, key=str)
    return normalized


def normalize_output_payload(payload_json: str) -> str:
    """Normalize one compact output row for semantic comparison."""

    row = json.loads(payload_json)
    for key in SET_LIKE_SIGNAL_FIELDS:
        value = row.get(key)
        if isinstance(value, list):
            row[key] = sorted(value, key=str)
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def snapshot_content_hash_from_validation(
    layout: WarehouseLayout,
    snapshot,
) -> str:
    """Reconstruct the deterministic snapshot content hash from its report."""

    manifest = json.loads(
        Path(snapshot.manifest_path).read_text(encoding="utf-8")
    )
    validation_report = manifest.get("validation_report")
    report_path = (
        layout.root / validation_report
        if validation_report
        else None
    )
    if report_path is None or not report_path.is_file():
        daily_hash = next(
            (
                value
                for key, value in manifest[
                    "canonical_file_hashes"
                ].items()
                if "/daily_bars/" in key
            ),
            "",
        )
        pool_hash = next(
            (
                value
                for key, value in manifest[
                    "canonical_file_hashes"
                ].items()
                if "/limit_up_pool/" in key
            ),
            "",
        )
        return _sha256_text(f"{daily_hash}|{pool_hash}")
    assert report_path is not None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return _sha256_text(f"{report['daily_hash']}|{report['pool_hash']}")


def _raise_failpoint(failpoint: str | None, name: str) -> None:
    if failpoint == name:
        raise ScreenFailpointError(name)


def state_semantic_root_hash(states_root: Path) -> tuple[str, int]:
    """Deterministic semantic root hash over sorted state files."""

    files = sorted(
        states_root.glob("[0-9]*.json"),
        key=lambda path: path.stem,
    )
    digest = hashlib.sha256()
    for path in files:
        state = ScreenState.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        payload = {
            "code": state.code,
            "last_processed_date": state.last_processed_date.isoformat(),
            "setup_id": state.setup_id,
            "snapshot_id": state.snapshot_id,
            "bars_prefix_hash": state.bars_prefix_hash,
            "limit_pool_prefix_hash": state.limit_pool_prefix_hash,
            "strategy_commit": state.strategy_commit,
            "config_hash": state.config_hash,
            "reconciliation_policy_version": (
                state.reconciliation_policy_version
            ),
            "signal": normalize_signal_payload(
                json.loads(state.signal_json)
            ),
        }
        digest.update(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest(), len(files)


def compact_output_roundtrip_hash(
    compact_output_path: Path,
) -> tuple[str, int]:
    """Bounded roundtrip hash over the compact-output payload column.

    Streams payload batches in PHYSICAL row order with the EXACT existing
    hash contract: ``b"["`` + payload0 + ``b", "`` + payload1 + ... + ``b"]"``
    over ``str(payload).encode("utf-8")``.  Returns ``(digest, row_count)``
    without materializing the full table or a full Python payload list.
    """

    digest = hashlib.sha256()
    digest.update(b"[")
    row_count = 0
    first = True
    batches = pq.ParquetFile(compact_output_path).iter_batches(
        columns=["payload"], batch_size=65536, use_threads=False
    )
    for batch in batches:
        for value in batch.column("payload").to_pylist():
            if not first:
                digest.update(b", ")
            first = False
            digest.update(str(value).encode("utf-8"))
            row_count += 1
    digest.update(b"]")
    return digest.hexdigest(), row_count


def _verify_generation(
    *,
    states_root: Path,
    compact_output_path: Path,
    manifest: Mapping[str, Any],
    snapshot_id: str,
    universe: Phase2d0Universe,
    expected_as_of: date,
    expected_config_hash: str,
    expected_commit: str,
    output_hash: str,
    confirmed_sessions: set[tuple[str, date]],
    latest_confirmed_by_code: dict[str, date],
    verified_no_trade: set[tuple[str, date]],
    session_calendar: Sequence[date],
) -> dict[str, Any]:
    semantic_hash, state_n = state_semantic_root_hash(states_root)
    codes = sorted(path.stem for path in states_root.glob("[0-9]*.json"))
    expected_codes = set(universe.members)
    old_only = sorted(set(codes) - expected_codes)
    new_only = sorted(expected_codes - set(codes))
    duplicates = len(codes) - len(set(codes))
    snapshot_mismatch = 0
    last_processed_as_of = 0
    last_processed_20260805 = 0
    setup_counts: dict[str, int] = {}
    invalid_invariant_fail = 0
    coverage_rows: list[dict[str, Any]] = []
    covered_through = 0
    verified_no_trade_covered = 0
    uncovered = 0
    confirmed_after_last = 0
    for path in states_root.glob("[0-9]*.json"):
        state = ScreenState.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if state.snapshot_id != snapshot_id:
            snapshot_mismatch += 1
        if state.last_processed_date == expected_as_of:
            last_processed_as_of += 1
        if state.last_processed_date == date(2026, 8, 5):
            last_processed_20260805 += 1
        signal = StrategySignal.model_validate_json(state.signal_json)
        setup_counts[signal.setup_stage.value] = (
            setup_counts.get(signal.setup_stage.value, 0) + 1
        )
        if signal.anchor is not None:
            eligible = getattr(signal, "eligible_from", None)
            if eligible is not None and eligible <= signal.anchor.frozen_as_of:
                invalid_invariant_fail += 1
        status, coverage_through, reasons = state_is_covered_through(
            last_processed_date=state.last_processed_date,
            as_of=expected_as_of,
            session_calendar=session_calendar,
            confirmed_traded_sessions=confirmed_sessions,
            verified_no_trade_sessions=verified_no_trade,
            code=state.code,
        )
        coverage_rows.append(
            {
                "code": state.code,
                "state_last_processed_date": state.last_processed_date,
                "latest_confirmed_traded_bar_date": (
                    latest_confirmed_by_code.get(state.code)
                ),
                "generation_as_of": expected_as_of,
                "verified_no_trade_session_n": sum(
                    1
                    for session in session_calendar
                    if (state.code, session) in verified_no_trade
                ),
                "unexplained_missing_session_n": len(
                    [
                        reason
                        for reason in reasons
                        if reason.startswith("UNEXPLAINED_SESSION:")
                    ]
                ),
                "coverage_status": status,
                "coverage_through": coverage_through,
                "coverage_evidence_hash": "",
            }
        )
        if status == STATE_COVERED_THROUGH_AS_OF:
            covered_through += 1
            if (
                state.last_processed_date < expected_as_of
                and not any(
                    (state.code, session) in confirmed_sessions
                    for session in session_calendar
                    if state.last_processed_date
                    < session
                    <= expected_as_of
                )
            ):
                verified_no_trade_covered += 1
        else:
            uncovered += 1
        if any(
            (state.code, session) in confirmed_sessions
            for session in session_calendar
            if state.last_processed_date < session <= expected_as_of
        ):
            confirmed_after_last += 1
    coverage_root_hash = _coverage_root_hash(coverage_rows)
    roundtrip_hash, compact_rows = compact_output_roundtrip_hash(
        compact_output_path
    )
    bindings_ok = (
        manifest.get("snapshot_id") == snapshot_id
        and manifest.get("config_hash") == expected_config_hash
        and manifest.get("strategy_commit") == expected_commit
    )
    issues: list[str] = []
    if state_n != universe.member_n:
        issues.append("STATE_COUNT")
    if old_only or new_only:
        issues.append("UNIVERSE_MEMBERSHIP")
    if duplicates:
        issues.append("DUPLICATE_CODE")
    if snapshot_mismatch:
        issues.append("SNAPSHOT_BINDING")
    for path in states_root.glob("[0-9]*.json"):
        state = ScreenState.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if state.last_processed_date > expected_as_of:
            issues.append("LAST_PROCESSED_FUTURE")
            break
    if covered_through != universe.member_n:
        issues.append("STATE_COVERAGE_THROUGH_AS_OF")
    if uncovered:
        issues.append("STATE_UNCOVERED")
    if confirmed_after_last:
        issues.append("LATEST_CONFIRMED_BAR_AFTER_STATE_LAST_PROCESSED")
    if invalid_invariant_fail:
        issues.append("ELIGIBLE_FROM_INVARIANT")
    if roundtrip_hash != output_hash:
        issues.append("COMPACT_ROUNDTRIP_HASH")
    if compact_rows != int(manifest.get("rows_count", -1)):
        issues.append("COMPACT_ROW_COUNT")
    if not bindings_ok:
        issues.append("GENERATION_BINDING")
    if str(manifest.get("output_hash", "")) != output_hash:
        issues.append("OUTPUT_HASH")
    return {
        "state_n": state_n,
        "state_semantic_root_hash": semantic_hash,
        "state_universe_old_only_n": len(old_only),
        "state_universe_new_only_n": len(new_only),
        "out_of_universe_active_state_n": len(old_only),
        "duplicate_code_n": duplicates,
        "snapshot_binding_mismatch_n": snapshot_mismatch,
        "last_processed_20260805_n": last_processed_20260805,
        "last_processed_as_of_n": last_processed_as_of,
        "verified_no_trade_covered_n": verified_no_trade_covered,
        "state_coverage_through_as_of_n": covered_through,
        "state_uncovered_n": uncovered,
        "latest_confirmed_bar_after_state_last_processed_n": (
            confirmed_after_last
        ),
        "state_coverage_root_hash": coverage_root_hash,
        "coverage_rows": coverage_rows,
        "setup_counts": dict(sorted(setup_counts.items())),
        "eligible_from_invariant_fail_n": invalid_invariant_fail,
        "compact_output_hash": output_hash,
        "compact_roundtrip_hash": roundtrip_hash,
        "compact_roundtrip_hash_match": roundtrip_hash == output_hash,
        "compact_output_row_n": compact_rows,
        "issues": issues,
        "passed": not issues,
    }


def _coverage_root_hash(
    coverage_rows: Sequence[Mapping[str, Any]],
) -> str:
    payload = [
        {
            key: (
                value.isoformat()
                if isinstance(value, (date, datetime))
                else value
            )
            for key, value in sorted(row.items())
            if key != "coverage_evidence_hash"
        }
        for row in coverage_rows
    ]
    return _sha256_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    )


def _coverage_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("code", pa.string()),
            pa.field("state_last_processed_date", pa.date32()),
            pa.field(
                "latest_confirmed_traded_bar_date",
                pa.date32(),
                nullable=True,
            ),
            pa.field("generation_as_of", pa.date32()),
            pa.field("verified_no_trade_session_n", pa.int64()),
            pa.field("unexplained_missing_session_n", pa.int64()),
            pa.field("coverage_status", pa.string()),
            pa.field("coverage_through", pa.date32()),
            pa.field("coverage_evidence_hash", pa.string()),
        ]
    )


def build_state_generation(
    layout: WarehouseLayout,
    *,
    snapshot_id: str,
    universe: Phase2d0Universe,
    config_path: Path,
    as_of: date,
    start: date | None,
    rebuild: bool,
    build_root: Path,
    strategy_commit: str | None = None,
    failpoint: str | None = None,
    dry_run: bool = False,
    seed_states_root: Path | None = None,
    verified_no_trade: Sequence[tuple[str, date]] = (),
    session_calendar: Sequence[date] = (),
) -> StateGenerationResult:
    """Build and (unless dry) atomically promote one state generation."""

    started = _utc_now()
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(snapshot_id)
        screen_pointer = metadata.get_formal_pointer()
        state_pointer_before = metadata.get_formal_state_pointer()
    if snapshot is None or snapshot.status != "SCREEN_READY":
        raise StateGenerationError(
            f"snapshot not SCREEN_READY: {snapshot_id}"
        )
    if screen_pointer is None or screen_pointer[0] != snapshot_id:
        raise StatePointerError(
            code="STATE_SNAPSHOT_POINTER_MISMATCH",
            detail=f"screen pointer={screen_pointer}, snapshot={snapshot_id}",
        )
    config_hash = sha256_file(config_path)
    commit = strategy_commit or _git_head()
    snapshot_content_hash = snapshot_content_hash_from_validation(
        layout,
        snapshot,
    )
    confirmed_sessions: set[tuple[str, date]] = set()
    latest_confirmed_by_code: dict[str, date] = {}
    if session_calendar:
        daily_rel = next(
            key
            for key in snapshot.canonical_file_hashes
            if key.endswith(
                "/daily_bars/" + snapshot.snapshot_id + ".parquet"
            )
        )
        pf = pq.ParquetFile(layout.root / daily_rel)
        session_set = set(session_calendar)
        for batch in pf.iter_batches(
            columns=["code", "trade_date", "reconciliation_status"],
            batch_size=65536,
            use_threads=False,
        ):
            mask = pc.is_in(
                batch["trade_date"],
                value_set=pa.array(sorted(session_set)),
            )
            mask = pc.and_(
                mask,
                pc.equal(
                    batch["reconciliation_status"],
                    pa.scalar("CONFIRMED"),
                ),
            )
            for row in batch.filter(mask).to_pylist():
                confirmed_sessions.add((str(row["code"]), row["trade_date"]))
        # Lightweight index of the latest CONFIRMED bar per code through as_of.
        pf = pq.ParquetFile(layout.root / daily_rel)
        for batch in pf.iter_batches(
            columns=["code", "trade_date", "reconciliation_status"],
            batch_size=65536,
            use_threads=False,
        ):
            mask = pc.equal(
                batch["reconciliation_status"],
                pa.scalar("CONFIRMED"),
            )
            mask = pc.and_(
                mask,
                pc.less_equal(
                    batch["trade_date"],
                    pa.scalar(as_of),
                ),
            )
            for row in batch.filter(mask).to_pylist():
                code = str(row["code"])
                previous = latest_confirmed_by_code.get(code)
                if previous is None or row["trade_date"] > previous:
                    latest_confirmed_by_code[code] = row["trade_date"]

    states_root = build_root / "states"
    compact_output_path = build_root / "screen-output.parquet"
    manifest_path = build_root / "manifest.json"
    states_root.mkdir(parents=True, exist_ok=True)
    if seed_states_root is not None and seed_states_root.exists():
        for path in seed_states_root.glob("[0-9]*.json"):
            shutil.copy2(path, states_root / path.name)

    result = run_screen(
        layout=layout,
        as_of=as_of,
        snapshot_id=snapshot_id,
        start=start,
        rebuild=rebuild,
        codes=universe.members,
        config_path=config_path,
        strategy_commit=commit,
        manifest_path_override=manifest_path,
        states_root=states_root,
        compact_output_path=compact_output_path,
        failpoint=failpoint,
    )
    _raise_failpoint(failpoint, "after_compact_output")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_hash = manifest["output_hash"]

    verification = _verify_generation(
        states_root=states_root,
        compact_output_path=compact_output_path,
        manifest=manifest,
        snapshot_id=snapshot_id,
        universe=universe,
        expected_as_of=as_of,
        expected_config_hash=config_hash,
        expected_commit=commit,
        output_hash=output_hash,
        confirmed_sessions=confirmed_sessions,
        latest_confirmed_by_code=latest_confirmed_by_code,
        verified_no_trade=set(verified_no_trade),
        session_calendar=session_calendar,
    )
    _raise_failpoint(failpoint, "during_verify")
    if not verification["passed"]:
        raise StateGenerationError(
            "STATE_VERIFICATION_FAILED:"
            + json.dumps(verification, sort_keys=True, default=str)
        )
    verification_path = build_root / "verification.json"
    verification["generation_as_of"] = as_of.isoformat()
    verification["snapshot_id"] = snapshot_id
    verification["universe_contract_version"] = universe.contract_version
    verification["universe_hash"] = universe.member_hash
    verification_hash = _sha256_text(
        json.dumps(
            {
                key: value
                for key, value in verification.items()
                if key != "coverage_rows"
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    )
    write_json_atomic(
        {
            key: value
            for key, value in verification.items()
            if key != "coverage_rows"
        },
        verification_path,
    )
    coverage_rows = verification["coverage_rows"]
    coverage_table = pa.Table.from_pylist(
        [
            {
                "code": row["code"],
                "state_last_processed_date": row[
                    "state_last_processed_date"
                ],
                "latest_confirmed_traded_bar_date": row[
                    "latest_confirmed_traded_bar_date"
                ],
                "generation_as_of": row["generation_as_of"],
                "verified_no_trade_session_n": row[
                    "verified_no_trade_session_n"
                ],
                "unexplained_missing_session_n": row[
                    "unexplained_missing_session_n"
                ],
                "coverage_status": row["coverage_status"],
                "coverage_through": row["coverage_through"],
                "coverage_evidence_hash": row["coverage_evidence_hash"],
            }
            for row in coverage_rows
        ],
        schema=_coverage_schema(),
    )
    pq.write_table(
        coverage_table,
        build_root / "state-coverage.parquet",
        compression="zstd",
    )
    _raise_failpoint(failpoint, "after_verify_before_metadata")

    semantic_hash = verification["state_semantic_root_hash"]
    coverage_root_hash = verification["state_coverage_root_hash"]
    identity = _sha256_text(
        "|".join(
            [
                semantic_hash,
                coverage_root_hash,
                snapshot_content_hash,
                universe.member_hash,
                config_hash,
                commit,
                as_of.isoformat(),
            ]
        )
    )
    generation_id = (
        f"stategen-{as_of.isoformat()}-{identity[:12]}"
    )

    generation_manifest = {
        "generation_id": generation_id,
        "status": STAGED,
        "as_of": as_of.isoformat(),
        "build_mode": (
            "FULL_REBUILD_FROM_CANONICAL" if rebuild else "INCREMENTAL"
        ),
        "snapshot_id": snapshot_id,
        "snapshot_content_hash": snapshot_content_hash,
        "snapshot_validation_hash": (
            screen_pointer[1] if screen_pointer else None
        ),
        "universe_contract_version": universe.contract_version,
        "universe_hash": universe.member_hash,
        "strategy_version": "phase-2d0",
        "strategy_config_hash": config_hash,
        "strategy_code_commit": commit,
        "state_semantic_root_hash": semantic_hash,
        "state_coverage_root_hash": coverage_root_hash,
        "state_coverage_through_as_of_n": verification[
            "state_coverage_through_as_of_n"
        ],
        "verified_no_trade_covered_n": verification[
            "verified_no_trade_covered_n"
        ],
        "state_uncovered_n": verification["state_uncovered_n"],
        "compact_output_hash": output_hash,
        "compact_output_row_n": verification["compact_output_row_n"],
        "verification_hash": verification_hash,
        "decision_use_status": DECISION_USE_STATUS,
        "decision_use_reason": DECISION_USE_REASON,
    }
    write_json_atomic(generation_manifest, build_root / "generation.json")
    _raise_failpoint(failpoint, "after_manifest")

    # Idempotency: same semantic content -> same generation id.
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        existing = metadata.state_generation_by_id(generation_id)
        state_pointer_now = metadata.get_formal_state_pointer()
    if existing is not None and existing["status"] == ACTIVE:
        return StateGenerationResult(
            generation_id=generation_id,
            status=ACTIVE,
            generation_root=(
                layout.root / "screen" / "generations" / generation_id
            ),
            state_semantic_root_hash=semantic_hash,
            compact_output_hash=output_hash,
            verification_hash=verification_hash,
            state_n=verification["state_n"],
            setup_counts=verification["setup_counts"],
            last_processed_20260805_n=verification[
                "last_processed_20260805_n"
            ],
            compact_output_row_n=verification["compact_output_row_n"],
            compact_roundtrip_hash_match=verification[
                "compact_roundtrip_hash_match"
            ],
            pointer_before=state_pointer_now,
            pointer_after=generation_id,
            idempotent=True,
            build_wall_seconds=0.0,
            peak_rss_bytes=peak_rss,
        )

    if dry_run:
        return StateGenerationResult(
            generation_id=generation_id,
            status=STAGED,
            generation_root=build_root,
            state_semantic_root_hash=semantic_hash,
            compact_output_hash=output_hash,
            verification_hash=verification_hash,
            state_n=verification["state_n"],
            setup_counts=verification["setup_counts"],
            last_processed_20260805_n=verification[
                "last_processed_20260805_n"
            ],
            compact_output_row_n=verification["compact_output_row_n"],
            compact_roundtrip_hash_match=verification[
                "compact_roundtrip_hash_match"
            ],
            pointer_before=state_pointer_now,
            pointer_after=None,
            idempotent=False,
            build_wall_seconds=(_utc_now() - started).total_seconds(),
            peak_rss_bytes=peak_rss,
        )

    # Finalize into the content-addressed generations namespace.
    final_root = layout.root / "screen" / "generations" / generation_id
    if final_root.exists():
        existing_hash = state_semantic_root_hash(
            final_root / "states"
        )[0]
        if existing_hash != semantic_hash:
            raise StateGenerationError("existing generation hash mismatch")
    else:
        final_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(build_root), str(final_root))
    _raise_failpoint(failpoint, "after_verify_before_metadata")

    with WarehouseMetadata(layout.duckdb_path) as metadata:
        with metadata.promotion_transaction() as tx:
            tx.insert_state_generation(
                generation_id=generation_id,
                snapshot_id=snapshot_id,
                snapshot_content_hash=snapshot_content_hash,
                snapshot_validation_hash=(
                    screen_pointer[1] if screen_pointer else None
                ),
                universe_contract_version=universe.contract_version,
                universe_hash=universe.member_hash,
                strategy_version="phase-2d0",
                strategy_config_hash=config_hash,
                strategy_code_commit=commit,
                as_of=as_of,
                status=VERIFIED,
                state_semantic_root_hash=semantic_hash,
                compact_output_hash=output_hash,
                verification_hash=verification_hash,
                created_at=_utc_now(),
            )
            tx.insert_state_generation_promotion(
                generation_id=generation_id,
                snapshot_id=snapshot_id,
                snapshot_hash=snapshot_content_hash,
                universe_contract=universe.contract_version,
                universe_hash=universe.member_hash,
                strategy_version="phase-2d0",
                strategy_config_hash=config_hash,
                code_commit=commit,
                state_semantic_root_hash=semantic_hash,
                compact_output_hash=output_hash,
                verification_hash=verification_hash,
                from_state=STAGED,
                to_state=ACTIVE,
                promoted_at=_utc_now(),
                promotion_reason=PROMOTION_REASON,
            )
            _raise_failpoint(failpoint, "during_metadata_transaction")
            tx.update_state_generation_status(
                generation_id=generation_id,
                status=ACTIVE,
            )
            _raise_failpoint(failpoint, "before_pointer_update")
            tx.set_formal_state_pointer(
                generation_id=generation_id,
                updated_at=_utc_now(),
            )

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        pointer_after = metadata.get_formal_state_pointer()
    return StateGenerationResult(
        generation_id=generation_id,
        status=ACTIVE,
        generation_root=final_root,
        state_semantic_root_hash=semantic_hash,
        compact_output_hash=output_hash,
        verification_hash=verification_hash,
        state_n=verification["state_n"],
        setup_counts=verification["setup_counts"],
        last_processed_20260805_n=verification["last_processed_20260805_n"],
        compact_output_row_n=verification["compact_output_row_n"],
        compact_roundtrip_hash_match=verification[
            "compact_roundtrip_hash_match"
        ],
        pointer_before=state_pointer_now,
        pointer_after=pointer_after,
        idempotent=False,
        build_wall_seconds=(_utc_now() - started).total_seconds(),
        peak_rss_bytes=peak_rss,
    )
