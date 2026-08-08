"""R7B multivariate execution targeted tests (frozen contract semantics).

Reads only committed artifacts (feature/outcome/signals CSVs); statsmodels
fits are synthetic or on committed CSVs -> cloud_ci.
"""

from __future__ import annotations

import inspect
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r6b_incremental_execution_v01 as r6b  # noqa: E402
import r7a_multivariate_contract_v01 as r7a  # noqa: E402
import r7b_multivariate_execution_v01 as r7b  # noqa: E402


pytestmark = pytest.mark.cloud_ci


# ---- metric formulas ----


def test_logloss_formula():
    p = np.array([0.9, 0.1, 0.5, 0.7])
    y = np.array([1, 0, 1, 1])
    pc = np.clip(p, 1e-15, 1 - 1e-15)
    expected = -np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))
    assert abs(r7b.logloss(p, y) - expected) < 1e-12


def test_brier_formula():
    p = np.array([0.9, 0.1, 0.5])
    y = np.array([1, 0, 1])
    assert abs(r7b.brier(p, y) - np.mean((p - y) ** 2)) < 1e-12


def test_aic_bic_formula():
    k, n, llf = 3, 100, -50.0
    aic, bic = r7b.aic_bic(k, n, llf)
    assert abs(aic - (2 * k - 2 * llf)) < 1e-12
    assert abs(bic - (np.log(n) * k - 2 * llf)) < 1e-12


# ---- fitter contract ----


def test_fitter_intercept_and_no_standardization():
    rng = np.random.default_rng(3)
    x = rng.normal(size=200)
    p = 1 / (1 + np.exp(-(0.5 * x - 0.2)))
    y = (rng.uniform(size=200) < p).astype(int)
    X = sm.add_constant(pd.DataFrame({"x": x}))
    res = r7b.fit_logit(X, y, "T")
    assert "const" in res.params.index
    assert r7b.LOGIT_METHOD == "newton"
    assert r7b.LOGIT_MAXITER == 100
    assert r7b.LOGIT_TOL == 1e-8
    # raw values used: no standardization constants anywhere in fit path
    assert "standardize" not in inspect.getsource(r7b.fit_logit).lower()


def test_fit_failure_perfect_separation_fails_closed():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    y = np.array([0, 0, 0, 1, 1, 1])
    X = sm.add_constant(pd.DataFrame({"x": x}))
    with pytest.raises(r7b.ModelFitError):
        r7b.fit_logit(X, y, "SEP")


def test_coefficient_direction_synthetic():
    rng = np.random.default_rng(7)
    x = rng.normal(size=500)
    p = 1 / (1 + np.exp(-(-1.2 * x)))
    y = (rng.uniform(size=500) < p).astype(int)
    X = sm.add_constant(pd.DataFrame({"x": x}))
    res = r7b.fit_logit(X, y, "T")
    assert res.params["x"] < 0  # negative relation -> NEGATIVE beta


# ---- samples on committed artifacts ----


def test_core_denominator_equality():
    feat, out, sig = r7b.input_gate()
    m3d = r7b.core_sample_mask(sig, out, feat, "outcome_3d")
    m5d = r7b.core_sample_mask(sig, out, feat, "outcome_5d")
    assert int(m3d.sum()) > 7000 and int(m5d.sum()) > 7000
    # M0-M3 share the exact same mask by construction (single mask)
    assert r7b.SAMPLE_FAMILY_OF_MODEL["M0"] == "CORE_LADDER"
    assert (m3d == m3d).all()


def test_f6_matched_reference_same_n():
    feat, out, sig = r7b.input_gate()
    a = r7b.f6_sample_mask(sig, out, feat, "outcome_3d",
                           "high_vs_pullback_high")
    b = r7b.f6_sample_mask(sig, out, feat, "outcome_3d",
                           "close_vs_pullback_high")
    assert int(a.sum()) == int(b.sum()) == 4225
    # M2_REF_A / M4A share mask; M2_REF_B / M4B share mask
    assert r7b.SAMPLE_FAMILY_OF_MODEL["M2_REF_A"] == "F6A"
    assert r7b.SAMPLE_FAMILY_OF_MODEL["M4A"] == "F6A"
    assert r7b.SAMPLE_FAMILY_OF_MODEL["M2_REF_B"] == "F6B"
    assert r7b.SAMPLE_FAMILY_OF_MODEL["M4B"] == "F6B"


# ---- frozen success rules ----


def _metric(auc, ll, br):
    return {"AUC": auc, "LogLoss": ll, "Brier": br, "res": None}


def test_range_rule_frozen_supported():
    m0 = _metric(0.575, 0.188, 0.0448)
    m1 = _metric(0.599, 0.187, 0.0447)
    class R:
        params = {"median_range_ratio": -0.37}
    m1["res"] = R()
    m0["res"] = R()
    assert r7b.range_rule(m0, m1, m0, m1) == "RANGE_INDEPENDENT_SUPPORTED"


def test_range_rule_frozen_not_supported_auc():
    class R:
        params = {"median_range_ratio": -0.37}
    m0 = _metric(0.599, 0.187, 0.0447)
    m1 = _metric(0.575, 0.188, 0.0448)
    m0["res"] = m1["res"] = R()
    assert r7b.range_rule(m0, m1, m0, m1) == "RANGE_INDEPENDENT_NOT_SUPPORTED"


def test_quiet_rule_frozen_supported():
    class R:
        params = {"quiet_days_n": 0.06}
    m1 = _metric(0.598, 0.188, 0.0448)
    m2 = _metric(0.602, 0.187, 0.0447)
    m1["res"] = m2["res"] = R()
    assert r7b.quiet_rule(m1, m2, m1, m2) == "QUIET_INCREMENTAL_SUPPORTED"


def test_quiet_rule_frozen_not_supported():
    class R:
        params = {"quiet_days_n": -0.06}
    m1 = _metric(0.598, 0.188, 0.0448)
    m2 = _metric(0.602, 0.187, 0.0447)
    m1["res"] = m2["res"] = R()
    assert r7b.quiet_rule(m1, m2, m1, m2) == "QUIET_INCREMENTAL_NOT_SUPPORTED"


# ---- model set / no expansion ----


def test_model_set_exact():
    assert set(r7b.MODEL_PREDICTORS) == {
        "M0", "M1", "M2", "M3", "M2_REF_A", "M4A", "M2_REF_B", "M4B"}
    assert r7b.MODEL_PREDICTORS["M0"] == ["B4", "B5", "B6", "B7"]
    src = inspect.getsource(r7b)
    assert "interaction" not in src.lower() or "no interaction" in src.lower()


def test_episode_shuffle_invariance():
    feat, out, sig = r7b.input_gate()
    rng = np.random.default_rng(11)
    idx = rng.permutation(len(feat))
    shuffled_out = out.iloc[idx].reset_index(drop=True)
    shuffled_sig = sig.iloc[idx].reset_index(drop=True)
    a, b, c = r6b.align_three_way(feat, shuffled_out, shuffled_sig)
    assert (a["episode_id"].to_numpy() == b["episode_id"].to_numpy()).all()
    assert (a["episode_id"].to_numpy() == c["episode_id"].to_numpy()).all()
