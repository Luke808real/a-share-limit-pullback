"""R8A — intraday acceptance contract & data readiness V01.

CONTRACT + DATA READINESS ONLY. No R8 feature/outcome attribution is
computed. Pure formula contracts are exposed as testable functions; they are
never executed on the 8,682 cohort in this module.
"""

from __future__ import annotations

from datetime import time as dtime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
INTRAday_DIR = REPO_ROOT / "research" / "second_launch" / "intraday_v01"

OUT_FEATURE_REGISTRY = INTRAday_DIR / "r8a_intraday_feature_registry_v01.csv"
OUT_COHORT_MANIFEST = INTRAday_DIR / "r8a_intraday_cohort_manifest_v01.csv"
OUT_MINUTE_COVERAGE = INTRAday_DIR / "r8a_minute_coverage_v01.csv"

FEATURE_SHA = "a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8"
OUTCOME_SHA = "01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d"
SOURCE_HEAD = "fa70dd6dd8c5946544e48ad0d1e5196db8dc1bd1"
COHORT_N = 8682

CHECKPOINTS = ["09:45", "10:00", "10:30", "11:30"]
R8_GRANULARITY = "5m"
R8_DATA_STATUS = "BLOCKED_BY_MINUTE_COVERAGE"
MINUTE_SOURCE = "ASL_5M (upstream rootSunc/ashare-lake; not locally available)"

LEGACY_CASE_SET = (
    REPO_ROOT / "research" / "intraday" / "success_control_cases_v01b.csv"
)
LEGACY_MINUTE_MANIFEST = (
    REPO_ROOT / "research" / "intraday" / "v02a_minute_manifest.csv"
)
CURRENT_OUTCOME_CSV = (
    REPO_ROOT / "research" / "second_launch" / "outcome_v01"
    / "second_launch_outcome_v01b_reproducible.csv"
)


# ---------------------------------------------------------------------------
# Pure contract functions (formulas only; used by tests; never run on cohort).
# ---------------------------------------------------------------------------


def completed_bars_through(bars: pd.DataFrame, checkpoint: str) -> pd.DataFrame:
    """Right-labeled completed-bar slicing: bar_end <= checkpoint only."""
    hh, mm = checkpoint.split(":")
    cutoff_min = int(hh) * 60 + int(mm)
    parts = bars["bar_end"].astype(str).str.split(":", expand=True).astype(int)
    mins = parts[0] * 60 + parts[1]
    return bars[mins <= cutoff_min].reset_index(drop=True)


def first_s1_touch_bar(bars: pd.DataFrame, s1: float) -> pd.Series | None:
    """ACTIVATION anchor = first completed 5m bar whose HIGH >= S1."""
    touched = bars[bars["high"] >= s1]
    if len(touched) == 0:
        return None
    return touched.iloc[0]


def acceptance_window_bars(
    bars: pd.DataFrame, anchor_idx: int,
) -> pd.DataFrame:
    """Post-activation bars: strictly after the touch anchor bar."""
    return bars.iloc[anchor_idx + 1:].reset_index(drop=True)


def breakout_hold_ratio(window: pd.DataFrame, s1: float) -> float:
    """F7-1: share of post-activation completed bars with close >= S1."""
    if len(window) == 0:
        return float("nan")
    return float((window["close"] >= s1).mean())


def vwap_of(amount: np.ndarray, volume: np.ndarray) -> float:
    """Session VWAP = cumulative amount / cumulative volume (no proxy)."""
    return float(np.sum(amount) / np.sum(volume))


def vwap_acceptance_ratio(window: pd.DataFrame, vwap: float) -> float:
    """F7-2: share of post-activation bars with close >= session VWAP."""
    if len(window) == 0:
        return float("nan")
    return float((window["close"] >= vwap).mean())


def retest_depth(window: pd.DataFrame, s1: float) -> float:
    """F7-3: min(low / S1 - 1) over post-activation bars."""
    if len(window) == 0:
        return float("nan")
    return float((window["low"] / s1 - 1.0).min())


def false_break_duration(window: pd.DataFrame, s1: float) -> int:
    """F7-4: max consecutive completed bars with close < S1 after activation."""
    below = (window["close"] < s1).to_numpy()
    best = cur = 0
    for b in below:
        cur = cur + 1 if b else 0
        best = max(best, cur)
    return int(best)


