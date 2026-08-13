"""P1: frozen-reference differential verifier tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from limit_pullback.evidence import read_run_summary, verify_against_reference

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "screen" / "runs"
REFERENCE_JSON = (
    ROOT
    / ".goal-task"
    / "architecture-convergence-v01"
    / "baseline"
    / "frozen-rebuild-summary-v01.json"
)


@pytest.mark.skipif(
    not (RUNS_DIR / "screen-rebuild-2026-07-31-snap-2026-07-0c0793274983.json").exists(),
    reason="frozen baseline run artifact not present in this checkout",
)
def test_baseline_summary_extraction_matches_recorded_reference():
    reference = json.loads(REFERENCE_JSON.read_text(encoding="utf-8"))
    summary = read_run_summary(
        RUNS_DIR / "screen-rebuild-2026-07-31-snap-2026-07-0c0793274983.json"
    )
    assert summary["output_hash"] == reference["output_hash"]
    assert summary["rows_count"] == reference["rows_count"]
    assert summary["universe_size"] == reference["universe_size"]
    assert summary["status_counts"] == reference["status_counts"]
    assert summary["chunk_runtimes"] == reference["chunk_runtimes"]


@pytest.mark.skipif(
    not (RUNS_DIR / "screen-rebuild-2026-07-31-snap-2026-07-e7c55287ff3f.json").exists(),
    reason="latest run artifact not present in this checkout",
)
def test_latest_rebuild_has_zero_state_signal_diff_vs_frozen_reference():
    reference = json.loads(REFERENCE_JSON.read_text(encoding="utf-8"))
    result = verify_against_reference(
        RUNS_DIR / "screen-rebuild-2026-07-31-snap-2026-07-e7c55287ff3f.json",
        reference,
    )
    assert result["passed"], result["problems"]
