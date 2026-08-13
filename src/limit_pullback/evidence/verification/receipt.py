"""Run receipt writer (P2, additive only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from limit_pullback.evidence.verification.fingerprint import (
    build_version_fingerprint,
    fingerprint_hash,
)
from limit_pullback.evidence.verification.frozen_differential import (
    read_run_summary,
    verify_against_reference,
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_run_receipt(
    *,
    artifact_path: Path,
    reference: dict[str, Any] | None,
    runtime_commit: str | None,
    strategy_version: str | None,
    config_hash: str | None,
    asl_version: str | None,
    data_snapshot_id: str | None,
    universe_id: str | None,
    universe_hash: str | None,
    predecessor_generation_id: str | None,
    engine_versions: dict[str, str] | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Write a hashable receipt beside (or at) the run artifact."""

    summary = read_run_summary(artifact_path)
    fingerprint = build_version_fingerprint(
        runtime_commit=runtime_commit,
        strategy_version=strategy_version,
        config_hash=config_hash,
        asl_version=asl_version,
        data_snapshot_id=data_snapshot_id,
        universe_id=universe_id,
        universe_hash=universe_hash,
        predecessor_generation_id=predecessor_generation_id,
        engine_versions=engine_versions,
    )
    verification = (
        verify_against_reference(artifact_path, reference)
        if reference is not None
        else None
    )
    receipt = {
        "run_id": summary.get("run_id"),
        "output_hash": summary.get("output_hash"),
        "written_at": _now_utc(),
        "fingerprint": fingerprint,
        "fingerprint_hash": fingerprint_hash(fingerprint),
        "verification": verification,
    }
    target = receipt_path or artifact_path.with_name(
        artifact_path.name + ".receipt.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return receipt


__all__ = ["write_run_receipt"]
