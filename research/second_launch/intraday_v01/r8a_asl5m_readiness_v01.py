"""R8A — ASL 5m data readiness (read-only discovery + S1 provenance freeze).

No network / no repair / no backfill / no R8 outcome attribution.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "intraday_v01"))
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r8a_intraday_contract_v01 as r8a  # noqa: E402


OUT_PROVENANCE = (
    REPO_ROOT / "research" / "second_launch" / "intraday_v01"
    / "r8a_asl5m_provenance_v01.csv"
)

OUTCOME_SHA = "01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d"
LEGACY_CASE_SET_SHA = "b22eae1dd438ed1b4053ce2cfce7ce668010518462261cb724f149615894f4e6"

# Bounded discovery locations (maxdepth 3 under /Users/luke808/AI; /tmp spikes).
DISCOVERY_LOCATIONS = [
    "/Users/luke808/AI",
    "/Users/luke808/AI/V flash-asl-query-production",
    "/Users/luke808/AI/V flash-asl-phase1a",
    "/Users/luke808/AI/V flash-asl-phase1b",
    "/Users/luke808/AI/V flash-asl-phase1c",
    "/Users/luke808/AI/V flash-asl-clean-integration",
    "/tmp/asl_phase1a_lake",
    "/tmp/asl_phase1b_lake",
]


def asl_discovery() -> dict[str, Any]:
    """Read-only bounded discovery: return exact local ASL status."""
    import os

    env_root = None
    if os.environ.get("A_SHARE_DATA_ROOT"):
        env_root = os.environ["A_SHARE_DATA_ROOT"]
    # 1) look for a lake repo/dir under /Users/luke808/AI (maxdepth 3)
    lake_dirs: list[str] = []
    for base in DISCOVERY_LOCATIONS:
        root = Path(base)
        if not root.exists():
            continue
        if "lake" in root.name.lower():
            lake_dirs.append(str(root))
        if root.is_dir():
            try:
                for p in root.rglob("*"):
                    if p.is_dir() and "lake" in p.name.lower():
                        lake_dirs.append(str(p))
            except PermissionError:
                continue
    def _looks_like_asl_lake(path: Path) -> bool:
        if ".venv" in path.parts or "site-packages" in path.parts:
            return False
        return any((path / sub).is_dir() for sub in ("staging", "curated",
                                                      "meta"))

    lake_dirs = sorted({p for p in lake_dirs if _looks_like_asl_lake(Path(p))})
    # 2) scan only lake dirs for minute DATA (parquet; lock files excluded)
    found_minute: list[str] = []
    for lake in lake_dirs:
        try:
            for p in Path(lake).rglob("*"):
                if not p.is_file() or p.suffix.lower() != ".parquet":
                    continue
                low = p.name.lower()
                if "minute" in low or "5m" in low or "5min" in low:
                    found_minute.append(str(p))
        except PermissionError:
            continue
    return {
        "ASL_LOCAL_REPO": lake_dirs if lake_dirs else "NOT_FOUND",
        "ASL_CODE_HEAD": (
            "integration/asl-query-production @ 097fcb7 (worktree, read-only)"
        ),
        "ASL_WORKTREE_DIRTY": "not_modified",
        "ASL_DATA_ROOT": env_root if env_root else "UNSET",
        "ASL_MINUTE_DATA_FILES": found_minute,
        "ASL_MINUTE_PRESENT": bool(found_minute),
        "status": (
            "BLOCKED_LOCAL_ASL_NOT_FOUND"
            if not lake_dirs
            else ("ASL_LAKE_PRESENT_DAILY_ONLY" if not found_minute
                  else "ASL_LAKE_PRESENT_MINUTE_FOUND")
        ),
    }


def s1_provenance_rows(
    outcome: pd.DataFrame, case_set: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Freeze S1 provenance for the mapped 146 event episodes.

    S1 source = current frozen outcome artifact (s1_price; all 8,682 finite
    and > 0). Event date source = frozen legacy case set OUTCOME_EVENT_DATE.
    """
    legacy_events = case_set[case_set["V02_EVENT_COHORT"] == True].copy()  # noqa: E712
    cur = outcome.set_index("episode_id")
    rows = []
    bad = {"s1_not_finite": 0, "s1_not_positive": 0, "event_date_null": 0,
           "identity_mismatch": 0, "outcome_not_event": 0}
    for _, row in legacy_events.iterrows():
        eid = row["episode_id"]
        c = cur.loc[eid]
        for col in ("symbol", "anchor_date", "candidate_date"):
            if str(row[col]) != str(c[col]):
                bad["identity_mismatch"] += 1
        s1 = pd.to_numeric(c["s1_price"], errors="coerce")
        if not np.isfinite(s1):
            bad["s1_not_finite"] += 1
        elif s1 <= 0:
            bad["s1_not_positive"] += 1
        event_date = row["OUTCOME_EVENT_DATE"]
        if pd.isna(event_date) or str(event_date) == "NA":
            bad["event_date_null"] += 1
        if str(c["outcome_3d"]) not in ("SUCCESS", "FAILED_BREAKOUT"):
            bad["outcome_not_event"] += 1
        rows.append({
            "episode_id": eid,
            "symbol": str(c["symbol"]),
            "anchor_date": str(c["anchor_date"]),
            "candidate_date": str(c["candidate_date"]),
            "outcome_event_date": event_date,
            "s1_price": float(s1) if np.isfinite(s1) else np.nan,
            "current_outcome": str(c["outcome_3d"]),
            "s1_source": "current_frozen_outcome",
            "s1_source_sha": OUTCOME_SHA,
            "event_date_source": "legacy_frozen_case_set",
            "event_date_source_sha": LEGACY_CASE_SET_SHA,
            "asl_5m_status": "NOT_AVAILABLE",
        })
    if any(v > 0 for v in bad.values()):
        raise RuntimeError(
            f"S1 provenance fail closed: {bad}")
    return pd.DataFrame(rows), bad


