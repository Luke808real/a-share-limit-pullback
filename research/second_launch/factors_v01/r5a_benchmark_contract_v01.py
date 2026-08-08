"""R5A — external benchmark V01 registry (contract only; NO outcome execution).

Deterministic registry generation + schema validation. Pre-registered
contract: research/reports/SECOND_LAUNCH_FACTOR_R5A_EXTERNAL_BENCHMARK_CONTRACT_V01.md
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
    / "r5a_benchmark_registry_v01.csv"
)

VALID_STATUS = {"READY", "UNDERDEFINED", "DATA_UNAVAILABLE", "BLOCKED"}

FEATURE_SHA = "a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8"
SNAPSHOT_SHA = "e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514"
POOL_SHA = "45faa1a23583b04acfd6c4faf5ef42311c2575c93a4c702cf5846d0213f31517"

CANONICAL_SNAPSHOT = (
    REPO_ROOT / "data" / "canonical" / "daily_bars"
    / "snap-2026-07-31-b5f84004de8a.parquet"
)

# Outcome CSV may ONLY be read with these identity columns (outcome-blind).
OUTCOME_IDENTITY_COLUMNS = [
    "episode_id",
    "anchor_date",
    "candidate_date",
    "symbol",
    "feature_snapshot_id",
]


def blind_input_gate(
    feature_csv: Path = r3a.FEATURE_CSV,
    outcome_csv: Path = r3a.OUTCOME_CSV,
    expected_feature_sha: str = r3a.EXPECTED_FEATURE_SHA256,
    expected_outcome_sha: str = r3a.EXPECTED_OUTCOME_SHA256,
    expected_snapshot_id: str = r3a.EXPECTED_FEATURE_SNAPSHOT_ID,
    canonical_snapshot: Path = CANONICAL_SNAPSHOT,
    expected_snapshot_sha: str = SNAPSHOT_SHA,
    expected_rows: int = 8682,
) -> None:
    """Reproducible outcome-blind input gate (fail closed).

    Outcome CSV is read ONLY with OUTCOME_IDENTITY_COLUMNS (never outcome
    fields such as outcome_3d/outcome_5d/MFE/MAE).
    """
    if r3a.sha256_file(feature_csv) != expected_feature_sha:
        raise RuntimeError("feature CSV SHA mismatch (fail closed)")
    if r3a.sha256_file(outcome_csv) != expected_outcome_sha:
        raise RuntimeError("outcome CSV SHA mismatch (fail closed)")
    feat = pd.read_csv(feature_csv, dtype={"symbol": str})
    out = pd.read_csv(
        outcome_csv, usecols=OUTCOME_IDENTITY_COLUMNS, dtype={"symbol": str}
    )
    if len(feat) != expected_rows or len(out) != expected_rows:
        raise RuntimeError(
            f"row counts {len(feat)}/{len(out)} != {expected_rows}/{expected_rows}"
        )
    if feat["episode_id"].duplicated().any() or out["episode_id"].duplicated().any():
        raise RuntimeError("duplicate episode_id (fail closed)")
    if set(feat["episode_id"]) != set(out["episode_id"]):
        raise RuntimeError("episode_id sets not 1:1 exact (fail closed)")
    merged = feat.merge(out, on="episode_id", suffixes=("_f", "_o"))
    for col in ["anchor_date", "candidate_date", "symbol"]:
        if not (merged[f"{col}_f"] == merged[f"{col}_o"]).all():
            raise RuntimeError(f"identity binding mismatch on {col} (fail closed)")
    if not (out["feature_snapshot_id"] == expected_snapshot_id).all():
        raise RuntimeError("feature_snapshot_id binding mismatch (fail closed)")
    if r3a.sha256_file(canonical_snapshot) != expected_snapshot_sha:
        raise RuntimeError("canonical snapshot SHA mismatch (fail closed)")


REGISTRY: list[dict[str, str]] = [
    {
        "benchmark_id": "B1",
        "benchmark_name": "N_PATTERN",
        "definition_source": "UNDERDEFINED",
        "status": "UNDERDEFINED",
        "exact_rule": (
            "NOT_DEFINED: benchmark name/listing source = project research "
            "plan (Second-Launch-Factor-Research-V01.md section 3/8); no "
            "mechanical rule exists; shape requires subjective thresholds"
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
        "definition_source": "UNDERDEFINED",
        "status": "UNDERDEFINED",
        "exact_rule": (
            "NOT_DEFINED: benchmark name/listing source = project research "
            "plan (section 3/8); no mechanical rule; '回头' depth/duration/"
            "confirmation undefined"
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
        "definition_source": "UNDERDEFINED",
        "status": "UNDERDEFINED",
        "exact_rule": (
            "NOT_DEFINED: benchmark name/listing source = project research "
            "plan (section 3/8); no mechanical rule; yang scale, hold "
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
            "close_D > max(high, last min(60, available) sessions strictly "
            "before T0); fully reuses frozen PRE_ANCHOR_LEFT_HIGH helper "
            "semantics (src/limit_pullback/strategy/structure.py "
            "generate_resistance_candidates, resistance."
            "left_high_lookback_days=60): pre_anchor[-60:] takes all "
            "available sessions when <60 (no min-history gate); 20~59 "
            "sessions allowed; missing bars simply absent from reference; "
            "no CA filtering (helper does none); max(high) with "
            "(high, trade_date) tie-break (value unaffected); strict "
            "greater, equality is not a signal; reference excludes T0 and D"
        ),
        "required_fields": (
            "high over pre-T0 sessions (up to 60, as available), close_D"
        ),
        "input_window": "pre-T0 sessions (last min(60, available)) + D (close)",
        "latest_allowed_date": "D (candidate_date)",
        "pit_status": "PIT-SAFE (pre-T0 high + D close only)",
        "data_source": "canonical daily_bars snap-2026-07-31-b5f84004de8a",
        "artifact_sha": SNAPSHOT_SHA,
        "missing_semantics": (
            "no pre-T0 session at all -> no reference high -> episode "
            "excluded (NO_REFERENCE, fail closed); otherwise all available "
            "pre-T0 sessions up to 60 enter the reference"
        ),
        "known_limitation": (
            "mechanical proxy assembled from name structure + frozen "
            "resistance helper semantics; '<20 sessions exclude' and 'CA "
            "exclude' clauses from the earlier draft were NOT in the frozen "
            "helper and were removed (reuse-only)"
        ),
    },
    {
        "benchmark_id": "B8",
        "benchmark_name": "HOT_SECTOR_FILTER",
        "definition_source": "UNDERDEFINED",
        "status": "DATA_UNAVAILABLE",
        "exact_rule": (
            "NOT_DEFINED: no mechanical rule (sector strength threshold / "
            "limit-up count threshold / ranking cutoff / heat formula not "
            "defined); name/listing source = project research plan; "
            "DEFINITION=UNDERDEFINED, DATA=DATA_UNAVAILABLE (two independent "
            "limits)"
        ),
        "required_fields": "",
        "input_window": "",
        "latest_allowed_date": "",
        "pit_status": "N/A (no artifact)",
        "data_source": "",
        "artifact_sha": "",
        "missing_semantics": "",
        "known_limitation": (
            "DEFINITION=UNDERDEFINED (no mechanical rule exists); "
            "DATA=DATA_UNAVAILABLE (sector membership only in 15-day "
            "limit_up_pool; sector-strength factors (F8 CONTEXT) unfrozen; "
            "temp fetch forbidden); no threshold/cutoff/formula invented"
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
    # Formal fail-closed path: blind input gate BEFORE any registry write.
    blind_input_gate()
    violations = validate_registry(REGISTRY)
    if violations:
        raise RuntimeError(
            f"registry validation failed (fail closed): {violations}"
        )
    df = pd.DataFrame(REGISTRY)
    df.to_csv(OUT_REGISTRY, index=False)
    print("BLIND_INPUT_GATE: PASS")
    print("REGISTRY_VALID: PASS")
    print(df[["benchmark_id", "benchmark_name", "definition_source", "status"]]
          .to_string(index=False))
    print("OUT:", OUT_REGISTRY)


if __name__ == "__main__":
    main()
