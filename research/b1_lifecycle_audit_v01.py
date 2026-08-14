"""B1 LIFECYCLE + SURVIVORSHIP AUDIT v0.1 (research-only).

Checks whether the day2 B1 +0.13R is a real independent effect or an artifact
of repeated episodes / survivorship filtering.

Inputs: corrected episodes 66d5943f..., snapshot b5f84004de8a.
Output: data/tmp/b1-lifecycle-audit-v01/metrics.json
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

import pandas as pd

from limit_pullback.screen.canonical import (
    iter_canonical_code_bars,
    load_canonical_metadata,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from research.entry_attribution_v01 import compute_episode_features, load_episodes


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
EPISODES_DIR = (
    DATA_ROOT
    / "outcome-study"
    / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome"
)
OUT_DIR = DATA_ROOT / "tmp" / "b1-lifecycle-audit-v01"
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
    vals = [v for v in vals if v is not None]
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
    ep_all = pd.read_parquet(EPISODES_DIR / "episodes.parquet")
    df = load_episodes()
    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, row in df.iterrows():
        by_code[row["code"]].append(row)

    rows = []
    for code, bars in iter_canonical_code_bars(
        layout, snapshot, codes=sorted(by_code.keys())
    ):
        if not bars or code not in by_code:
            continue
        idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
        for row in by_code[code]:
            f = compute_episode_features(row, bars, idx_by_date)
            if f is None:
                continue
            f["canonical_R_10bp"] = (
                float(row["conservative_net_execution_R_10bp"])
                if pd.notna(row["conservative_net_execution_R_10bp"])
                else None
            )
            f["exec_status"] = row["conservative_execution_status"]
            f["exit_type"] = row["conservative_execution_exit_type"]
            f["deep_washout"] = bool(
                f.get("attack_high_dd_pct") is not None
                and f["attack_high_dd_pct"] <= -8.0
            )
            f["is_arch3"] = bool(f["deep_washout"] and f.get("reclaim_ma5"))
            if f["first_hit"] in ("S1_FIRST", "INVALID_FIRST") and f["exec_status"] == "RESOLVED":
                f["label"] = "WINNER" if f["first_hit"] == "S1_FIRST" else "LOSER"
            else:
                f["label"] = f["first_hit"]
            rows.append(f)

    # per (code, anchor) B1 signal registry from full episodes
    sig_by_anchor = defaultdict(list)
    b1_all = ep_all[ep_all["execution_label"] == "B1_READY"]
    for _, r in b1_all.iterrows():
        key = (str(r["code"]), str(r["anchor_date"])[:10])
        sig_by_anchor[key].append(
            {
                "signal_date": str(r["signal_date"])[:10],
                "fill_status": str(r["fill_status"]),
                "is_entry_candidate": bool(r["is_entry_candidate"]),
            }
        )
    for key in sig_by_anchor:
        sig_by_anchor[key].sort(key=lambda x: x["signal_date"])

    main = [r for r in rows if r["label"] in ("WINNER", "LOSER")]

    def day_bucket(days):
        if days is None:
            return None
        if days <= 2:
            return f"day{days}"
        return "day3+"

    # 1. anchor lifecycle stats
    anchors_all = len(sig_by_anchor)
    anchors_actionable = len({(r["code"], r.get("anchor_date")) for r in main})
    per_anchor = defaultdict(int)
    for key, sigs in sig_by_anchor.items():
        actionable = [s for s in sigs if s["is_entry_candidate"] and s["fill_status"] == "FILLED"]
        per_anchor[len(actionable)] += 1
    total_episodes = len(sig_by_anchor)
    total_actionable = len(main)
    repeat_share = round(
        (total_actionable - anchors_actionable) / total_actionable, 4
    ) if total_actionable else None

    # per-episode: day bucket + first-actionable flag + repeat flag + prior-day state
    first_map = {}
    for key, sigs in sig_by_anchor.items():
        first = next(
            (s for s in sigs if s["is_entry_candidate"] and s["fill_status"] == "FILLED"),
            None,
        )
        if first:
            first_map[(key[0], key[1], first["signal_date"])] = True
    for r in main:
        key = (r["code"], r.get("anchor_date"))
        sigs = sig_by_anchor.get(key, [])
        r["day_bucket"] = day_bucket(r.get("days_since_anchor"))
        r["is_first_actionable"] = (r["code"], r.get("anchor_date"), r["signal_date"]) in first_map
        # prior-day B1 state for day2 episodes
        r["prior_day1_state"] = None
        if r.get("days_since_anchor") == 2:
            day1 = next((s for s in sigs if s["signal_date"] < r["signal_date"]), None)
            if day1:
                if not day1["is_entry_candidate"]:
                    r["prior_day1_state"] = "NOT_CANDIDATE"
                else:
                    r["prior_day1_state"] = day1["fill_status"]
            else:
                r["prior_day1_state"] = "NO_B1_SIGNAL"
        r["is_repeat_day2_after_day1"] = bool(
            r.get("days_since_anchor") == 2
            and r["prior_day1_state"] == "FILLED"
        )
        # survivor flag: anchor had actionable day1 fill and a day2 B1 signal
        r["anchor_survived_day1"] = False
        if r.get("days_since_anchor") == 2:
            day1 = next((s for s in sigs if s["signal_date"] < r["signal_date"]), None)
            if day1 and day1["is_entry_candidate"] and day1["fill_status"] == "FILLED":
                r["anchor_survived_day1"] = True

    RKEY = "canonical_R_10bp"

    def summarize(sub, label=None):
        vals = [r[RKEY] for r in sub if r[RKEY] is not None]
        out = stats(vals)
        if out:
            out["s1_first_rate"] = round(
                sum(1 for r in sub if r["label"] == "WINNER") / len(sub), 4
            ) if sub else None
            out["invalid_first_rate"] = round(
                sum(1 for r in sub if r["label"] == "LOSER") / len(sub), 4
            ) if sub else None
            out["gap_stop_rate"] = round(
                sum(1 for r in sub if str(r.get("exit_type")) == "GAP_STOP") / len(sub), 4
            ) if sub else None
        return out

    # 2-3. first-actionable-only stats by day bucket
    first_only = [r for r in main if r["is_first_actionable"]]
    first_by_day = {}
    for b in ("day1", "day2", "day3+"):
        sub = [r for r in first_only if r["day_bucket"] == b]
        row = summarize(sub)
        if row:
            for period in ("DISCOVERY", "VALIDATION"):
                row[period] = summarize([r for r in sub if r["period"] == period])
            for year in (2024, 2025, 2026):
                row[str(year)] = summarize([r for r in sub if r.get("fill_year") == year])
        first_by_day[b] = row

    # all-episodes day buckets (for comparison)
    all_by_day = {}
    for b in ("day1", "day2", "day3+"):
        sub = [r for r in main if r["day_bucket"] == b]
        all_by_day[b] = summarize(sub)

    # 4. repeat day2 after day1
    repeat_day2 = [r for r in main if r["is_repeat_day2_after_day1"]]
    first_day2 = [r for r in main if r["day_bucket"] == "day2" and r["is_first_actionable"]]
    day2_survivor = [r for r in main if r["day_bucket"] == "day2" and r["anchor_survived_day1"]]
    prior_state_counts = defaultdict(int)
    for r in main:
        if r["day_bucket"] == "day2":
            prior_state_counts[r["prior_day1_state"]] += 1

    # 5. survivorship: day1-filled anchors' day2 vs first-actionable day2
    surv = {
        "REPEAT_DAY2_AFTER_DAY1": summarize(repeat_day2),
        "FIRST_ACTIONABLE_DAY2": summarize(first_day2),
        "DAY2_AFTER_DAY1_SURVIVOR_ALL": summarize(day2_survivor),
        "DAY1_ALL": summarize([r for r in main if r["day_bucket"] == "day1"]),
        "prior_day1_state_counts": dict(prior_state_counts),
    }

    # 6. minimal four-cell on first-actionable: day1/day2 x reclaim_ma5
    cells = {}
    for day in ("day1", "day2"):
        for rm in (0, 1):
            sub = [
                r
                for r in first_only
                if r["day_bucket"] == day and r.get("reclaim_ma5") == bool(rm)
            ]
            cells[f"{day}_rm{rm}"] = summarize(sub)
            for period in ("DISCOVERY", "VALIDATION"):
                sp = [r for r in sub if r["period"] == period]
                cells[f"{day}_rm{rm}"][period] = summarize(sp)
            for year in (2024, 2025, 2026):
                sy = [r for r in sub if r.get("fill_year") == year]
                cells[f"{day}_rm{rm}"][str(year)] = summarize(sy)

    # 7. ARCH3 on first-actionable sample
    arch3_first = [r for r in first_only if r.get("deep_washout") is not None and r["is_arch3"]]
    arch3_summary = summarize(arch3_first)
    arch3_periods = {
        p: summarize([r for r in arch3_first if r["period"] == p])
        for p in ("DISCOVERY", "VALIDATION")
    }

    metrics = {
        "title": "B1 LIFECYCLE + SURVIVORSHIP AUDIT v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "DESCRIPTIVE_OBSERVE_ONLY",
        "ANCHOR_LIFECYCLE": {
            "anchors_with_b1_signals": anchors_all,
            "anchors_with_actionable_b1": anchors_actionable,
            "total_b1_signals": total_episodes,
            "total_actionable_episodes": total_actionable,
            "unique_anchors_resolved_720": anchors_actionable,
            "repeat_episode_share": repeat_share,
            "actionable_count_per_anchor": {str(k): v for k, v in sorted(per_anchor.items())},
        },
        "ALL_EPISODES_BY_DAY": all_by_day,
        "FIRST_ACTIONABLE_BY_DAY": first_by_day,
        "SURVIVORSHIP": surv,
        "FIRST_ACTIONABLE_FOUR_CELL": cells,
        "ARCH3_FIRST_ACTIONABLE": {
            "summary": arch3_summary,
            "periods": arch3_periods,
        },
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
