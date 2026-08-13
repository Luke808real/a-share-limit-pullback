"""Wire the evidence protocol into formal run emission (P6, additive)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from limit_pullback.evidence.verification.receipt import write_run_receipt


def emit_formal_run_receipt(
    *,
    artifact_path: Path,
    reference: dict[str, Any] | None,
    runtime_commit: str | None,
    strategy_version: str | None,
    config_hash: str | None,
    asl_version: str | None,
    data_snapshot_id: str | None,
    universe_id: str | None,
    predecessor_generation_id: str | None,
    engine_versions: dict[str, str] | None = None,
) -> Path:
    """Emit a hashable receipt beside a formal run artifact."""

    receipt = write_run_receipt(
        artifact_path=artifact_path,
        reference=reference,
        runtime_commit=runtime_commit,
        strategy_version=strategy_version,
        config_hash=config_hash,
        asl_version=asl_version,
        data_snapshot_id=data_snapshot_id,
        universe_id=universe_id,
        universe_hash=None,
        predecessor_generation_id=predecessor_generation_id,
        engine_versions=engine_versions,
    )
    return artifact_path.with_name(artifact_path.name + ".receipt.json")


__all__ = ["emit_formal_run_receipt"]
