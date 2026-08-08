"""R6A — incremental-value contract V01 (contract + availability only).

Outcome-blind: this module never reads outcome labels (SHA/schema only).
All pins are verified against frozen committed artifacts at runtime.
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
    / "r6a_incremental_registry_v01.csv"
)

R3A_RESULTS_CSV = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r3a_univariate_factor_results.csv"
)
R4_VERDICTS_CSV = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r4_stability_verdicts_3d.csv"
)
SIGNALS_CSV = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r5b_benchmark_episode_signals_v01.csv"
)

# ---- frozen pins (R5 final source commit ec3de4d) ----
FEATURE_SHA = "a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8"
SIGNALS_SHA = "ee1c132bf8baa9d479eb0fd01592fe0a44d4851503353986620fc978720995c8"
# R4 frozen material-effect threshold (contract section 5 / r4_stability_v01.py
# MATERIAL_EFFECT = 0.03); reused verbatim, not re-invented.
MATERIAL_EFFECT = 0.03
MATERIAL_EFFECT_SOURCE = (
    "research/reports/SECOND_LAUNCH_FACTOR_R4_STABILITY_CONTRACT_V01.md section 5 "
    "and research/second_launch/factors_v01/r4_stability_v01.py MATERIAL_EFFECT"
)

BASELINES = {
    "B4": "SECONDARY_BASELINE",
    "B5": "WEAK_CONTROL_BASELINE",
    "B6": "PRIMARY_BASELINE",
    "B7": "WEAK_CONTROL_BASELINE",
}

F3_FACTORS = [
    "pullback_volume_ratio",
    "min_volume_ratio",
    "median_range_ratio",
    "quiet_days_n",
]
F6_CONTROLS = ["high_vs_pullback_high", "close_vs_pullback_high"]

EXPECTED_R3_DIRECTION = {
    "pullback_volume_ratio": "NEGATIVE",
    "min_volume_ratio": "NEGATIVE",
    "median_range_ratio": "NEGATIVE",
    "quiet_days_n": "POSITIVE",
    "high_vs_pullback_high": "POSITIVE",
    "close_vs_pullback_high": "POSITIVE",
}
EXPECTED_R4_STATUS = {
    "pullback_volume_ratio": "DATA_LIMITED",
    "min_volume_ratio": "DATA_LIMITED",
    "median_range_ratio": "DATA_LIMITED",
    "quiet_days_n": "DATA_LIMITED",
    "high_vs_pullback_high": "UNSTABLE",
    "close_vs_pullback_high": "TIME_DEPENDENT",
}

PRIMARY_METHOD = (
    "CONDITIONAL_RESIDUAL_DISCRIMINATION: within benchmark signal group "
    "(benchmark eligible AND signal AND factor nonmissing AND outcome known), "
    "native AUC of the continuous factor on SUCCESS vs KNOWN_NON_SUCCESS"
)
PRIMARY_SAMPLE = (
    "benchmark eligible AND benchmark signal == true AND factor nonmissing "
    "AND outcome known (baseline signal group)"
)


def verify_pins() -> None:
    if r3a.sha256_file(r3a.FEATURE_CSV) != FEATURE_SHA:
        raise RuntimeError("feature CSV SHA mismatch (fail closed)")
    if r3a.sha256_file(SIGNALS_CSV) != SIGNALS_SHA:
        raise RuntimeError("R5B signals SHA mismatch (fail closed)")


def load_r3_direction(factor: str) -> str:
    df = pd.read_csv(R3A_RESULTS_CSV)
    row = df[df["factor"] == factor]
    if len(row) != 1:
        raise RuntimeError(f"R3A direction missing for {factor} (fail closed)")
    direction = str(row.iloc[0]["effect_direction"])
    if direction != EXPECTED_R3_DIRECTION[factor]:
        raise RuntimeError(
            f"R3 direction drift for {factor}: {direction} != "
            f"{EXPECTED_R3_DIRECTION[factor]} (fail closed)"
        )
    return direction


def load_r4_status(factor: str) -> str:
    df = pd.read_csv(R4_VERDICTS_CSV)
    row = df[(df["factor"] == factor) & (df["dimension"] == "OVERALL")]
    if len(row) != 1:
        raise RuntimeError(f"R4 OVERALL status missing for {factor} (fail closed)")
    status = str(row.iloc[0]["verdict"])
    if status != EXPECTED_R4_STATUS[factor]:
        raise RuntimeError(
            f"R4 status drift for {factor}: {status} != "
            f"{EXPECTED_R4_STATUS[factor]} (fail closed)"
        )
    return status


def build_registry() -> list[dict[str, str]]:
    verify_pins()
    rows: list[dict[str, str]] = []
    for baseline_id, baseline_role in BASELINES.items():
        for factor in F3_FACTORS:
            rows.append(_row(baseline_id, baseline_role, factor, "F3",
                             "PRIMARY_INCREMENTAL_CANDIDATE"))
        for factor in F6_CONTROLS:
            rows.append(_row(baseline_id, baseline_role, factor, "F6",
                             "ROBUSTNESS_CONTROL"))
    return rows


def _row(
    baseline_id: str, baseline_role: str, factor: str, family: str,
    factor_role: str,
) -> dict[str, str]:
    return {
        "baseline_id": baseline_id,
        "baseline_role": baseline_role,
        "factor_name": factor,
        "factor_family": family,
        "factor_role": factor_role,
        "r3_direction": load_r3_direction(factor),
        "r4_status": load_r4_status(factor),
        "primary_sample": PRIMARY_SAMPLE,
        "primary_method": PRIMARY_METHOD,
        "material_effect_threshold": str(MATERIAL_EFFECT),
        "material_effect_source": MATERIAL_EFFECT_SOURCE,
        "feature_artifact_sha": FEATURE_SHA,
        "benchmark_signal_artifact_sha": SIGNALS_SHA,
        "missing_semantics": (
            "factor structured NULL (CA/insufficient history per R1B contract) "
            "-> excluded from conditional sample (factor nonmissing gate)"
        ),
        "status": "CONTRACT_ONLY",
        "known_limitation": (
            "R6B must report OWN_BASELINE_SAMPLE and COMMON_COMPARABLE_SAMPLE; "
            "PRIMARY comparison on common comparable sample; no direction "
            "flip; no threshold optimization; no F3/F6 combination tuning"
        ),
    }


def validate_registry(rows: list[dict[str, str]]) -> list[str]:
    violations: list[str] = []
    if len(rows) != 24:
        violations.append(f"registry rows must be 24, got {len(rows)}")
    base_ids = {r["baseline_id"] for r in rows}
    if base_ids != set(BASELINES):
        violations.append(f"baseline set mismatch: {sorted(base_ids)}")
    primary = [r for r in rows if r["baseline_role"] == "PRIMARY_BASELINE"]
    if len({r["baseline_id"] for r in primary}) != 1 or primary[0]["baseline_id"] != "B6":
        violations.append("PRIMARY baseline must be exactly B6")
    factors = {r["factor_name"] for r in rows}
    if factors != set(F3_FACTORS) | set(F6_CONTROLS):
        violations.append(f"factor set mismatch: {sorted(factors)}")
    for r in rows:
        if r["factor_family"] == "F3" and r["factor_role"] != "PRIMARY_INCREMENTAL_CANDIDATE":
            violations.append(f"{r['factor_name']}: F3 role wrong")
        if r["factor_family"] == "F6" and r["factor_role"] != "ROBUSTNESS_CONTROL":
            violations.append(f"{r['factor_name']}: F6 role wrong")
        if r["material_effect_threshold"] != str(MATERIAL_EFFECT):
            violations.append(f"{r['factor_name']}: material effect not from R4")
        if r["benchmark_signal_artifact_sha"] != SIGNALS_SHA:
            violations.append(f"{r['factor_name']}: signals SHA not pinned")
        if r["r3_direction"] != EXPECTED_R3_DIRECTION[r["factor_name"]]:
            violations.append(f"{r['factor_name']}: R3 direction not pinned")
        if r["r4_status"] != EXPECTED_R4_STATUS[r["factor_name"]]:
            violations.append(f"{r['factor_name']}: R4 status not pinned")
    return violations


def main() -> None:
    rows = build_registry()
    violations = validate_registry(rows)
    if violations:
        raise RuntimeError(
            f"R6A registry validation failed (fail closed): {violations}"
        )
    df = pd.DataFrame(rows)
    df.to_csv(OUT_REGISTRY, index=False)
    print("R6A_PINS: PASS")
    print("R6A_REGISTRY_ROWS:", len(df))
    print("OUT:", OUT_REGISTRY)


if __name__ == "__main__":
    main()
