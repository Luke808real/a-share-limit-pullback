"""R6B — incremental-value execution V01.

Executes the frozen R6A contract: conditional residual discrimination of the
F3 contraction factors within R5 benchmark signal groups (primary B6).
Classification state machine is frozen here BEFORE any outcome reading.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402


OUT_CONDITIONAL = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r6b_incremental_conditional_results_v01.csv"
)
OUT_SUMMARY = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r6b_incremental_summary_v01.csv"
)

# ---- frozen pins (R6A contract / R5 final source head 7e046c7) ----
FEATURE_SHA = "a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8"
OUTCOME_SHA = "01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d"
SIGNALS_SHA = "ee1c132bf8baa9d479eb0fd01592fe0a44d4851503353986620fc978720995c8"
R6A_REGISTRY_SHA = (
    "08b8e01d1a2f11970871366a265e32cba723f27a16b27f165a924de1571b2e1f"
)
SOURCE_HEAD = "7e046c7ba14c8822ad042a2915e3ed4cf16df132"
MATERIAL_EFFECT = 0.03

FROZEN_R3_DIRECTION = {
    "pullback_volume_ratio": "NEGATIVE",
    "min_volume_ratio": "NEGATIVE",
    "median_range_ratio": "NEGATIVE",
    "quiet_days_n": "POSITIVE",
    "high_vs_pullback_high": "POSITIVE",
    "close_vs_pullback_high": "POSITIVE",
}
BASELINE_ROLE = {
    "B4": "SECONDARY_BASELINE",
    "B5": "WEAK_CONTROL_BASELINE",
    "B6": "PRIMARY_BASELINE",
    "B7": "WEAK_CONTROL_BASELINE",
}


# ---------------------------------------------------------------------------
# Frozen classification state machine (frozen BEFORE outcome labels are read).
# ---------------------------------------------------------------------------


def direction_of(auc: Any) -> str:
    """sign(AUC - 0.5): >0.5 POSITIVE, <0.5 NEGATIVE, ==0.5 NEUTRAL,
    non-identifiable -> UNKNOWN. Never uses auc >= 0.5."""
    if isinstance(auc, str) or auc is None:
        return "UNKNOWN"
    try:
        a = float(auc)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not np.isfinite(a):
        return "UNKNOWN"
    if a > 0.5:
        return "POSITIVE"
    if a < 0.5:
        return "NEGATIVE"
    return "NEUTRAL"


def opposite_direction(direction: str) -> str:
    return {"POSITIVE": "NEGATIVE", "NEGATIVE": "POSITIVE"}.get(
        direction, "NEUTRAL"
    )


def classify_incremental(
    auc_3d: Any,
    auc_5d: Any,
    r3_direction: str,
    identifiable: bool,
) -> tuple[str, str]:
    """Frozen classification (R6B contract section 6).

    Returns (classification, sensitivity_note).
    """
    if not identifiable:
        return "DATA_LIMITED", ""
    dir3 = direction_of(auc_3d)
    dir5 = direction_of(auc_5d)
    if dir3 in ("UNKNOWN",) or dir5 in ("UNKNOWN",):
        return "DATA_LIMITED", ""
    effect3 = abs(float(auc_3d) - 0.5)
    # 3D direction must match frozen R3 direction.
    if dir3 != r3_direction:
        return "NO_INCREMENTAL_VALUE", ""
    if effect3 >= MATERIAL_EFFECT:
        # Material 3D edge must survive 5D sensitivity.
        if dir5 != r3_direction:
            return "NO_INCREMENTAL_VALUE", "SENSITIVITY_REVERSED_OR_NEUTRAL"
        return "INCREMENTAL_SUPPORTED", ""
    # Weak 3D edge: no opposite-direction reversal in 5D.
    if dir5 == opposite_direction(r3_direction):
        return "NO_INCREMENTAL_VALUE", "SENSITIVITY_OPPOSITE"
    if dir5 == "NEUTRAL":
        return "INCREMENTAL_WEAK", "WEAK_WITH_NEUTRAL_SENSITIVITY"
    return "INCREMENTAL_WEAK", ""


# ---------------------------------------------------------------------------
# Input / registry gates.
# ---------------------------------------------------------------------------


def input_gate() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if r3a.sha256_file(r3a.FEATURE_CSV) != FEATURE_SHA:
        raise RuntimeError("feature CSV SHA mismatch (fail closed)")
    if r3a.sha256_file(r3a.OUTCOME_CSV) != OUTCOME_SHA:
        raise RuntimeError("outcome CSV SHA mismatch (fail closed)")
    signals_csv = REPO_ROOT / "research" / "second_launch" / "factors_v01" \
        / "r5b_benchmark_episode_signals_v01.csv"
    if r3a.sha256_file(signals_csv) != SIGNALS_SHA:
        raise RuntimeError("R5B signals SHA mismatch (fail closed)")
    feat = pd.read_csv(r3a.FEATURE_CSV, dtype={"symbol": str})
    out = pd.read_csv(r3a.OUTCOME_CSV, dtype={"symbol": str})
    sig = pd.read_csv(signals_csv, dtype={"symbol": str})
    for df, n in ((feat, 8682), (out, 8682), (sig, 8682)):
        if len(df) != n:
            raise RuntimeError(f"row count {len(df)} != {n} (fail closed)")
    for df in (feat, out, sig):
        if df["episode_id"].duplicated().any():
            raise RuntimeError("duplicate episode_id (fail closed)")
    ids = [set(df["episode_id"]) for df in (feat, out, sig)]
    if not (ids[0] == ids[1] == ids[2]):
        raise RuntimeError("episode_id sets not 1:1 exact (fail closed)")
    m = feat.merge(out, on="episode_id", suffixes=("_f", "_o"))
    for col in ["anchor_date", "candidate_date", "symbol"]:
        if not (m[f"{col}_f"] == m[f"{col}_o"]).all():
            raise RuntimeError(f"identity binding mismatch on {col}")
    return feat, out, sig


def registry_gate() -> pd.DataFrame:
    reg_csv = (
        REPO_ROOT / "research" / "second_launch" / "factors_v01"
        / "r6a_incremental_registry_v01.csv"
    )
    if r3a.sha256_file(reg_csv) != R6A_REGISTRY_SHA:
        raise RuntimeError("R6A registry SHA mismatch (fail closed)")
    reg = pd.read_csv(reg_csv)
    if len(reg) != 24:
        raise RuntimeError(f"R6A registry rows {len(reg)} != 24 (fail closed)")
    if set(reg["baseline_id"]) != set(BASELINE_ROLE):
        raise RuntimeError("baseline set mismatch (fail closed)")
    primary = set(reg.loc[reg["baseline_role"] == "PRIMARY_BASELINE",
                          "baseline_id"])
    if primary != {"B6"}:
        raise RuntimeError("PRIMARY baseline must be exactly B6 (fail closed)")
    factors = set(reg["factor_name"])
    if factors != set(FROZEN_R3_DIRECTION):
        raise RuntimeError("factor set mismatch (fail closed)")
    for _, r in reg.iterrows():
        if r["r3_direction"] != FROZEN_R3_DIRECTION[r["factor_name"]]:
            raise RuntimeError("R3 direction drift (fail closed)")
        if float(r["material_effect_threshold"]) != MATERIAL_EFFECT:
            raise RuntimeError("material effect threshold drift (fail closed)")
    return reg


# ---------------------------------------------------------------------------
# Conditional metrics.
# ---------------------------------------------------------------------------


def conditional_row(
    feat: pd.DataFrame,
    out: pd.DataFrame,
    sig: pd.DataFrame,
    baseline_id: str,
    factor: str,
    scope: str,
    group: str,
    target: str,
    reg_row: pd.Series,
) -> dict[str, Any]:
    base_elig = sig[f"{baseline_id}_eligible"].astype(bool).to_numpy()
    base_sig = sig[f"{baseline_id}_signal"].astype(bool).to_numpy()
    scope_mask = (
        np.ones(len(sig), dtype=bool)
        if scope == "OWN"
        else sig["common_eligible"].astype(bool).to_numpy()
    )
    if group == "SIGNAL":
        group_mask = base_sig
    else:
        group_mask = base_elig & (~base_sig)
    elig_mask = scope_mask & base_elig & group_mask
    factor_vals = pd.to_numeric(feat[factor], errors="coerce").to_numpy()
    factor_finite = np.isfinite(factor_vals)
    known = out[target].to_numpy() != "UNKNOWN"
    labels_raw = out[target].to_numpy()
    sample = elig_mask & factor_finite & known
    eligible_group_n = int(elig_mask.sum())
    factor_nonmissing_n = int((elig_mask & factor_finite).sum())
    outcome_known_n = int(sample.sum())
    success_n = int((labels_raw[sample] == "SUCCESS").sum())
    non_success_n = outcome_known_n - success_n
    unique_vals = np.unique(factor_vals[sample]) if outcome_known_n else np.array([])
    identifiable = (
        outcome_known_n > 0
        and success_n > 0
        and non_success_n > 0
        and len(unique_vals) >= 2
    )
    if identifiable:
        auc = r3a.binary_auc(factor_vals[sample],
                             (labels_raw[sample] == "SUCCESS").astype(int))
    else:
        auc = float("nan")
    direction = direction_of(auc)
    effect = abs(auc - 0.5) if np.isfinite(auc) else float("nan")
    r3_dir = str(reg_row["r3_direction"])
    if outcome_known_n == 0:
        missing_reason = "EMPTY_OR_ALL_UNKNOWN"
    elif success_n == 0:
        missing_reason = "NO_SUCCESS"
    elif non_success_n == 0:
        missing_reason = "NO_NON_SUCCESS"
    elif len(unique_vals) < 2:
        missing_reason = "FACTOR_CONSTANT_OR_SINGLE_VALUE"
    else:
        missing_reason = ""
    return {
        "baseline_id": baseline_id,
        "baseline_role": str(reg_row["baseline_role"]),
        "factor_name": factor,
        "factor_family": str(reg_row["factor_family"]),
        "factor_role": str(reg_row["factor_role"]),
        "sample_scope": scope,
        "baseline_group": group,
        "target": target,
        "eligible_group_n": eligible_group_n,
        "factor_nonmissing_n": factor_nonmissing_n,
        "outcome_known_n": outcome_known_n,
        "success_n": success_n,
        "non_success_n": non_success_n,
        "native_auc": auc,
        "native_direction": direction,
        "r3_direction": r3_dir,
        "direction_match": bool(direction == r3_dir),
        "effect": effect,
        "identifiability_status": (
            "IDENTIFIABLE" if identifiable else "NOT_IDENTIFIABLE"
        ),
        "missing_reason": missing_reason,
    }


def main() -> None:
    feat, out, sig = input_gate()
    reg = registry_gate()
    rows: list[dict[str, Any]] = []
    for _, reg_row in reg.iterrows():
        for scope in ("OWN", "COMMON"):
            for group in ("SIGNAL", "NON_SIGNAL"):
                for target in ("outcome_3d", "outcome_5d"):
                    rows.append(conditional_row(
                        feat, out, sig, reg_row["baseline_id"],
                        reg_row["factor_name"], scope, group, target, reg_row,
                    ))
    cond = pd.DataFrame(rows)
    cond = cond.sort_values(
        ["baseline_id", "factor_name", "sample_scope", "baseline_group",
         "target"]
    ).reset_index(drop=True)
    cond.to_csv(OUT_CONDITIONAL, index=False)

    # summary: one row per baseline x factor x scope; classification from
    # SIGNAL-group 3D/5D per the frozen state machine.
    summary_rows: list[dict[str, Any]] = []
    for (bid, factor, scope), g in cond.groupby(
        ["baseline_id", "factor_name", "sample_scope"]
    ):
        sig3 = g[(g["baseline_group"] == "SIGNAL") & (g["target"] == "outcome_3d")]
        sig5 = g[(g["baseline_group"] == "SIGNAL") & (g["target"] == "outcome_5d")]
        non3 = g[(g["baseline_group"] == "NON_SIGNAL")
                 & (g["target"] == "outcome_3d")]
        non5 = g[(g["baseline_group"] == "NON_SIGNAL")
                 & (g["target"] == "outcome_5d")]
        r3_dir = str(sig3.iloc[0]["r3_direction"])
        identifiable = (
            sig3.iloc[0]["identifiability_status"] == "IDENTIFIABLE"
            and sig5.iloc[0]["identifiability_status"] == "IDENTIFIABLE"
        )
        classification, note = classify_incremental(
            sig3.iloc[0]["native_auc"], sig5.iloc[0]["native_auc"],
            r3_dir, identifiable,
        )
        summary_rows.append({
            "baseline_id": bid,
            "baseline_role": str(sig3.iloc[0]["baseline_role"]),
            "factor_name": factor,
            "factor_family": str(sig3.iloc[0]["factor_family"]),
            "factor_role": str(sig3.iloc[0]["factor_role"]),
            "sample_scope": scope,
            "auc_3d_signal": sig3.iloc[0]["native_auc"],
            "effect_3d_signal": sig3.iloc[0]["effect"],
            "direction_match_3d": bool(sig3.iloc[0]["direction_match"]),
            "auc_5d_signal": sig5.iloc[0]["native_auc"],
            "effect_5d_signal": sig5.iloc[0]["effect"],
            "direction_match_5d": bool(sig5.iloc[0]["direction_match"]),
            "auc_3d_nonsignal": non3.iloc[0]["native_auc"],
            "auc_5d_nonsignal": non5.iloc[0]["native_auc"],
            "incremental_classification": classification,
            "sensitivity_note": note,
        })
    summary = pd.DataFrame(summary_rows)
    summary = summary.sort_values(
        ["baseline_id", "factor_name", "sample_scope"]
    ).reset_index(drop=True)
    summary.to_csv(OUT_SUMMARY, index=False)

    # ---- QA reconciliation (fail closed) ----
    for _, r in cond.iterrows():
        assert r["outcome_known_n"] == r["success_n"] + r["non_success_n"]
        assert r["eligible_group_n"] >= r["factor_nonmissing_n"] >= r["outcome_known_n"]
    # signal / non-signal disjoint and partition of eligible known sample
    for bid in BASELINE_ROLE:
        for scope in ("OWN", "COMMON"):
            base_elig = sig[f"{bid}_eligible"].astype(bool).to_numpy()
            base_sig = sig[f"{bid}_signal"].astype(bool).to_numpy()
            scope_m = (np.ones(len(sig), dtype=bool) if scope == "OWN"
                       else sig["common_eligible"].astype(bool).to_numpy())
            known3 = out["outcome_3d"].to_numpy() != "UNKNOWN"
            sig_n = int((scope_m & base_elig & base_sig & known3).sum())
            non_n = int((scope_m & base_elig & ~base_sig & known3).sum())
            assert sig_n + non_n == int((scope_m & base_elig & known3).sum())
    # 3D/5D membership invariance: only outcome-known mask may differ
    wide = cond.pivot_table(
        index=["baseline_id", "factor_name", "sample_scope", "baseline_group"],
        columns="target", values=["eligible_group_n", "factor_nonmissing_n"],
        aggfunc="first",
    )
    for col in ["eligible_group_n", "factor_nonmissing_n"]:
        a = wide[(col, "outcome_3d")].to_numpy()
        b = wide[(col, "outcome_5d")].to_numpy()
        assert (a == b).all(), f"{col} differs between 3D/5D"
    # 24 combos present, no duplicates
    assert len(cond) == 192 and len(summary) == 48
    assert not cond.duplicated().any() and not summary.duplicated().any()
    print("R6B QA RECONCILIATION: PASS")
    print("CONDITIONAL_ROWS:", len(cond), "SUMMARY_ROWS:", len(summary))
    print("OUT:", OUT_CONDITIONAL)
    print("OUT:", OUT_SUMMARY)


if __name__ == "__main__":
    main()
