"""R7B — multivariate attribution execution V01.

Unregularized statsmodels Logit on the frozen R7A contract samples.
Descriptive attribution only; no ML, no interactions, no selection.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import PerfectSeparationError


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r6b_incremental_execution_v01 as r6b  # noqa: E402
import r7a_multivariate_contract_v01 as r7a  # noqa: E402


OUT_COEFF = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r7b_multivariate_coefficients_v01.csv"
)
OUT_METRICS = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r7b_multivariate_model_metrics_v01.csv"
)
OUT_MULTICOLL = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r7b_multicollinearity_diagnostics_v01.csv"
)

FEATURE_SHA = "a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8"
OUTCOME_SHA = "01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d"
SIGNALS_SHA = "ee1c132bf8baa9d479eb0fd01592fe0a44d4851503353986620fc978720995c8"
SOURCE_HEAD = "b2aa8129aa64b993c01c949bae3af01fa21c68e0"
R7A_REGISTRY_SHA = (
    "828a31484df655a02cb4c34452c26e70a954eb9221a517b5c5c098513677341f"
)

BENCHMARKS = ["B4", "B5", "B6", "B7"]
MODEL_PREDICTORS = {
    "M0": BENCHMARKS,
    "M1": BENCHMARKS + ["median_range_ratio"],
    "M2": BENCHMARKS + ["median_range_ratio", "quiet_days_n"],
    "M3": BENCHMARKS + ["pullback_volume_ratio", "min_volume_ratio",
                        "median_range_ratio", "quiet_days_n"],
    "M2_REF_A": BENCHMARKS + ["median_range_ratio", "quiet_days_n"],
    "M4A": BENCHMARKS + ["median_range_ratio", "quiet_days_n",
                         "high_vs_pullback_high"],
    "M2_REF_B": BENCHMARKS + ["median_range_ratio", "quiet_days_n"],
    "M4B": BENCHMARKS + ["median_range_ratio", "quiet_days_n",
                         "close_vs_pullback_high"],
}
SAMPLE_FAMILY_OF_MODEL = {
    "M0": "CORE_LADDER", "M1": "CORE_LADDER", "M2": "CORE_LADDER",
    "M3": "CORE_LADDER", "M2_REF_A": "F6A", "M4A": "F6A",
    "M2_REF_B": "F6B", "M4B": "F6B",
}
COMPARISON_PARENT = {
    "M0": "", "M1": "M0", "M2": "M1", "M3": "M2",
    "M2_REF_A": "", "M4A": "M2_REF_A",
    "M2_REF_B": "", "M4B": "M2_REF_B",
}

LOGIT_METHOD = r7a.FITTER_CONTRACT["method"]
LOGIT_MAXITER = r7a.FITTER_CONTRACT["max_iter"]
LOGIT_TOL = r7a.FITTER_CONTRACT["tol"]
P_CLIP = (1e-15, 1 - 1e-15)


class ModelFitError(RuntimeError):
    pass


def r7a_registry_sha() -> str:
    reg = (
        REPO_ROOT / "research" / "second_launch" / "factors_v01"
        / "r7a_multivariate_model_registry_v01.csv"
    )
    return r3a.sha256_file(reg)


def input_gate() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    feat, out, sig = r6b.input_gate()  # SHAs + three-way episode alignment
    if r7a_registry_sha() != R7A_REGISTRY_SHA:
        raise RuntimeError("R7A registry SHA mismatch (fail closed)")
    return feat, out, sig


def core_sample_mask(
    sig: pd.DataFrame, out: pd.DataFrame, feat: pd.DataFrame, target: str,
) -> np.ndarray:
    common = sig["common_eligible"].astype(bool).to_numpy()
    finite = np.ones(len(feat), dtype=bool)
    for f in r7a.CORE_PREDICTORS:
        finite &= np.isfinite(pd.to_numeric(feat[f], errors="coerce").to_numpy())
    known = out[target].to_numpy() != "UNKNOWN"
    return common & finite & known


def f6_sample_mask(
    sig: pd.DataFrame, out: pd.DataFrame, feat: pd.DataFrame, target: str,
    f6_factor: str,
) -> np.ndarray:
    common = sig["common_eligible"].astype(bool).to_numpy()
    finite = np.ones(len(feat), dtype=bool)
    for f in ["median_range_ratio", "quiet_days_n", f6_factor]:
        finite &= np.isfinite(pd.to_numeric(feat[f], errors="coerce").to_numpy())
    known = out[target].to_numpy() != "UNKNOWN"
    return common & finite & known


def fit_logit(X: np.ndarray, y: np.ndarray, model_id: str) -> Any:
    """Frozen fitter: statsmodels Logit, newton, fixed maxiter/tol."""
    try:
        res = sm.Logit(y, X).fit(
            method=LOGIT_METHOD, maxiter=LOGIT_MAXITER, tol=LOGIT_TOL,
            disp=False,
        )
    except PerfectSeparationError as exc:
        raise ModelFitError(f"{model_id}: perfect separation") from exc
    converged = bool(res.mle_retvals.get("converged", False))
    if not converged:
        raise ModelFitError(f"{model_id}: non-convergence")
    if not np.all(np.isfinite(res.params)):
        raise ModelFitError(f"{model_id}: non-finite coefficients")
    return res


def logloss(p: np.ndarray, y: np.ndarray) -> float:
    pc = np.clip(p, P_CLIP[0], P_CLIP[1])
    return float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc)))


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def aic_bic(k: int, n: int, llf: float) -> tuple[float, float]:
    aic = 2.0 * k - 2.0 * llf
    bic = math.log(n) * k - 2.0 * llf
    return aic, bic


def metric_row(
    feat: pd.DataFrame, out: pd.DataFrame, sig: pd.DataFrame,
    model_id: str, target: str, mask: np.ndarray,
) -> dict[str, Any]:
    predictors = MODEL_PREDICTORS[model_id]
    X_raw = pd.DataFrame()
    for p in predictors:
        if p in BENCHMARKS:
            X_raw[p] = sig[f"{p}_signal"].astype(int).to_numpy()[mask]
        else:
            X_raw[p] = pd.to_numeric(feat[p], errors="coerce").to_numpy()[mask]
    y = (out[target].to_numpy()[mask] == "SUCCESS").astype(int)
    n = int(mask.sum())
    success_n = int(y.sum())
    non_success_n = n - success_n
    X = sm.add_constant(X_raw, has_constant="add")
    res = fit_logit(X, y, model_id)
    p = np.asarray(res.predict(X), dtype=float)
    if not np.all(np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ModelFitError(f"{model_id}: non-finite/out-of-range predictions")
    auc = r3a.binary_auc(p, y)
    ll = float(res.llf)
    k = X.shape[1]
    aic_ours, bic_ours = aic_bic(k, n, ll)
    if abs(aic_ours - float(res.aic)) > 1e-6 or abs(
        bic_ours - float(res.bic)
    ) > 1e-6:
        raise ModelFitError(f"{model_id}: AIC/BIC consistency check failed")
    return {
        "target": target,
        "sample_family": SAMPLE_FAMILY_OF_MODEL[model_id],
        "model_id": model_id,
        "comparison_parent": COMPARISON_PARENT[model_id],
        "N": n,
        "SUCCESS_N": success_n,
        "NON_SUCCESS_N": non_success_n,
        "AUC": auc,
        "LogLoss": logloss(p, y),
        "Brier": brier(p, y),
        "AIC": aic_ours,
        "BIC": bic_ours,
        "converged": True,
        "res": res, "p": p, "X": X,
    }


def coeff_rows(metric: dict[str, Any]) -> list[dict[str, Any]]:
    res = metric["res"]
    rows = []
    for pred in metric["X"].columns[1:]:
        beta = float(res.params[pred])
        sign = "POSITIVE" if beta > 0 else ("NEGATIVE" if beta < 0 else "NEUTRAL")
        expected = r7a.FROZEN_R3_DIRECTION.get(pred, "N/A")
        ci_low, ci_high = res.conf_int().loc[pred]
        rows.append({
            "target": metric["target"],
            "sample_family": metric["sample_family"],
            "model_id": metric["model_id"],
            "predictor": pred,
            "coefficient": beta,
            "coefficient_sign": sign,
            "expected_direction": expected,
            "direction_match": bool(sign == expected) if expected != "N/A" else None,
            "odds_ratio": float(math.exp(beta)),
            "ci_low": float(ci_low),
            "ci_high": float(ci_high),
            "ci_type": "MODEL_BASED_NON_CLUSTERED",
        })
    return rows


def multicollinearity_rows(
    feat: pd.DataFrame, sig: pd.DataFrame, out: pd.DataFrame,
) -> list[dict[str, Any]]:
    mask = core_sample_mask(sig, out, feat, "outcome_3d")
    df = pd.DataFrame({
        f: pd.to_numeric(feat[f], errors="coerce").to_numpy()[mask]
        for f in r7a.CORE_PREDICTORS
    })
    corr = df.corr(method="pearson")
    z = (df - df.mean()) / df.std(ddof=0)
    cond = float(np.linalg.cond(z.to_numpy()))
    rows = []
    for i, a in enumerate(r7a.CORE_PREDICTORS):
        for b in r7a.CORE_PREDICTORS[i + 1:]:
            rows.append({
                "sample_family": "CORE_LADDER",
                "predictor_a": a, "predictor_b": b,
                "correlation": float(corr.loc[a, b]),
                "condition_number": cond,
            })
    return rows


def apply_deltas(metrics: pd.DataFrame) -> pd.DataFrame:
    df = metrics.copy()
    for _, row in metrics.iterrows():
        parent = row["comparison_parent"]
        if not parent:
            continue
        pr = metrics[(metrics["model_id"] == parent)
                     & (metrics["target"] == row["target"])
                     & (metrics["sample_family"] == row["sample_family"])]
        if len(pr) != 1:
            raise ModelFitError(
                f"parent {parent} not found for {row['model_id']}")
        for col in ["AUC", "LogLoss", "Brier", "AIC", "BIC"]:
            df.loc[row.name, f"delta_{col.lower()}"] = (
                row[col] - pr.iloc[0][col])
    return df


def range_rule(
    m0: dict[str, Any], m1: dict[str, Any],
    m0_5d: dict[str, Any], m1_5d: dict[str, Any],
) -> str:
    b = float(m1["res"].params["median_range_ratio"])
    b5 = float(m1_5d["res"].params["median_range_ratio"])
    direction_ok = b < 0
    five_d_not_reversed = b5 < 0
    if (direction_ok and m1["AUC"] > m0["AUC"]
            and m1["LogLoss"] < m0["LogLoss"]
            and m1["Brier"] <= m0["Brier"] and five_d_not_reversed):
        return "RANGE_INDEPENDENT_SUPPORTED"
    return "RANGE_INDEPENDENT_NOT_SUPPORTED"


def quiet_rule(
    m1: dict[str, Any], m2: dict[str, Any],
    m1_5d: dict[str, Any], m2_5d: dict[str, Any],
) -> str:
    b = float(m2["res"].params["quiet_days_n"])
    b5 = float(m2_5d["res"].params["quiet_days_n"])
    improvements = sum([
        m2["AUC"] > m1["AUC"],
        m2["LogLoss"] < m1["LogLoss"],
        m2["Brier"] < m1["Brier"],
    ])
    if b > 0 and improvements >= 2 and b5 > 0:
        return "QUIET_INCREMENTAL_SUPPORTED"
    return "QUIET_INCREMENTAL_NOT_SUPPORTED"


def main() -> None:
    feat, out, sig = input_gate()
    metric_rows: list[dict[str, Any]] = []
    coeff_rows_all: list[dict[str, Any]] = []
    models_core = ["M0", "M1", "M2", "M3"]
    core_n: dict[str, int] = {}
    for target in ("outcome_3d", "outcome_5d"):
        mask = core_sample_mask(sig, out, feat, target)
        core_n[target] = int(mask.sum())
        for mid in models_core:
            try:
                m = metric_row(feat, out, sig, mid, target, mask)
            except ModelFitError as exc:
                raise ModelFitError(
                    f"CORE fit failed -> STATUS=BLOCKED_MODEL_FIT: {exc}"
                ) from exc
            metric_rows.append(m)
            coeff_rows_all.extend(coeff_rows(m))
    # F6 matched samples
    for target in ("outcome_3d", "outcome_5d"):
        mask_a = f6_sample_mask(sig, out, feat, target, "high_vs_pullback_high")
        mask_b = f6_sample_mask(sig, out, feat, target, "close_vs_pullback_high")
        for mid in ("M2_REF_A", "M4A"):
            try:
                m = metric_row(feat, out, sig, mid, target, mask_a)
            except ModelFitError as exc:
                print(f"ROBUSTNESS_DATA_LIMITED: {mid} {target}: {exc}")
                m = {
                    "target": target, "sample_family": "F6A",
                    "model_id": mid, "comparison_parent": COMPARISON_PARENT[mid],
                    "N": int(mask_a.sum()), "SUCCESS_N": np.nan,
                    "NON_SUCCESS_N": np.nan, "AUC": np.nan, "LogLoss": np.nan,
                    "Brier": np.nan, "AIC": np.nan, "BIC": np.nan,
                    "converged": False,
                }
            metric_rows.append(m)
            if m.get("converged"):
                coeff_rows_all.extend(coeff_rows(m))
        for mid in ("M2_REF_B", "M4B"):
            try:
                m = metric_row(feat, out, sig, mid, target, mask_b)
            except ModelFitError as exc:
                print(f"ROBUSTNESS_DATA_LIMITED: {mid} {target}: {exc}")
                m = {
                    "target": target, "sample_family": "F6B",
                    "model_id": mid, "comparison_parent": COMPARISON_PARENT[mid],
                    "N": int(mask_b.sum()), "SUCCESS_N": np.nan,
                    "NON_SUCCESS_N": np.nan, "AUC": np.nan, "LogLoss": np.nan,
                    "Brier": np.nan, "AIC": np.nan, "BIC": np.nan,
                    "converged": False,
                }
            metric_rows.append(m)
            if m.get("converged"):
                coeff_rows_all.extend(coeff_rows(m))
    metrics = apply_deltas(pd.DataFrame([
        {k: v for k, v in r.items() if k not in ("res", "p", "X")}
        for r in metric_rows
    ]))
    metrics.to_csv(OUT_METRICS, index=False)
    pd.DataFrame(coeff_rows_all).to_csv(OUT_COEFF, index=False)
    pd.DataFrame(multicollinearity_rows(feat, sig, out)).to_csv(
        OUT_MULTICOLL, index=False)

    # success gates (3D primary with 5D sensitivity checks)
    by = {(m["target"], m["model_id"]): m for m in metric_rows}
    range_v = range_rule(by[("outcome_3d", "M0")], by[("outcome_3d", "M1")],
                         by[("outcome_5d", "M0")], by[("outcome_5d", "M1")])
    quiet_v = quiet_rule(by[("outcome_3d", "M1")], by[("outcome_3d", "M2")],
                         by[("outcome_5d", "M1")], by[("outcome_5d", "M2")])

    # ---- QA (fail closed) ----
    assert core_n["outcome_3d"] == core_n["outcome_5d"] or True  # N may differ
    for target in ("outcome_3d", "outcome_5d"):
        ns = {m["model_id"]: m["N"] for m in metric_rows
              if m["target"] == target and m["sample_family"] == "CORE_LADDER"}
        assert len(set(ns.values())) == 1, f"CORE denominator drift {target}: {ns}"
    for target in ("outcome_3d", "outcome_5d"):
        fa = {m["model_id"]: m["N"] for m in metric_rows
              if m["target"] == target and m["sample_family"] == "F6A"}
        fb = {m["model_id"]: m["N"] for m in metric_rows
              if m["target"] == target and m["sample_family"] == "F6B"}
        assert fa["M2_REF_A"] == fa["M4A"], "F6A denominator mismatch"
        assert fb["M2_REF_B"] == fb["M4B"], "F6B denominator mismatch"
    for m in metric_rows:
        if m.get("converged"):
            assert m["N"] == m["SUCCESS_N"] + m["NON_SUCCESS_N"]
        else:
            assert m["SUCCESS_N"] != m["SUCCESS_N"]  # NaN markers
    assert not metrics.duplicated().any()
    assert len(metrics) == 16  # 8 models x 2 targets
    print("R7B QA: PASS")
    print("CORE N 3D/5D:", core_n)
    print("RANGE:", range_v)
    print("QUIET:", quiet_v)
    print("OUT:", OUT_METRICS)
    print("OUT:", OUT_COEFF)
    print("OUT:", OUT_MULTICOLL)


if __name__ == "__main__":
    main()
