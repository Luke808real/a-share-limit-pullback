"""R1A.2 conflict forensics for the 64 three-day provenance conflicts.

Read-only research audit (no label changes, no 5D publication). Produces
`research/second_launch/outcome_v01/case_provenance_conflicts_v01.csv` and
prints Parts B-F statistics for the R1A.2 report.

Only the 3D window (candidate date + up to 3 sessions) is forensically
examined; no full-market reconciliation is performed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import glob
import json
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

import build_second_launch_outcome_v01 as gen


RAW_TUSHARE_GLOB = gen.REPO_ROOT / "data/raw/tushare/daily_bars/*.parquet"
RAW_AKSHARE_GLOB = gen.REPO_ROOT / "data/raw/akshare/daily_bars/*.parquet"

PRICE_FIELDS = ["open", "high", "low", "close", "volume"]


def dedupe_raw(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Dedupe raw provider rows by (code, trade_date), fail closed on conflicts.

    - identical OHLCV duplicates: deterministically deduped (keep first),
      counted in raw_duplicate_identical_n;
    - conflicting OHLCV versions: kept as RAW_PROVIDER_VERSION_CONFLICT records
      (not silently dropped); the conflict dates are returned so the provider
      cross-check never marks them as a provider MATCH.
    """
    if df.empty:
        return df, {
            "raw_duplicate_identical_n": 0,
            "raw_duplicate_conflict_n": 0,
            "raw_duplicate_conflict_dates": [],
        }
    grouped = df.groupby(["code", "trade_date"], sort=False)
    identical_n = 0
    conflict_groups: set[tuple[str, date]] = set()
    keep_indexes: list[int] = []
    for (code, trade_date), group in grouped:
        if len(group) == 1:
            keep_indexes.append(group.index[0])
            continue
        rounded = group[PRICE_FIELDS].round(2)
        first = rounded.iloc[0]
        all_identical = bool((rounded == first).all(axis=1).all())
        if all_identical:
            identical_n += len(group) - 1
            keep_indexes.append(group.index[0])
        else:
            conflict_groups.add((code, trade_date))
            keep_indexes.extend(group.index.tolist())
    deduped = df.loc[keep_indexes].reset_index(drop=True)
    # Keep conflict dates flagged so provider matching never treats them as MATCH.
    deduped["_raw_version_conflict"] = deduped.apply(
        lambda r: (r["code"], r["trade_date"]) in conflict_groups, axis=1
    )
    return deduped, {
        "raw_duplicate_identical_n": identical_n,
        "raw_duplicate_conflict_n": len(conflict_groups),
        "raw_duplicate_conflict_dates": sorted(
            f"{c}:{d}" for c, d in conflict_groups
        ),
    }


# ---------------------------------------------------------------------------
# Loaders (explicit snapshot paths; reconciliation-aware).
# ---------------------------------------------------------------------------

def load_canonical_with_reconciliation(
    path: Path, codes: set[str]
) -> pd.DataFrame:
    """Canonical bars with reconciliation/status columns for the given codes."""
    table = pq.read_table(
        path,
        columns=list(
            dict.fromkeys(gen.BAR_COLUMNS + ["reconciliation_status", "selected_provider"])
        ),
        filters=[("code", "in", sorted(codes))],
    )
    df = table.to_pandas()
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df.sort_values(["code", "trade_date"]).reset_index(drop=True)


