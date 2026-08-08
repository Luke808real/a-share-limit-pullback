"""R7A multivariate contract tests (contract-only; outcome-blind)."""

from __future__ import annotations

import inspect
from pathlib import Path
import sys

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r7a_multivariate_contract_v01 as r7a  # noqa: E402


pytestmark = pytest.mark.cloud_ci


def test_model_set_exactly_six():
    rows = r7a.build_registry()
    assert [r["model_id"] for r in rows] == ["M0", "M1", "M2", "M3", "M4A", "M4B"]


def test_model_predictor_ladder():
    rows = r7a.build_registry()
    by_id = {r["model_id"]: r["predictors"].split(" + ") for r in rows}
    assert by_id["M0"] == ["B4", "B5", "B6", "B7"]
    assert by_id["M1"] == ["B4", "B5", "B6", "B7", "median_range_ratio"]
    assert by_id["M2"] == ["B4", "B5", "B6", "B7", "median_range_ratio",
                           "quiet_days_n"]
    assert by_id["M3"] == ["B4", "B5", "B6", "B7",
                           "pullback_volume_ratio", "min_volume_ratio",
                           "median_range_ratio", "quiet_days_n"]
    assert by_id["M4A"] == by_id["M2"] + ["high_vs_pullback_high"]
    assert by_id["M4B"] == by_id["M2"] + ["close_vs_pullback_high"]


def test_f6_never_both():
    rows = r7a.build_registry()
    for r in rows:
        preds = r["predictors"]
        assert not (
            "high_vs_pullback_high" in preds
            and "close_vs_pullback_high" in preds
        )


def test_no_interactions():
    rows = r7a.build_registry()
    for r in rows:
        assert "×" not in r["predictors"]
        assert " x " not in r["predictors"].lower()
        assert "no interactions" in r["known_limitation"].lower()


def test_no_threshold_search_no_feature_selection():
    rows = r7a.build_registry()
    for r in rows:
        lim = r["known_limitation"].lower()
        assert "no automated feature selection" in lim
        assert "no threshold search" in lim
        assert "no random train/test split" in lim
    src = inspect.getsource(r7a)
    assert "grid" not in src.lower()
    assert "stepwise" not in src.lower()
    assert "lasso" not in src.lower()
    assert "randomforest" not in src.lower() and "xgb" not in src.lower()


def test_r3_directions_pinned():
    rows = r7a.build_registry()
    for factor, direction in r7a.FROZEN_R3_DIRECTION.items():
        for r in rows:
            assert f"{factor}={direction}" in r["direction_contract"]


def test_same_sample_comparison_contract():
    rows = r7a.build_registry()
    for r in rows:
        assert "SAME complete-case sample" in r["sample_contract"]
        assert "complete-case exclude" in r["missing_policy"]


def test_3d_primary_5d_sensitivity():
    rows = r7a.build_registry()
    for r in rows:
        assert r["target_primary"] == "outcome_3d"
        assert r["target_sensitivity"] == "outcome_5d"


def test_model_type_and_metrics_frozen():
    assert "UNREGULARIZED_LOGISTIC" in r7a.MODEL_TYPE
    for m in ["AUC", "LogLoss", "Brier", "AIC", "BIC"]:
        assert m in r7a.METRIC_SET
    assert "M1_vs_M0" in r7a.NESTED_DELTAS
    assert "RANGE_INDEPENDENT_SUPPORTED" in r7a.SUCCESS_CRITERIA
    assert "QUIET_INCREMENTAL_SUPPORTED" in r7a.SUCCESS_CRITERIA


def test_outcome_blind_r7a():
    src = inspect.getsource(r7a)
    # outcome artifact is touched ONLY via sha256_file (SHA pin), never read
    assert "read_csv" not in src
    # no model-fitting / metric-computing machinery exists in the contract
    assert "import sklearn" not in src.lower()
    assert "from sklearn" not in src.lower()
    assert "fit(" not in src.lower()
    rows = r7a.build_registry()
    assert all(r["status"] == "CONTRACT_ONLY" for r in rows)


