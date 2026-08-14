"""B1 POST-SIGNAL CONFIRMATION ATTRIBUTION v0.1 (research-only).

Uses the first executable B1 session (fill day) as OBSERVATION_SESSION and
classifies it by same-session invalid touch and MA5 reclaim, then measures
future path quality. No new thresholds; no look-ahead.

Inputs: corrected episodes 66d5943f..., snapshot b5f84004de8a.
Output: data/tmp/b1-confirmation-attribution-v01/metrics.json
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
OUT_DIR = DATA_ROOT / "tmp" / "b1-confirmation-attribution-v01"
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


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ep_all = pd.read_parquet(EPISODES_DIR / "episodes.parquet")
    df = load_episodes()
    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, row in df.iterrows():
        by_code[row["code"]].append(row)

    # next-session stage registry per (code, anchor): signal_date -> label
    stage_by_anchor = defaultdict(dict)
    for _, r in ep_all.iterrows():
        key = (str(r["code"]), str(r["anchor_date"])[:10])
        stage_by_anchor[key][str(r["signal_date"])[:10]] = str(r["execution_label"])

    rows = []
    for code, bars in iter_canonical_code_bars(
        layout, snapshot, codes=sorted(by_code.keys())
    ):
        if not bars or code not in by_code:
            continue
        idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
        bar_list = list(bars)
        for row in by_code[code]:
            f = compute_episode_features(row, bars, idx_by_date)
            if f is None:
                continue
            fill_idx = idx_by_date.get(row["fill_date"])
            if fill_idx is None:
                continue
            fill_bar = bar_list[fill_idx]
            fill_price = float(row["fill_price"])
            invalid = float(row["invalid_price"])
            s1 = float(row["s1_price"])
            f["canonical_R_10bp"] = (
                float(row["conservative_net_execution_R_10bp"])
                if pd.notna(row["conservative_net_execution_R_10bp"])
                else None
            )
            f["exec_status"] = row["conservative_execution_status"]
            f["exit_type"] = row["conservative_execution_exit_type"]
            if f["first_hit"] in ("S1_FIRST", "INVALID_FIRST") and f["exec_status"] == "RESOLVED":
                f["label"] = "WINNER" if f["first_hit"] == "S1_FIRST" else "LOSER"
            else:
                f["label"] = f["first_hit"]

            # observation-session classification (fill day, close-known info only)
            same_session_invalid = float(fill_bar.low) <= invalid
            close = float(fill_bar.close)
            ma5 = statistics.fmean(
                float(bar_list[i].close)
                for i in range(max(0, fill_idx - 4), fill_idx + 1)
            )
            f["obs_group"] = (
                "INVALIDATED_SAME_SESSION"
                if same_session_invalid
                else ("SURVIVED_RECLAIM_MA5" if close >= ma5 else "SURVIVED_BELOW_MA5")
            )
            f["ma5_fill_day"] = ma5

            # future path metrics: sessions fill+1 .. fill+k, reference = fill price
            for k in (1, 3, 5):
                if fill_idx + k < len(bar_list):
                    seg = bar_list[fill_idx + 1 : fill_idx + k + 1]
                    f[f"future_mfe_{k}d"] = max(float(b.high) for b in seg) / fill_price - 1
                    f[f"future_mae_{k}d"] = min(float(b.low) for b in seg) / fill_price - 1
            t_s1 = t_inv = None
            for idx in range(fill_idx + 1, min(len(bar_list), fill_idx + 11)):
                b = bar_list[idx]
                if t_s1 is None and float(b.high) >= s1:
                    t_s1 = idx - fill_idx
                if t_inv is None and float(b.low) <= invalid:
                    t_inv = idx - fill_idx
                if t_s1 is not None and t_inv is not None:
                    break
            f["future_time_to_s1"] = t_s1
            f["future_time_to_invalid"] = t_inv
            # next-session production stage
            nxt = bar_list[fill_idx + 1].trade_date if fill_idx + 1 < len(bar_list) else None
            f["next_session_stage"] = (
                stage_by_anchor.get((code, str(row["anchor_date"])), {}).get(
                    nxt.isoformat() if nxt else "", "OTHER"
                )
                if nxt
                else "OTHER"
            )
            f["day_bucket"] = (
                f"day{f['days_since_anchor']}"
                if f.get("days_since_anchor") in (1, 2)
                else "day3+"
            )
            rows.append(f)

    main = [r for r in rows if r["label"] in ("WINNER", "LOSER")]
    groups = {}
    for g in ("INVALIDATED_SAME_SESSION", "SURVIVED_SESSION", "SURVIVED_RECLAIM_MA5", "SURVIVED_BELOW_MA5"):
        sub = (
            [r for r in main if r["obs_group"] == g]
            if g != "SURVIVED_SESSION"
            else [r for r in main if r["obs_group"] in ("SURVIVED_RECLAIM_MA5", "SURVIVED_BELOW_MA5")]
        )
        row = {
            "n": len(sub),
            "share": round(len(sub) / len(main), 4),
            **summarize(sub),
        }
        for k in (1, 3, 5):
            row[f"future_mfe_{k}d"] = stats(
                [r.get(f"future_mfe_{k}d") for r in sub]
            )
            row[f"future_mae_{k}d"] = stats(
                [r.get(f"future_mae_{k}d") for r in sub]
            )
        row["future_time_to_s1"] = stats(
            [r.get("future_time_to_s1") for r in sub if r.get("future_time_to_s1") is not None]
        )
        row["future_time_to_invalid"] = stats(
            [r.get("future_time_to_invalid") for r in sub if r.get("future_time_to_invalid") is not None]
        )
        hazard = defaultdict(int)
        for r in sub:
            hazard[str(r["exit_type"])] += 1
        row["hazard"] = dict(hazard)
        groups[g] = row

    # by day bucket: group share + summary
    by_day = {}
    for b in ("day1", "day2", "day3+"):
        sub = [r for r in main if r["day_bucket"] == b]
        share = defaultdict(int)
        for r in sub:
            share[r["obs_group"]] += 1
        by_day[b] = {
            "n": len(sub),
            **summarize(sub),
            "group_shares": {
                k: round(v / len(sub), 4) for k, v in sorted(share.items())
            },
        }

    # stability for SURVIVED_RECLAIM_MA5
    rec = [r for r in main if r["obs_group"] == "SURVIVED_RECLAIM_MA5"]
    stability = {
        "ALL": summarize(rec),
        "DISCOVERY": summarize([r for r in rec if r["period"] == "DISCOVERY"]),
        "VALIDATION": summarize([r for r in rec if r["period"] == "VALIDATION"]),
        "2024": summarize([r for r in rec if r.get("fill_year") == 2024]),
        "2025": summarize([r for r in rec if r.get("fill_year") == 2025]),
        "2026": summarize([r for r in rec if r.get("fill_year") == 2026]),
    }

    # transition matrix: obs_group x next_session_stage
    trans = defaultdict(lambda: defaultdict(int))
    for r in main:
        trans[r["obs_group"]][str(r["next_session_stage"])] += 1
    trans_out = {
        g: {
            s: {"n": v, "share": round(v / sum(trans[g].values()), 4)}
            for s, v in sorted(trans[g].items())
        }
        for g in trans
    }

    metrics = {
        "title": "B1 POST-SIGNAL CONFIRMATION ATTRIBUTION v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "DESCRIPTIVE_OBSERVE_ONLY",
        "n_main": len(main),
        "OBSERVATION_GROUPS": groups,
        "BY_DAY": by_day,
        "STABILITY_RECLAIM_MA5": stability,
        "TRANSITION_MATRIX": trans_out,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
