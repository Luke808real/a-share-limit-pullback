"""HISTORICAL_ANALOG_ENGINE_V0.2 — robustness + path order audit (research-only).

Builds on V0.1 (same fingerprint, no new params / weights / thresholds).
Adds: similarity block audit, calibration vs stage background, neighbor
concentration + leave-same-stock-out, first-passage S1/INVALID order,
NEW_20D_HIGH_PROXY T+1 concentration check, day-by-day corridor quantiles,
and fixed feature ablation A/B/C/D.

Output: data/tmp/historical-analog-engine-v02/metrics.json
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from limit_pullback.screen.canonical import (
    iter_canonical_code_bars,
    load_canonical_metadata,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from research.historical_analog_engine_v01 import fingerprint


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
EPISODES_DIR = (
    DATA_ROOT
    / "outcome-study"
    / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome"
)
EOD_PARQUET = DATA_ROOT / "tmp" / "eod-recovery-2026-08-03" / "eod_20260803.parquet"
OUT_DIR = DATA_ROOT / "tmp" / "historical-analog-engine-v02"

PRICE_STATE = [
    "close_vs_ma5", "close_vs_ma10", "close_vs_ma20", "dist_20d_high",
    "dist_attack_high", "pullback_depth", "days_since_attack", "close_loc",
]
TECHNICAL = ["atr20_pct", "rsi14", "macd_hist_slope", "adx14", "bollinger_bw"]
BLOCKS = {"price_shape": 20, "vol_shape": 20, "price_state": PRICE_STATE, "technical": TECHNICAL}


def q(vals, q):
    s = sorted(vals)
    return s[int((len(s) - 1) * q)] if s else None


def build_library_and_candidates():
    ep = pd.read_parquet(EPISODES_DIR / "episodes.parquet")
    sig = ep[ep["execution_label"].isin(("B1_READY", "B2_READY", "B2_CONFIRMED"))].copy()
    for col in ("signal_date", "anchor_date"):
        sig[col] = pd.to_datetime(sig[col]).dt.date
    for col in ("invalid_price", "s1_price"):
        sig[col] = pd.to_numeric(sig[col].astype(str), errors="coerce")
    layout = WarehouseLayout(DATA_ROOT)
    snap, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, r in sig.iterrows():
        by_code[str(r["code"])].append(r)

    library = []
    for code, bars in iter_canonical_code_bars(layout, snap, codes=sorted(by_code.keys())):
        if not bars or code not in by_code:
            continue
        idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
        bar_list = list(bars)
        for row in by_code[code]:
            idx = idx_by_date.get(row["signal_date"])
            if idx is None:
                continue
            fp = fingerprint(bar_list, idx)
            if fp is None:
                continue
            inv = float(row["invalid_price"]) if pd.notna(row["invalid_price"]) else None
            s1 = float(row["s1_price"]) if pd.notna(row["s1_price"]) else None
            rec = {
                "code": str(code),
                "anchor": row["anchor_date"].isoformat(),
                "T": row["signal_date"].isoformat(),
                "stage": {"B1_READY": "PREPOSITION", "B2_READY": "B2_READY", "B2_CONFIRMED": "LAUNCH_READY"}[str(row["execution_label"])],
                "invalid": inv,
                "s1": s1,
                **fp,
            }
            if idx + 1 < len(bar_list) and inv is not None and s1 is not None:
                cT = float(bar_list[idx].close)
                high20 = max(float(b.high) for b in bar_list[max(0, idx - 19) : idx + 1])
                rec["fwd"] = {
                    "cT": cT,
                    "high20_T": high20,
                    "s1": s1,
                    "invalid": inv,
                    "bars": bar_list[idx + 1 : min(len(bar_list), idx + 11)],
                }
            library.append(rec)
    return library, layout, snap


def first_passage(rec):
    f = rec.get("fwd")
    if not f:
        return None
    s1, inv = f["s1"], f["invalid"]
    t_s1 = t_inv = None
    for j, b in enumerate(f["bars"], start=1):
        if t_s1 is None and float(b.high) >= s1:
            t_s1 = j
        if t_inv is None and float(b.low) <= inv:
            t_inv = j
        if t_s1 is not None and t_inv is not None:
            break
    return {
        "t_s1": t_s1,
        "t_inv": t_inv,
        "day_to_s1": t_s1,
        "day_to_invalid": t_inv,
        "s1_hit": t_s1 is not None,
        "invalid_hit": t_inv is not None,
        "new_high_10d": any(
            float(b.high) > f["high20_T"] for b in f["bars"]
        ),
        "first_new_high_day": next(
            (j for j, b in enumerate(f["bars"], start=1) if float(b.high) > f["high20_T"]),
            None,
        ),
    }


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    library, layout, snap = build_library_and_candidates()
    lib_with_fwd = [r for r in library if r.get("fwd")]
    for r in lib_with_fwd:
        r["fp_passage"] = first_passage(r)

    # z-stats over library (feature-level)
    fstats = {}
    for f in PRICE_STATE + TECHNICAL:
        vals = [r[f] for r in library if r[f] is not None]
        fstats[f] = {"mean": statistics.fmean(vals), "std": statistics.pstdev(vals) or 1}

    def block_vec(sample, block):
        if block == "price_shape":
            return list(sample["price_shape"])
        if block == "vol_shape":
            return list(sample["vol_shape"])
        feats = PRICE_STATE if block == "price_state" else TECHNICAL
        out = []
        for f in feats:
            v = sample.get(f)
            out.append(0.0 if v is None else (v - fstats[f]["mean"]) / fstats[f]["std"])
        return out

    def block_sq(a, b, block):
        va, vb = block_vec(a, block), block_vec(b, block)
        return sum((x - y) ** 2 for x, y in zip(va, vb))

    def dist_blocks(a, b):
        return {blk: block_sq(a, b, blk) for blk in BLOCKS}

    def total_dist(ds):
        return math.sqrt(sum(ds.values()))

    # candidates (T=8/3 via EOD fallback)
    eod = pd.read_parquet(EOD_PARQUET)
    eod["trade_date"] = pd.to_datetime(eod["trade_date"]).dt.date
    eod = eod[eod["trade_date"] == date(2026, 8, 3)]
    eod_by = {str(r["code"]): r for _, r in eod.iterrows()}
    candidates = [
        {"code": "603980", "name": "吉华集团", "stage": "B2_READY", "invalid": 6.23, "s1": 7.02},
        {"code": "600756", "name": "浪潮软件", "stage": "B2_READY", "invalid": 15.66, "s1": 16.99},
    ]
    cand_rows = []
    for cand in candidates:
        for c, bars in iter_canonical_code_bars(layout, snap, codes=[cand["code"]], as_of=date(2026, 7, 31)):
            bar_list = list(bars)
            r8 = eod_by[cand["code"]]
            b = type("B", (), {})()
            b.trade_date = date(2026, 8, 3)
            b.open = float(r8["open"]); b.high = float(r8["high"])
            b.low = float(r8["low"]); b.close = float(r8["close"])
            b.volume = float(r8["volume"]); b.preclose = float(bar_list[-1].close)
            bar_list.append(b)
            fp = fingerprint(bar_list, len(bar_list) - 1)
            if fp is not None:
                cand_rows.append({"code": cand["code"], "name": cand["name"], "stage": cand["stage"], "T": "2026-08-03", "invalid": cand["invalid"], "s1": cand["s1"], **fp})

    reports = {}
    for cand in cand_rows:
        lib = [r for r in lib_with_fwd if r["stage"] == cand["stage"]]
        scored = []
        for r in lib:
            ds = dist_blocks(cand, r)
            scored.append((total_dist(ds), ds, r))
        scored.sort(key=lambda x: x[0])
        bg = [s[0] for s in scored]
        top150 = scored[:150]
        top_dist = top150[0][0]
        med_dist = top150[74][0]
        pct = sum(1 for d in bg if d < top_dist) / len(bg)
        # block contribution (share of mean squared distance among top150)
        block_contrib = {}
        for blk in BLOCKS:
            block_contrib[blk] = round(
                statistics.fmean(s[1][blk] for s in top150)
                / statistics.fmean(sum(s[1].values()) for s in top150),
                3,
            )
        # concentration
        stocks = [s[2]["code"] for s in top150]
        anchors = [s[2]["anchor"] for s in top150]
        stock_counts = defaultdict(int)
        for x in stocks:
            stock_counts[x] += 1
        top_stock_share = round(max(stock_counts.values()) / 150, 3)
        same_stock_share = round(sum(1 for x in stocks if x == cand["code"]) / 150, 3)
        # leave-same-stock-out: nearest per stock
        per_stock = {}
        for d, ds, r in top150:
            per_stock.setdefault(r["code"], (d, r))
        lso = list(per_stock.values())
        # first-passage stats
        def fp_stats(rows):
            out = {"n": len(rows)}
            for k in (1, 3, 5, 10):
                s1f = invf = same = neither = 0
                for d, r in rows:
                    p = r["fp_passage"]
                    ts, ti = p["t_s1"], p["t_inv"]
                    if ts is not None and (ti is None or ts < ti) and ts <= k:
                        s1f += 1
                    elif ti is not None and (ts is None or ti < ts) and ti <= k:
                        invf += 1
                    elif ts is not None and ti is not None and ts == ti and ts <= k:
                        same += 1
                    else:
                        neither += 1
                out[f"{k}d"] = {
                    "S1_FIRST": round(s1f / len(rows), 3),
                    "INVALID_FIRST": round(invf / len(rows), 3),
                    "SAME_DAY": round(same / len(rows), 3),
                    "NEITHER": round(neither / len(rows), 3),
                }
            ds1 = [r["fp_passage"]["day_to_s1"] for _, r in rows if r["fp_passage"]["day_to_s1"] is not None]
            dinv = [r["fp_passage"]["day_to_invalid"] for _, r in rows if r["fp_passage"]["day_to_invalid"] is not None]
            out["median_day_to_S1"] = statistics.median(ds1) if ds1 else None
            out["median_day_to_invalid"] = statistics.median(dinv) if dinv else None
            out["s1_hit_10d"] = round(sum(1 for _, r in rows if r["fp_passage"]["s1_hit"]) / len(rows), 3)
            out["invalid_hit_10d"] = round(sum(1 for _, r in rows if r["fp_passage"]["invalid_hit"]) / len(rows), 3)
            return out

        full = fp_stats([(s[0], s[2]) for s in top150])
        lso_stats = fp_stats(lso)
        # NEW_20D_HIGH_PROXY concentration vs near-high geometry
        near = [r for _, _, r in top150 if r.get("dist_20d_high") is not None and r["dist_20d_high"] >= -0.03]
        far = [r for _, _, r in top150 if r.get("dist_20d_high") is not None and r["dist_20d_high"] < -0.03]
        t1_near = round(sum(1 for r in near if r["fp_passage"]["first_new_high_day"] == 1) / len(near), 3) if near else None
        t1_far = round(sum(1 for r in far if r["fp_passage"]["first_new_high_day"] == 1) / len(far), 3) if far else None
        # corridor: day-by-day cumulative high/low quantiles
        corridor = {}
        for k in (1, 2, 3, 5, 10):
            ch, cl = [], []
            for _, _, r in top150:
                seg = r["fwd"]["bars"][:k]
                if not seg:
                    continue
                cT = r["fwd"]["cT"]
                ch.append(max(float(b.high) for b in seg) / cT - 1)
                cl.append(min(float(b.low) for b in seg) / cT - 1)
            corridor[str(k)] = {
                "cum_high": {p: round(q(ch, p), 4) for p in (0.25, 0.5, 0.75, 0.9)},
                "cum_low": {p: round(q(cl, p), 4) for p in (0.25, 0.5, 0.75, 0.9)},
            }
        reports[cand["code"]] = {
            "name": cand["name"],
            "SIMILARITY_AUDIT": {
                "top_neighbor_dist": round(top_dist, 3),
                "median_neighbor_dist": round(med_dist, 3),
                "similarity_percentile_vs_stage_baseline": round(pct, 4),
                "stage_baseline_median_dist": round(q(bg, 0.5), 3),
                "block_contribution_share": block_contrib,
            },
            "CONCENTRATION_AUDIT": {
                "unique_stocks": len(stock_counts),
                "unique_anchors": len(set(anchors)),
                "same_stock_share": same_stock_share,
                "top_stock_share": top_stock_share,
                "leave_same_stock_out": lso_stats,
            },
            "FIRST_PASSAGE": full,
            "NEW_20D_HIGH_PROXY": {
                "label": "NEW_20D_HIGH_PROXY (not real SECOND_LAUNCH)",
                "t+1_rate_near_high_analogs": t1_near,
                "t+1_rate_far_analogs": t1_far,
            },
            "TARGET_CORRIDOR": corridor,
        }

    # feature ablation (fixed sets) on 603980
    ablation = {}
    cand = next(c for c in cand_rows if c["code"] == "603980")
    lib = [r for r in lib_with_fwd if r["stage"] == cand["stage"]]
    sets = {
        "A_shape_only": ["price_shape"],
        "B_shape_price_state": ["price_shape", "price_state"],
        "C_plus_volume": ["price_shape", "price_state", "vol_shape"],
        "D_full": list(BLOCKS),
    }
    for name, blocks in sets.items():
        def dset(a, b):
            return math.sqrt(sum(block_sq(a, b, blk) for blk in blocks))
        scored = sorted(((dset(cand, r), r) for r in lib), key=lambda x: x[0])[:150]
        rows = [(d, r) for d, r in scored]
        st = fp_stats(rows)
        mfe3 = [r["fwd"].get("mfe_3d") for _, r in rows if r["fwd"].get("mfe_3d") is not None]
        # compute mfe3 on the fly from bars
        mfe3 = []
        for _, r in rows:
            seg = r["fwd"]["bars"][:3]
            if seg:
                mfe3.append(max(float(b.high) for b in seg) / r["fwd"]["cT"] - 1)
        ablation[name] = {
            "3d_mfe_dispersion_std": round(statistics.pstdev(mfe3), 4) if mfe3 else None,
            "s1_first_3d": st["3d"]["S1_FIRST"],
            "invalid_first_3d": st["3d"]["INVALID_FIRST"],
        }

    metrics = {
        "title": "HISTORICAL_ANALOG_ENGINE_V0.2",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "RESEARCH_OVERLAY_ONLY",
        "REPORTS": reports,
        "FEATURE_ABLATION": ablation,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
