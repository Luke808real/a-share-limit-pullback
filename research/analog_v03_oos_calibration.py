"""ANALOG_V03_OOS_CALIBRATION (research-only).

Pseudo-current queries from the full frozen episode library; each query's
analogs are restricted to strictly earlier dates (PIT). Compares RAW_V02 vs
BLOCK_BALANCED (four blocks internally z-normalized then equal weight) on:
5d S1_FIRST / INVALID_FIRST calibration (Brier + decile reliability),
3d/5d MFE/MAE median error, corridor coverage, rank correlation, and fixed
A/B/C/D ablation by period/year. Duplicate-anchor + leave-same-stock-out
audit retained.

No production / frozen / G / sizing changes; no tuning on 600756/603980.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from limit_pullback.warehouse.layout import WarehouseLayout
from research.historical_analog_engine_v02 import build_library_and_candidates


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
OUT_DIR = ROOT / "research" / "runs" / "ANALOG_V03_OOS_CALIBRATION"
QUERY_PER_STAGE_PER_YEAR = 500

PRICE_STATE = [
    "close_vs_ma5", "close_vs_ma10", "close_vs_ma20", "dist_20d_high",
    "dist_attack_high", "pullback_depth", "days_since_attack", "close_loc",
]
TECHNICAL = ["atr20_pct", "rsi14", "macd_hist_slope", "adx14", "bollinger_bw"]
BLOCKS = ["price_shape", "vol_shape", "price_state", "technical"]


def first_passage_5d(rec):
    f = rec.get("fwd")
    if not f:
        return None
    s1, inv = f["s1"], f["invalid"]
    t_s1 = t_inv = None
    for j, b in enumerate(f["bars"][:5], start=1):
        if t_s1 is None and float(b.high) >= s1:
            t_s1 = j
        if t_inv is None and float(b.low) <= inv:
            t_inv = j
        if t_s1 is not None and t_inv is not None:
            break
    if t_s1 is not None and t_inv is not None:
        lab = "S1_FIRST" if t_s1 < t_inv else ("INVALID_FIRST" if t_inv < t_s1 else "SAME_DAY")
    elif t_s1 is not None:
        lab = "S1_FIRST"
    elif t_inv is not None:
        lab = "INVALID_FIRST"
    else:
        lab = "NEITHER"
    return lab, t_s1, t_inv


def realized_mfe_mae(rec, k):
    f = rec.get("fwd")
    if not f:
        return None, None
    seg = f["bars"][:k]
    if not seg:
        return None, None
    cT = f["cT"]
    return (
        max(float(b.high) for b in seg) / cT - 1,
        min(float(b.low) for b in seg) / cT - 1,
    )


def rank_corr(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        for pos, idx in enumerate(order):
            r[idx] = pos + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    library, _, _ = build_library_and_candidates()
    lib = [r for r in library if r.get("fwd")]
    stages = sorted({r["stage"] for r in lib})
    print("library", len(lib), "stages", stages, flush=True)

    results = {}
    for stage in stages:
        recs = [r for r in lib if r["stage"] == stage]
        # query sample: per year up to QUERY_PER_STAGE_PER_YEAR
        per_year = defaultdict(list)
        for r in recs:
            per_year[int(r["T"][:4])].append(r)
        queries = []
        for y in sorted(per_year):
            queries.extend(sorted(per_year[y], key=lambda r: r["T"])[:QUERY_PER_STAGE_PER_YEAR])
        # feature arrays
        def block_arr(key, feats=None):
            if key in ("price_shape", "vol_shape"):
                return np.array([r[key] for r in recs], dtype=float)
            return np.array([[r[f] if r[f] is not None else 0.0 for f in feats] for r in recs], dtype=float)

        arr = {
            "price_shape": block_arr("price_shape"),
            "vol_shape": block_arr("vol_shape"),
            "price_state": block_arr("price_state", PRICE_STATE),
            "technical": block_arr("technical", TECHNICAL),
        }
        # z-normalize each block per feature (for BLOCK_BALANCED and RAW level/tech)
        zarr = {}
        for blk, a in arr.items():
            mu = a.mean(axis=0)
            sd = a.std(axis=0)
            sd[sd == 0] = 1.0
            zarr[blk] = (a - mu) / sd

        def eval_from_sq(q_idx, block_sq, variant, blocks_mask=None, balanced=False):
            n = len(recs)
            qT = recs[q_idx]["T"]
            earlier = np.array([recs[i]["T"] < qT for i in range(n)], dtype=bool)
            if variant == "RAW":
                d2 = sum(block_sq.values())
            else:
                d2 = np.zeros(n)
                for blk in BLOCKS:
                    d2 += np.sqrt(np.maximum(block_sq[blk] / arr[blk].shape[1], 0))
            d2 = np.where(earlier, d2, np.inf)
            order = np.argsort(d2)[:150]
            if blocks_mask is not None:
                d2b = np.zeros(n)
                for blk in blocks_mask:
                    d2b += block_sq[blk]
                d2b = np.where(earlier, d2b, np.inf)
                order = np.argsort(d2b)[:150]
            top = [recs[i] for i in order if np.isfinite(d2[i])][:150]
            if not top:
                return None
            labs = [first_passage_5d(r)[0] for r in top]
            s1_rate = sum(1 for x in labs if x == "S1_FIRST") / len(top)
            inv_rate = sum(1 for x in labs if x == "INVALID_FIRST") / len(top)
            meds = {}
            for k in (3, 5):
                mfes = [realized_mfe_mae(r, k)[0] for r in top]
                maes = [realized_mfe_mae(r, k)[1] for r in top]
                meds[f"mfe{k}"] = statistics.median([x for x in mfes if x is not None])
                meds[f"mae{k}"] = statistics.median([x for x in maes if x is not None])
                meds[f"p25mfe{k}"] = np.percentile([x for x in mfes if x is not None], 25)
                meds[f"p75mfe{k}"] = np.percentile([x for x in mfes if x is not None], 75)
                meds[f"p10mae{k}"] = np.percentile([x for x in maes if x is not None], 10)
                meds[f"p90mae{k}"] = np.percentile([x for x in maes if x is not None], 90)
            return {
                "s1_rate": s1_rate,
                "inv_rate": inv_rate,
                **meds,
                "unique_anchors": len({r["anchor"] for r in top}),
                "unique_stocks": len({r["code"] for r in top}),
                "same_stock_share": sum(1 for r in top if r["code"] == recs[q_idx]["code"]) / len(top),
            }

        def query_block_sq(q_idx):
            rawsq, zsq = {}, {}
            for blk in BLOCKS:
                src_raw = arr[blk]
                qr = src_raw[q_idx]
                rawsq[blk] = ((src_raw - qr) ** 2).sum(axis=1)
                src_z = zarr[blk]
                qz = src_z[q_idx]
                zsq[blk] = ((src_z - qz) ** 2).sum(axis=1)
            # RAW v0.2: raw price/vol shapes + z level/technical
            rawsq["price_state"] = zsq["price_state"]
            rawsq["technical"] = zsq["technical"]
            return rawsq, zsq

        stage_out = {"RAW": [], "BAL": []}
        for qi in range(len(queries)):
            q_idx = recs.index(queries[qi])
            rawsq, zsq = query_block_sq(q_idx)
            qrec = queries[qi]
            lab5, _, _ = first_passage_5d(qrec)
            r3 = realized_mfe_mae(qrec, 3)
            r5 = realized_mfe_mae(qrec, 5)
            for variant in ("RAW", "BAL"):
                row = eval_from_sq(q_idx, rawsq if variant == "RAW" else zsq, variant)
                if row is not None:
                    row.update(
                        {
                            "realized_lab5": lab5,
                            "realized_mfe3": r3[0],
                            "realized_mae3": r3[1],
                            "realized_mfe5": r5[0],
                            "realized_mae5": r5[1],
                            "query_T": qrec["T"],
                            "query_year": int(qrec["T"][:4]),
                        }
                    )
                stage_out[variant].append(row)
        # ablation on a subsample of queries
        abl_queries = queries[::3][:400]
        ablation = {name: [] for name in ("A", "B", "C", "D")}
        masks = {
            "A": ["price_shape"],
            "B": ["price_shape", "price_state"],
            "C": ["price_shape", "price_state", "vol_shape"],
            "D": BLOCKS,
        }
        for qi in range(len(abl_queries)):
            idx = recs.index(abl_queries[qi])
            rawsq, _ = query_block_sq(idx)
            qrec = abl_queries[qi]
            lab5, _, _ = first_passage_5d(qrec)
            r5 = realized_mfe_mae(qrec, 5)
            for name, m in masks.items():
                r = eval_from_sq(idx, rawsq, "RAW", blocks_mask=m)
                if r:
                    r.update(
                        {
                            "realized_lab5": lab5,
                            "realized_mfe5": r5[0],
                            "realized_mae5": r5[1],
                            "query_T": qrec["T"],
                            "query_year": int(qrec["T"][:4]),
                        }
                    )
                    ablation[name].append(r)
        results[stage] = {"queries": len(queries), "RAW": stage_out["RAW"], "BAL": stage_out["BAL"], "ablation": ablation}
        print("stage", stage, "queries", len(queries), "done", flush=True)

    summary = {}
    for stage, sd in results.items():
        summary[stage] = {}
        for variant in ("RAW", "BAL"):
            rows = [r for r in sd[variant] if r and r.get("realized_lab5") is not None]
            if not rows:
                continue
            brier_s1 = statistics.fmean((r["s1_rate"] - (1 if r["realized_lab5"] == "S1_FIRST" else 0)) ** 2 for r in rows)
            brier_inv = statistics.fmean((r["inv_rate"] - (1 if r["realized_lab5"] == "INVALID_FIRST" else 0)) ** 2 for r in rows)
            err_mfe5 = statistics.fmean(abs(r["mfe5"] - r["realized_mfe5"]) for r in rows if r["realized_mfe5"] is not None)
            err_mae5 = statistics.fmean(abs(r["mae5"] - r["realized_mae5"]) for r in rows if r["realized_mae5"] is not None)
            cov_mfe = statistics.fmean(1 if r["realized_mfe5"] is not None and r["p25mfe5"] <= r["realized_mfe5"] <= r["p75mfe5"] else 0 for r in rows)
            cov_mae = statistics.fmean(1 if r["realized_mae5"] is not None and r["p10mae5"] <= r["realized_mae5"] <= r["p90mae5"] else 0 for r in rows)
            pairs = [(r["mfe5"], r["realized_mfe5"]) for r in rows if r["realized_mfe5"] is not None]
            rcorr_mfe = rank_corr([a for a, _ in pairs], [b for _, b in pairs]) if len(pairs) > 3 else None
            rcorr_s1 = rank_corr([r["s1_rate"] for r in rows], [1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in rows])
            deciles = {}
            srt = sorted(rows, key=lambda r: r["s1_rate"])
            n_d = len(srt) // 10
            for d in range(10):
                grp = srt[d * n_d : (d + 1) * n_d]
                deciles[str(d + 1)] = {
                    "analog_s1_rate": round(statistics.fmean(r["s1_rate"] for r in grp), 3),
                    "realized_s1_freq": round(
                        statistics.fmean(1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in grp), 3
                    ),
                }
            per_period = {}
            for p, key in (("DISCOVERY", lambda r: r["query_T"] < "2025-07-01"), ("VALIDATION", lambda r: r["query_T"] >= "2025-07-01")):
                sub = [r for r in rows if key(r)]
                per_period[p] = {
                    "n": len(sub),
                    "brier_s1": round(statistics.fmean((r["s1_rate"] - (1 if r["realized_lab5"] == "S1_FIRST" else 0)) ** 2 for r in sub), 4) if sub else None,
                    "mean_abs_err_mfe5": round(statistics.fmean(abs(r["mfe5"] - r["realized_mfe5"]) for r in sub), 4) if sub else None,
                    "realized_s1_first_rate": round(statistics.fmean(1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in sub), 4) if sub else None,
                }
            for y in ("2024", "2025", "2026"):
                sub = [r for r in rows if str(r["query_year"]) == y]
                per_period[y] = {
                    "n": len(sub),
                    "brier_s1": round(statistics.fmean((r["s1_rate"] - (1 if r["realized_lab5"] == "S1_FIRST" else 0)) ** 2 for r in sub), 4) if sub else None,
                    "mean_abs_err_mfe5": round(statistics.fmean(abs(r["mfe5"] - r["realized_mfe5"]) for r in sub), 4) if sub else None,
                    "realized_s1_first_rate": round(statistics.fmean(1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in sub), 4) if sub else None,
                }
            summary[stage][variant] = {
                "n": len(rows),
                "brier_s1": round(brier_s1, 4),
                "brier_inv": round(brier_inv, 4),
                "mean_abs_err_mfe5": round(err_mfe5, 4),
                "mean_abs_err_mae5": round(err_mae5, 4),
                "corridor_coverage_mfe_p25_75": round(cov_mfe, 4),
                "corridor_coverage_mae_p10_90": round(cov_mae, 4),
                "rank_corr_mfe5": round(rcorr_mfe, 3) if rcorr_mfe is not None else None,
                "rank_corr_s1": round(rcorr_s1, 3),
                "calibration_deciles": deciles,
                "periods": per_period,
                "unique_anchors_mean": round(statistics.fmean(r["unique_anchors"] for r in rows), 1),
                "unique_stocks_mean": round(statistics.fmean(r["unique_stocks"] for r in rows), 1),
                "same_stock_share_mean": round(statistics.fmean(r["same_stock_share"] for r in rows), 4),
            }
        abl_out = {}
        for name in ("A", "B", "C", "D"):
            rows = [r for r in sd["ablation"][name] if r]
            abl_out[name] = {
                "n": len(rows),
                "neighbor_s1_rate_mean": round(statistics.fmean(r["s1_rate"] for r in rows), 4) if rows else None,
                "realized_s1_first_rate": round(
                    statistics.fmean(1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in rows), 4
                ) if rows else None,
                "mean_abs_err_mfe5": round(statistics.fmean(abs(r["mfe5"] - r["realized_mfe5"]) for r in rows), 4) if rows else None,
            }
        summary[stage]["ABLATION"] = abl_out

    metrics = {"RUN_ID": "ANALOG_V03_OOS_CALIBRATION", "summary": summary, "results": results}
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return metrics


if __name__ == "__main__":
    main()
