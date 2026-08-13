"""P2 evidence protocol tests: fingerprint and receipt (additive only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from limit_pullback.evidence import (
    build_version_fingerprint,
    emit_formal_run_receipt,
    fingerprint_hash,
    write_run_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "screen" / "runs"
REFERENCE_JSON = (
    ROOT
    / ".goal-task"
    / "architecture-convergence-v01"
    / "baseline"
    / "frozen-rebuild-summary-v01.json"
)


def test_fingerprint_is_deterministic():
    first = build_version_fingerprint(
        runtime_commit="1cb5fb7a",
        strategy_version="phase-2d0",
        config_hash="47a0ea2b",
        asl_version="VFLASH_ASL_PHASE1A_V1",
        data_snapshot_id="snap-2026-07-31-b5f84004de8a",
        universe_id="phase-2d0",
        universe_hash="member-hash",
        predecessor_generation_id=None,
        engine_versions={"state": "r5"},
    )
    second = build_version_fingerprint(
        engine_versions={"state": "r5"},
        predecessor_generation_id=None,
        universe_hash="member-hash",
        universe_id="phase-2d0",
        data_snapshot_id="snap-2026-07-31-b5f84004de8a",
        asl_version="VFLASH_ASL_PHASE1A_V1",
        config_hash="47a0ea2b",
        strategy_version="phase-2d0",
        runtime_commit="1cb5fb7a",
    )
    assert first == second
    assert len(fingerprint_hash(first)) == 64


@pytest.mark.skipif(
    not (RUNS_DIR / "screen-rebuild-2026-07-31-snap-2026-07-e7c55287ff3f.json").exists(),
    reason="latest run artifact not present in this checkout",
)
def test_run_receipt_is_written_and_hashable(tmp_path):
    reference = json.loads(REFERENCE_JSON.read_text(encoding="utf-8"))
    receipt = write_run_receipt(
        artifact_path=RUNS_DIR
        / "screen-rebuild-2026-07-31-snap-2026-07-e7c55287ff3f.json",
        reference=reference,
        runtime_commit="1cb5fb7a",
        strategy_version="phase-2d0",
        config_hash="47a0ea2b",
        asl_version="VFLASH_ASL_PHASE1A_V1",
        data_snapshot_id="snap-2026-07-31-b5f84004de8a",
        universe_id="phase-2d0",
        universe_hash="member-hash",
        predecessor_generation_id=None,
        engine_versions={"state": "r5"},
        receipt_path=tmp_path / "run.receipt.json",
    )
    assert receipt["verification"]["passed"] is True
    assert receipt["output_hash"].startswith("9abb16e4")
    stored = json.loads((tmp_path / "run.receipt.json").read_text())
    assert stored == receipt
    assert len(stored["fingerprint_hash"]) == 64


def test_formal_run_receipt_emission(tmp_path):
    artifact = tmp_path / "run.json"
    artifact.write_text(
        json.dumps(
            {
                "run_id": "run-x",
                "output_hash": "9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec",
                "rows_count": 1,
                "universe_size": 1,
                "status_counts": {"NORMAL": 1},
            }
        ),
        encoding="utf-8",
    )
    receipt_path = emit_formal_run_receipt(
        artifact_path=artifact,
        reference=None,
        runtime_commit="1cb5fb7a",
        strategy_version="phase-2d0",
        config_hash="47a0ea2b",
        asl_version="VFLASH_ASL_PHASE1A_V1",
        data_snapshot_id="snap-2026-07-31-b5f84004de8a",
        universe_id="phase-2d0",
        predecessor_generation_id=None,
        engine_versions={"runtime": "chunked-v1"},
    )
    assert receipt_path.exists()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["run_id"] == "run-x"
    assert receipt["output_hash"].startswith("9abb16e4")
    assert receipt["fingerprint"]["strategy_version"] == "phase-2d0"
    assert len(receipt["fingerprint_hash"]) == 64