def load_raw_provider(
    glob_pattern: Path, codes: set[str]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Raw provider daily bars + duplicate stats (fail closed on conflicts)."""
    frames = []
    for path in sorted(glob.glob(str(glob_pattern))):
        table = pq.read_table(
            path,
            columns=["code", "trade_date", "open", "high", "low", "close", "volume"],
            filters=[("code", "in", sorted(codes))],
        )
        df = table.to_pandas()
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        frames.append(df)
    if not frames:
        return (
            pd.DataFrame(columns=["code", "trade_date"] + PRICE_FIELDS),
            {
                "raw_duplicate_identical_n": 0,
                "raw_duplicate_conflict_n": 0,
                "raw_duplicate_conflict_dates": [],
            },
        )
    out = pd.concat(frames, ignore_index=True)
    return dedupe_raw(out)


def _rounded(row: pd.Series) -> tuple[float, ...]:
    return tuple(round(float(row[f]), 2) for f in PRICE_FIELDS)


def _same(row_a: pd.Series, row_b: pd.Series) -> bool:
    return _rounded(row_a) == _rounded(row_b)


# ---------------------------------------------------------------------------
# Part B: conflict classification.
# ---------------------------------------------------------------------------

def classify_conflict(
    frozen_pattern: str,
    recomputed_pattern: str,
    frozen_outcome: str,
    recomputed_outcome: str,
    frozen_reason: str,
    recomputed_reason: str,
) -> str:
    """Dynamic conflict class; no hardcoded counts."""
    if frozen_pattern != recomputed_pattern:
        return "PATTERN_CHANGED"
    if "no S1-touch bar found" in frozen_reason:
        return "S1_TOUCH_RESOLUTION_CHANGED"
    if frozen_outcome != recomputed_outcome:
        if "SUCCESS" in (frozen_outcome, recomputed_outcome):
            combined = frozen_reason + " " + recomputed_reason
            if "FAILED_EXPANSION" in combined or "volume < signal-day" in combined:
                return "EXPANSION_CHANGED"
            return "ACCEPTANCE_CHANGED"
        return "OTHER"
    if frozen_reason != recomputed_reason:
        return "OTHER"
    return "OTHER"


def build_conflict_rows(
    cases: pd.DataFrame,
    episodes: pd.DataFrame,
    feature_bars: pd.DataFrame,
    rows: list[dict[str, Any]],
) -> pd.DataFrame:
    """Forensic rows for the 3D gate mismatches (Part B)."""
    gate = pd.DataFrame(
        [
            {
                "episode_id": row["episode_id"],
                "symbol": row["symbol"],
                "candidate_date": row["candidate_date"],
                "recomputed_outcome_3d": row["_gate_outcome_3d"],
            }
            for row in rows
        ]
    )
    conflicts = gate[gate["recomputed_outcome_3d"] != gate["episode_id"].map(
        cases.set_index("episode_id")["outcome"]
    )].copy()
    cases_keyed = cases.set_index("episode_id")
    episodes_keyed = episodes.set_index(["episode_id", "signal_date"])
    bars_keyed = feature_bars.set_index(["code", "trade_date"]).sort_index()
    out: list[dict[str, Any]] = []
    for _, c in conflicts.iterrows():
        case = cases_keyed.loc[c["episode_id"]]
        cand = c["candidate_date"]
        s1 = Decimal(str(case["s1_price"]))
        invalid = Decimal(str(case["invalid_price"]))
        code = case["symbol"]
        window = gen.future_window(
            feature_bars[feature_bars["code"] == code], cand, gen.HORIZON_3D
        )
        s1_touch = window[window["high"] >= s1]
        inv_touch = window[window["low"] <= invalid]
        s1_date = s1_touch.iloc[0]["trade_date"] if len(s1_touch) else None
        inv_date = inv_touch.iloc[0]["trade_date"] if len(inv_touch) else None

        # Recomputed pattern + reason (feature snapshot, same code path).
        pattern = gen.recompute_pattern(
            feature_bars[feature_bars["code"] == code], cand, gen.HORIZON_3D, s1, invalid
        )
        sig_vol = gen._signal_volume(
            feature_bars[feature_bars["code"] == code], cand
        )
        recomputed = gen.classify_outcome(
            pattern, window, s1, sig_vol, "3 sessions"
        )

        # Candidate row reconciliation status (feature snapshot).
        cand_row = bars_keyed.loc[(code, cand)] if (code, cand) in bars_keyed.index else None
        # Event row by REAL first-event order (recomputed), never by "S1 exists
        # anywhere": S1_FIRST / INVALID_FIRST / AMBIGUOUS / NONE.
        _, _, first_event_type, first_event_date = gen.first_event_times(
            window, s1, invalid
        )
        event_row = (
            bars_keyed.loc[(code, first_event_date)]
            if first_event_date is not None
            else None
        )

        frozen_pat = str(
            episodes_keyed.loc[(case.name, cand), "pattern_3d"]
            if (case.name, cand) in episodes_keyed.index
            else ""
        )
        episode_snap = str(
            episodes_keyed.loc[(case.name, cand), "snapshot_id"]
            if (case.name, cand) in episodes_keyed.index
            else ""
        )
        out.append(
            {
                "episode_id": case.name,
                "symbol": code,
                "anchor_date": case["anchor_date"],
                "candidate_date": cand,
                "frozen_pattern_3d": frozen_pat,
                "recomputed_pattern_3d": pattern.value,
                "frozen_outcome_3d": case["outcome"],
                "recomputed_outcome_3d": recomputed.outcome,
                "frozen_outcome_reason": case["outcome_reason"],
                "recomputed_outcome_reason": recomputed.reason,
                "s1_price": case["s1_price"],
                "invalid_price": case["invalid_price"],
                "first_s1_touch_date": s1_date,
                "first_invalid_touch_date": inv_date,
                "conflict_class": classify_conflict(
                    frozen_pat,
                    pattern.value,
                    case["outcome"],
                    recomputed.outcome,
                    case["outcome_reason"],
                    recomputed.reason,
                ),
                "candidate_row_reconciliation_status": (
                    cand_row["reconciliation_status"] if cand_row is not None else ""
                ),
                "event_row_reconciliation_status": (
                    event_row["reconciliation_status"] if event_row is not None else ""
                ),
                "feature_snapshot_id": gen.FEATURE_SNAPSHOT_ID,
                "feature_snapshot_hash": gen.EXPECTED_FEATURE_SNAPSHOT_SHA256,
                "episode_snapshot_id": episode_snap,
            }
        )
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Part C: provider cross-check on conflict-involved dates.
# ---------------------------------------------------------------------------

def provider_crosscheck(
    conflicts: pd.DataFrame,
    cases: pd.DataFrame,
    canonical: pd.DataFrame,
    tushare: pd.DataFrame,
    akshare: pd.DataFrame,
) -> pd.DataFrame:
    """Compare canonical vs raw providers on the conflict windows (Part C)."""
    cases_keyed = cases.set_index("episode_id")
    canon_keyed = canonical.set_index(["code", "trade_date"]).sort_index()
    tush_keyed = tushare.set_index(["code", "trade_date"]).sort_index()
    aksh_keyed = akshare.set_index(["code", "trade_date"]).sort_index()
    tush_conflicts = set(
        tushare[tushare["_raw_version_conflict"]][["code", "trade_date"]].itertuples(
            index=False, name=None
        )
    ) if "_raw_version_conflict" in tushare.columns else set()
    aksh_conflicts = set(
        akshare[akshare["_raw_version_conflict"]][["code", "trade_date"]].itertuples(
            index=False, name=None
        )
    ) if "_raw_version_conflict" in akshare.columns else set()
    rows: list[dict[str, Any]] = []
    for _, c in conflicts.iterrows():
        case = cases_keyed.loc[c["episode_id"]]
        code = case["symbol"]
        cand = c["candidate_date"]
        window = gen.future_window(
            canonical[canonical["code"] == code], cand, gen.HORIZON_3D
        )
        dates = [cand] + list(window["trade_date"])
        t_diffs: set[str] = set()
        a_diffs: set[str] = set()
        t_present = 0
        a_present = 0
        version_conflict = False
        for d in dates:
            c_row = canon_keyed.loc[(code, d)] if (code, d) in canon_keyed.index else None
            if c_row is None:
                continue
            if (code, d) in tush_conflicts or (code, d) in aksh_conflicts:
                # Raw provider versions conflict on this date: never a MATCH.
                version_conflict = True
                continue
            t_row = tush_keyed.loc[(code, d)] if (code, d) in tush_keyed.index else None
            a_row = aksh_keyed.loc[(code, d)] if (code, d) in aksh_keyed.index else None
            if t_row is not None:
                t_present += 1
                if not _same(c_row, t_row):
                    t_diffs.update(
                        f for f in PRICE_FIELDS
                        if round(float(c_row[f]), 2) != round(float(t_row[f]), 2)
                    )
            if a_row is not None:
                a_present += 1
                if not _same(c_row, a_row):
                    a_diffs.update(
                        f for f in PRICE_FIELDS
                        if round(float(c_row[f]), 2) != round(float(a_row[f]), 2)
                    )
        t_ok = t_present == len(dates) and not t_diffs
        a_ok = a_present == len(dates) and not a_diffs
        if version_conflict:
            cls = "RAW_PROVIDER_VERSION_CONFLICT"
        elif t_present == 0 and a_present == 0:
            cls = "RAW_DATA_MISSING"
        elif t_ok and a_ok:
            cls = "CURRENT_CANONICAL_MATCHES_BOTH"
        elif t_ok:
            cls = "CURRENT_CANONICAL_MATCHES_TUSHARE"
        elif a_ok:
            cls = "CURRENT_CANONICAL_MATCHES_AKSHARE"
        else:
            cls = "RAW_PROVIDERS_DISAGREE"
        rows.append(
            {
                "episode_id": c["episode_id"],
                "involved_dates_n": len(dates),
                "provider_agreement_class": cls,
                "canonical_vs_tushare_diff_fields": ",".join(sorted(t_diffs)),
                "canonical_vs_akshare_diff_fields": ",".join(sorted(a_diffs)),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Part D: canonical row policy (CONFIRMED vs PROVISIONAL).
# ---------------------------------------------------------------------------

def row_policy_audit(
    cases: pd.DataFrame,
    canonical_feature: pd.DataFrame,
    canonical_label: pd.DataFrame,
    conflict_ids: set[str],
) -> dict[str, Any]:
    """Row-policy metrics with two explicit semantics (Part D / A3).

    - ROW_ROLE_EXPOSURE: every (case, date, snapshot) role occurrence counts
      (a date present in both the feature 3D window and the label 5D window is
      exposed twice — once per snapshot role);
    - UNIQUE_CASE_DATE_SNAPSHOT: unique (case, date, snapshot) triples.
    """
    feat_keyed = canonical_feature.set_index(["code", "trade_date"]).sort_index()
    label_keyed = canonical_label.set_index(["code", "trade_date"]).sort_index()
    role_confirmed = 0
    role_provisional = 0
    unique_status: dict[tuple[str, date, str], str] = {}
    per_case_provisional: dict[str, bool] = {}
    for _, case in cases.iterrows():
        code = case["symbol"]
        cand = case["candidate_date"]
        roles: list[tuple[date, str, pd.Series | None]] = []
        roles.append(
            (cand, gen.FEATURE_SNAPSHOT_ID, feat_keyed.loc[(code, cand)] if (code, cand) in feat_keyed.index else None)
        )
        fwin = gen.future_window(canonical_feature[canonical_feature["code"] == code], cand, 3)
        lwin = gen.future_window(canonical_label[canonical_label["code"] == code], cand, 5)
        for d in list(fwin["trade_date"]):
            roles.append(
                (d, gen.FEATURE_SNAPSHOT_ID, feat_keyed.loc[(code, d)] if (code, d) in feat_keyed.index else None)
            )
        for d in list(lwin["trade_date"]):
            roles.append(
                (d, gen.LABEL_SNAPSHOT_ID, label_keyed.loc[(code, d)] if (code, d) in label_keyed.index else None)
            )
        has_provisional = False
        for d, snap, r in roles:
            if r is None:
                continue
            if r["reconciliation_status"] == "CONFIRMED":
                role_confirmed += 1
                unique_status[(case["episode_id"], d, snap)] = "CONFIRMED"
            elif r["reconciliation_status"] == "PROVISIONAL":
                role_provisional += 1
                unique_status[(case["episode_id"], d, snap)] = "PROVISIONAL"
                has_provisional = True
        per_case_provisional[case["episode_id"]] = has_provisional
    conflict_with_provisional = sum(
        1 for eid in conflict_ids if per_case_provisional.get(eid, False)
    )
    return {
        "row_role_exposure": {
            "confirmed_n": role_confirmed,
            "provisional_n": role_provisional,
            "provisional_share": round(
                role_provisional / max(1, role_confirmed + role_provisional), 4
            ),
        },
        "unique_case_date_snapshot": {
            "confirmed_n": sum(1 for v in unique_status.values() if v == "CONFIRMED"),
            "provisional_n": sum(1 for v in unique_status.values() if v == "PROVISIONAL"),
        },
        "conflict_with_provisional_n": conflict_with_provisional,
        "conflict_all_confirmed_n": len(conflict_ids) - conflict_with_provisional,
    }


def build_quarantine(conflicts_df: pd.DataFrame) -> pd.DataFrame:
    """Freeze the quarantine artifact from the current 3D mismatch set."""
    q = conflicts_df[
        ["episode_id", "symbol", "candidate_date", "conflict_class"]
    ].copy()
    q["quarantine_reason"] = "3D_PROVENANCE_CONFLICT:" + q["conflict_class"]
    q["source_forensic_artifact"] = (
        "research/second_launch/outcome_v01/case_provenance_conflicts_v01.csv"
    )
    return q


# ---------------------------------------------------------------------------
# Part E: cohort provenance risk (targeted; no replay).
# ---------------------------------------------------------------------------

def cohort_provenance(
    conflicts: pd.DataFrame,
    cases: pd.DataFrame,
    canonical: pd.DataFrame,
    tushare: pd.DataFrame,
    akshare: pd.DataFrame,
    episodes: pd.DataFrame,
) -> dict[str, Any]:
    """Targeted evidence on whether candidate semantics could be affected."""
    cases_keyed = cases.set_index("episode_id")
    canon_keyed = canonical.set_index(["code", "trade_date"]).sort_index()
    tush_keyed = tushare.set_index(["code", "trade_date"]).sort_index()
    aksh_keyed = akshare.set_index(["code", "trade_date"]).sort_index()
    episodes_keyed = episodes.set_index(["episode_id", "signal_date"])
    cand_both = 0
    anchor_both = 0
    anchor_missing = 0
    inferred_anchor = 0
    for _, c in conflicts.iterrows():
        case = cases_keyed.loc[c["episode_id"]]
        code = case["symbol"]
        cand = c["candidate_date"]
        anchor = pd.to_datetime(case["anchor_date"]).date()
        for d, counter_name in ((cand, "cand"), (anchor, "anchor")):
            c_row = canon_keyed.loc[(code, d)] if (code, d) in canon_keyed.index else None
            t_row = tush_keyed.loc[(code, d)] if (code, d) in tush_keyed.index else None
            a_row = aksh_keyed.loc[(code, d)] if (code, d) in aksh_keyed.index else None
            if counter_name == "anchor" and c_row is None:
                anchor_missing += 1
                continue
            if (
                c_row is not None
                and t_row is not None
                and a_row is not None
                and _same(c_row, t_row)
                and _same(c_row, a_row)
            ):
                if counter_name == "cand":
                    cand_both += 1
                else:
                    anchor_both += 1
        flags = str(
            episodes_keyed.loc[(case.name, cand), "quality_flags"]
            if (case.name, cand) in episodes_keyed.index
            else ""
        )
        if "INFERRED_LIMIT_ANCHOR" in flags:
            inferred_anchor += 1
    return {
        "conflict_n": len(conflicts),
        "candidate_day_matches_both_providers_n": cand_both,
        "anchor_day_matches_both_providers_n": anchor_both,
        "anchor_day_missing_in_canonical_n": anchor_missing,
        "conflict_with_inferred_anchor_n": inferred_anchor,
    }


# ---------------------------------------------------------------------------
# Part F: reproducible subset statistics.
# ---------------------------------------------------------------------------

def subset_stats(
    cases: pd.DataFrame,
    conflict_ids: set[str],
    canonical: pd.DataFrame,
) -> dict[str, Any]:
    cases = cases.copy()
    cases["in_conflict"] = cases["episode_id"].isin(conflict_ids)
    cases["year"] = pd.to_datetime(cases["candidate_date"]).dt.year
    cases["month"] = pd.to_datetime(cases["candidate_date"]).dt.strftime("%Y-%m")
    prov_map = (
        canonical.set_index(["code", "trade_date"])["selected_provider"]
        .to_dict()
    )
    cases["candidate_provider"] = cases.apply(
        lambda r: prov_map.get((r["symbol"], r["candidate_date"]), "MISSING"), axis=1
    )
    concentration: dict[str, dict[str, int]] = {}
    for dim in ["year", "month", "outcome", "data_quality", "candidate_provider"]:
        tab = cases.groupby([dim, "in_conflict"]).size().unstack(fill_value=0)
        concentration[dim] = tab.to_dict()
    full = cases
    rep = cases[~cases["in_conflict"]]
    quar = cases[cases["in_conflict"]]
    return {
        "reproducible_n": int((~cases["in_conflict"]).sum()),
        "quarantine_n": int(cases["in_conflict"].sum()),
        "full_outcome_counts": full["outcome"].value_counts().to_dict(),
        "reproducible_outcome_counts": rep["outcome"].value_counts().to_dict(),
        "quarantine_outcome_counts": quar["outcome"].value_counts().to_dict(),
        "concentration": concentration,
        "top_conflict_codes": (
            cases[cases["in_conflict"]]["symbol"].value_counts().head(10).to_dict()
        ),
    }


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------

def main() -> None:
    cases = gen.load_case_set(gen.CASE_SET_PATH)
    all_codes = set(cases["symbol"])
    conflicts = None
    canonical_feature = load_canonical_with_reconciliation(
        gen.FEATURE_SNAPSHOT_PATH, all_codes
    )
    canonical_label = load_canonical_with_reconciliation(
        gen.LABEL_SNAPSHOT_PATH, all_codes
    )
    feature_bars = gen.load_bars_by_code(gen.FEATURE_SNAPSHOT_PATH, all_codes)
    label_bars = gen.load_bars_by_code(gen.LABEL_SNAPSHOT_PATH, all_codes)
    episodes = gen.load_episodes_patterns(gen.EPISODES_PATH)
    episodes_full = pq.read_table(
        gen.EPISODES_PATH,
        columns=["setup_id", "signal_date", "pattern_3d", "snapshot_id", "quality_flags"],
    ).to_pandas()
    episodes_full["signal_date"] = pd.to_datetime(episodes_full["signal_date"]).dt.date
    episodes_full = episodes_full.rename(columns={"setup_id": "episode_id"})
    episodes_full = episodes_full.drop_duplicates(
        subset=["episode_id", "signal_date"]
    )
    rows, _ = gen._build_rows(cases, feature_bars, label_bars)

    # Part B: conflicts CSV.
    conflict_df = build_conflict_rows(cases, episodes_full, canonical_feature, rows)
    conflict_ids = set(conflict_df["episode_id"])
    print("CONFLICT_TOTAL:", len(conflict_df))
    print("CONFLICT_CLASS:", conflict_df["conflict_class"].value_counts().to_dict())
    gen.OUT_DIR.mkdir(parents=True, exist_ok=True)
    conflict_df.to_csv(gen.OUT_CONFLICTS_PATH, index=False)
    quarantine = build_quarantine(conflict_df)
    quarantine_path = gen.OUT_DIR / "quarantine_v01b.csv"
    quarantine.to_csv(quarantine_path, index=False)
    import hashlib

    print(
        "QUARANTINE_SHA256:",
        hashlib.sha256(quarantine_path.read_bytes()).hexdigest(),
    )

    # Part C: provider cross-check.
    tushare, tush_stats = load_raw_provider(RAW_TUSHARE_GLOB, set(conflict_df["symbol"]))
    akshare, aksh_stats = load_raw_provider(RAW_AKSHARE_GLOB, set(conflict_df["symbol"]))
    print("RAW_DUP_TUSHARE:", json.dumps(tush_stats, sort_keys=True))
    print("RAW_DUP_AKSHARE:", json.dumps(aksh_stats, sort_keys=True))
    cross = provider_crosscheck(
        conflict_df, cases, canonical_feature, tushare, akshare
    )
    print("PROVIDER_CLASS:", cross["provider_agreement_class"].value_counts().to_dict())
    diff_rows = cross[cross["provider_agreement_class"] != "CURRENT_CANONICAL_MATCHES_BOTH"]
    print(diff_rows.to_string(index=False))

    # Part D: row policy.
    policy = row_policy_audit(cases, canonical_feature, canonical_label, conflict_ids)
    print("ROW_POLICY:", json.dumps(policy, sort_keys=True))
    print(
        "ROW_ROLE_EXPOSURE:",
        json.dumps(policy["row_role_exposure"], sort_keys=True),
    )
    print(
        "UNIQUE_CASE_DATE_SNAPSHOT:",
        json.dumps(policy["unique_case_date_snapshot"], sort_keys=True),
    )

    # Part E: cohort provenance.
    cohort = cohort_provenance(
        conflict_df, cases, canonical_feature, tushare, akshare, episodes_full
    )
    print("COHORT:", json.dumps(cohort, sort_keys=True))

    # Part F: subset stats.
    subset = subset_stats(cases, conflict_ids, canonical_feature)
    print("SUBSET_REPRODUCIBLE_N:", subset["reproducible_n"])
    print("SUBSET_QUARANTINE_N:", subset["quarantine_n"])
    print("QUARANTINE_OUTCOME:", subset["quarantine_outcome_counts"])
    print("FULL_OUTCOME:", subset["full_outcome_counts"])
    for dim in ["year", "month", "data_quality", "candidate_provider"]:
        print(f"CONCENTRATION[{dim}]:", subset["concentration"][dim])
    print("TOP_CONFLICT_CODES:", subset["top_conflict_codes"])


if __name__ == "__main__":
    main()
