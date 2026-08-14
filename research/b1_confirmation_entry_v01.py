"""RESEARCH-ONLY B1 CONFIRMATION ENTRY v0.1 (no production change).

Pre-registered variants on the 720 unique first-actionable B1 anchors:
  BASELINE : original canonical B1 fill + conservative T+1 execution
  C1       : skip original fill day; next session fill allowed only if
             observation-day low > invalid (existing buy-zone rules)
  C2       : C1 + observation-day close >= MA5

Entry on the confirmation session uses existing buy-zone levels
(open <= buy_zone_high -> fill at open; low <= buy_zone_high -> fill at
buy_zone_high; open <= invalid or no touch -> NO_FILL). Invalid / S1 / exit
rules unchanged. Anchor-level expectancy counts unfilled anchors as 0R.

Inputs: corrected episodes 66d5943f..., snapshot b5f84004de8a.
Output: data/tmp/b1-confirmation-entry-v01/metrics.json
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
OUT_DIR = DATA_ROOT / "tmp" / "b1-confirmation-entry-v01"
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


def simulate_trade(bar_list, fill_idx, fill_price, invalid, s1):
    """Canonical conservative T+1 execution from one fill."""

    fill_bar = bar_list[fill_idx]
    if float(fill_bar.low) <= invalid:
        if fill_idx + 1 < len(bar_list):
            px = float(bar_list[fill_idx + 1].open)
            return {
                "exit_type": "STOP_TRIGGERED_T1_BLOCKED",
                "exit_price": px,
                "gross_pct": px / fill_price - 1,
            }
        return {"exit_type": "CENSORED", "exit_price": None, "gross_pct": None}
    end = min(len(bar_list), fill_idx + 11)
    for idx in range(fill_idx + 1, end):
        b = bar_list[idx]
        o, h, l = float(b.open), float(b.high), float(b.low)
        if o <= invalid:
            return {"exit_type": "GAP_STOP", "exit_price": o, "gross_pct": o / fill_price - 1}
        if o >= s1:
            return {"exit_type": "GAP_TARGET", "exit_price": s1, "gross_pct": s1 / fill_price - 1}
        hit_inv = l <= invalid
        hit_s1 = h >= s1
        if hit_inv and hit_s1:
            return {"exit_type": "STOP_FIRST", "exit_price": invalid, "gross_pct": invalid / fill_price - 1}
        if hit_inv:
            return {"exit_type": "STOP", "exit_price": invalid, "gross_pct": invalid / fill_price - 1}
        if hit_s1:
            return {"exit_type": "TARGET", "exit_price": s1, "gross_pct": s1 / fill_price - 1}
    last = min(len(bar_list), fill_idx + 10)
    px = float(bar_list[last].close) if last < len(bar_list) else fill_price
    return {"exit_type": "MAX_HOLD", "exit_price": px, "gross_pct": px / fill_price - 1}


def net_r(gross_pct, risk_pct, bp):
    if gross_pct is None:
        return None
    return (gross_pct - bp / 10000) / risk_pct if risk_pct else None


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_episodes()
    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, row in df.iterrows():
        by_code[row["code"]].append(row)

    recs = []
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
            fill_price = float(row["fill_price"])
            invalid = float(row["invalid_price"])
            s1 = float(row["s1_price"])
            risk_pct = (fill_price - invalid) / fill_price
            if risk_pct <= 0:
                continue
            f["canonical_R_10bp"] = (
                float(row["conservative_net_execution_R_10bp"])
                if pd.notna(row["conservative_net_execution_R_10bp"])
                else None
            )
            f["canonical_R_20bp"] = (
                float(row["conservative_net_execution_R_20bp"])
                if pd.notna(row["conservative_net_execution_R_20bp"])
                else None
            )
            f["exec_status"] = row["conservative_execution_status"]
            f["exit_type"] = row["conservative_execution_exit_type"]
            if f["first_hit"] in ("S1_FIRST", "INVALID_FIRST") and f["exec_status"] == "RESOLVED":
                f["label"] = "WINNER" if f["first_hit"] == "S1_FIRST" else "LOSER"
            else:
                f["label"] = f["first_hit"]

            obs_bar = bar_list[fill_idx]
            obs_low = float(obs_bar.low)
            obs_close = float(obs_bar.close)
            ma5 = statistics.fmean(
                float(bar_list[i].close)
                for i in range(max(0, fill_idx - 4), fill_idx + 1)
            )
            survived = obs_low > invalid
            reclaim = obs_close >= ma5
            f["c1_eligible"] = bool(survived)
            f["c2_eligible"] = bool(survived and reclaim)

            # confirmation fill at fill_idx + 1 using existing buy-zone levels
            bz_high = (
                float(row["buy_zone_high"])
                if pd.notna(row["buy_zone_high"])
                else None
            )
            nxt = fill_idx + 1
            c_fill = None
            if nxt < len(bar_list):
                nb = bar_list[nxt]
                no, nl = float(nb.open), float(nb.low)
                if no <= invalid:
                    c_fill = {"status": "NO_FILL", "reason": "OPEN_BELOW_INVALID"}
                elif bz_high is not None and no <= bz_high:
                    c_fill = {"status": "FILLED", "price": no, "kind": "OPEN_FILL"}
                elif bz_high is not None and nl <= bz_high:
                    c_fill = {"status": "FILLED", "price": bz_high, "kind": "TOUCH_FILL"}
                else:
                    c_fill = {"status": "NO_FILL", "reason": "NO_ZONE_TOUCH"}
            else:
                c_fill = {"status": "NO_FILL", "reason": "NO_NEXT_SESSION"}
            f["c_fill"] = c_fill

            for variant in ("C1", "C2"):
                eligible = f["c1_eligible"] if variant == "C1" else f["c2_eligible"]
                if not eligible:
                    f[f"{variant}_fill_status"] = "NOT_ELIGIBLE"
                    f[f"{variant}_R_10bp"] = None
                    f[f"{variant}_R_20bp"] = None
                    f[f"{variant}_exit_type"] = None
                    continue
                if c_fill["status"] != "FILLED":
                    f[f"{variant}_fill_status"] = "NO_FILL"
                    f[f"{variant}_R_10bp"] = None
                    f[f"{variant}_R_20bp"] = None
                    f[f"{variant}_exit_type"] = None
                    continue
                out = simulate_trade(
                    bar_list, nxt, c_fill["price"], invalid, s1
                )
                if out["gross_pct"] is None:
                    f[f"{variant}_fill_status"] = "CENSORED"
                    f[f"{variant}_R_10bp"] = None
                    f[f"{variant}_R_20bp"] = None
                    f[f"{variant}_exit_type"] = out["exit_type"]
                    continue
                f[f"{variant}_fill_status"] = "FILLED"
                f[f"{variant}_R_10bp"] = net_r(out["gross_pct"], risk_pct, 10)
                f[f"{variant}_R_20bp"] = net_r(out["gross_pct"], risk_pct, 20)
                f[f"{variant}_exit_type"] = out["exit_type"]
            recs.append(f)

    main = [r for r in recs if r["label"] in ("WINNER", "LOSER")]
    assert len(main) == 720, len(main)

    def anchor_summary(recs_, rkey, exit_key):
        filled = [r for r in recs_ if r.get(rkey) is not None]
        all_vals = [
            r.get(rkey) if r.get(rkey) is not None else 0.0
            for r in recs_
        ]
        out = {
            "anchors": len(recs_),
            "filled": len(filled),
            "no_fill_or_0R": len(recs_) - len(filled),
            "fill_rate": round(len(filled) / len(recs_), 4),
            "filled": stats([r[rkey] for r in filled]),
            "anchor_level_expectancy": stats(all_vals),
            "target_exit_rate_filled": round(
                sum(1 for r in filled if r.get(exit_key) in ("TARGET", "GAP_TARGET")) / len(filled), 4
            ) if filled else None,
            "t1_blocked_rate_filled": round(
                sum(1 for r in filled if r.get(exit_key) == "STOP_TRIGGERED_T1_BLOCKED")
                / len(filled),
                4,
            ) if filled else None,
            "gap_stop_rate_filled": round(
                sum(1 for r in filled if r.get(exit_key) == "GAP_STOP") / len(filled),
                4,
            ) if filled else None,
        }
        return out

    baseline_10 = {
        "filled": stats([r["canonical_R_10bp"] for r in main]),
        "anchor_level_expectancy": stats([r["canonical_R_10bp"] for r in main]),
        "s1_first_rate": round(sum(1 for r in main if r["label"] == "WINNER") / len(main), 4),
        "t1_blocked_rate": round(
            sum(1 for r in main if r["exit_type"] == "STOP_TRIGGERED_T1_BLOCKED") / len(main), 4
        ),
        "gap_stop_rate": round(
            sum(1 for r in main if r["exit_type"] == "GAP_STOP") / len(main), 4
        ),
    }

    variants = {}
    for variant in ("C1", "C2"):
        rkey = f"{variant}_R_10bp"
        exit_key = f"{variant}_exit_type"
        variants[variant] = anchor_summary(main, rkey, exit_key)
        # C1/C2 exit-type breakdown among filled
        filled = [r for r in main if r.get(f"{variant}_fill_status") == "FILLED"]
        hazard = defaultdict(int)
        for r in filled:
            hazard[str(r.get(f"{variant}_exit_type"))] += 1
        variants[variant]["hazard_filled"] = dict(hazard)
        # period / year anchor-level expectancy
        for period in ("DISCOVERY", "VALIDATION"):
            sub = [r for r in main if r["period"] == period]
            variants[variant][period] = anchor_summary(sub, rkey, exit_key)
        for year in (2024, 2025, 2026):
            sub = [r for r in main if r.get("fill_year") == year]
            variants[variant][str(year)] = anchor_summary(sub, rkey, exit_key)
        baseline_period = {}
        for period in ("DISCOVERY", "VALIDATION"):
            sub = [r for r in main if r["period"] == period]
            baseline_period[period] = stats([r["canonical_R_10bp"] for r in sub])
        for year in (2024, 2025, 2026):
            sub = [r for r in main if r.get("fill_year") == year]
            baseline_period[str(year)] = stats([r["canonical_R_10bp"] for r in sub])
        variants[variant]["baseline_anchor_level"] = baseline_period

    # classification of retained / avoided / missed
    for variant in ("C1", "C2"):
        avoided = [r for r in main if r["label"] == "LOSER" and r.get(f"{variant}_fill_status") != "FILLED"]
        missed = [r for r in main if r["label"] == "WINNER" and r.get(f"{variant}_fill_status") != "FILLED"]
        retained_w = [r for r in main if r["label"] == "WINNER" and r.get(f"{variant}_fill_status") == "FILLED"]
        retained_l = [r for r in main if r["label"] == "LOSER" and r.get(f"{variant}_fill_status") == "FILLED"]
        variants[variant]["classification"] = {
            "avoided_losers": len(avoided),
            "missed_winners": len(missed),
            "retained_winners": len(retained_w),
            "retained_losers": len(retained_l),
        }

    metrics = {
        "title": "RESEARCH-ONLY B1 CONFIRMATION ENTRY v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "RESEARCH_ONLY",
        "pre_registered": {
            "C1": "observation-day low > invalid; fill next session per buy-zone rules",
            "C2": "C1 + observation-day close >= MA5",
            "anchor_level_expectancy": "unfilled anchors counted as 0R",
        },
        "BASELINE": baseline_10,
        "VARIANTS": variants,
        "fill_reason_breakdown": {},
    }
    reasons = defaultdict(int)
    for r in main:
        reasons[str(r["c_fill"]["reason"] if r["c_fill"]["status"] != "FILLED" else r["c_fill"]["kind"])] += 1
    metrics["fill_reason_breakdown"] = dict(reasons)
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