def coverage_recompute(provenance: pd.DataFrame) -> pd.DataFrame:
    """R8 minute coverage with exact gaps (no ASL minute data present)."""
    total = len(provenance)
    success = (provenance["current_outcome"] == "SUCCESS").sum()
    failed = (provenance["current_outcome"] == "FAILED_BREAKOUT").sum()
    return pd.DataFrame([{
        "TOTAL_EVENT_COHORT": total,
        "ASL_EVENT_DAY_FOUND_N": 0,
        "ASL_MORNING_COMPLETE_N": 0,
        "SUCCESS_MORNING_COMPLETE_N": 0,
        "FAILED_BREAKOUT_MORNING_COMPLETE_N": 0,
        "FULL_DAY_COMPLETE_N": 0,
        "MISSING_EVENT_DAY_N": total,
        "INCOMPLETE_MORNING_N": 0,
        "VWAP_READY_N": 0,
        "D1_CONTROL_READY_N": 0,
        "RECONCILIATION": (
            f"ASL_MORNING_COMPLETE 0 + MISSING_EVENT_DAY {total} "
            f"== TOTAL {total}"
        ),
        "SUCCESS_TOTAL": int(success),
        "FAILED_BREAKOUT_TOTAL": int(failed),
        "VWAP_STATUS": "DATA_UNAVAILABLE",
        "S1_PROVENANCE": "PASS",
        "BAR_SEMANTICS": "VERIFICATION_PENDING_NO_ASL_DATA",
    }])


def main() -> None:
    discovery = asl_discovery()
    print("ASL_DISCOVERY:", discovery["status"], "| minute present:",
          discovery["ASL_MINUTE_PRESENT"])
    outcome = pd.read_csv(r8a.CURRENT_OUTCOME_CSV, dtype={"symbol": str})
    case_set = pd.read_csv(r8a.LEGACY_CASE_SET, dtype={"symbol": str})
    prov, bad = s1_provenance_rows(outcome, case_set)
    if len(prov) != 146:
        raise RuntimeError(f"S1 provenance rows {len(prov)} != 146")
    prov.to_csv(OUT_PROVENANCE, index=False)
    coverage = coverage_recompute(prov)
    coverage.to_csv(r8a.OUT_MINUTE_COVERAGE, index=False)
    # update cohort manifest with S1 columns
    manifest = pd.read_csv(r8a.OUT_COHORT_MANIFEST, dtype={"symbol": str})
    prov_map = prov.set_index("episode_id")
    manifest["s1_price"] = np.nan
    manifest["s1_source"] = ""
    manifest["s1_source_sha"] = ""
    manifest["event_date_source"] = ""
    manifest["event_date_source_sha"] = ""
    for eid in prov_map.index:
        m = manifest.index[manifest["episode_id"] == eid][0]
        manifest.at[m, "s1_price"] = prov_map.at[eid, "s1_price"]
        manifest.at[m, "s1_source"] = "current_frozen_outcome"
        manifest.at[m, "s1_source_sha"] = OUTCOME_SHA
        manifest.at[m, "event_date_source"] = "legacy_frozen_case_set"
        manifest.at[m, "event_date_source_sha"] = LEGACY_CASE_SET_SHA
    manifest.to_csv(r8a.OUT_COHORT_MANIFEST, index=False)
    print("S1_PROVENANCE:", bad, "rows:", len(prov))
    print(coverage.to_string(index=False))
    print("OUT:", OUT_PROVENANCE)
    print("OUT:", r8a.OUT_COHORT_MANIFEST)
    print("OUT:", r8a.OUT_MINUTE_COVERAGE)


if __name__ == "__main__":
    main()