def vwap_reclaim_rebreak(
    prev_close: float, cur_close: float, vwap: float,
) -> str:
    """V01B golden direction semantics:
    below->above crossing of VWAP = RECLAIM; above->below = REBREAK."""
    if prev_close < vwap <= cur_close:
        return "RECLAIM"
    if prev_close >= vwap > cur_close:
        return "REBREAK"
    return "NO_CROSS"


def activation_state(bars: pd.DataFrame, s1: float, checkpoint: str) -> str:
    """Layer A: activated_by_checkpoint (HIGH >= S1) or NOT_YET_ACTIVATED."""
    window = completed_bars_through(bars, checkpoint)
    return "ACTIVATED" if (window["high"] >= s1).any() else "NOT_YET_ACTIVATED"


# ---------------------------------------------------------------------------
# Feature registry (static contract).
# ---------------------------------------------------------------------------

FEATURE_ROWS: list[dict[str, str]] = [
    {
        "feature_id": "F7-1", "feature_name": "BREAKOUT_HOLD_RATIO",
        "layer": "B_ACCEPTANCE", "role": "PRIMARY",
        "required_activation": "FIRST_S1_TOUCH_5M_BAR",
        "checkpoint": "09:45/10:00/10:30/11:30",
        "formula": "share of post-activation completed 5m bars with close >= S1 "
                   "(touch anchor bar excluded)",
        "anchor_semantics": "first completed bar with HIGH >= S1; window starts "
                            "at NEXT completed bar",
        "data_source": "ASL_5M", "PIT_safe": "TRUE",
        "missing_semantics": "no post-activation bars -> NaN; not activated -> "
                             "NOT_YET_ACTIVATED (not 0)",
        "status": "CONTRACT_ONLY", "known_limitation": "requires ASL 5m coverage",
    },
    {
        "feature_id": "F7-2", "feature_name": "VWAP_ACCEPTANCE_RATIO",
        "layer": "B_ACCEPTANCE", "role": "PRIMARY",
        "required_activation": "FIRST_S1_TOUCH_5M_BAR",
        "checkpoint": "09:45/10:00/10:30/11:30",
        "formula": "share of post-activation bars with close >= session VWAP; "
                   "VWAP = cumulative amount / cumulative volume",
        "anchor_semantics": "same as F7-1",
        "data_source": "ASL_5M", "PIT_safe": "TRUE",
        "missing_semantics": "amount unavailable -> DATA_UNAVAILABLE "
                             "(NO close-weighted proxy fallback)",
        "status": "CONTRACT_ONLY",
        "known_limitation": "depends on ASL amount reliability",
    },
    {
        "feature_id": "F7-3", "feature_name": "RETEST_DEPTH",
        "layer": "B_ACCEPTANCE", "role": "PRIMARY",
        "required_activation": "FIRST_S1_TOUCH_5M_BAR",
        "checkpoint": "09:45/10:00/10:30/11:30",
        "formula": "min(low / S1 - 1) over post-activation bars to checkpoint",
        "anchor_semantics": "anchor bar excluded",
        "data_source": "ASL_5M", "PIT_safe": "TRUE",
        "missing_semantics": "no post-activation bars -> NaN",
        "status": "CONTRACT_ONLY", "known_limitation": "",
    },
    {
        "feature_id": "F7-4", "feature_name": "FALSE_BREAK_DURATION",
        "layer": "B_ACCEPTANCE", "role": "PRIMARY",
        "required_activation": "FIRST_S1_TOUCH_5M_BAR",
        "checkpoint": "09:45/10:00/10:30/11:30",
        "formula": "max consecutive completed 5m bars with close < S1 after "
                   "activation through checkpoint (unit: bars)",
        "anchor_semantics": "anchor bar excluded",
        "data_source": "ASL_5M", "PIT_safe": "TRUE",
        "missing_semantics": "no post-activation bars -> 0",
        "status": "CONTRACT_ONLY", "known_limitation": "",
    },
    {
        "feature_id": "S1", "feature_name": "S1_DISTANCE / S1_STATE",
        "layer": "A_ACTIVATION", "role": "SECONDARY",
        "required_activation": "NONE", "checkpoint": "09:45/10:00/10:30/11:30",
        "formula": "dist_to_s1_pct; high_vs_s1_pct; activated_by_checkpoint",
        "anchor_semantics": "checkpoint-level only",
        "data_source": "ASL_5M + frozen S1", "PIT_safe": "TRUE",
        "missing_semantics": "not activated -> NOT_YET_ACTIVATED",
        "status": "CONTRACT_ONLY", "known_limitation": "LAYER A denominator",
    },
    {
        "feature_id": "S2", "feature_name": "VWAP_DISTANCE / VWAP_STATE",
        "layer": "A_ACTIVATION", "role": "SECONDARY",
        "required_activation": "NONE", "checkpoint": "09:45/10:00/10:30/11:30",
        "formula": "close vs session VWAP distance and above/below state",
        "anchor_semantics": "VWAP from completed bars only",
        "data_source": "ASL_5M", "PIT_safe": "TRUE",
        "missing_semantics": "amount unavailable -> DATA_UNAVAILABLE",
        "status": "CONTRACT_ONLY", "known_limitation": "",
    },
    {
        "feature_id": "S3", "feature_name": "PREV_CLOSE_STATE",
        "layer": "A_ACTIVATION", "role": "SECONDARY",
        "required_activation": "NONE", "checkpoint": "09:45/10:00/10:30/11:30",
        "formula": "close vs previous close state",
        "anchor_semantics": "checkpoint-level",
        "data_source": "ASL_5M", "PIT_safe": "TRUE",
        "missing_semantics": "",
        "status": "CONTRACT_ONLY", "known_limitation": "",
    },
    {
        "feature_id": "S4", "feature_name": "HIGH_PROGRESSION",
        "layer": "A_ACTIVATION", "role": "SECONDARY",
        "required_activation": "NONE", "checkpoint": "09:45/10:00/10:30/11:30",
        "formula": "high progression through checkpoints",
        "anchor_semantics": "checkpoint-level",
        "data_source": "ASL_5M", "PIT_safe": "TRUE",
        "missing_semantics": "",
        "status": "CONTRACT_ONLY", "known_limitation": "",
    },
    {
        "feature_id": "S5", "feature_name": "OPEN_GAP / OPENING_DRAWDOWN",
        "layer": "A_ACTIVATION", "role": "CONTROL",
        "required_activation": "NONE", "checkpoint": "open",
        "formula": "open gap vs prev close; opening drawdown",
        "anchor_semantics": "first completed bar",
        "data_source": "ASL_5M", "PIT_safe": "TRUE",
        "missing_semantics": "",
        "status": "CONTRACT_ONLY", "known_limitation": "",
    },
    {
        "feature_id": "S6",
        "feature_name": "CUM_VOLUME_RELATIVE_TO_D1_SAME_TIME",
        "layer": "A_ACTIVATION", "role": "CONTROL",
        "required_activation": "NONE",
        "checkpoint": "09:45/10:00/10:30/11:30",
        "formula": "cumulative volume to checkpoint vs D1 same checkpoint "
                   "(same bar completion semantics; never full-day D1 volume)",
        "anchor_semantics": "checkpoint-level, right-labeled",
        "data_source": "ASL_5M", "PIT_safe": "TRUE",
        "missing_semantics": "D1 missing -> DATA_UNAVAILABLE",
        "status": "CONTRACT_ONLY", "known_limitation": "",
    },
    {
        "feature_id": "D1",
        "feature_name": "POST_BREAK_30M_RETURN / POST_BREAK_60M_RETURN",
        "layer": "B_ACCEPTANCE", "role": "DEFERRED",
        "required_activation": "FIRST_S1_TOUCH_5M_BAR",
        "checkpoint": "event-anchored",
        "formula": "DEFERRED: requires unique event-anchored PIT contract "
                   "without post-checkpoint future data",
        "anchor_semantics": "UNRESOLVED",
        "data_source": "ASL_5M", "PIT_safe": "FALSE_FOR_V01",
        "missing_semantics": "",
        "status": "DEFERRED",
        "known_limitation": "not implemented to avoid feature-count inflation",
    },
]


