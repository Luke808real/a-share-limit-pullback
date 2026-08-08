"""R7A — multivariate (unregularized logistic) contract V01.

Contract + availability ONLY. Outcome-blind: outcome artifact is touched only
via SHA pin; no model coefficients / AUC / LogLoss / Brier are computed.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402


OUT_REGISTRY = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r7a_multivariate_model_registry_v01.csv"
)

FEATURE_SHA = "a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8"
OUTCOME_SHA = "01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d"
R5B_SIGNALS_SHA = "ee1c132bf8baa9d479eb0fd01592fe0a44d4851503353986620fc978720995c8"
SOURCE_HEAD = "632390d4c34946d9964f9f34e269d4de5b1e6e6c"

BENCHMARK_PREDICTORS = ["B4", "B5", "B6", "B7"]
F3_PREDICTORS = [
    "pullback_volume_ratio", "min_volume_ratio", "median_range_ratio",
    "quiet_days_n",
]
F6_CONTROLS = ["high_vs_pullback_high", "close_vs_pullback_high"]

FROZEN_R3_DIRECTION = {
    "median_range_ratio": "NEGATIVE",
    "pullback_volume_ratio": "NEGATIVE",
    "min_volume_ratio": "NEGATIVE",
    "quiet_days_n": "POSITIVE",
    "high_vs_pullback_high": "POSITIVE",
    "close_vs_pullback_high": "POSITIVE",
}

MODEL_TYPE = "UNREGULARIZED_LOGISTIC_REGRESSION (descriptive attribution; not ML)"
SAMPLE_CONTRACT = (
    "B4/B5/B6/B7 common_eligible == true AND all model predictors non-missing "
    "AND outcome known; ALL nested comparisons share the SAME complete-case "
    "sample (no denominator drift)"
)
MISSING_POLICY = (
    "complete-case exclude; missing N per predictor reported; no imputation"
)
TARGET_PRIMARY = "outcome_3d"
TARGET_SENSITIVITY = "outcome_5d"

METRIC_SET = ["N", "SUCCESS_N", "NON_SUCCESS_N", "AUC", "LogLoss", "Brier",
              "AIC", "BIC"]
NESTED_DELTAS = [
    "delta_auc_vs_m0", "delta_logloss_vs_m0", "delta_brier_vs_m0",
    "M1_vs_M0", "M2_vs_M1", "M3_vs_M2",
]

SUCCESS_CRITERIA = {
    "RANGE_INDEPENDENT_SUPPORTED": (
        "median_range_ratio coefficient direction == NEGATIVE in M1 AND "
        "M1 AUC > M0 AUC AND M1 LogLoss < M0 LogLoss AND M1 Brier <= M0 Brier "
        "AND 5D coefficient direction not reversed"
    ),
    "QUIET_INCREMENTAL_SUPPORTED": (
        "quiet_days_n coefficient POSITIVE in M2 AND >=2 of "
        "AUC/LogLoss/Brier improve (M2 vs M1) AND 5D direction not reversed"
    ),
}

CLUSTER_SE_IMPLEMENTATION = "UNRESOLVED"


def verify_pins() -> None:
    if r3a.sha256_file(r3a.FEATURE_CSV) != FEATURE_SHA:
        raise RuntimeError("feature CSV SHA mismatch (fail closed)")
    if r3a.sha256_file(r3a.OUTCOME_CSV) != OUTCOME_SHA:
        raise RuntimeError("outcome CSV SHA mismatch (fail closed)")
    sig_csv = (
        REPO_ROOT / "research" / "second_launch" / "factors_v01"
        / "r5b_benchmark_episode_signals_v01.csv"
    )
    if r3a.sha256_file(sig_csv) != R5B_SIGNALS_SHA:
        raise RuntimeError("R5B signals SHA mismatch (fail closed)")


def _model(
    model_id: str, role: str, predictors: list[str],
    comparison_parent: str, limitation: str,
) -> dict[str, str]:
    return {
        "model_id": model_id,
        "model_role": role,
        "predictors": " + ".join(predictors),
        "target_primary": TARGET_PRIMARY,
        "target_sensitivity": TARGET_SENSITIVITY,
        "sample_contract": SAMPLE_CONTRACT,
        "missing_policy": MISSING_POLICY,
        "direction_contract": " | ".join(
            f"{k}={v}" for k, v in FROZEN_R3_DIRECTION.items()
        ),
        "comparison_parent": comparison_parent,
        "status": "CONTRACT_ONLY",
        "known_limitation": limitation,
    }


NO_INTERACTION_LIMITATION = (
    "V01 no interactions / no polynomials / no splines; no automated feature "
    "selection; no threshold search; no random train/test split (R9); "
    f"CLUSTER_SE_IMPLEMENTATION={CLUSTER_SE_IMPLEMENTATION}"
)


def build_registry() -> list[dict[str, str]]:
    verify_pins()
    m0 = _model(
        "M0", "BASELINE", BENCHMARK_PREDICTORS, "",
        "simple benchmark multivariate baseline (R5 frozen binary signals); "
        + NO_INTERACTION_LIMITATION,
    )
    m1 = _model(
        "M1", "PRIMARY_CANDIDATE",
        BENCHMARK_PREDICTORS + ["median_range_ratio"], "M0",
        "PRIMARY candidate: range contraction beyond all simple benchmarks; "
        + NO_INTERACTION_LIMITATION,
    )
    m2 = _model(
        "M2", "PRIMARY_CANDIDATE",
        BENCHMARK_PREDICTORS + ["median_range_ratio", "quiet_days_n"], "M1",
        "range + quiet independent contribution; "
        + NO_INTERACTION_LIMITATION,
    )
    m3 = _model(
        "M3", "DIAGNOSTIC",
        BENCHMARK_PREDICTORS + F3_PREDICTORS, "M2",
        "DIAGNOSTIC ONLY: confirms pvr/mvr redundancy under B6+range+quiet; "
        "not for model selection; " + NO_INTERACTION_LIMITATION,
    )
    m4a = _model(
        "M4A", "ROBUSTNESS_CONTROL",
        BENCHMARK_PREDICTORS + ["median_range_ratio", "quiet_days_n",
                                "high_vs_pullback_high"],
        "M2",
        "F6 separate (never both F6); high_vs_pullback_high R4=UNSTABLE, "
        "cannot override R4; " + NO_INTERACTION_LIMITATION,
    )
    m4b = _model(
        "M4B", "ROBUSTNESS_CONTROL",
        BENCHMARK_PREDICTORS + ["median_range_ratio", "quiet_days_n",
                                "close_vs_pullback_high"],
        "M2",
        "F6 separate (never both F6); close_vs_pullback_high "
        "R4=TIME_DEPENDENT, cannot override R4; " + NO_INTERACTION_LIMITATION,
    )
    return [m0, m1, m2, m3, m4a, m4b]


def validate_registry(rows: list[dict[str, str]]) -> list[str]:
    violations: list[str] = []
    ids = [r["model_id"] for r in rows]
    if ids != ["M0", "M1", "M2", "M3", "M4A", "M4B"]:
        violations.append(f"model set mismatch: {ids}")
    by_id = {r["model_id"]: r["predictors"].split(" + ") for r in rows}
    if by_id["M0"] != BENCHMARK_PREDICTORS:
        violations.append("M0 predictors must be B4-B7")
    if by_id["M1"] != BENCHMARK_PREDICTORS + ["median_range_ratio"]:
        violations.append("M1 must be M0 + median_range_ratio")
    if by_id["M2"] != BENCHMARK_PREDICTORS + [
        "median_range_ratio", "quiet_days_n",
    ]:
        violations.append("M2 must be M1 + quiet_days_n")
    if by_id["M3"] != BENCHMARK_PREDICTORS + F3_PREDICTORS:
        violations.append("M3 must be M0 + F3 x4")
    if by_id["M4A"] != BENCHMARK_PREDICTORS + [
        "median_range_ratio", "quiet_days_n", "high_vs_pullback_high",
    ]:
        violations.append("M4A must be M2 + high_vs_pullback_high")
    if by_id["M4B"] != BENCHMARK_PREDICTORS + [
        "median_range_ratio", "quiet_days_n", "close_vs_pullback_high",
    ]:
        violations.append("M4B must be M2 + close_vs_pullback_high")
    for r in rows:
        if "×" in r["predictors"] or " x " in r["predictors"].lower():
            violations.append(f"{r['model_id']}: interaction term present")
        if r["status"] != "CONTRACT_ONLY":
            violations.append(f"{r['model_id']}: status not CONTRACT_ONLY")
        if r["target_primary"] != "outcome_3d" or r[
            "target_sensitivity"
        ] != "outcome_5d":
            violations.append(f"{r['model_id']}: target contract drift")
        for f, d in FROZEN_R3_DIRECTION.items():
            if f"{f}={d}" not in r["direction_contract"]:
                violations.append(f"{r['model_id']}: direction pin missing")
    return violations


def main() -> None:
    rows = build_registry()
    violations = validate_registry(rows)
    if violations:
        raise RuntimeError(
            f"R7A registry validation failed (fail closed): {violations}"
        )
    df = pd.DataFrame(rows)
    df.to_csv(OUT_REGISTRY, index=False)
    print("R7A_PINS: PASS")
    print("R7A_MODELS:", len(df))
    print("CLUSTER_SE_IMPLEMENTATION:", CLUSTER_SE_IMPLEMENTATION)
    print("OUT:", OUT_REGISTRY)


if __name__ == "__main__":
    main()
