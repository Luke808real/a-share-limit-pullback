"""R6B incremental execution targeted tests (frozen state machine + samples).

All tests read only committed artifacts (feature/outcome/signals/registry
CSVs); no local market database required -> cloud_ci.
"""

from __future__ import annotations

import inspect
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r6b_incremental_execution_v01 as r6b  # noqa: E402


pytestmark = pytest.mark.cloud_ci


# ---- frozen direction semantics ----


def test_direction_semantics():
    assert r6b.direction_of(0.51) == "POSITIVE"
    assert r6b.direction_of(0.49) == "NEGATIVE"
    assert r6b.direction_of(0.50) == "NEUTRAL"
    assert r6b.direction_of(float("nan")) == "UNKNOWN"
    assert r6b.direction_of("NOT_IDENTIFIABLE") == "UNKNOWN"
    assert r6b.direction_of(None) == "UNKNOWN"


# ---- frozen classification state machine ----


def test_classification_supported():
    c, note = r6b.classify_incremental(0.58, 0.57, "POSITIVE", True)
    assert c == "INCREMENTAL_SUPPORTED" and note == ""


def test_classification_weak():
    c, note = r6b.classify_incremental(0.52, 0.53, "POSITIVE", True)
    assert c == "INCREMENTAL_WEAK" and note == ""


def test_classification_weak_with_neutral_sensitivity():
    c, note = r6b.classify_incremental(0.52, 0.50, "POSITIVE", True)
    assert c == "INCREMENTAL_WEAK"
    assert note == "WEAK_WITH_NEUTRAL_SENSITIVITY"


def test_classification_3d_reverse_no_value():
    c, _ = r6b.classify_incremental(0.44, 0.55, "POSITIVE", True)
    assert c == "NO_INCREMENTAL_VALUE"


def test_classification_3d_neutral_no_value():
    c, _ = r6b.classify_incremental(0.50, 0.52, "POSITIVE", True)
    assert c == "NO_INCREMENTAL_VALUE"


def test_classification_material_3d_but_5d_reversed_no_value():
    c, note = r6b.classify_incremental(0.58, 0.44, "POSITIVE", True)
    assert c == "NO_INCREMENTAL_VALUE"
    assert note == "SENSITIVITY_REVERSED_OR_NEUTRAL"


def test_classification_material_3d_but_5d_neutral_no_value():
    c, _ = r6b.classify_incremental(0.58, 0.50, "POSITIVE", True)
    assert c == "NO_INCREMENTAL_VALUE"


def test_classification_weak_but_5d_opposite_no_value():
    c, note = r6b.classify_incremental(0.52, 0.45, "POSITIVE", True)
    assert c == "NO_INCREMENTAL_VALUE"
    assert note == "SENSITIVITY_OPPOSITE"


def test_classification_data_limited():
    c, _ = r6b.classify_incremental(0.58, 0.57, "POSITIVE", False)
    assert c == "DATA_LIMITED"


def test_classification_negative_direction_supported():
    c, _ = r6b.classify_incremental(0.42, 0.43, "NEGATIVE", True)
    assert c == "INCREMENTAL_SUPPORTED"


# ---- no direction flip ----


def test_no_direction_flip_machinery():
    src = inspect.getsource(r6b)
    assert "max(auc" not in src.lower()
    assert "1 - auc" not in src.lower().replace("auc - 0.5", "")
    assert "1-auc" not in src.lower()
    # 0.5 -> NEUTRAL is enforced by test_direction_semantics (authoritative);
    # docstring prohibition text is allowed to mention the pattern.


# ---- sample semantics on synthetic frames ----


def _frames():
    feat = pd.DataFrame({
        "episode_id": ["e1", "e2", "e3", "e4", "e5"],
        "symbol": ["600000"] * 5,
        "anchor_date": ["2024-07-01"] * 5,
        "candidate_date": ["2024-07-03"] * 5,
        "pullback_volume_ratio": [0.5, 0.6, 0.4, np.nan, 0.7],
    })
    out = pd.DataFrame({
        "episode_id": ["e1", "e2", "e3", "e4", "e5"],
        "outcome_3d": ["SUCCESS", "STRUCTURE_FAIL", "NO_LAUNCH", "UNKNOWN",
                       "FAILED_BREAKOUT"],
        "outcome_5d": ["SUCCESS", "SUCCESS", "NO_LAUNCH", "UNKNOWN",
                       "FAILED_BREAKOUT"],
    })
    sig = pd.DataFrame({
        "episode_id": ["e1", "e2", "e3", "e4", "e5"],
        "B6_eligible": [True, True, True, True, False],
        "B6_signal": [True, False, True, True, False],
        "common_eligible": [True, True, True, False, False],
    })
    reg = pd.Series({
        "baseline_id": "B6", "baseline_role": "PRIMARY_BASELINE",
        "factor_name": "pullback_volume_ratio", "factor_family": "F3",
        "factor_role": "PRIMARY_INCREMENTAL_CANDIDATE",
        "r3_direction": "NEGATIVE",
    })
    return feat, out, sig, reg


