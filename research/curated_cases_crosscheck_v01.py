"""CURATED SUCCESS CASES x HISTORICAL B1 CROSSCHECK v0.1 (research-only).

Maps KB/overlay curated cases to corrected B1 episodes and checks them against
the stable winner traits from ENTRY SELECTION ATTRIBUTION v0.1.

Inputs:
  - corrected episodes SHA 66d5943f... (B1 actionable filled)
  - snapshot snap-2026-07-31-b5f84004de8a
  - entry-attribution stable features (recomputed per episode here)
Output: data/tmp/curated-cases-crosscheck-v01/metrics.json
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
from research.entry_attribution_v01 import compute_episode_features, load_episodes


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
OUT_DIR = DATA_ROOT / "tmp" / "curated-cases-crosscheck-v01"
SPLIT_DATE = date(2025, 7, 1)


CASES = [
    {
        "code": "002640",
        "name": "跨境通",
        "role": "PRE_B_OBSERVATION",
        "ref_date": "2026-07-27",
        "source": "KB 02_Cases/Success/002640-2026-07-27.md",
        "summary": "低位筑底+均线簇收复+收盘最高；人工正向样本，非 entry ground truth",
    },
    {
        "code": "002891",
        "name": "中宠股份",
        "role": "POST_B_/REPAIR_OBSERVATION",
        "ref_date": "2026-07-28",
        "source": "KB 02_Cases/Success/002891-2026-07-28.md",
        "summary": "回踩MA20/30后快速修复、站回MA5/10、收盘近高；非涨停锚点",
    },
    {
        "code": "600199",
        "name": "金种子酒",
        "role": "POST_B_SUCCESS_CASE",
        "ref_date": "2026-07-28",
        "source": "KB 02_Cases/Success/600199-2026-07-28.md",
        "summary": "第一轮上涨→回踩MA20/30→涨停再启动；人工成功观察，不代表策略收益",
    },
    {
        "code": "600756",
        "name": "浪潮软件",
        "role": "B2_CASE_/POST_B_OBSERVATION",
        "ref_date": "2026-07-31",
        "source": "overlay v0.2 human_attention OBSERVE_NOW + 5-stock review",
        "summary": "B2 trigger watch，MIXED context，support SOFT；7/28 二板后已走出一段、偏 extended",
    },
    {
        "code": "603980",
        "name": "吉华集团",
        "role": "B2_CASE_/SECOND_LAUNCH_CANDIDATE",
        "ref_date": "2026-07-31",
        "source": "overlay v0.2 human_attention OBSERVE_NOW + 5-stock review",
        "summary": "第一次表态(6/22-23非涨停攻击)→洗盘平台→7/28涨停二次发动候选；FAVORABLE",
    },
    {
        "code": "600468",
        "name": "百利电气",
        "role": "POST_B_SECOND_LAUNCH_SUCCESS",
        "ref_date": "2026-08-03",
        "source": "human observation appended 2026-08-03 (KB 02_Cases/Success/600468-2026-08-03)",
        "summary": (
            "STRUCTURE_SUCCESS/SECOND_LAUNCH_SUCCESS: 7/23 first limit-up (~5.54), "
            "pullback without breaking base, short MA repair, 8/3 limit-up 6.22 "
            "breaking prior high ~6.18; TIME_TO_SECOND_LAUNCH≈7 trading days; "
            "human B area 5.40-5.70 post-hoc only; sector=电网设备/输变电 + "
            "超导/可控核聚变 theme but NOT an earnings case; FORWARD observation "
            "beyond frozen episodes cutoff (7/31), not mapable to corrected "
            "episodes; RESEARCH_STATUS=PAUSED, no rerun."
        ),
    },
]


def stable_trait_check(f):
    return {
        "reclaim_ma5": bool(f.get("reclaim_ma5")),
        "shallow_vs_anchor_close": (
            f.get("entry_anchor_close_pct") is not None
            and f["entry_anchor_close_pct"] >= -3.0
        ),
        "near_20d_high": (
            f.get("entry_high20_pct") is not None
            and f["entry_high20_pct"] >= -10.0
        ),
        "above_ma5": f.get("close_ma5_pct") is not None and f["close_ma5_pct"] >= 0,
        "shallow_pullback": (
            f.get("pullback_max_dd_pct") is not None
            and f["pullback_max_dd_pct"] >= -5.0
        ),
    }


def arch_membership(f):
    out = {}
    out["ARCH1_SHALLOW_RECLAIM"] = bool(
        f.get("days_since_anchor") is not None
        and f["days_since_anchor"] <= 3
        and f.get("reclaim_ma5")
        and f.get("entry_anchor_close_pct") is not None
        and -3.0 <= f["entry_anchor_close_pct"] <= 2.0
    )
    out["ARCH2_NEAR_HIGH_RELAUNCH"] = bool(
        f.get("entry_high20_pct") is not None
        and f["entry_high20_pct"] >= -10.0
        and f.get("reclaim_ma5")
        and f.get("close_ma5_pct") is not None
        and f["close_ma5_pct"] >= 0
    )
    out["ARCH3_DEEP_WASHOUT_RECLAIM"] = bool(
        f.get("attack_high_dd_pct") is not None
        and f["attack_high_dd_pct"] <= -8.0
        and f.get("reclaim_ma5")
    )
    return out


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_episodes()
    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, row in df.iterrows():
        by_code[row["code"]].append(row)

    all_rows = []
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
            if f["first_hit"] in ("S1_FIRST", "INVALID_FIRST") and f["exec_status"] == "RESOLVED":
                f["label"] = "WINNER" if f["first_hit"] == "S1_FIRST" else "LOSER"
            else:
                f["label"] = f["first_hit"]
            f["stable_traits"] = stable_trait_check(f)
            f["archetypes"] = arch_membership(f)
            all_rows.append(f)

    # 1. case -> episode mapping
    case_map = []
    for case in CASES:
        code = case["code"]
        ref = date.fromisoformat(case["ref_date"])
        eps = [
            r
            for r in all_rows
            if r["code"] == code
            and abs((date.fromisoformat(r["signal_date"]) - ref).days) <= 30
        ]
        b1 = [r for r in eps if r["label"] in ("WINNER", "LOSER", "SAME_DAY", "NONE_10D")]
        entry = {
            "case_role": case["role"],
            "n_episodes_in_window": len(eps),
            "b1_resolved": len([r for r in b1 if r["label"] in ("WINNER", "LOSER")]),
            "labels": sorted({r["label"] for r in eps}),
            "data_complete": bool(b1),
            "episodes": [
                {
                    "signal_date": r["signal_date"],
                    "label": r["label"],
                    "R_10bp": r["canonical_R_10bp"],
                    "entry": r["fill_price"],
                    "invalid": r["invalid"],
                    "s1": r["s1"],
                    "stable_traits": r["stable_traits"],
                    "archetypes": r["archetypes"],
                }
                for r in eps
            ],
        }
        case_map.append({"code": code, "name": case["name"], **entry})

    # 2. stable trait crosscheck on the mapped B1 episode (nearest to ref date)
    cross = []
    for case, cm in zip(CASES, case_map):
        b1s = [r for r in all_rows if r["code"] == case["code"] and r["label"] in ("WINNER", "LOSER")]
        if not b1s:
            cross.append({"code": case["code"], "mapped": False})
            continue
        ref = date.fromisoformat(case["ref_date"])
        best = min(b1s, key=lambda r: abs((date.fromisoformat(r["signal_date"]) - ref).days))
        st = best["stable_traits"]
        cross.append(
            {
                "code": case["code"],
                "mapped": True,
                "signal_date": best["signal_date"],
                "label": best["label"],
                "R_10bp": best["canonical_R_10bp"],
                "stable_traits_present": [k for k, v in st.items() if v],
                "stable_traits_absent": [k for k, v in st.items() if not v],
                "atypical": {
                    "pre_attack_present": best.get("pre_attack_present"),
                    "ma20_up": best.get("ma20_up"),
                    "big_vol_down_days": best.get("big_vol_down_days"),
                    "vol_post_anchor_ratio": best.get("vol_post_anchor_ratio"),
                },
            }
        )

    # 3. matched failure control: INVALID_FIRST similar to curated B1 cases
    winners = [r for r in all_rows if r["label"] == "WINNER"]
    losers = [r for r in all_rows if r["label"] == "LOSER"]
    similar_losers = [
        r
        for r in losers
        if r.get("days_since_anchor") is not None
        and r["days_since_anchor"] <= 3
        and r.get("reclaim_ma5")
        and r.get("entry_anchor_close_pct") is not None
        and r["entry_anchor_close_pct"] >= -5.0
    ]
    # feature vector for distance (normalized by winner/loser pooled std)
    keys = ["entry_anchor_close_pct", "entry_high20_pct", "close_ma5_pct", "pullback_max_dd_pct"]
    pool = {
        k: statistics.pstdev(
            [r[k] for r in winners + losers if r.get(k) is not None]
        )
        or 1
        for k in keys
    }
    med = {
        k: statistics.median([r[k] for r in winners if r.get(k) is not None])
        for k in keys
    }

    def dist(r):
        return sum(
            (((r.get(k) if r.get(k) is not None else med[k]) - med[k]) / pool[k]) ** 2
            for k in keys
        )

    matched = sorted(similar_losers, key=dist)[:8]
    failure_cases = [
        {
            "code": r["code"],
            "signal_date": r["signal_date"],
            "R_10bp": r["canonical_R_10bp"],
            "time_to_invalid": r.get("time_to_invalid"),
            "time_to_s1": r.get("time_to_s1"),
            "why_looks_similar": {
                "days_since_anchor": r.get("days_since_anchor"),
                "reclaim_ma5": r.get("reclaim_ma5"),
                "entry_anchor_close_pct": r.get("entry_anchor_close_pct"),
                "close_ma5_pct": r.get("close_ma5_pct"),
            },
            "why_failed": {
                "ma20_up": r.get("ma20_up"),
                "big_vol_down_days": r.get("big_vol_down_days"),
                "vol_post_anchor_ratio": r.get("vol_post_anchor_ratio"),
                "pre_attack_present": r.get("pre_attack_present"),
                "entry_high20_pct": r.get("entry_high20_pct"),
                "washout_min_vol_ratio": r.get("washout_min_vol_ratio"),
            },
        }
        for r in matched
    ]

    # 4. archetype coverage
    coverage = {}
    for arch in ("ARCH1_SHALLOW_RECLAIM", "ARCH2_NEAR_HIGH_RELAUNCH", "ARCH3_DEEP_WASHOUT_RECLAIM"):
        sub = [r for r in all_rows if r["label"] in ("WINNER", "LOSER") and r["archetypes"].get(arch)]
        row = {
            "n": len(sub),
            "winner_rate": round(sum(1 for r in sub if r["label"] == "WINNER") / len(sub), 4) if sub else None,
            "invalid_first_rate": round(sum(1 for r in sub if r["label"] == "LOSER") / len(sub), 4) if sub else None,
            "mean_R": round(
                statistics.fmean([r["canonical_R_10bp"] for r in sub if r["canonical_R_10bp"] is not None]), 4
            ) if sub else None,
        }
        for period in ("DISCOVERY", "VALIDATION"):
            sp = [r for r in sub if r["period"] == period]
            row[period] = {
                "n": len(sp),
                "winner_rate": round(sum(1 for r in sp if r["label"] == "WINNER") / len(sp), 4) if sp else None,
                "mean_R": round(
                    statistics.fmean([r["canonical_R_10bp"] for r in sp if r["canonical_R_10bp"] is not None]), 4
                ) if sp else None,
            }
        coverage[arch] = row
    coverage["BASELINE"] = {
        "n": len(winners) + len(losers),
        "winner_rate": round(len(winners) / (len(winners) + len(losers)), 4),
        "invalid_first_rate": round(len(losers) / (len(winners) + len(losers)), 4),
        "mean_R": round(
            statistics.fmean(
                [r["canonical_R_10bp"] for r in winners + losers if r["canonical_R_10bp"] is not None]
            ),
            4,
        ),
    }

    # 5. current 5 archetype mapping (recompute full features)
    current5_spec = [
        {"code": "603980", "anchor": "2026-07-28", "asof": "2026-07-31", "entry": 6.73, "invalid": 6.23, "s1": 7.02},
        {"code": "600756", "anchor": "2026-07-28", "asof": "2026-07-31", "entry": 16.52, "invalid": 15.66, "s1": 16.99},
        {"code": "603232", "anchor": "2026-07-28", "asof": "2026-07-31", "entry": 15.50, "invalid": 13.79, "s1": 16.68},
        {"code": "601858", "anchor": "2026-07-29", "asof": "2026-07-31", "entry": 20.61, "invalid": 18.71, "s1": 21.72},
        {"code": "603185", "anchor": "2026-07-30", "asof": "2026-07-31", "entry": 16.08, "invalid": 15.29, "s1": 17.05},
    ]
    current5 = []
    for item in current5_spec:
        anchor = date.fromisoformat(item["anchor"])
        asof = date.fromisoformat(item["asof"])
        for code, bars in iter_canonical_code_bars(layout, snapshot, codes=[item["code"]]):
            idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
            a, s = idx_by_date.get(anchor), idx_by_date.get(asof)
            if a is None or s is None:
                continue
            fake = pd.Series(
                {
                    "anchor_date": anchor,
                    "signal_date": asof,
                    "fill_date": asof,
                    "fill_price": item["entry"],
                    "invalid_price": item["invalid"],
                    "s1_price": item["s1"],
                    "support_center": None,
                    "anchor_price": None,
                    "code": code,
                    "setup_id": code,
                }
            )
            f = compute_episode_features(fake, bars, idx_by_date)
            if f:
                current5.append(
                    {
                        "code": code,
                        "archetypes": arch_membership(f),
                        "features": {
                            "days_since_anchor": f.get("days_since_anchor"),
                            "reclaim_ma5": f.get("reclaim_ma5"),
                            "entry_anchor_close_pct": f.get("entry_anchor_close_pct"),
                            "entry_high20_pct": f.get("entry_high20_pct"),
                            "close_ma5_pct": f.get("close_ma5_pct"),
                            "attack_high_dd_pct": f.get("attack_high_dd_pct"),
                        },
                    }
                )

    metrics = {
        "title": "CURATED SUCCESS CASES x HISTORICAL B1 CROSSCHECK v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "DESCRIPTIVE_OBSERVE_ONLY",
        "baseline": {"winner": len(winners), "loser": len(losers)},
        "CASE_TO_EPISODE_MAPPING": case_map,
        "STABLE_TRAIT_CROSSCHECK": cross,
        "MATCHED_FAILURE_CASES": failure_cases,
        "ARCHETYPE_COVERAGE": coverage,
        "CURRENT_5_ARCHETYPES": current5,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