def test_pins_and_registry_deterministic(tmp_path):
    r7a.verify_pins()
    rows = r7a.build_registry()
    assert r7a.validate_registry(rows) == []
    df = pd.DataFrame(rows)
    p1, p2 = tmp_path / "a.csv", tmp_path / "b.csv"
    df.to_csv(p1, index=False)
    df.to_csv(p2, index=False)
    assert p1.read_bytes() == p2.read_bytes()
    assert r7a.CLUSTER_SE_IMPLEMENTATION == "UNRESOLVED"


# ---- R7A execution freeze (outcome-blind contract only) ----


def test_core_ladder_sample_family():
    fam = r7a.SAMPLE_FAMILIES["CORE_LADDER"]
    assert fam["models"] == ["M0", "M1", "M2", "M3"]
    assert "finite pullback_volume_ratio" in fam["universe"]
    assert "finite min_volume_ratio" in fam["universe"]
    assert "finite median_range_ratio" in fam["universe"]
    assert "finite quiet_days_n" in fam["universe"]
    assert "SAME complete-case sample" in fam["note"]


def test_f6_sample_families():
    f6a = r7a.SAMPLE_FAMILIES["F6A"]
    f6b = r7a.SAMPLE_FAMILIES["F6B"]
    assert f6a["models"] == ["M2_REF_A", "M4A"]
    assert f6b["models"] == ["M2_REF_B", "M4B"]
    assert "high_vs_pullback_high" in f6a["universe"]
    assert "close_vs_pullback_high" in f6b["universe"]
    assert "never M4A vs M4B" in f6b["note"]


def test_fitter_contract_frozen():
    f = r7a.FITTER_CONTRACT
    assert f["implementation"] == "statsmodels.discrete.discrete_model.Logit"
    assert f["intercept"] is True
    assert f["standardization"] == "NONE"
    assert f["regularization"] == "NONE"
    assert f["method"] == "newton"
    assert f["max_iter"] == 100
    assert f["tol"] == 1e-8
    assert f["no_sklearn_fallback"] is True
    assert f["no_solver_shopping"] is True


def test_fit_failure_policy_frozen():
    assert "BLOCKED_MODEL_FIT" in r7a.FIT_FAILURE_POLICY["CORE"]
    assert "ROBUSTNESS_DATA_LIMITED" in r7a.FIT_FAILURE_POLICY["ROBUSTNESS"]


def test_metric_formulas_frozen():
    m = r7a.METRIC_FORMULAS
    assert "clip(p, 1e-15, 1-1e-15)" in m["LogLoss"]
    assert "mean((p - y)^2)" in m["Brier"]
    assert "2*k - 2*log_likelihood" in m["AIC"]
    assert "ln(N)*k - 2*log_likelihood" in m["BIC"]
    assert m["k"] == "intercept + predictor count"
    assert "no flip" in m["AUC"]


def test_ci_contract_frozen():
    ci = r7a.CI_CONTRACT
    assert ci["ci_type"] == "MODEL_BASED_NON_CLUSTERED"
    assert ci["cluster_robust_se"] == "DEFERRED"
    assert ci["odds_ratio"] == "exp(beta)"
    assert ci["not_for_success_gate"] is True
    assert "not cluster-robust" in ci["note"]


def test_multicollinearity_contract_frozen():
    mc = r7a.MULTICOLLINEARITY_CONTRACT
    assert mc["no_auto_deletion"] is True
    assert "diagnostic" in mc["condition_number"]


def test_execution_freeze_outcome_blind():
    """The freeze adds no model fitting / outcome reading to R7A."""
    src = inspect.getsource(r7a)
    assert "read_csv" not in src
    assert "import sklearn" not in src.lower()
    assert "from sklearn" not in src.lower()
    assert "logit.fit" not in src.lower()