def test_sample_semantics_own_signal():
    feat, out, sig, reg = _frames()
    row = r6b.conditional_row(feat, out, sig, "B6", "pullback_volume_ratio",
                              "OWN", "SIGNAL", "outcome_3d", reg)
    # eligible & signal: e1, e3, e4; factor finite: e1, e3 (e4 NaN);
    # outcome known: e1 (SUCCESS), e3 (NO_LAUNCH); e4 UNKNOWN excluded
    assert row["eligible_group_n"] == 3
    assert row["factor_nonmissing_n"] == 2
    assert row["outcome_known_n"] == 2
    assert row["success_n"] == 1 and row["non_success_n"] == 1
    assert row["identifiability_status"] == "IDENTIFIABLE"


def test_sample_semantics_own_nonsignal():
    feat, out, sig, reg = _frames()
    row = r6b.conditional_row(feat, out, sig, "B6", "pullback_volume_ratio",
                              "OWN", "NON_SIGNAL", "outcome_3d", reg)
    # eligible & non-signal: e2 only (e5 ineligible is NOT non-signal)
    assert row["eligible_group_n"] == 1
    assert row["outcome_known_n"] == 1  # e2 STRUCTURE_FAIL
    assert row["success_n"] == 0 and row["non_success_n"] == 1
    assert row["identifiability_status"] == "NOT_IDENTIFIABLE"
    assert row["missing_reason"] == "NO_SUCCESS"


def test_sample_semantics_common():
    feat, out, sig, reg = _frames()
    row = r6b.conditional_row(feat, out, sig, "B6", "pullback_volume_ratio",
                              "COMMON", "SIGNAL", "outcome_3d", reg)
    # common_eligible: e1, e2, e3; signal among them: e1, e3
    assert row["eligible_group_n"] == 2
    assert row["factor_nonmissing_n"] == 2
    assert row["outcome_known_n"] == 2


def test_signal_nonsignal_disjoint():
    feat, out, sig, reg = _frames()
    sig_row = r6b.conditional_row(feat, out, sig, "B6", "pullback_volume_ratio",
                                  "OWN", "SIGNAL", "outcome_3d", reg)
    non_row = r6b.conditional_row(feat, out, sig, "B6", "pullback_volume_ratio",
                                  "OWN", "NON_SIGNAL", "outcome_3d", reg)
    assert sig_row["eligible_group_n"] + non_row["eligible_group_n"] == 4


# ---- frozen registry / pins ----


def test_frozen_registry_values():
    reg = r6b.registry_gate()
    assert len(reg) == 24
    assert set(reg["baseline_id"]) == {"B4", "B5", "B6", "B7"}
    primary = reg.loc[reg["baseline_role"] == "PRIMARY_BASELINE",
                      "baseline_id"].unique()
    assert list(primary) == ["B6"]
    for factor, direction in r6b.FROZEN_R3_DIRECTION.items():
        assert set(reg.loc[reg["factor_name"] == factor, "r3_direction"]) == {
            direction}
    assert {float(x) for x in reg["material_effect_threshold"]} == {0.03}


def test_input_gate_positive():
    feat, out, sig = r6b.input_gate()
    assert len(feat) == 8682 and len(out) == 8682 and len(sig) == 8682
    assert (feat["episode_id"].to_numpy() == out["episode_id"].to_numpy()).all()
    assert (feat["episode_id"].to_numpy() == sig["episode_id"].to_numpy()).all()


# ---- three-way episode alignment (R6B alignment closeout) ----


def _aligned_frames():
    feat = pd.DataFrame({
        "episode_id": ["e1", "e2", "e3", "e4"],
        "symbol": ["600001", "600002", "600003", "600004"],
        "anchor_date": ["2024-07-01"] * 4,
        "candidate_date": ["2024-07-03"] * 4,
        "median_range_ratio": [0.4, 0.5, 0.6, 0.7],
    })
    out = pd.DataFrame({
        "episode_id": ["e1", "e2", "e3", "e4"],
        "symbol": ["600001", "600002", "600003", "600004"],
        "anchor_date": ["2024-07-01"] * 4,
        "candidate_date": ["2024-07-03"] * 4,
        "outcome_3d": ["SUCCESS", "SUCCESS", "STRUCTURE_FAIL", "NO_LAUNCH"],
        "outcome_5d": ["SUCCESS", "SUCCESS", "STRUCTURE_FAIL", "NO_LAUNCH"],
    })
    sig = pd.DataFrame({
        "episode_id": ["e1", "e2", "e3", "e4"],
        "symbol": ["600001", "600002", "600003", "600004"],
        "anchor_date": ["2024-07-01"] * 4,
        "candidate_date": ["2024-07-03"] * 4,
        "B6_eligible": [True] * 4,
        "B6_signal": [True, True, False, False],
        "common_eligible": [True] * 4,
    })
    return feat, out, sig


