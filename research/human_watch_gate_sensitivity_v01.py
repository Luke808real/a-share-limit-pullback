"""HUMAN-WATCH GATE SENSITIVITY v0.1 (research-only, no production change).

Targets:
  OLD = AUTO_ENTRY_CANDIDATE (is_entry_candidate True)
  NEW = HUMAN_WATCH_CANDIDATE ("worth intraday watch next day", not auto-trade)

Counterfactuals (single semantic change each, no threshold scan):
  A RR/ROOM hard veto -> execution reference
  B DATA_LIMITED exclusion -> MANUAL_REVIEW
  C B2_READY non-candidates allowed into watch
  D near-S1/near-20d-high not chase-negative (G ranking)
  E entry_quality auxiliary only

Combos:
  BASELINE = old candidate pool, ranked by entry_quality (old-priority proxy)
  WATCH_V1 = BASELINE + non-candidate signals with levels (RR/ROOM not veto)
  WATCH_V2 = V1 + unmapped signals (manual review)
  WATCH_V3 = V2 ranked by G geometry (entry_quality auxiliary)

Output: data/tmp/human-watch-gate-sensitivity-v01/metrics.json
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
OUT_DIR = DATA_ROOT / "tmp" / "human-watch-gate-sensitivity-v01"
SPLIT_DATE = __import__("datetime").date(2025, 7, 1)
NEAR_S1 = 0.98
EXPANSION_GAIN = 0.05


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
    sig = ep[
        ep["execution_label"].isin(("B1_READY", "B2_READY", "B2_CONFIRMED"))
    ].copy()
    for col in ("signal_date", "anchor_date"):
        sig[col] = pd.to_datetime(sig[col]).dt.date
    for col in (
        "invalid_price", "s1_price", "buy_zone_high", "buy_zone_low",
        "preferred_entry", "setup_quality_score", "entry_quality_score",
    ):
        sig[col] = pd.to_numeric(sig[col].astype(str), errors="coerce")
    sig["is_entry_candidate"] = sig["is_entry_candidate"].astype(bool)

    layout = WarehouseLayout(DATA_ROOT)
    snap, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, r in sig.iterrows():
        by_code[str(r["code"])].append(r)

    recs = []
    for code, bars in iter_canonical_code_bars(
        layout, snap, codes=sorted(by_code.keys())
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
            entry_ref = (
                float(row["preferred_entry"])
                if pd.notna(row["preferred_entry"])
                else (float(row["buy_zone_high"]) if pd.notna(row["buy_zone_high"]) else None)
            )
            rec = {
                "code": str(code),
                "signal_date": row["signal_date"],
                "label": str(row["execution_label"]),
                "is_entry_candidate": bool(row["is_entry_candidate"]),
                "room": str(row["entry_room_state"]),
                "setup_q": (
                    float(row["setup_quality_score"])
                    if pd.notna(row["setup_quality_score"])
                    else None
                ),
                "entry_q": (
                    float(row["entry_quality_score"])
                    if pd.notna(row["entry_quality_score"])
                    else None
                ),
                "mapped": bool(invalid is not None and s1 is not None and entry_ref is not None),
                "invalid": invalid,
                "s1": s1,
                "entry_ref": entry_ref,
                "period": "DISCOVERY" if row["signal_date"] < SPLIT_DATE else "VALIDATION",
                "year": row["signal_date"].year,
            }
            if rec["mapped"]:
                rec["rr"] = (s1 - entry_ref) / (entry_ref - invalid) if entry_ref > invalid else None
            if rec["mapped"] and sig_idx + 3 < len(bar_list):
                c = float(bar_list[sig_idx].close)
                high20 = max(float(bar_list[i].high) for i in range(max(0, sig_idx - 19), sig_idx + 1))
                rec["close_vs_s1"] = (c / s1 - 1) * 100
                rec["dist_20d_high"] = (c / high20 - 1) * 100
                win = list(range(sig_idx + 1, min(len(bar_list), sig_idx + 4)))
                max_high = max(float(bar_list[i].high) for i in win)
                rec["actionable"] = bool(
                    max_high >= NEAR_S1 * s1
                    or max_high > high20
                    or max(float(bar_list[i].close) / float(bar_list[i].preclose) - 1 for i in win)
                    >= EXPANSION_GAIN
                )
                t_s1 = t_inv = None
                for idx in range(sig_idx + 1, min(len(bar_list), sig_idx + 11)):
                    b = bar_list[idx]
                    if t_s1 is None and float(b.high) >= s1:
                        t_s1 = idx - sig_idx
                    if t_inv is None and float(b.low) <= invalid:
                        t_inv = idx - sig_idx
                    if t_s1 is not None and t_inv is not None:
                        break
                rec["s1_first"] = bool(t_s1 is not None and (t_inv is None or t_s1 < t_inv))
                rec["invalid_first"] = bool(t_inv is not None and (t_s1 is None or t_inv < t_s1))
                for k in (3, 5):
                    if sig_idx + k < len(bar_list):
                        seg = bar_list[sig_idx + 1 : sig_idx + k + 1]
                        rec[f"mfe_{k}d"] = max(float(b.high) for b in seg) / c - 1
                        rec[f"mae_{k}d"] = min(float(b.low) for b in seg) / c - 1
                rec["g"] = statistics.fmean(
                    [(rec["close_vs_s1"] + 8) / 6, (rec["dist_20d_high"] + 10) / 5]
                )  # plain scaled geometry (no refit; ranking only)
            recs.append(rec)

    mapped = [r for r in recs if r["mapped"]]
    unmapped = [r for r in recs if not r["mapped"]]
    global_actionable_keys = {
        r["code"] + r["signal_date"].isoformat()
        for r in recs
        if r.get("actionable") is True
    }

    def pool_variant(name):
        if name == "BASELINE":
            return [r for r in mapped if r["is_entry_candidate"]]
        if name == "A":
            return list(mapped)
        if name == "WATCH_V1":
            # A: RR/ROOM no hard veto -> all mapped signals with levels
            return list(mapped)
        if name == "B":
            return [r for r in mapped if r["is_entry_candidate"]] + list(unmapped)
        if name == "C":
            base = [r for r in mapped if r["is_entry_candidate"]]
            b2_non = [
                r
                for r in mapped
                if not r["is_entry_candidate"] and r["label"] == "B2_READY"
            ]
            return base + b2_non
        if name == "WATCH_V2":
            # B: unmapped -> manual review (include); C: B2 non-candidates already covered by V1 pool
            return list(mapped) + list(unmapped)
        if name in ("D", "E"):
            return [r for r in mapped if r["is_entry_candidate"]]
        if name == "WATCH_V3":
            return list(mapped) + list(unmapped)
        raise ValueError(name)

    def rank_key(r, variant):
        if variant in ("WATCH_V3", "D", "E"):
            return (r.get("g") if r.get("g") is not None else -999, r.get("entry_q") or -999)
        return (r.get("entry_q") or -999, r.get("setup_q") or -999)

    results = {}
    for variant in ("BASELINE", "A", "B", "C", "D", "E", "WATCH_V1", "WATCH_V2", "WATCH_V3"):
        pool = pool_variant(variant)
        by_day = defaultdict(list)
        for r in pool:
            by_day[r["signal_date"]].append(r)
        daily_counts = [len(v) for v in by_day.values()]
        top10_union = []
        top20_union = []
        for day, items in by_day.items():
            items_sorted = sorted(items, key=lambda r: rank_key(r, variant), reverse=True)
            top10_union.extend(items_sorted[:10])
            top20_union.extend(items_sorted[:20])
        act_pool = [r for r in pool if r.get("actionable") is True]
        act_top10 = [r for r in top10_union if r.get("actionable") is True]
        act_top20 = [r for r in top20_union if r.get("actionable") is True]
        top10_keys = {x["code"] + x["signal_date"].isoformat() for x in act_top10}
        top20_keys = {x["code"] + x["signal_date"].isoformat() for x in act_top20}
        global_top10_coverage = round(len(top10_keys) / len(global_actionable_keys), 4) if global_actionable_keys else None
        global_top20_coverage = round(len(top20_keys) / len(global_actionable_keys), 4) if global_actionable_keys else None
        pool_stats = {
            "watchlist_size": len(pool),
            "daily_median_candidates": round(statistics.median(daily_counts), 2) if daily_counts else None,
            "actionable_rate": round(len(act_pool) / len(pool), 4) if pool else None,
            "top10_coverage": round(len(set(x["code"] + x["signal_date"].isoformat() for x in act_top10)) / len(set(x["code"] + x["signal_date"].isoformat() for x in act_pool)), 4) if act_pool else None,
            "top20_coverage": round(len(set(x["code"] + x["signal_date"].isoformat() for x in act_top20)) / len(set(x["code"] + x["signal_date"].isoformat() for x in act_pool)), 4) if act_pool else None,
            "global_top10_coverage": global_top10_coverage,
            "global_top20_coverage": global_top20_coverage,
            "s1_first_rate": round(sum(1 for r in pool if r.get("s1_first")) / sum(1 for r in pool if r.get("s1_first") is not None), 4) if any(r.get("s1_first") is not None for r in pool) else None,
            "invalid_first_rate": round(sum(1 for r in pool if r.get("invalid_first")) / sum(1 for r in pool if r.get("invalid_first") is not None), 4) if any(r.get("invalid_first") is not None for r in pool) else None,
            "mfe_3d": stats([r.get("mfe_3d") for r in pool]),
            "mfe_5d": stats([r.get("mfe_5d") for r in pool]),
            "mae_3d": stats([r.get("mae_3d") for r in pool]),
            "mae_5d": stats([r.get("mae_5d") for r in pool]),
        }
        for period in ("DISCOVERY", "VALIDATION"):
            p = [r for r in pool if r["period"] == period]
            a = [r for r in p if r.get("actionable") is True]
            pool_stats[period] = {
                "n": len(p),
                "actionable_rate": round(len(a) / len(p), 4) if p else None,
            }
        for year in (2024, 2025, 2026):
            p = [r for r in pool if r["year"] == year]
            a = [r for r in p if r.get("actionable") is True]
            pool_stats[str(year)] = {
                "n": len(p),
                "actionable_rate": round(len(a) / len(p), 4) if p else None,
            }
        results[variant] = pool_stats

    # human-case mapping (top 10/20/50 within their signal day)
    case_codes = {"600756", "600468", "600199", "603980", "002640", "002891"}
    cases = []
    for code in sorted(case_codes):
        r = [
            x
            for x in recs
            if x["code"] == code
            and x["signal_date"] >= __import__("datetime").date(2026, 7, 25)
        ]
        entry = {"code": code, "signals_after_7_25": len(r)}
        for x in r:
            day = x["signal_date"]
            pos_day = {}
            for variant in ("BASELINE", "WATCH_V1", "WATCH_V2", "WATCH_V3"):
                pool = pool_variant(variant)
                day_items = sorted(
                    [y for y in pool if y["signal_date"] == day],
                    key=lambda y: rank_key(y, variant),
                    reverse=True,
                )
                pos = next((i + 1 for i, y in enumerate(day_items) if y["code"] == code), None)
                pos_day[variant] = pos
            entry[f"pos_{day}"] = pos_day
        cases.append(entry)

    metrics = {
        "title": "HUMAN-WATCH GATE SENSITIVITY v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "DESCRIPTIVE_OBSERVE_ONLY",
        "VARIANT_RESULTS": results,
        "HUMAN_CASE_MAPPING": cases,
        "note": "BASELINE ranked by entry_quality (old-priority proxy); V3 ranked by scaled G geometry; "
        "top10/20 coverage = union over days of per-day top-K actionable / pool actionable; no threshold scan",
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