# ---------------------------------------------------------------------------
# Cohort rebase (legacy event alignment -> current 8,682).
# ---------------------------------------------------------------------------


def legacy_rebase(
    outcome: pd.DataFrame, case_set: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Map legacy event-alignment rows onto the current cohort by episode_id.

    Fail closed on identity mismatch or label drift.
    """
    legacy_events = case_set[case_set["V02_EVENT_COHORT"] == True].copy()  # noqa: E712
    stats: dict[str, int] = {
        "LEGACY_EVENT_N": len(legacy_events),
        "MAPPED_TO_8682_N": 0,
        "NOT_IN_CURRENT_COHORT_N": 0,
        "LABEL_DRIFT_N": 0,
        "IDENTITY_MISMATCH_N": 0,
    }
    cur = outcome.set_index("episode_id")
    manifest = outcome[["episode_id", "symbol", "anchor_date",
                        "candidate_date", "outcome_3d"]].copy()
    manifest["outcome_event_date"] = pd.NA
    manifest["legacy_event_mapping_status"] = "NOT_IN_LEGACY_EVENT_SET"
    manifest["asl_5m_coverage_status"] = "NOT_AVAILABLE"
    manifest["eligible_r8"] = False
    manifest["missing_reason"] = ""
    for _, row in legacy_events.iterrows():
        eid = row["episode_id"]
        if eid not in cur.index:
            stats["NOT_IN_CURRENT_COHORT_N"] += 1
            continue
        stats["MAPPED_TO_8682_N"] += 1
        c = cur.loc[eid]
        for col in ("symbol", "anchor_date", "candidate_date"):
            if str(row[col]) != str(c[col]):
                stats["IDENTITY_MISMATCH_N"] += 1
        if str(row["outcome"]) != str(c["outcome_3d"]):
            stats["LABEL_DRIFT_N"] += 1
        idx = manifest.index[manifest["episode_id"] == eid][0]
        manifest.at[idx, "outcome_event_date"] = row["OUTCOME_EVENT_DATE"]
        manifest.at[idx, "legacy_event_mapping_status"] = "MAPPED"
        manifest.at[idx, "eligible_r8"] = (
            str(c["outcome_3d"]) in ("SUCCESS", "FAILED_BREAKOUT")
        )
        manifest.at[idx, "missing_reason"] = (
            "ASL_5M_NOT_AVAILABLE" if manifest.at[idx, "eligible_r8"] else "")
    if stats["IDENTITY_MISMATCH_N"] > 0 or stats["LABEL_DRIFT_N"] > 0:
        raise RuntimeError(
            f"rebase fail closed: identity {stats['IDENTITY_MISMATCH_N']} "
            f"drift {stats['LABEL_DRIFT_N']}"
        )
    return manifest, stats


def minute_coverage_rows(
    legacy_manifest: pd.DataFrame,
) -> list[dict[str, Any]]:
    return [
        {
            "source": "ASL_5M",
            "status": "BLOCKED_BY_MINUTE_COVERAGE",
            "complete_n": 0,
            "success_complete_n": 0,
            "failed_breakout_complete_n": 0,
            "note": "upstream rootSunc/ashare-lake not locally available; "
                    "no fetch/backfill permitted",
        },
        {
            "source": "LEGACY_5M_PARITY_REFERENCE",
            "status": "LEGACY_PARITY_REFERENCE_ONLY",
            "complete_n": 139,
            "success_complete_n": 40,
            "failed_breakout_complete_n": 99,
            "note": "V02A verification doc (AKShare/Sina 5m); cache retains "
                    f"{int((legacy_manifest['bar_count'] > 0).sum())} days "
                    "with bars; NOT a formal R8 source",
        },
        {
            "source": "LEGACY_1M",
            "status": "LEGACY_PARITY_REFERENCE_ONLY",
            "complete_n": 7,
            "success_complete_n": 2,
            "failed_breakout_complete_n": 5,
            "note": "Sina 1m coverage ~8 trading days (2026-07-28..30); "
                    "1m NOT_PRIMARY for R8 V01",
        },
    ]


def main() -> None:
    INTRAday_DIR.mkdir(parents=True, exist_ok=True)
    outcome = pd.read_csv(CURRENT_OUTCOME_CSV, dtype={"symbol": str})
    case_set = pd.read_csv(LEGACY_CASE_SET, dtype={"symbol": str})
    if len(outcome) != COHORT_N:
        raise RuntimeError("current cohort row count drift (fail closed)")
    manifest, stats = legacy_rebase(outcome, case_set)
    manifest.to_csv(OUT_COHORT_MANIFEST, index=False)
    legacy_manifest = pd.read_csv(LEGACY_MINUTE_MANIFEST,
                                  dtype={"symbol": str})
    pd.DataFrame(minute_coverage_rows(legacy_manifest)).to_csv(
        OUT_MINUTE_COVERAGE, index=False)
    pd.DataFrame(FEATURE_ROWS).to_csv(OUT_FEATURE_REGISTRY, index=False)
    print("REBASE:", stats)
    print("OUT:", OUT_COHORT_MANIFEST)
    print("OUT:", OUT_MINUTE_COVERAGE)
    print("OUT:", OUT_FEATURE_REGISTRY)


if __name__ == "__main__":
    main()
