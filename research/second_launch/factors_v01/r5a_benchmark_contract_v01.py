"""R5A — external benchmark V01 registry (contract only; NO outcome execution).

Deterministic registry generation + schema validation. Pre-registered
contract: research/reports/SECOND_LAUNCH_FACTOR_R5A_EXTERNAL_BENCHMARK_CONTRACT_V01.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_REGISTRY = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r5a_benchmark_registry_v01.csv"
)

VALID_STATUS = {"READY", "UNDERDEFINED", "DATA_UNAVAILABLE", "BLOCKED"}

FEATURE_SHA = "a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8"
SNAPSHOT_SHA = "e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514"
POOL_SHA = "45faa1a23583b04acfd6c4faf5ef42311c2575c93a4c702cf5846d0213f31517"


REGISTRY: list[dict[str, str]] = [
    {
        "benchmark_id": "B1",
        "benchmark_name": "N_PATTERN",
        "definition_source": "PROJECT_DOCUMENTED",
        "status": "UNDERDEFINED",
        "exact_rule": (
            "NOT_DEFINED: project lists 'N字战法' name only; mechanical shape "
            "requires subjective thresholds -> kept UNDERDEFINED"
        ),
        "required_fields": "",
        "input_window": "",
        "latest_allowed_date": "",
        "pit_status": "N/A (no rule frozen)",
        "data_source": "",
        "artifact_sha": "",
        "missing_semantics": "",
        "known_limitation": (
            "must be frozen manually before READY; inventing rules forbidden"
        ),
    },
    {
        "benchmark_id": "B2",
        "benchmark_name": "DRAGON_RETURN_2N",
        "definition_source": "PROJECT_DOCUMENTED",
        "status": "UNDERDEFINED",
        "exact_rule": (
            "NOT_DEFINED: project lists '龙回头 / 2+N' name only; '回头' depth/"
            "duration/confirmation undefined"
        ),
        "required_fields": "",
        "input_window": "",
        "latest_allowed_date": "",
        "pit_status": "N/A (no rule frozen)",
        "data_source": "",
        "artifact_sha": "",
        "missing_semantics": "",
        "known_limitation": "must be frozen manually before READY",
    },
    {
        "benchmark_id": "B3",
        "benchmark_name": "SINGLE_YANG_HOLD",
        "definition_source": "PROJECT_DOCUMENTED",
        "status": "UNDERDEFINED",
        "exact_rule": (
            "NOT_DEFINED: project lists '单阳不破' name only; yang scale, hold "
            "reference, duration undefined"
        ),
        "required_fields": "",
        "input_window": "",
        "latest_allowed_date": "",
        "pit_status": "N/A (no rule frozen)",
        "data_source": "",
        "artifact_sha": "",
        "missing_semantics": "",
        "known_limitation": "must be frozen manually before READY",
    },
    {
        "benchmark_id": "B4",
        "benchmark_name": "FIXED_PULLBACK_TIME",
        "definition_source": "PROJECT_FROZEN",
        "status": "READY",
        "exact_rule": "2 <= days_since_t0 <= 5",
        "required_fields": "days_since_t0",
        "input_window": "T0..D",
        "latest_allowed_date": "D (candidate_date)",
        "pit_status": "PIT-SAFE (feature as-of D)",
        "data_source": "second_launch_factors_v01b_reproducible.csv",
        "artifact_sha": FEATURE_SHA,
        "missing_semantics": (
            "days_since_t0 missing (MISSING_D_BAR) -> episode excluded"
        ),
        "known_limitation": (
            "thresholds from project's own frozen strategy config "
            "(b1.optimal_days_min/max); self-baseline, not community standard"
        ),
    },
    {
        "benchmark_id": "B5",
        "benchmark_name": "FIXED_PULLBACK_DEPTH",
        "definition_source": "PROJECT_FROZEN",
        "status": "READY",
        "exact_rule": "close_D / close_T0 - 1 >= -0.04",
        "required_fields": "close_D, close_T0",
        "input_window": "{T0, D}",
        "latest_allowed_date": "D (candidate_date)",
        "pit_status": "PIT-SAFE (D-close vs T0-close)",
        "data_source": "canonical daily_bars snap-2026-07-31-b5f84004de8a",
        "artifact_sha": SNAPSHOT_SHA,
        "missing_semantics": (
            "T0 or D CA day (preclose divergence >0.5%) or missing bar -> "
            "episode excluded (fail closed)"
        ),
        "known_limitation": (
            "thresholds from project's own frozen strategy config "
            "(b1.close_to_anchor_min); self-baseline; uses D-close depth, "
            "not min-pullback-close"
        ),
    },
    {
        "benchmark_id": "B6",
        "benchmark_name": "FIXED_VOLUME_CONTRACTION",
        "definition_source": "PROJECT_FROZEN",
        "status": "READY",
        "exact_rule": "volume_D / volume_T0 <= 0.85",
        "required_fields": "volume_D, volume_T0",
        "input_window": "{T0, D}",
        "latest_allowed_date": "D (candidate_date)",
        "pit_status": "PIT-SAFE (D volume vs T0 volume)",
        "data_source": "canonical daily_bars snap-2026-07-31-b5f84004de8a",
        "artifact_sha": SNAPSHOT_SHA,
        "missing_semantics": (
            "T0 or D CA day or missing bar or volume<=0 -> episode excluded"
        ),
        "known_limitation": (
            "thresholds from project's own frozen strategy config "
            "(b1.volume_to_anchor_max); self-baseline; uses D-day volume, "
            "not PB median"
        ),
    },
    {
        "benchmark_id": "B7",
        "benchmark_name": "POST_LIMIT_NEW_HIGH_PROXY",
        "definition_source": "MECHANICAL_PROXY",
        "status": "READY",
        "exact_rule": (
            "close_D > max(high, sessions [T0-60 .. T0-1]); reference "
            "excludes T0 and D; strict greater (no equality); close-based "
            "breakout; window from frozen resistance.left_high_lookback_days=60"
        ),
        "required_fields": (
            "high over 60 pre-T0 sessions, close_D, preclose (CA detection)"
        ),
        "input_window": "[T0-60 .. T0-1] (high) + D (close)",
        "latest_allowed_date": "D (candidate_date)",
        "pit_status": "PIT-SAFE (pre-T0 high + D close only)",
        "data_source": "canonical daily_bars snap-2026-07-31-b5f84004de8a",
        "artifact_sha": SNAPSHOT_SHA,
        "missing_semantics": (
            "CA event in reference window or <20 valid prior sessions -> "
            "episode excluded (fail closed)"
        ),
        "known_limitation": (
            "mechanical proxy assembled from name structure + frozen window; "
            "'break T0 high' variant considered but not selected (single rule)"
        ),
    },
    {
        "benchmark_id": "B8",
        "benchmark_name": "HOT_SECTOR_FILTER",
        "definition_source": "PROJECT_DOCUMENTED",
        "status": "DATA_UNAVAILABLE",
        "exact_rule": "NOT_RUN: no PIT-safe sector artifact",
        "required_fields": "",
        "input_window": "",
        "latest_allowed_date": "",
        "pit_status": "N/A (no artifact)",
        "data_source": "",
        "artifact_sha": "",
        "missing_semantics": "",
        "known_limitation": (
            "sector membership only in 15-day limit_up_pool; sector-strength "
            "factors (F8 CONTEXT) unfrozen; temp fetch forbidden"
        ),
    },
]


def validate_registry(rows: list[dict[str, str]]) -> list[str]:
    """Schema / status checks. Returns list of violations (empty = valid)."""
    violations: list[str] = []
    ids = [r["benchmark_id"] for r in rows]
    if len(ids) != len(set(ids)):
        violations.append("duplicate benchmark_id")
    if ids != sorted(ids, key=lambda x: (len(x), x)):
        violations.append("benchmark_id not sorted")
    if len(rows) != 8:
        violations.append(f"universe must be 8, got {len(rows)}")
    names = {r["benchmark_name"] for r in rows}
    if "TRIPLE_VOLUME" in names or "SAN_BEI_LIANG" in names:
        violations.append("三倍量 must not be added (research plan excludes it)")
    for r in rows:
        if r["status"] not in VALID_STATUS:
            violations.append(f"{r['benchmark_id']}: invalid status {r['status']}")
        if r["definition_source"] not in {
            "PROJECT_FROZEN", "PROJECT_DOCUMENTED", "MECHANICAL_PROXY",
            "UNDERDEFINED",
        }:
            violations.append(
                f"{r['benchmark_id']}: invalid definition_source "
                f"{r['definition_source']}"
            )
        if r["status"] == "READY":
            if not r["exact_rule"]:
                violations.append(f"{r['benchmark_id']}: READY without exact_rule")
            if not r["required_fields"]:
                violations.append(f"{r['benchmark_id']}: READY without required_fields")
            if not r["input_window"]:
                violations.append(f"{r['benchmark_id']}: READY without input_window")
            if r["latest_allowed_date"] != "D (candidate_date)":
                violations.append(
                    f"{r['benchmark_id']}: latest_allowed_date must be D"
                )
            if "PIT-SAFE" not in r["pit_status"]:
                violations.append(f"{r['benchmark_id']}: pit_status must be PIT-SAFE")
            if not r["data_source"] or not r["artifact_sha"]:
                violations.append(f"{r['benchmark_id']}: READY without data lineage")
        if "future" in r["exact_rule"].lower() or "D+1" in r["exact_rule"]:
            violations.append(f"{r['benchmark_id']}: rule references future data")
    return violations


def main() -> None:
    violations = validate_registry(REGISTRY)
    if violations:
        raise RuntimeError(
            f"registry validation failed (fail closed): {violations}"
        )
    df = pd.DataFrame(REGISTRY)
    df.to_csv(OUT_REGISTRY, index=False)
    print("REGISTRY_VALID: PASS")
    print(df[["benchmark_id", "benchmark_name", "definition_source", "status"]]
          .to_string(index=False))
    print("OUT:", OUT_REGISTRY)


if __name__ == "__main__":
    main()
