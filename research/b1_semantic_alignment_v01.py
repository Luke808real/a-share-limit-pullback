"""B1 SEMANTIC ALIGNMENT + CURATED CASE CROSSCHECK v0.1 (research-only).

Checks whether production B1_READY corresponds to the human "B point":
  - curated case inventory (KB 02_Cases + overlay attention)
  - case -> production anchor / B1 / B2 date mapping
  - all-historical B1 days_since_anchor bucket audit
  - stable traits on curated cases + similar INVALID_FIRST controls

Inputs: corrected episodes 66d5943f..., snapshot b5f84004de8a.
Output: data/tmp/b1-semantic-alignment-v01/metrics.json
"""

from __future__ import annotations

import json
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
EPISODES_DIR = (
    DATA_ROOT
    / "outcome-study"
    / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome"
)
OUT_DIR = DATA_ROOT / "tmp" / "b1-semantic-alignment-v01"
SPLIT_DATE = date(2025, 7, 1)


CASES = [
    {
        "code": "002640",
        "name": "跨境通",
        "role": "PRE_B_OBSERVATION",
        "ref_date": "2026-07-27",
        "human_first_attack": "2026-07-27 强K（+9.97%，收盘最高）",
        "human_washout": "前期低点 2.72（人工参考，非冻结 support）",
        "human_b_point": "未定义（观察日即启动日）",
        "source": "KB Success/002640-2026-07-27",
    },
    {
        "code": "002891",
        "name": "中宠股份",
        "role": "POST_B_REPAIR_OBSERVATION",
        "ref_date": "2026-07-28",
        "human_first_attack": "此前上涨（未记录日期）",
        "human_washout": "回踩 MA20/30",
        "human_b_point": "2026-07-28 回踩后快速修复日（非涨停）",
        "source": "KB Success/002891-2026-07-28",
    },
    {
        "code": "600199",
        "name": "金种子酒",
        "role": "POST_B_SUCCESS_CASE",
        "ref_date": "2026-07-28",
        "human_first_attack": "第一轮上涨（未记录日期）",
        "human_washout": "回踩 MA20/30",
        "human_b_point": "2026-07-28 涨停再启动日（B 点后）",
        "source": "KB Success/600199-2026-07-28",
    },
    {
        "code": "600756",
        "name": "浪潮软件",
        "role": "B2_CASE_POST_B_OBSERVATION",
        "ref_date": "2026-07-31",
        "human_first_attack": "2026-07-08 低位涨停",
        "human_washout": "7/9-7/24 平台（PROVISIONAL 数据，生产不可见）",
        "human_b_point": "2026-07-27 前后（B 点后已走出一段）",
        "source": "overlay v0.2 OBSERVE_NOW + 5-stock review",
    },
    {
        "code": "603980",
        "name": "吉华集团",
        "role": "B2_CASE_SECOND_LAUNCH_CANDIDATE",
        "ref_date": "2026-07-31",
        "human_first_attack": "2026-06-22/23 非涨停放量攻击（+8.7%/+5.5%）",
        "human_washout": "6/24-7/8 洗盘平台（-9.6%）",
        "human_b_point": "2026-07-28 涨停二次发动后的 B 区（7/28-7/30）",
        "source": "overlay v0.2 OBSERVE_NOW + 5-stock review",
    },
]


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df_all = pd.read_parquet(EPISODES_DIR / "episodes.parquet")
    df_b1 = load_episodes()
    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)

    # per-code production dates (anchor / B1 / B2) from full episodes
    date_map = {}
    for code in {c["code"] for c in CASES}:
        sub = df_all[df_all["code"] == code]
        anchors = sorted(
            {str(d)[:10] for d in sub["anchor_date"].dropna().unique()}
        )
        b1 = sorted(
            str(d)[:10]
            for d in sub.loc[sub["execution_label"] == "B1_READY", "signal_date"].dropna().unique()
        )
        b2 = sorted(
            str(d)[:10]
            for d in sub.loc[
                sub["execution_label"].isin(("B2_READY", "B2_CONFIRMED")),
                "signal_date",
            ]
            .dropna()
            .unique()
        )
        b1_status = {
            str(r["signal_date"])[:10]: str(r["fill_status"])
            for _, r in sub[sub["execution_label"] == "B1_READY"].iterrows()
        }
        date_map[code] = {
            "anchors": anchors,
            "b1_dates": b1,
            "b1_fill_status": b1_status,
            "b2_dates": b2,
        }

    # all-historical B1 features (actionable filled)
    by_code: dict[str, list] = defaultdict(list)
    for _, row in df_b1.iterrows():
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
            if f["first_hit"] in ("S1_FIRST", "INVALID_FIRST") and f["exec_status"] == "RESOLVED":
                f["label"] = "WINNER" if f["first_hit"] == "S1_FIRST" else "LOSER"
            else:
                f["label"] = f["first_hit"]
            rows.append(f)

    main = [r for r in rows if r["label"] in ("WINNER", "LOSER")]

    def bucket(days):
        if days is None:
            return None
        if days <= 3:
            return f"day{days}"
        if days <= 5:
            return "day4-5"
        return "day6+"

    buckets = {}
    for b in ("day1", "day2", "day3", "day4-5", "day6+"):
        sub = [r for r in main if bucket(r.get("days_since_anchor")) == b]
        buckets[b] = {
            "n": len(sub),
            "s1_first_rate": round(
                sum(1 for r in sub if r["label"] == "WINNER") / len(sub), 4
            ) if sub else None,
            "invalid_first_rate": round(
                sum(1 for r in sub if r["label"] == "LOSER") / len(sub), 4
            ) if sub else None,
            "mean_R": round(
                statistics.fmean(
                    [r["canonical_R_10bp"] for r in sub if r["canonical_R_10bp"] is not None]
                ),
                4,
            ) if sub else None,
            "n_resolved": len(sub),
        }
    buckets["ALL"] = {
        "n": len(main),
        "s1_first_rate": round(sum(1 for r in main if r["label"] == "WINNER") / len(main), 4),
        "invalid_first_rate": round(sum(1 for r in main if r["label"] == "LOSER") / len(main), 4),
        "mean_R": round(
            statistics.fmean([r["canonical_R_10bp"] for r in main if r["canonical_R_10bp"] is not None]),
            4,
        ),
    }

    # stable traits on curated cases + similar INVALID_FIRST controls
    case_map = []
    for case in CASES:
        code = case["code"]
        ref = date.fromisoformat(case["ref_date"])
        b1s = [
            r
            for r in rows
            if r["code"] == code
            and abs((date.fromisoformat(r["signal_date"]) - ref).days) <= 30
        ]
        hist_b1 = [r for r in rows if r["code"] == code and r["label"] in ("WINNER", "LOSER")]
        entry = {
            "code": code,
            "name": case["name"],
            "role": case["role"],
            "human_first_attack": case["human_first_attack"],
            "human_washout": case["human_washout"],
            "human_b_point": case["human_b_point"],
            "production": date_map.get(code, {}),
            "b1_in_window": [
                {
                    "signal_date": r["signal_date"],
                    "label": r["label"],
                    "days_since_anchor": r.get("days_since_anchor"),
                    "R_10bp": r["canonical_R_10bp"],
                    "stable_traits": {
                        "reclaim_ma5": r.get("reclaim_ma5"),
                        "entry_anchor_close_pct": r.get("entry_anchor_close_pct"),
                        "entry_high20_pct": r.get("entry_high20_pct"),
                        "close_ma5_pct": r.get("close_ma5_pct"),
                    },
                }
                for r in b1s
            ],
            "historical_resolved_b1": [
                {
                    "signal_date": r["signal_date"],
                    "label": r["label"],
                    "R_10bp": r["canonical_R_10bp"],
                }
                for r in hist_b1
            ],
        }
        case_map.append(entry)

    # similar-looking INVALID_FIRST controls (structure: <=3 days, reclaim MA5, near anchor close)
    controls = [
        r
        for r in main
        if r["label"] == "LOSER"
        and r.get("days_since_anchor") is not None
        and r["days_since_anchor"] <= 3
        and r.get("reclaim_ma5")
        and r.get("entry_anchor_close_pct") is not None
        and -5.0 <= r["entry_anchor_close_pct"] <= 2.0
    ]
    controls = sorted(
        controls,
        key=lambda r: abs(r.get("entry_anchor_close_pct", 0) + 1.5)
        + abs(r.get("entry_high20_pct", -8) + 8.5) / 3,
    )[:10]
    control_rows = [
        {
            "code": r["code"],
            "signal_date": r["signal_date"],
            "R_10bp": r["canonical_R_10bp"],
            "days_since_anchor": r.get("days_since_anchor"),
            "entry_anchor_close_pct": r.get("entry_anchor_close_pct"),
            "close_ma5_pct": r.get("close_ma5_pct"),
            "entry_high20_pct": r.get("entry_high20_pct"),
            "ma20_up": r.get("ma20_up"),
            "pre_attack_present": r.get("pre_attack_present"),
            "big_vol_down_days": r.get("big_vol_down_days"),
            "time_to_invalid": r.get("time_to_invalid"),
        }
        for r in controls
    ]

    metrics = {
        "title": "B1 SEMANTIC ALIGNMENT + CURATED CASE CROSSCHECK v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "DESCRIPTIVE_OBSERVE_ONLY",
        "CASE_MAPPING": case_map,
        "DAYS_BUCKETS": buckets,
        "MATCHED_FAILURE_CONTROLS": control_rows,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
