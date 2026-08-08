"""R5B benchmark execution targeted tests (frozen contract semantics)."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r5b_benchmark_execution_v01 as r5b  # noqa: E402


# ---- B4 exact boundaries ----


def test_b4_boundaries():
    d = pd.Series([1, 2, 3, 5, 6, np.nan], dtype="float64")
    elig, sig = r5b.b4_signal(d)
    assert elig.tolist() == [True, True, True, True, True, False]
    assert sig.tolist() == [False, True, True, True, False, False]


# ---- B5 exact equality / depth ----


def test_b5_exact_equality_is_signal():
    assert r5b.b5_signal(10.0, 9.6) is True      # exactly -4%
    assert r5b.b5_signal(10.0, 9.599) is False   # below -4%
    assert r5b.b5_signal(10.0, 9.7) is True      # shallower


# ---- B6 exact equality / zero volume ----


def test_b6_exact_equality_is_signal():
    assert r5b.b6_signal(100.0, 85.0) is True    # exactly 0.85
    assert r5b.b6_signal(100.0, 86.0) is False
    assert r5b.b6_signal(100.0, 84.0) is True


def test_b6_zero_volume_is_ineligible():
    # eligibility handled by caller; zero volume must never reach the ratio
    with pytest.raises(ZeroDivisionError):
        r5b.b6_signal(0.0, 85.0)


# ---- B7 reference semantics ----


def test_b7_less_than_60_history():
    highs = np.arange(1.0, 31.0)  # 30 sessions
    assert r5b.b7_reference_high(highs) == 30.0


def test_b7_exactly_60_history():
    highs = np.arange(1.0, 61.0)
    assert r5b.b7_reference_high(highs) == 60.0


def test_b7_more_than_60_truncation():
    highs = np.arange(1.0, 71.0)  # 70 sessions
    assert r5b.b7_reference_high(highs) == 70.0  # last 60 -> max 70
    highs2 = np.concatenate([np.full(10, 999.0), np.arange(1.0, 61.0)])
    assert r5b.b7_reference_high(highs2) == 60.0  # 999 outside window


def test_b7_no_reference():
    assert r5b.b7_reference_high(np.array([])) is None


def test_b7_equality_not_signal_and_t0_d_excluded():
    # equality: close_D == ref -> NOT signal (strict greater in caller)
    ref = r5b.b7_reference_high(np.array([10.0, 11.0, 12.0]))
    assert ref == 12.0


# ---- denominator contract ----


def _sig_df():
    return pd.DataFrame({
        "episode_id": ["e1", "e2", "e3", "e4"],
        "B4_eligible": [True, True, True, True],
        "B4_signal": [True, False, False, True],
        "B5_eligible": [True, True, True, False],
        "B5_signal": [True, False, False, False],
        "B6_eligible": [True, True, True, True],
        "B6_signal": [True, False, True, False],
        "B7_eligible": [True, True, True, True],
        "B7_signal": [False, False, False, True],
        "common_eligible": [True, True, True, False],
    })


def _out_df():
    return pd.DataFrame({
        "episode_id": ["e1", "e2", "e3", "e4"],
        "outcome_3d": ["SUCCESS", "STRUCTURE_FAIL", "NO_LAUNCH", "UNKNOWN"],
        "outcome_5d": ["SUCCESS", "SUCCESS", "NO_LAUNCH", "UNKNOWN"],
    })


def test_data_ineligible_not_counted_as_nonsignal():
    sig, out = _sig_df(), _out_df()
    row = r5b.benchmark_row(
        sig, out, "B5", np.ones(len(sig), dtype=bool), "outcome_3d")
    # e4 is B5-ineligible -> excluded from both signal and non-signal
    assert row["signal_n"] == 1
    assert row["non_signal_n"] == 2
    assert row["data_eligible_n"] == 3
    assert row["unknown_n"] == 0


def test_unknown_excluded_from_metrics():
    sig, out = _sig_df(), _out_df()
    row = r5b.benchmark_row(
        sig, out, "B7", np.ones(len(sig), dtype=bool), "outcome_3d")
    # e4 eligible with UNKNOWN -> excluded; e1-e3 known
    assert row["data_eligible_n"] == 4
    assert row["outcome_known_n"] == 3
    assert row["unknown_n"] == 1
    assert row["signal_n"] == 0  # e4 (the only signal) excluded
    assert row["non_signal_n"] == 3


def test_common_sample_exact_intersection():
    sig, out = _sig_df(), _out_df()
    common = sig["common_eligible"].to_numpy().astype(bool)
    row = r5b.benchmark_row(sig, out, "B5", common, "outcome_3d")
    assert row["sample"] == "COMMON"
    assert row["data_eligible_n"] == 3
    row_own = r5b.benchmark_row(
        sig, out, "B5", np.ones(len(sig), dtype=bool), "outcome_3d")
    assert row_own["data_eligible_n"] == 3  # B5 own == common here


# ---- binary AUC constant signal ----


def test_constant_signal_auc_not_fake():
    assert r5b.binary_auc_signal(np.ones(5), np.array([1, 0, 1, 0, 1])) == (
        "NOT_IDENTIFIABLE_CONSTANT_SIGNAL")
    assert r5b.binary_auc_signal(np.zeros(5), np.array([1, 0, 1, 0, 1])) == (
        "NOT_IDENTIFIABLE_CONSTANT_SIGNAL")


def test_binary_auc_signal_direction():
    # signal == label -> perfect separation AUC 1.0
    assert r5b.binary_auc_signal(np.array([1, 1, 0, 0]), np.array([1, 1, 0, 0])) == 1.0
    # anti-signal -> AUC 0.0 (never flipped)
    assert r5b.binary_auc_signal(np.array([1, 1, 0, 0]), np.array([0, 0, 1, 1])) == 0.0


# ---- OR zero-cell policy (project-consistent 0.5 correction) ----


def test_or_zero_cell_policy():
    r = r5b.or_2x2(0, 5, 3, 4)
    assert r["zero_cell_corrected"] is True
    assert r["signal_success"] == 0 and r["signal_nonsuccess"] == 5
    assert np.isfinite(r["or"])


def test_or_normal_cells_no_correction():
    r = r5b.or_2x2(4, 6, 2, 8)
    assert r["zero_cell_corrected"] is False
    assert abs(r["or"] - (4 / 6) / (2 / 8)) < 1e-9


# ---- classification rule (pre-registered) ----


def test_classification_rules():
    assert r5b.classify_benchmark(0.06, 0.04, 1.5, 0.55) == "POSITIVE_BENCHMARK"
    assert r5b.classify_benchmark(0.03, 0.05, 0.6, 0.45) == "NEGATIVE_BENCHMARK"
    assert r5b.classify_benchmark(0.05, 0.05, 1.0, 0.5) == "NEUTRAL_BENCHMARK"
    assert r5b.classify_benchmark(float("nan"), 0.05, 1.0, 0.5) == "DATA_LIMITED"
    assert r5b.classify_benchmark(0.05, 0.04, 1.2, "NOT_IDENTIFIABLE") == "DATA_LIMITED"


# ---- 3D/5D same signal invariance ----


def test_3d_5d_same_signal_invariance():
    sig, out = _sig_df(), _out_df()
    mask = np.ones(len(sig), dtype=bool)
    r3 = r5b.benchmark_row(sig, out, "B6", mask, "outcome_3d")
    r5 = r5b.benchmark_row(sig, out, "B6", mask, "outcome_5d")
    assert r3["signal_n"] == r5["signal_n"]
    assert r3["non_signal_n"] == r5["non_signal_n"]


# ---- fail-closed gates ----


def test_registry_gate_rejects_broken_ready_set(monkeypatch):
    broken = [dict(r) for r in r5b.r5a.REGISTRY]
    for r in broken:
        if r["benchmark_id"] == "B5":
            r["status"] = "UNDERDEFINED"
    monkeypatch.setattr(r5b.r5a, "REGISTRY", broken)
    with pytest.raises(RuntimeError, match="B5 status != READY"):
        r5b.registry_gate()


def test_input_gate_positive():
    feat, out = r5b.input_gate()
    assert len(feat) == 8682 and len(out) == 8682
    assert set(feat["episode_id"]) == set(out["episode_id"])


def test_canonical_sha_gate():
    assert r3a.sha256_file(r5b.r5a.CANONICAL_SNAPSHOT) == r5b.r5a.SNAPSHOT_SHA
