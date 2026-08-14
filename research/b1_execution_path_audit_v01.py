"""B1 ENTRY LIFECYCLE + EXECUTION PATH AUDIT v0.1 (research-only).

Extends the lifecycle audit with execution-event decomposition and a
day1-vs-day2 execution-path comparison, on all historical B1 (not current 5).

Inputs: corrected episodes 66d5943f..., snapshot b5f84004de8a.
Output: data/tmp/b1-execution-path-audit-v01/metrics.json
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
OUT_DIR = DATA_ROOT / "tmp" / "b1-execution-path-audit-v01"
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


def summarize(sub):
    vals = [r["canonical_R_10bp"] for r in sub if r["canonical_R_10bp"] is not None]
    out = stats(vals)
    if out:
        out["s1_first_rate"] = round(
            sum(1 for r in sub if r["label"] == "WINNER") / len(sub), 4
        ) if sub else None
        out["invalid_first_rate"] = round(
            sum(1 for r in sub if r["label"] == "LOSER") / len(sub), 4
        ) if sub else None
    return out


def rate(sub, pred):
    return round(sum(1 for r in sub if pred(r)) / len(sub), 4) if sub else None


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
            f["fill_type"] = str(row["fill_type"])
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

    for r in main:
        key = (r["code"], r.get("anchor_date"))
        sigs = sig_by_anchor.get(key, [])
        r["day_bucket"] = day_bucket(r.get("days_since_anchor"))
        r["is_first_actionable"] = any(
            s["signal_date"] == r["signal_date"]
            and s["is_entry_candidate"]
            and s["fill_status"] == "FILLED"
            for s in sigs
        )
        r["is_repeat_actionable"] = (
            not r["is_first_actionable"]
            and r["label"] in ("WINNER", "LOSER")
        )
        r["prior_day1_state"] = None
        if r.get("days_since_anchor") == 2:
            day1 = next((s for s in sigs if s["signal_date"] < r["signal_date"]), None)
            r["prior_day1_state"] = (
                "NO_B1_SIGNAL"
                if day1 is None
                else (
                    "NOT_CANDIDATE"
                    if not day1["is_entry_candidate"]
                    else day1["fill_status"]
                )
            )

    # 1. lifecycle
    anchors_all = len(sig_by_anchor)
    per_anchor = defaultdict(int)
    for key, sigs in sig_by_anchor.items():
        n = sum(1 for s in sigs if s["is_entry_candidate"] and s["fill_status"] == "FILLED")
        per_anchor[n] += 1
    first = [r for r in main if r["is_first_actionable"]]
    repeat = [r for r in main if r["is_repeat_actionable"]]
    lifecycle = {
        "unique_anchors_with_b1_signals": anchors_all,
        "unique_anchors_first_actionable": len({(r["code"], r.get("anchor_date")) for r in first}),
        "actionable_count_per_anchor": {str(k): v for k, v in sorted(per_anchor.items())},
        "first_actionable_n": len(first),
        "repeat_actionable_n": len(repeat),
    }

    # 2. first-actionable by day
    first_by_day = {}
    for b in ("day1", "day2", "day3+"):
        sub = [r for r in first if r["day_bucket"] == b]
        first_by_day[b] = summarize(sub)

    # 3. execution event grouping: fill_type x exit_type
    decomp = {}
    for ft in sorted({r["fill_type"] for r in main}):
        sub = [r for r in main if r["fill_type"] == ft]
        by_exit = {}
        for et in sorted({r["exit_type"] for r in sub}):
            e = [r for r in sub if r["exit_type"] == et]
            vals = [r["canonical_R_10bp"] for r in e if r["canonical_R_10bp"] is not None]
            by_exit[et] = {
                "n": len(e),
                "share_of_fill_type": round(len(e) / len(sub), 4) if sub else None,
                "mean_R": round(statistics.fmean(vals), 4) if vals else None,
            }
        decomp[ft] = {
            "n": len(sub),
            "mean_R": round(
                statistics.fmean(
                    [r["canonical_R_10bp"] for r in sub if r["canonical_R_10bp"] is not None]
                ),
                4,
            ),
            "exit_breakdown": by_exit,
        }

    # overall exit decomposition
    overall_exit = {}
    for et in sorted({r["exit_type"] for r in main}):
        e = [r for r in main if r["exit_type"] == et]
        vals = [r["canonical_R_10bp"] for r in e if r["canonical_R_10bp"] is not None]
        overall_exit[et] = {
            "n": len(e),
            "share": round(len(e) / len(main), 4),
            "mean_R": round(statistics.fmean(vals), 4) if vals else None,
            "sum_R": round(sum(vals), 4) if vals else None,
        }

    # 4. day1 vs day2 execution path (first-actionable)
    d1 = [r for r in first if r["day_bucket"] == "day1"]
    d2 = [r for r in first if r["day_bucket"] == "day2"]
    d1d2 = {
        "FIRST_DAY1": {
            **summarize(d1),
            "t1_blocked_stop_rate": rate(d1, lambda r: r["exit_type"] == "STOP_TRIGGERED_T1_BLOCKED"),
            "same_day_invalid_rate": rate(
                d1, lambda r: r["exit_type"] in ("STOP_TRIGGERED_T1_BLOCKED",)
            ),
            "gap_stop_rate": rate(d1, lambda r: r["exit_type"] == "GAP_STOP"),
            "intraday_touch_share": rate(d1, lambda r: r["fill_type"] == "INTRADAY_TOUCH_FILL"),
            "open_fill_share": rate(d1, lambda r: r["fill_type"] == "OPEN_FILL"),
        },
        "FIRST_DAY2": {
            **summarize(d2),
            "t1_blocked_stop_rate": rate(d2, lambda r: r["exit_type"] == "STOP_TRIGGERED_T1_BLOCKED"),
            "same_day_invalid_rate": rate(
                d2, lambda r: r["exit_type"] in ("STOP_TRIGGERED_T1_BLOCKED",)
            ),
            "gap_stop_rate": rate(d2, lambda r: r["exit_type"] == "GAP_STOP"),
            "intraday_touch_share": rate(d2, lambda r: r["fill_type"] == "INTRADAY_TOUCH_FILL"),
            "open_fill_share": rate(d2, lambda r: r["fill_type"] == "OPEN_FILL"),
        },
    }

    # 5. survivorship split
    day2_after_day1 = [r for r in first if r["day_bucket"] == "day2" and r["prior_day1_state"] == "FILLED"]
    day2_first = [r for r in first if r["day_bucket"] == "day2" and r["prior_day1_state"] != "FILLED"]
    survivorship = {
        "day2_anchors_with_day1_fill": len(day2_after_day1),
        "day2_anchors_first_signal": len(day2_first),
        "day2_prior_state_counts": defaultdict(int, {
            str(r["prior_day1_state"]): 0
            for r in first
            if r["day_bucket"] == "day2"
        }),
    }
    for r in first:
        if r["day_bucket"] == "day2":
            survivorship["day2_prior_state_counts"][str(r["prior_day1_state"])] += 1
    survivorship["day2_prior_state_counts"] = dict(survivorship["day2_prior_state_counts"])

    # 6. reclaim_ma5 + ARCH3 on first-actionable
    cells = {}
    for day in ("day1", "day2"):
        for rm in (0, 1):
            sub = [
                r
                for r in first
                if r["day_bucket"] == day and r.get("reclaim_ma5") == bool(rm)
            ]
            cells[f"{day}_rm{rm}"] = summarize(sub)
    arch3_first = [r for r in first if r["is_arch3"]]
    arch3 = {
        "summary": summarize(arch3_first),
        "DISCOVERY": summarize([r for r in arch3_first if r["period"] == "DISCOVERY"]),
        "VALIDATION": summarize([r for r in arch3_first if r["period"] == "VALIDATION"]),
    }

    metrics = {
        "title": "B1 ENTRY LIFECYCLE + EXECUTION PATH AUDIT v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "DESCRIPTIVE_OBSERVE_ONLY",
        "LIFECYCLE": lifecycle,
        "FIRST_ACTIONABLE_BY_DAY": first_by_day,
        "EXECUTION_DECOMPOSITION": {
            "by_fill_type": decomp,
            "overall_exit": overall_exit,
        },
        "DAY1_VS_DAY2": d1d2,
        "SURVIVORSHIP": survivorship,
        "FIRST_ACTIONABLE_CELLS": cells,
        "ARCH3_FIRST_ACTIONABLE": arch3,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
