"""B1 SIGNAL -> EXECUTION FUNNEL AUDIT v0.1 (research-only).

Deduplicates all historical B1 signals by (code, anchor_date), builds the
execution funnel, and compares future structure paths (PIT invalid/S1, no
trade simulation) across FILLED / candidate-no-fill / non-candidate.

Inputs: corrected episodes 66d5943f..., snapshot b5f84004de8a.
Output: data/tmp/b1-execution-funnel-audit-v01/metrics.json
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import pandas as pd

from limit_pullback.screen.canonical import (
    iter_canonical_code_bars,
    load_canonical_metadata,
)
from limit_pullback.warehouse.layout import WarehouseLayout


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
EPISODES_DIR = (
    DATA_ROOT
    / "outcome-study"
    / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome"
)
OUT_DIR = DATA_ROOT / "tmp" / "b1-execution-funnel-audit-v01"
SPLIT_DATE = __import__("datetime").date(2025, 7, 1)


def _pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    idx = (len(s) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    f = idx - lo
    return s[lo] * (1 - f) + s[hi] * f


def stats(vals):
    vals = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not vals:
        return None
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 4),
        "median": round(statistics.median(vals), 4),
        "p10": round(_pct(vals, 0.10), 4),
        "p90": round(_pct(vals, 0.90), 4),
    }


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ep = pd.read_parquet(EPISODES_DIR / "episodes.parquet")
    b1 = ep[ep["execution_label"] == "B1_READY"].copy()
    for col in ("signal_date", "anchor_date"):
        b1[col] = pd.to_datetime(b1[col]).dt.date
    for col in ("invalid_price", "s1_price", "buy_zone_high", "buy_zone_low"):
        b1[col] = pd.to_numeric(b1[col].astype(str), errors="coerce")
    b1["fill_status"] = b1["fill_status"].astype(str)
    b1["is_entry_candidate"] = b1["is_entry_candidate"].astype(bool)

    # dedup per (code, anchor_date): keep the FIRST B1 signal
    b1 = b1.sort_values(["code", "anchor_date", "signal_date"])
    first = b1.groupby(["code", "anchor_date"], as_index=False).first()
    print("first B1 signal anchors:", len(first), "of", b1.shape[0], "signals")

    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, r in first.iterrows():
        by_code[str(r["code"])].append(r)

    rows = []
    for code, bars in iter_canonical_code_bars(
        layout, snapshot, codes=sorted(by_code.keys())
    ):
        if not bars or code not in by_code:
            continue
        idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
        bar_list = list(bars)
        for row in by_code[code]:
            sig_idx = idx_by_date.get(row["signal_date"])
            if sig_idx is None:
                continue
            invalid = float(row["invalid_price"]) if pd.notna(row["invalid_price"]) else None
            s1 = float(row["s1_price"]) if pd.notna(row["s1_price"]) else None
            sig_close = float(bar_list[sig_idx].close)
            rec = {
                "code": code,
                "signal_date": row["signal_date"].isoformat(),
                "anchor_date": row["anchor_date"].isoformat(),
                "is_entry_candidate": bool(row["is_entry_candidate"]),
                "fill_status": str(row["fill_status"]),
                "period": "DISCOVERY" if row["signal_date"] < SPLIT_DATE else "VALIDATION",
                "year": row["signal_date"].year,
                "invalid": invalid,
                "s1": s1,
            }
            sig_high = float(bar_list[sig_idx].high)
            sig_low = float(bar_list[sig_idx].low)
            sig_open = float(bar_list[sig_idx].open)
            sig_range = sig_high - sig_low
            rec["c1_eligible"] = bool(sig_low > invalid) if invalid is not None else None
            rec["close_loc"] = (sig_close - sig_low) / sig_range if sig_range else None
            rec["range_pct"] = sig_range / float(bar_list[sig_idx].preclose) * 100
            rec["body_pct"] = abs(sig_close - sig_open) / float(bar_list[sig_idx].preclose) * 100
            high20 = max(
                float(bar_list[i].high)
                for i in range(max(0, sig_idx - 19), sig_idx + 1)
            )
            rec["dist_20d_high_pct"] = (sig_close / high20 - 1) * 100
            if invalid is None or s1 is None:
                rec["path"] = "NO_LEVELS"
            else:
                t_s1 = t_inv = None
                for idx in range(sig_idx + 1, min(len(bar_list), sig_idx + 11)):
                    b = bar_list[idx]
                    if t_s1 is None and float(b.high) >= s1:
                        t_s1 = idx - sig_idx
                    if t_inv is None and float(b.low) <= invalid:
                        t_inv = idx - sig_idx
                    if t_s1 is not None and t_inv is not None:
                        break
                if t_s1 is not None and t_inv is not None:
                    rec["path"] = (
                        "S1_FIRST"
                        if t_s1 < t_inv
                        else ("INVALID_FIRST" if t_inv < t_s1 else "SAME_DAY")
                    )
                elif t_s1 is not None:
                    rec["path"] = "S1_FIRST"
                elif t_inv is not None:
                    rec["path"] = "INVALID_FIRST"
                else:
                    rec["path"] = "NONE"
                for k in (3, 5, 10):
                    if sig_idx + k < len(bar_list):
                        seg = bar_list[sig_idx + 1 : sig_idx + k + 1]
                        rec[f"mfe_{k}d"] = max(float(b.high) for b in seg) / sig_close - 1
                        rec[f"mae_{k}d"] = min(float(b.low) for b in seg) / sig_close - 1
            # next-day open vs zone for NO_FILL / CANCEL reason split (PIT)
            bz_high = float(row["buy_zone_high"]) if pd.notna(row["buy_zone_high"]) else None
            if sig_idx + 1 < len(bar_list):
                nxt = bar_list[sig_idx + 1]
                rec["next_open"] = float(nxt.open)
                rec["next_low"] = float(nxt.low)
            rec["bz_high"] = bz_high
            rows.append(rec)

    # cohort reconciliation: 276 (720-main, signal-session C1) vs 284 (all 747)
    ex_status = {
        (str(r["code"]), str(r["signal_date"])[:10]): str(r["conservative_execution_status"])
        for _, r in pd.read_parquet(
            EPISODES_DIR / "execution-reality" / "execution_episodes.parquet"
        ).iterrows()
    }
    action = [r for r in rows if r["is_entry_candidate"] and r["fill_status"] == "FILLED"]
    resolved_action = [
        r for r in action if ex_status.get((r["code"], r["signal_date"])) == "RESOLVED"
    ]
    main_720 = [
        r
        for r in resolved_action
        if r.get("path") in ("S1_FIRST", "INVALID_FIRST")
    ]
    c1_all = [r for r in action if r["c1_eligible"]]
    c1_main = [r for r in main_720 if r["c1_eligible"]]
    cohort_reconciliation = {
        "actionable_filled_all": len(action),
        "resolved_actionable": len(resolved_action),
        "main_720_resolved_with_path": len(main_720),
        "c1_eligible_all_747": len(c1_all),
        "c1_eligible_main_720": len(c1_main),
        "note": (
            "previous signal-session C1 audit summarized on the 720-episode main sample "
            "(resolved + S1/INVALID path) -> confirmed 276 / filled(R) 276; "
            "confirmed-selection attribution summarized all 747 actionable fills "
            "-> fill-status FILLED 284 (the +8 are non-resolved/censored episodes with "
            "R=None; among them 4 get path labels, 4 are OTHER)."
        ),
    }

    n_signal = len(rows)
    n_candidate = sum(1 for r in rows if r["is_entry_candidate"])
    funnel = {
        "B1_SIGNAL_anchors": n_signal,
        "ENTRY_CANDIDATE": n_candidate,
        "NON_ENTRY_CANDIDATE": n_signal - n_candidate,
        "candidate_share": round(n_candidate / n_signal, 4) if n_signal else None,
    }
    cand = [r for r in rows if r["is_entry_candidate"]]
    for status in ("FILLED", "NO_FILL", "CANCEL_GAP_INVALID", "CENSORED"):
        sub = [r for r in cand if r["fill_status"] == status]
        funnel[status] = {
            "n": len(sub),
            "share_of_candidates": round(len(sub) / n_candidate, 4) if n_candidate else None,
        }

    def summarize(sub, label):
        out = {"n": len(sub), "label": label}
        paths = [r["path"] for r in sub if r.get("path") and r["path"] != "NO_LEVELS"]
        if paths:
            out["path_counts"] = {p: paths.count(p) for p in ("S1_FIRST", "INVALID_FIRST", "SAME_DAY", "NONE")}
            out["s1_first_rate"] = round(paths.count("S1_FIRST") / len(paths), 4)
            out["invalid_first_rate"] = round(paths.count("INVALID_FIRST") / len(paths), 4)
        for k in (3, 5, 10):
            out[f"mfe_{k}d"] = stats([r.get(f"mfe_{k}d") for r in sub])
            out[f"mae_{k}d"] = stats([r.get(f"mae_{k}d") for r in sub])
        return out

    def group_stats(sub):
        """Structural outcome summary for one funnel group."""

        paths = [r["path"] for r in sub if r.get("path") and r["path"] != "NO_LEVELS"]
        return {
            "n": len(sub),
            "n_path_valid": len(paths),
            "path_counts": {p: paths.count(p) for p in ("S1_FIRST", "INVALID_FIRST", "SAME_DAY", "NONE")},
            "s1_first_rate": round(paths.count("S1_FIRST") / len(paths), 4) if paths else None,
            "invalid_first_rate": round(paths.count("INVALID_FIRST") / len(paths), 4) if paths else None,
            "mfe_3d": stats([r.get("mfe_3d") for r in sub]),
            "mfe_5d": stats([r.get("mfe_5d") for r in sub]),
            "mfe_10d": stats([r.get("mfe_10d") for r in sub]),
            "mae_3d": stats([r.get("mae_3d") for r in sub]),
            "mae_5d": stats([r.get("mae_5d") for r in sub]),
            "mae_10d": stats([r.get("mae_10d") for r in sub]),
        }

    filled = [r for r in cand if r["fill_status"] == "FILLED"]
    cand_no_fill = [r for r in cand if r["fill_status"] != "FILLED"]
    non_cand = [r for r in rows if not r["is_entry_candidate"]]
    groups = {
        "FILLED": group_stats(filled),
        "ENTRY_CANDIDATE_BUT_NO_FILL": group_stats(cand_no_fill),
        "NON_ENTRY_CANDIDATE": group_stats(non_cand),
        "CANCEL_GAP_INVALID": group_stats(
            [r for r in cand if r["fill_status"] == "CANCEL_GAP_INVALID"]
        ),
    }

    # confirmed-features mapping (signal-close features) per funnel group
    feature_groups = {}
    for gname, sub in (
        ("FILLED", filled),
        ("NO_FILL", [r for r in cand if r["fill_status"] == "NO_FILL"]),
        ("CANCEL_GAP_INVALID", [r for r in cand if r["fill_status"] == "CANCEL_GAP_INVALID"]),
        ("NON_ENTRY_CANDIDATE", non_cand),
    ):
        feature_groups[gname] = {
            fname: stats([r.get(fname) for r in sub])
            for fname in ("dist_20d_high_pct", "range_pct", "body_pct", "close_loc")
        }

    # NO_FILL / CANCEL reason split (existing statuses + PIT bar conditions)
    reason_split = {}
    for status in ("NO_FILL", "CANCEL_GAP_INVALID", "CENSORED"):
        sub = [r for r in cand if r["fill_status"] == status]
        if status == "NO_FILL":
            above = [r for r in sub if r["bz_high"] is not None and r.get("next_open", 0) > r["bz_high"] and r.get("next_low", 0) > r["bz_high"]]
            reason_split[status] = {
                "n": len(sub),
                "GAP_ABOVE_ZONE_NO_TOUCH": len(above),
                "other": len(sub) - len(above),
            }
        else:
            reason_split[status] = {"n": len(sub)}
    reason_split["note"] = "reasons reused from existing fill_status; NO_FILL split by PIT next-day open/low vs buy_zone_high"

    # strong-run-away (gap above zone, no fill) vs fell-back-and-filled
    gap_away = [r for r in cand if r["fill_status"] == "NO_FILL" and r["bz_high"] is not None and r.get("next_open", 0) > r["bz_high"] and r.get("next_low", 0) > r["bz_high"]]
    strength = {
        "GAP_AWAY_NO_FILL": summarize(gap_away, "GAP_AWAY"),
        "FELL_TO_ZONE_FILLED": summarize(filled, "FELL_FILLED"),
    }

    # direction stability D/V/years for key rates
    stability = {}
    for gname, sub in (("FILLED", filled), ("CAND_NO_FILL", cand_no_fill), ("NON_CAND", non_cand)):
        stability[gname] = {}
        for period in ("DISCOVERY", "VALIDATION"):
            sp = [r for r in sub if r["period"] == period]
            paths = [r["path"] for r in sp if r.get("path") and r["path"] != "NO_LEVELS"]
            stability[gname][period] = {
                "n": len(sp),
                "s1_first_rate": round(paths.count("S1_FIRST") / len(paths), 4) if paths else None,
            }
        for year in (2024, 2025, 2026):
            sp = [r for r in sub if r["year"] == year]
            paths = [r["path"] for r in sp if r.get("path") and r["path"] != "NO_LEVELS"]
            stability[gname][str(year)] = {
                "n": len(sp),
                "s1_first_rate": round(paths.count("S1_FIRST") / len(paths), 4) if paths else None,
            }

    metrics = {
        "title": "B1 SIGNAL -> EXECUTION FUNNEL AUDIT v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "DESCRIPTIVE_OBSERVE_ONLY",
        "FUNNEL": funnel,
        "COHORT_RECONCILIATION": cohort_reconciliation,
        "GROUPS": groups,
        "CONFIRMED_FEATURES": feature_groups,
        "NO_FILL_CANCEL_REASONS": reason_split,
        "STRONG_RUN_AWAY": strength,
        "STABILITY": stability,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
