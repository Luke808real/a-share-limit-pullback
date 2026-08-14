"""ARCH3 ROBUSTNESS + FAILURE DECOMPOSITION v0.1 (research-only).

Frozen ARCH3 = DEEP_WASHOUT_RECLAIM:
    first-attack high drawdown >= 8% AND reclaim MA5 before entry.

Checks: four-cell increment, tail decomposition, execution robustness,
temporal stability + cluster bootstrap, ARCH3 failure profile.

Inputs: corrected episodes 66d5943f..., snapshot b5f84004de8a.
Output: data/tmp/arch3-robustness-v01/metrics.json
"""

from __future__ import annotations

import json
import random
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
OUT_DIR = DATA_ROOT / "tmp" / "arch3-robustness-v01"
SPLIT_DATE = __import__("datetime").date(2025, 7, 1)
WASHOUT_DEPTH = -8.0  # frozen ARCH3 boundary


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
        "p25": round(_pct(vals, 0.25), 4),
        "p75": round(_pct(vals, 0.75), 4),
        "p90": round(_pct(vals, 0.90), 4),
    }


def cluster_bootstrap(rows, rkey, n_iter=2000, seed=7):
    clusters = defaultdict(list)
    for r in rows:
        clusters[(r["code"], r.get("anchor_date"))].append(r)
    keys = list(clusters)
    rng = random.Random(seed)
    means = []
    for _ in range(n_iter):
        sample = []
        for _ in range(len(keys)):
            sample.extend(clusters[rng.choice(keys)])
        vals = [r[rkey] for r in sample if r.get(rkey) is not None]
        if vals:
            means.append(statistics.fmean(vals))
    means.sort()
    return {
        "n_clusters": len(keys),
        "lo": round(means[int(0.025 * len(means))], 4),
        "hi": round(means[int(0.975 * len(means))], 4),
        "median": round(statistics.median(means), 4),
    }


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
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
            for col in (
                "net_execution_R_0bp",
                "net_execution_R_10bp",
                "net_execution_R_20bp",
                "net_execution_R_30bp",
                "conservative_net_execution_R_0bp",
                "conservative_net_execution_R_10bp",
                "conservative_net_execution_R_20bp",
                "conservative_net_execution_R_30bp",
            ):
                f[col] = (
                    float(row[col])
                    if pd.notna(row[col])
                    else None
                )
            f["exit_type"] = row["conservative_execution_exit_type"]
            f["exec_status"] = row["conservative_execution_status"]
            f["deep_washout"] = bool(
                f.get("attack_high_dd_pct") is not None
                and f["attack_high_dd_pct"] <= WASHOUT_DEPTH
            )
            f["reclaim_ma5"] = bool(f.get("reclaim_ma5"))
            f["is_arch3"] = bool(f["deep_washout"] and f["reclaim_ma5"])
            if f["first_hit"] in ("S1_FIRST", "INVALID_FIRST") and f["exec_status"] == "RESOLVED":
                f["label"] = "WINNER" if f["first_hit"] == "S1_FIRST" else "LOSER"
            else:
                f["label"] = f["first_hit"]
            rows.append(f)

    main = [r for r in rows if r["label"] in ("WINNER", "LOSER")]
    RKEY = "conservative_net_execution_R_10bp"

    # 1. four-cell comparison
    cells = {}
    for dw in (0, 1):
        for rm in (0, 1):
            sub = [r for r in main if r["deep_washout"] == bool(dw) and r["reclaim_ma5"] == bool(rm)]
            vals = [r[RKEY] for r in sub if r[RKEY] is not None]
            cells[f"dw{dw}_rm{rm}"] = {
                "n": len(sub),
                "n_resolved": len(vals),
                **stats(vals),
                "s1_first_rate": round(sum(1 for r in sub if r["label"] == "WINNER") / len(sub), 4) if sub else None,
                "invalid_first_rate": round(sum(1 for r in sub if r["label"] == "LOSER") / len(sub), 4) if sub else None,
            }

    arch3 = [r for r in main if r["is_arch3"]]
    baseline = main

    # 2. ARCH3 tail decomposition (conservative 10bp)
    vals = [r[RKEY] for r in arch3 if r[RKEY] is not None]
    total = sum(vals)
    neg = sorted(v for v in vals if v < 0)
    pos = sorted((v for v in vals if v > 0), reverse=True)
    total_neg = sum(neg)
    total_pos = sum(pos)

    def worst_share(fraction):
        k = max(1, int(len(neg) * fraction))
        return round(sum(neg[:k]) / total_neg * 100, 1) if total_neg else None

    def top_win_share(fraction):
        k = max(1, int(len(pos) * fraction))
        return round(sum(pos[:k]) / total_pos * 100, 1) if total_pos else None

    exit_decomp = {}
    for r in arch3:
        key = str(r["exit_type"])
        exit_decomp.setdefault(key, []).append(r[RKEY] if r[RKEY] is not None else 0)
    exit_summary = {
        k: {
            "n": len(v),
            "mean_R": round(statistics.fmean(v), 4),
            "sum_R": round(sum(v), 4),
        }
        for k, v in sorted(exit_decomp.items())
    }
    status_counts = defaultdict(int)
    for r in arch3:
        status_counts[str(r["exec_status"])] += 1
    tail = {
        "total_R": round(total, 4),
        "total_neg": round(total_neg, 4),
        "total_pos": round(total_pos, 4),
        "worst1_pct_share_of_neg": worst_share(0.01),
        "worst5_pct_share_of_neg": worst_share(0.05),
        "worst10_pct_share_of_neg": worst_share(0.10),
        "top1_pct_share_of_pos": top_win_share(0.01),
        "top5_pct_share_of_pos": top_win_share(0.05),
        "top10_pct_share_of_pos": top_win_share(0.10),
        "exit_type_summary": exit_summary,
        "status_counts": dict(status_counts),
        "n_negative": len(neg),
        "n_positive": len(pos),
    }

    # 3. execution robustness
    exec_rob = {}
    for variant in ("strict", "conservative"):
        for bp in (0, 10, 20, 30):
            key = f"{variant}_{bp}bp"
            col = f"{variant}_net_execution_R_{bp}bp" if variant == "conservative" else f"net_execution_R_{bp}bp"
            vals = [r[col] for r in arch3 if r.get(col) is not None]
            exec_rob[key] = stats(vals)

    # 4. temporal stability + cluster bootstrap
    temporal = {}
    arch3_v = [r[RKEY] for r in arch3 if r[RKEY] is not None]
    base_v = [r[RKEY] for r in baseline if r[RKEY] is not None]
    temporal["ALL"] = {
        "ARCH3": stats(arch3_v),
        "BASELINE": stats(base_v),
    }
    for period in ("DISCOVERY", "VALIDATION"):
        temporal[period] = {
            "ARCH3": stats([r[RKEY] for r in arch3 if r["period"] == period and r[RKEY] is not None]),
            "BASELINE": stats([r[RKEY] for r in baseline if r["period"] == period and r[RKEY] is not None]),
        }
    for year in (2024, 2025, 2026):
        temporal[str(year)] = {
            "ARCH3": stats([r[RKEY] for r in arch3 if r.get("fill_year") == year and r[RKEY] is not None]),
            "BASELINE": stats([r[RKEY] for r in baseline if r.get("fill_year") == year and r[RKEY] is not None]),
        }
    boot = {
        "ARCH3_mean_R_CI": cluster_bootstrap(arch3, RKEY),
        "BASELINE_mean_R_CI": cluster_bootstrap(baseline, RKEY),
    }
    # paired-cluster bootstrap of the difference
    clusters_a = defaultdict(list)
    clusters_b = defaultdict(list)
    for r in arch3:
        clusters_a[(r["code"], r.get("anchor_date"))].append(r)
    for r in baseline:
        clusters_b[(r["code"], r.get("anchor_date"))].append(r)
    keys = list(clusters_a)
    rng = random.Random(11)
    diffs = []
    for _ in range(2000):
        ma, mb = [], []
        for _ in range(len(keys)):
            k = rng.choice(keys)
            ma.extend(clusters_a[k])
            for bk, bv in clusters_b.items():
                if bk[0] == k[0]:
                    mb.extend(bv)
                    break
        va = [r[RKEY] for r in ma if r.get(RKEY) is not None]
        vb = [r[RKEY] for r in mb if r.get(RKEY) is not None]
        if va and vb:
            diffs.append(statistics.fmean(va) - statistics.fmean(vb))
    diffs.sort()
    boot["ARCH3_minus_BASELINE_CI"] = {
        "lo": round(diffs[int(0.025 * len(diffs))], 4),
        "hi": round(diffs[int(0.975 * len(diffs))], 4),
        "median": round(statistics.median(diffs), 4),
    }

    # 5. ARCH3 failure profile (S1_FIRST vs INVALID_FIRST within ARCH3)
    w = [r for r in arch3 if r["label"] == "WINNER"]
    l = [r for r in arch3 if r["label"] == "LOSER"]

    def desc(field, fun=stats):
        return {
            "WINNER": fun([r[field] for r in w if r.get(field) is not None]),
            "LOSER": fun([r[field] for r in l if r.get(field) is not None]),
        }

    profile = {
        "n_winner": len(w),
        "n_loser": len(l),
        "gap_stop_frequency": {
            "WINNER": round(
                sum(1 for r in w if str(r.get("exit_type")) == "GAP_STOP") / len(w), 4
            ) if w else None,
            "LOSER": round(
                sum(1 for r in l if str(r.get("exit_type")) == "GAP_STOP") / len(l), 4
            ) if l else None,
        },
        "entry_day": desc("time_to_invalid"),
        "days_since_anchor": desc("days_since_anchor"),
        "reclaim_ma5": {
            "WINNER": round(sum(1 for r in w if r["reclaim_ma5"]) / len(w), 4) if w else None,
            "LOSER": round(sum(1 for r in l if r["reclaim_ma5"]) / len(l), 4) if l else None,
        },
        "distance_anchor_pct": desc("entry_anchor_close_pct"),
        "distance_high20_pct": desc("entry_high20_pct"),
        "washout_depth_pct": desc("attack_high_dd_pct"),
        "pre_attack_present": {
            "WINNER": round(sum(1 for r in w if r.get("pre_attack_present")) / len(w), 4) if w else None,
            "LOSER": round(sum(1 for r in l if r.get("pre_attack_present")) / len(l), 4) if l else None,
        },
    }

    metrics = {
        "title": "ARCH3 ROBUSTNESS + FAILURE DECOMPOSITION v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "arch3_frozen_definition": {
            "deep_washout": "first-attack high drawdown <= -8%",
            "reclaim_ma5": "close >= MA5 before entry",
        },
        "conclusion_status": "HYPOTHESIS_ONLY",
        "FOUR_CELL_COMPARISON": cells,
        "TAIL_DECOMPOSITION": tail,
        "EXECUTION_ROBUSTNESS": exec_rob,
        "TEMPORAL_STABILITY": temporal,
        "BOOTSTRAP": boot,
        "ARCH3_FAILURE_PROFILE": profile,
        "n_arch3_total": len(arch3),
        "n_arch3_resolved": len([r for r in arch3 if r[RKEY] is not None]),
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
