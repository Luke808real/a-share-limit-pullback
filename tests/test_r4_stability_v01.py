"""R4 stability pre-registered rule regression tests."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r4_stability_v01 as r4  # noqa: E402


# ---- board mapping ----


def test_board_mapping_deterministic():
    cases = {
        "600000": "SH_MAIN",
        "601318": "SH_MAIN",
        "603259": "SH_MAIN",
        "605117": "SH_MAIN",
        "688981": "SH_STAR",
        "689009": "SH_STAR",
        "000001": "SZ_MAIN",
        "001979": "SZ_MAIN",
        "002594": "SZ_MAIN",
        "003816": "SZ_MAIN",
        "300750": "SZ_CHINEXT",
        "301236": "SZ_CHINEXT",
        "302132": "SZ_CHINEXT",
        "920819": "BSE",
        "123456": "UNMAPPED",
        "999999": "UNMAPPED",
        "abc": "UNMAPPED",
    }
    for sym, expected in cases.items():
        assert r4.board_of(sym) == expected


def test_board_mapping_does_not_merge_layers():
    boards = [r4.board_of(s) for s in ("688001", "300001", "000001", "600001")]
    assert len(set(boards)) == 4


# ---- T0 type buckets ----


def test_t0_position_absolute_boundaries():
    assert r4.t0_position_bucket(0.0) == "LOW"
    assert r4.t0_position_bucket(1.0 / 3.0 - 1e-9) == "LOW"
    assert r4.t0_position_bucket(1.0 / 3.0) == "MID"
    assert r4.t0_position_bucket(0.5) == "MID"
    assert r4.t0_position_bucket(2.0 / 3.0 - 1e-9) == "MID"
    assert r4.t0_position_bucket(2.0 / 3.0) == "HIGH"
    assert r4.t0_position_bucket(1.0) == "HIGH"
    assert r4.t0_position_bucket(float("nan")) is None
    assert r4.t0_position_bucket(None) is None


def test_t0_gap_bucket_sign():
    assert r4.t0_gap_bucket(0.01) == "GAP_UP"
    assert r4.t0_gap_bucket(0.0) == "NO_GAP_UP"
    assert r4.t0_gap_bucket(-0.01) == "NO_GAP_UP"
    assert r4.t0_gap_bucket(float("nan")) is None


# ---- regime labels ----


def test_regime_labels_above_below_median():
    # 30 sessions; breadth oscillates; trailing-20 median is stable.
    rng = np.random.default_rng(7)
    breadth = pd.Series(
        np.concatenate([np.full(15, 0.4), rng.uniform(0.3, 0.5, 15)]),
        index=pd.date_range("2024-01-02", periods=30, freq="B").date,
    )
    labels, audit = r4.regime_labels(breadth, lookback=20, min_prior=15)
    # first 15 sessions have no 15-prior window -> DATA_LIMITED
    limited = [d for d in breadth.index if labels[d] == "DATA_LIMITED"]
    assert len(limited) >= 14
    # a clearly high breadth after the window must be RISK_ON
    high = pd.Series(
        np.concatenate([np.full(25, 0.4), [0.65, 0.7, 0.62, 0.68, 0.66]]),
        index=pd.date_range("2024-01-02", periods=30, freq="B").date,
    )
    labels2, _ = r4.regime_labels(high, lookback=20, min_prior=15)
    last = breadth.index[-1]
    assert labels2[last] in ("RISK_ON", "RISK_OFF", "NEUTRAL")
    for d in list(high.index)[25:]:
        assert labels2[d] == "RISK_ON", d


def test_regime_needs_prior_sessions():
    breadth = pd.Series(
        np.full(10, 0.5), index=pd.date_range("2024-01-02", periods=10, freq="B").date
    )
    labels, _ = r4.regime_labels(breadth, lookback=20, min_prior=15)
    assert all(v == "DATA_LIMITED" for v in labels.values())


# ---- stratum gates ----


def _frame_with_values(factor_vals, labels, known=None):
    n = len(factor_vals)
    if known is None:
        known = np.ones(n, dtype=bool)
    return (
        pd.DataFrame({"factor": factor_vals, "outcome": labels}),
        known,
        (np.asarray(labels) == "SUCCESS").astype(int),
    )


def test_stratum_gate_min_success():
    vals = list(range(200))
    lbs = ["NON"] * 195 + ["SUCCESS"] * 5
    df, known, labels = _frame_with_values(vals, lbs)
    st = r4.stratum_stats(df, "factor", known, labels, np.ones(len(df), dtype=bool))
    assert st["reportable"] is False
    assert st["note"].startswith("GATE success_n")


def test_stratum_gate_min_n():
    vals = list(range(40))
    lbs = ["SUCCESS"] * 15 + ["NON"] * 25
    df, known, labels = _frame_with_values(vals, lbs)
    st = r4.stratum_stats(df, "factor", known, labels, np.ones(len(df), dtype=bool))
    assert st["reportable"] is False
    assert st["note"].startswith("GATE n<")


def test_stratum_reportable_auc_direction():
    # higher values -> higher success probability -> AUC > 0.5
    vals = list(range(120)) + list(range(120, 240))
    lbs = ["NON"] * 120 + ["SUCCESS"] * 120
    df, known, labels = _frame_with_values(vals, lbs)
    st = r4.stratum_stats(df, "factor", known, labels, np.ones(len(df), dtype=bool))
    assert st["reportable"] is True
    assert st["auc"] > 0.5
    assert st["direction"] == "POSITIVE"


# ---- verdict rules ----


def _stratum(auc, reportable=True):
    return {
        "auc": auc,
        "effect": abs(auc - 0.5),
        "direction": "POSITIVE" if auc >= 0.5 else "NEGATIVE",
        "reportable": reportable,
    }


def test_verdict_stable_all_same_direction():
    strata = [_stratum(0.58), _stratum(0.55), _stratum(0.53), _stratum(0.60)]
    verdict, consistency, reversals, opposite = r4.dimension_verdict(
        "POSITIVE", strata
    )
    assert verdict == "STABLE"
    assert consistency == 1.0 and reversals == 0


def test_verdict_mixed_one_tiny_opposite_no_material_reversal():
    strata = [_stratum(0.58), _stratum(0.55), _stratum(0.49), _stratum(0.60)]
    verdict, consistency, _, _ = r4.dimension_verdict("POSITIVE", strata)
    assert verdict == "MIXED"
    assert consistency == 0.75


def test_verdict_unstable_material_reversal():
    strata = [_stratum(0.58), _stratum(0.42), _stratum(0.45), _stratum(0.60)]
    verdict, _, reversals, opposite = r4.dimension_verdict("POSITIVE", strata)
    assert verdict == "UNSTABLE"
    assert opposite == 2 and reversals >= 1


def test_verdict_unstable_by_consistency():
    strata = [_stratum(0.58), _stratum(0.45), _stratum(0.52), _stratum(0.40)]
    verdict, consistency, _, _ = r4.dimension_verdict("POSITIVE", strata)
    assert verdict == "UNSTABLE"
    assert consistency <= 0.50


def test_verdict_data_limited_few_strata():
    strata = [_stratum(0.58), _stratum(0.55)]
    verdict, _, _, _ = r4.dimension_verdict("POSITIVE", strata)
    assert verdict == "DATA_LIMITED"


def test_verdict_nonreportable_strata_excluded():
    strata = [
        _stratum(0.58), _stratum(0.55), _stratum(0.53),
        _stratum(0.45, reportable=False),
    ]
    verdict, consistency, _, _ = r4.dimension_verdict("POSITIVE", strata)
    assert verdict == "STABLE"
    assert consistency == 1.0


# ---- binary-dimension clause ----


def test_binary_verdict_stable_both_same_direction():
    strata = [_stratum(0.58), _stratum(0.54)]
    verdict, consistency, _, _ = r4.binary_dimension_verdict("POSITIVE", strata)
    assert verdict == "STABLE"
    assert consistency == 1.0


def test_binary_verdict_unstable_opposite():
    strata = [_stratum(0.58), _stratum(0.42)]
    verdict, consistency, reversals, opposite = r4.binary_dimension_verdict(
        "POSITIVE", strata
    )
    assert verdict == "UNSTABLE"
    assert consistency == 0.5 and opposite == 1 and reversals == 1


def test_binary_verdict_data_limited_weak_state():
    # second state has effect below MATERIAL_EFFECT -> not directional
    strata = [_stratum(0.58), _stratum(0.51)]
    verdict, _, _, _ = r4.binary_dimension_verdict("POSITIVE", strata)
    assert verdict == "DATA_LIMITED"


def test_binary_verdict_data_limited_one_reportable():
    strata = [_stratum(0.58), _stratum(0.42, reportable=False)]
    verdict, _, _, _ = r4.binary_dimension_verdict("POSITIVE", strata)
    assert verdict == "DATA_LIMITED"


# ---- overall rules ----


def test_overall_unstable_wins():
    v = {"year": "STABLE", "quarter": "UNSTABLE", "board": "STABLE",
         "regime": "STABLE", "t0_position": "STABLE", "t0_gap_up": "STABLE"}
    assert r4.overall_verdict(v) == "UNSTABLE"


def test_overall_mixed_family_priority():
    v = {"year": "STABLE", "quarter": "MIXED", "board": "STABLE",
         "regime": "STABLE", "t0_position": "MIXED", "t0_gap_up": "STABLE"}
    assert r4.overall_verdict(v) == "TIME_DEPENDENT"
    v2 = {"year": "STABLE", "quarter": "STABLE", "board": "STABLE",
          "regime": "MIXED", "t0_position": "STABLE", "t0_gap_up": "STABLE"}
    assert r4.overall_verdict(v2) == "REGIME_DEPENDENT"


def test_overall_data_limited_fallback():
    v = {"year": "STABLE", "quarter": "STABLE", "board": "DATA_LIMITED",
         "regime": "STABLE", "t0_position": "STABLE", "t0_gap_up": "STABLE"}
    assert r4.overall_verdict(v) == "DATA_LIMITED"


def test_overall_stable_only_if_all_stable():
    v = {"year": "STABLE", "quarter": "STABLE", "board": "STABLE",
         "regime": "STABLE", "t0_position": "STABLE", "t0_gap_up": "STABLE"}
    assert r4.overall_verdict(v) == "STABLE"


# ---- direction never flipped ----


def test_auc_direction_not_flipped():
    # SUCCESS group holds the LOWER values -> AUC < 0.5, never flipped
    vals = np.array(list(range(80, 160)) + list(range(80)))
    labels = np.array([0] * 80 + [1] * 80)
    auc = r4.r3a.binary_auc(vals, labels)
    assert auc < 0.5
    assert r4.direction_of(auc) == "NEGATIVE"