def test_shuffle_alignment_recovers_canonical_order():
    feat, out, sig = _aligned_frames()
    shuffled_out = out.iloc[[2, 0, 3, 1]].reset_index(drop=True)   # e3 e1 e4 e2
    shuffled_sig = sig.iloc[[3, 1, 0, 2]].reset_index(drop=True)   # e4 e2 e1 e3
    a, b, c = r6b.align_three_way(feat, shuffled_out, shuffled_sig)
    assert b["episode_id"].tolist() == ["e1", "e2", "e3", "e4"]
    assert c["episode_id"].tolist() == ["e1", "e2", "e3", "e4"]


def test_shuffle_metrics_identical_to_canonical_order():
    feat, out, sig = _aligned_frames()
    reg = pd.Series({
        "baseline_id": "B6", "baseline_role": "PRIMARY_BASELINE",
        "factor_name": "median_range_ratio", "factor_family": "F3",
        "factor_role": "PRIMARY_INCREMENTAL_CANDIDATE",
        "r3_direction": "NEGATIVE",
    })
    canon = r6b.conditional_row(feat, out, sig, "B6", "median_range_ratio",
                                "COMMON", "SIGNAL", "outcome_3d", reg)
    shuffled_out = out.iloc[[2, 0, 3, 1]].reset_index(drop=True)
    shuffled_sig = sig.iloc[[3, 1, 0, 2]].reset_index(drop=True)
    a, b, c = r6b.align_three_way(feat, shuffled_out, shuffled_sig)
    aligned = r6b.conditional_row(a, b, c, "B6", "median_range_ratio",
                                  "COMMON", "SIGNAL", "outcome_3d", reg)
    for key in ["eligible_group_n", "outcome_known_n", "success_n",
                "non_success_n", "native_auc", "effect", "native_direction"]:
        av, cv = aligned[key], canon[key]
        same = (av == cv) or (
            isinstance(av, float) and isinstance(cv, float)
            and pd.isna(av) and pd.isna(cv)
        )
        assert same, key


def test_alignment_identity_mismatch_fails_closed():
    feat, out, sig = _aligned_frames()
    bad_sig = sig.copy()
    bad_sig.loc[0, "symbol"] = "999999"
    with pytest.raises(RuntimeError, match="feature/signals identity binding"):
        r6b.align_three_way(feat, out, bad_sig)


def test_alignment_anchor_mismatch_fails_closed():
    feat, out, sig = _aligned_frames()
    bad_sig = sig.copy()
    bad_sig.loc[1, "anchor_date"] = "2024-07-02"
    with pytest.raises(RuntimeError, match="feature/signals identity binding"):
        r6b.align_three_way(feat, out, bad_sig)


def test_alignment_candidate_mismatch_fails_closed():
    feat, out, sig = _aligned_frames()
    bad_out = out.copy()
    bad_out.loc[2, "candidate_date"] = "2024-07-04"
    with pytest.raises(RuntimeError, match="feature/outcome identity binding"):
        r6b.align_three_way(feat, bad_out, sig)


def test_alignment_episode_set_mismatch_fails_closed():
    feat, out, sig = _aligned_frames()
    bad_out = out.copy()
    bad_out.loc[0, "episode_id"] = "e9"
    with pytest.raises(RuntimeError, match="episode_id set mismatch"):
        r6b.align_three_way(feat, bad_out, sig)


def test_b6_mrr_primary_exact_pin():
    """Frozen byte-invariance pin: B6 x median_range_ratio x COMMON x SIGNAL."""
    s = pd.read_csv(REPO_ROOT / "research" / "second_launch" / "factors_v01"
                    / "r6b_incremental_summary_v01.csv")
    row = s[(s["baseline_id"] == "B6") & (s["factor_name"] == "median_range_ratio")
            & (s["sample_scope"] == "COMMON")].iloc[0]
    # CSV round-trip keeps full precision within 1e-14 of the in-memory value
    assert abs(row["auc_3d_signal"] - 0.42221997070987116) < 1e-14
    assert abs(row["effect_3d_signal"] - 0.07778002929012884) < 1e-14
    assert abs(row["auc_5d_signal"] - 0.40993238304093566) < 1e-14
    assert row["incremental_classification"] == "INCREMENTAL_SUPPORTED"
