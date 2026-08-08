"""R6A incremental-value contract tests (contract-only; outcome-blind)."""

from __future__ import annotations

import inspect
from pathlib import Path
import sys

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r6a_incremental_contract_v01 as r6a  # noqa: E402


pytestmark = pytest.mark.cloud_ci


def test_baseline_set_exactly_b4_b7():
    assert set(r6a.BASELINES) == {"B4", "B5", "B6", "B7"}
    assert r6a.BASELINES["B6"] == "PRIMARY_BASELINE"
    assert r6a.BASELINES["B4"] == "SECONDARY_BASELINE"
    assert r6a.BASELINES["B5"] == "WEAK_CONTROL_BASELINE"
    assert r6a.BASELINES["B7"] == "WEAK_CONTROL_BASELINE"


def test_primary_baseline_exactly_b6():
    rows = r6a.build_registry()
    primary = [r for r in rows if r["baseline_role"] == "PRIMARY_BASELINE"]
    assert len({r["baseline_id"] for r in primary}) == 1
    assert primary[0]["baseline_id"] == "B6"


def test_factor_set_exact():
    rows = r6a.build_registry()
    factors = {r["factor_name"] for r in rows}
    assert factors == set(r6a.F3_FACTORS) | set(r6a.F6_CONTROLS)
    assert len(r6a.F3_FACTORS) == 4
    assert len(r6a.F6_CONTROLS) == 2
    for r in rows:
        if r["factor_family"] == "F3":
            assert r["factor_role"] == "PRIMARY_INCREMENTAL_CANDIDATE"
        else:
            assert r["factor_role"] == "ROBUSTNESS_CONTROL"


def test_r3_direction_pinned():
    rows = r6a.build_registry()
    for factor, direction in r6a.EXPECTED_R3_DIRECTION.items():
        got = {r["r3_direction"] for r in rows if r["factor_name"] == factor}
        assert got == {direction}, factor
        # direction comes from the frozen R3 artifact, not hardcoded per row
        assert r6a.load_r3_direction(factor) == direction


def test_r4_status_pinned():
    rows = r6a.build_registry()
    for factor, status in r6a.EXPECTED_R4_STATUS.items():
        got = {r["r4_status"] for r in rows if r["factor_name"] == factor}
        assert got == {status}, factor
        assert r6a.load_r4_status(factor) == status


def test_material_effect_sourced_from_r4():
    assert r6a.MATERIAL_EFFECT == 0.03
    assert "R4_STABILITY_CONTRACT_V01.md" in r6a.MATERIAL_EFFECT_SOURCE
    rows = r6a.build_registry()
    for r in rows:
        assert r["material_effect_threshold"] == "0.03"
        assert "R4" in r["material_effect_source"]


def test_r5b_signal_sha_pinned():
    sha = r3a.sha256_file(r6a.SIGNALS_CSV)
    assert sha == r6a.SIGNALS_SHA
    rows = r6a.build_registry()
    for r in rows:
        assert r["benchmark_signal_artifact_sha"] == r6a.SIGNALS_SHA
        assert r["feature_artifact_sha"] == r6a.FEATURE_SHA


def test_no_direction_flip_no_threshold_optimization():
    src = inspect.getsource(r6a)
    # No optimization machinery: no grid / cutoff search / AUC flip logic.
    assert "grid" not in src.lower()
    assert "threshold_search" not in src.lower()
    assert "binary_auc" not in src
    assert "if auc" not in src.lower()
    rows = r6a.build_registry()
    for r in rows:
        assert "no direction flip" in r["known_limitation"]
        assert "no threshold optimization" in r["known_limitation"]


def test_outcome_blind_r6a():
    """R6A must not read outcome labels or compute any outcome metric."""
    src = inspect.getsource(r6a)
    assert "OUTCOME_CSV" not in src
    assert "outcome_3d" not in src
    assert "outcome_5d" not in src
    assert "read_csv" not in src or "OUTCOME" not in src
    rows = r6a.build_registry()
    assert all(r["status"] == "CONTRACT_ONLY" for r in rows)


def test_registry_valid_and_deterministic(tmp_path):
    rows = r6a.build_registry()
    assert r6a.validate_registry(rows) == []
    assert len(rows) == 24  # 4 baselines x (4 F3 + 2 F6)
    df = pd.DataFrame(rows)
    p1, p2 = tmp_path / "a.csv", tmp_path / "b.csv"
    df.to_csv(p1, index=False)
    df.to_csv(p2, index=False)
    assert p1.read_bytes() == p2.read_bytes()
