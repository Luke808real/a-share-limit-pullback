"""ANALOG_V03A_STRICT_PIT (research-only; fixes V03 PIT + sampling).

Fixes:
  1. Every query T standardizes its features using ONLY the analog universe
     with date < T (strict PIT; no future records in mean/std).
  2. Query sampling: deterministic evenly-spaced selection per year per stage
     (max 500/year, covering the full year); no target-based sampling.

RAW_V02 / BLOCK_BALANCED definitions unchanged. Same metrics as V03.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

from research.historical_analog_engine_v02 import build_library_and_candidates
from research.analog_v03_oos_calibration import (
    first_passage_5d,
    realized_mfe_mae,
    rank_corr,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "runs" / "ANALOG_V03_OOS_CALIBRATION"
MAX_PER_YEAR = 500

PRICE_STATE = [
    "close_vs_ma5", "close_vs_ma10", "close_vs_ma20", "dist_20d_high",
    "dist_attack_high", "pullback_depth", "days_since_attack", "close_loc",
]
TECHNICAL = ["atr20_pct", "rsi14", "macd_hist_slope", "adx14", "bollinger_bw"]
BLOCKS = ["price_shape", "vol_shape", "price_state", "technical"]
BLOCK_DIM = {"price_shape": 20, "vol_shape": 20, "price_state": len(PRICE_STATE), "technical": len(TECHNICAL)}


def sample_year(recs):
    n = len(recs)
    if n <= MAX_PER_YEAR:
        return list(range(n))
    idx = sorted({round(i * (n - 1) / (MAX_PER_YEAR - 1)) for i in range(MAX_PER_YEAR)})
    return idx


def eval_query_strict(q_idx, recs, query_blocks, variant, blocks_mask=None):
    qT = recs[q_idx]["T"]
    earlier = [i for i, r in enumerate(recs) if r["T"] < qT]
    if len(earlier) < 30:
        return None
    earlier_recs = [recs[i] for i in earlier]
    block_sq = {}
    for blk in BLOCKS:
        feats = PRICE_STATE if blk == "price_state" else (TECHNICAL if blk == "technical" else None)
        if feats is not None:
            A = np.array([[r[f] if r[f] is not None else 0.0 for f in feats] for r in earlier_recs], dtype=float)
            q = np.array([recs[q_idx][f] if recs[q_idx][f] is not None else 0.0 for f in feats], dtype=float)
        else:
            A = np.array([r[blk] for r in earlier_recs], dtype=float)
            q = np.array(recs[q_idx][blk], dtype=float)
        if blk in ("price_shape", "vol_shape") and not (variant == "BAL"):
            # RAW keeps raw shape blocks
            block_sq[blk] = ((A - q) ** 2).sum(axis=1)
        else:
            mu = A.mean(axis=0)
            sd = A.std(axis=0)
            sd[sd == 0] = 1.0
            Az = (A - mu) / sd
            qz = (q - mu) / sd
            block_sq[blk] = ((Az - qz) ** 2).sum(axis=1)
    if blocks_mask is not None:
        d2 = sum(block_sq[b] for b in blocks_mask)
    elif variant == "RAW":
        d2 = sum(block_sq.values())
    else:
        d2 = np.zeros(len(earlier))
        for blk in BLOCKS:
            d2 += np.sqrt(np.maximum(block_sq[blk] / BLOCK_DIM[blk], 0))
    order = np.argsort(d2)[:150]
    top = [recs[earlier[i]] for i in order]
    labs = [first_passage_5d(r)[0] for r in top]
    s1_rate = sum(1 for x in labs if x == "S1_FIRST") / len(top)
    inv_rate = sum(1 for x in labs if x == "INVALID_FIRST") / len(top)
    meds = {}
    for k in (3, 5):
        mfes = [realized_mfe_mae(r, k)[0] for r in top]
        maes = [realized_mfe_mae(r, k)[1] for r in top]
        mfes = [x for x in mfes if x is not None]
        maes = [x for x in maes if x is not None]
        meds[f"mfe{k}"] = statistics.median(mfes) if mfes else None
        meds[f"mae{k}"] = statistics.median(maes) if maes else None
        meds[f"p25mfe{k}"] = np.percentile(mfes, 25) if mfes else None
        meds[f"p75mfe{k}"] = np.percentile(mfes, 75) if mfes else None
        meds[f"p10mae{k}"] = np.percentile(maes, 10) if maes else None
        meds[f"p90mae{k}"] = np.percentile(maes, 90) if maes else None
    return {
        "s1_rate": s1_rate,
        "inv_rate": inv_rate,
        **meds,
        "unique_anchors": len({r["anchor"] for r in top}),
        "unique_stocks": len({r["code"] for r in top}),
        "same_stock_share": sum(1 for r in top if r["code"] == recs[q_idx]["code"]) / len(top),
    }


def main():
    library, _, _ = build_library_and_candidates()
    lib = [r for r in library if r.get("fwd")]
    stages = sorted({r["stage"] for r in lib})
    results = {}
    for stage in stages:
        recs = [r for r in lib if r["stage"] == stage]
        per_year = defaultdict(list)
        for i, r in enumerate(recs):
            per_year[int(r["T"][:4])].append(i)
        q_indices = sorted({i for y in per_year.values() for i in sample_year(y)})
        queries = [recs[i] for i in q_indices]
        out = {"RAW": [], "BAL": []}
        masks = {
            "A": ["price_shape"],
            "B": ["price_shape", "price_state"],
            "C": ["price_shape", "price_state", "vol_shape"],
            "D": BLOCKS,
        }
        ablation = {name: [] for name in masks}
        abl_indices = q_indices[::3][:400]
        for qi in q_indices:
            qrec = recs[qi]
            lab5, _, _ = first_passage_5d(qrec)
            r5 = realized_mfe_mae(qrec, 5)
            r3 = realized_mfe_mae(qrec, 3)
            for variant in ("RAW", "BAL"):
                row = eval_query_strict(qi, recs, None, variant)
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
                out[variant].append(row)
        for qi in abl_indices:
            qrec = recs[qi]
            lab5, _, _ = first_passage_5d(qrec)
            r5 = realized_mfe_mae(qrec, 5)
            for name, m in masks.items():
                row = eval_query_strict(qi, recs, None, "RAW", blocks_mask=m)
                if row is not None:
                    row.update(
                        {
                            "realized_lab5": lab5,
                            "realized_mfe5": r5[0],
                            "realized_mae5": r5[1],
                            "query_T": qrec["T"],
                            "query_year": int(qrec["T"][:4]),
                        }
                    )
                    ablation[name].append(row)
        results[stage] = {"queries": len(q_indices), "RAW": out["RAW"], "BAL": out["BAL"], "ablation": ablation}
        print("stage", stage, "queries", len(q_indices), flush=True)

    summary = {}
    for stage, sd in results.items():
        summary[stage] = {}
        for variant in ("RAW", "BAL"):
            rows = [r for r in sd[variant] if r and r.get("realized_lab5") is not None]
            if not rows:
                continue
            summary[stage][variant] = {
                "n": len(rows),
                "brier_s1": round(statistics.fmean((r["s1_rate"] - (1 if r["realized_lab5"] == "S1_FIRST" else 0)) ** 2 for r in rows), 4),
                "brier_inv": round(statistics.fmean((r["inv_rate"] - (1 if r["realized_lab5"] == "INVALID_FIRST" else 0)) ** 2 for r in rows), 4),
                "mean_abs_err_mfe5": round(statistics.fmean(abs(r["mfe5"] - r["realized_mfe5"]) for r in rows), 4),
                "mean_abs_err_mae5": round(statistics.fmean(abs(r["mae5"] - r["realized_mae5"]) for r in rows), 4),
                "corridor_coverage_mfe_p25_75": round(statistics.fmean(1 if r["p25mfe5"] <= r["realized_mfe5"] <= r["p75mfe5"] else 0 for r in rows), 4),
                "corridor_coverage_mae_p10_90": round(statistics.fmean(1 if r["p10mae5"] <= r["realized_mae5"] <= r["p90mae5"] else 0 for r in rows), 4),
                "rank_corr_mfe5": round(rank_corr([r["mfe5"] for r in rows], [r["realized_mfe5"] for r in rows]), 3),
                "rank_corr_s1": round(rank_corr([r["s1_rate"] for r in rows], [1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in rows]), 3),
                "periods": {
                    p: {
                        "n": len(sub),
                        "brier_s1": round(statistics.fmean((r["s1_rate"] - (1 if r["realized_lab5"] == "S1_FIRST" else 0)) ** 2 for r in sub), 4),
                        "mean_abs_err_mfe5": round(statistics.fmean(abs(r["mfe5"] - r["realized_mfe5"]) for r in sub), 4),
                        "realized_s1_first_rate": round(statistics.fmean(1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in sub), 4),
                    }
                    for p, sub in (
                        ("DISCOVERY", [r for r in rows if r["query_T"] < "2025-07-01"]),
                        ("VALIDATION", [r for r in rows if r["query_T"] >= "2025-07-01"]),
                        ("2024", [r for r in rows if r["query_year"] == 2024]),
                        ("2025", [r for r in rows if r["query_year"] == 2025]),
                        ("2026", [r for r in rows if r["query_year"] == 2026]),
                    )
                },
                "unique_anchors_mean": round(statistics.fmean(r["unique_anchors"] for r in rows), 1),
                "unique_stocks_mean": round(statistics.fmean(r["unique_stocks"] for r in rows), 1),
                "same_stock_share_mean": round(statistics.fmean(r["same_stock_share"] for r in rows), 4),
            }
        abl = {}
        for name, rws in sd["ablation"].items():
            rows = [x for x in rws if x]
            abl[name] = {
                "n": len(rows),
                "neighbor_s1_rate_mean": round(statistics.fmean(r["s1_rate"] for r in rows), 4) if rows else None,
                "realized_s1_first_rate": round(statistics.fmean(1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in rows), 4) if rows else None,
                "mean_abs_err_mfe5": round(statistics.fmean(abs(r["mfe5"] - r["realized_mfe5"]) for r in rows), 4) if rows else None,
            }
        summary[stage]["ABLATION"] = abl

    out = {"RUN_ID": "ANALOG_V03A_STRICT_PIT", "summary": summary, "results": results}
    (OUT_DIR / "metrics_v03a.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    full = {"RUN_ID": out["RUN_ID"], "results": results}
    Path("data/tmp/analog-v03a-oos-calibration/queries.json").parent.mkdir(parents=True, exist_ok=True)
    Path("data/tmp/analog-v03a-oos-calibration/queries.json").write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
