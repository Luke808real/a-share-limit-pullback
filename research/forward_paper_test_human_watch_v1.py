"""FORWARD PAPER TEST — HUMAN_WATCH_V1 (8/4, research-only).

Frozen V1 (from gate-sensitivity study):
  pool  = existing production plan universe (frozen watch) + B2_READY
          non-candidates with valid invalid/S1 levels
  rank  = locked G geometry (close_vs_s1 + dist_20d_high), discovery params
  entry_q / RR / ROOM / Q = explanatory only
  DATA_LIMITED / PROVISIONAL / unmapped -> MANUAL_REVIEW (<=5), not ranked

8/3 close data: PUBLIC_FALLBACK EOD. No refit, no threshold change.
Output: data/forward-paper/human-watch-v1/2026-08-04/*
"""

from __future__ import annotations

import json
import statistics
from datetime import date
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
DECISION_SHEET = DATA_ROOT / "forward-paper" / "2026-08-03-final-human-watch" / "decision_sheet.json"
FULL_CANDIDATES = DATA_ROOT / "forward-paper" / "manual-first-plan" / "full_candidates.parquet"
STATE_METRICS = DATA_ROOT / "tmp" / "b-actionable-state-v01" / "metrics.json"
EOD_PARQUET = DATA_ROOT / "tmp" / "eod-recovery-2026-08-03" / "eod_20260803.parquet"
OUT_DIR = DATA_ROOT / "forward-paper" / "human-watch-v1" / "2026-08-04"
ASOF = date(2026, 7, 31)
EOD = date(2026, 8, 3)
DATA_LIMITED_CODES = {"600756"}
NAME_OVERRIDES = {"603818": "曲美家居"}


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sheet = json.loads(DECISION_SHEET.read_text(encoding="utf-8"))
    params = json.loads(STATE_METRICS.read_text(encoding="utf-8"))["FIT_PARAMS"]["G"]
    eod = pd.read_parquet(EOD_PARQUET)
    eod["trade_date"] = pd.to_datetime(eod["trade_date"]).dt.date
    eod = eod[eod["trade_date"] == EOD]
    eod_by = {str(r["code"]): r for _, r in eod.iterrows()}
    fc = pd.read_parquet(FULL_CANDIDATES)
    fc_by = {str(r["code"]): r for _, r in fc.iterrows()}

    # extended pool: B2_READY non-candidates with levels (7/28-31)
    ep = pd.read_parquet(EPISODES_DIR / "episodes.parquet")
    ext = ep[
        (ep["execution_label"] == "B2_READY")
        & (ep["is_entry_candidate"] == False)  # noqa: E712
        & (ep["invalid_price"].notna())
        & (ep["s1_price"].notna())
        & (ep["signal_date"].astype(str).str[:10] >= "2026-07-28")
        & (ep["signal_date"].astype(str).str[:10] <= "2026-07-31")
    ].copy()

    layout = WarehouseLayout(DATA_ROOT)
    snap, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    codes = sorted({str(r["code"]) for r in sheet} | {str(r["code"]) for _, r in ext.iterrows()})
    history = {}
    for code, bars in iter_canonical_code_bars(layout, snap, codes=codes, as_of=ASOF):
        closes = [float(b.close) for b in bars]
        highs = [float(b.high) for b in bars]
        history[str(code)] = {"ma5": statistics.fmean(closes[-5:]), "high20": max(highs[-20:])}

    def fnum(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    rows = []
    for item in sheet:
        code = str(item["code"])
        r8 = eod_by.get(code)
        if r8 is None:
            continue
        s1 = fnum(item.get("s1_price"))
        inv = fnum(item.get("invalid_price"))
        if s1 is None or inv is None:
            continue
        h20 = max(history.get(code, {}).get("high20", float(r8["high"])), float(r8["high"]))
        f1 = (float(r8["close"]) / s1 - 1) * 100
        f2 = (float(r8["close"]) / h20 - 1) * 100
        g = statistics.fmean(
            [
                (f1 - params["close_vs_s1_pct"]["mean"]) / params["close_vs_s1_pct"]["std"],
                (f2 - params["dist_20d_high_pct"]["mean"]) / params["dist_20d_high_pct"]["std"],
            ]
        )
        fc_row = fc_by.get(code, {})
        close8 = float(r8["close"])
        rr = (s1 - close8) / (close8 - inv) if close8 > inv else None
        rows.append(
            {
                "code": code,
                "name": item.get("name"),
                "stage": item.get("execution_label"),
                "bucket": item.get("final_human_bucket"),
                "close_8_3": close8,
                "close_vs_s1": round(f1, 2),
                "dist_20d_high": round(f2, 2),
                "G": round(g, 4),
                "entry_q": fnum(fc_row.get("entry_quality_score")) if len(fc_row) else None,
                "rr": round(rr, 2) if rr is not None else None,
                "room": fc_row.get("entry_room_state") if len(fc_row) else None,
                "support": fnum(item.get("buy_zone_low")),
                "invalid": inv,
                "s1": s1,
                "extended_warning": bool(f2 >= -3.0),
                "near_s1_no_chase": bool(f1 >= -2.0),
            }
        )
    for _, r in ext.iterrows():
        code = str(r["code"])
        r8 = eod_by.get(code)
        if r8 is None:
            continue
        s1 = float(r["s1_price"])
        inv = float(r["invalid_price"])
        h20 = max(history.get(code, {}).get("high20", float(r8["high"])), float(r8["high"]))
        f1 = (float(r8["close"]) / s1 - 1) * 100
        f2 = (float(r8["close"]) / h20 - 1) * 100
        g = statistics.fmean(
            [
                (f1 - params["close_vs_s1_pct"]["mean"]) / params["close_vs_s1_pct"]["std"],
                (f2 - params["dist_20d_high_pct"]["mean"]) / params["dist_20d_high_pct"]["std"],
            ]
        )
        close8 = float(r8["close"])
        rr = (s1 - close8) / (close8 - inv) if close8 > inv else None
        rows.append(
            {
                "code": code,
                "name": None,
                "stage": "B2_READY(non-candidate)",
                "bucket": "V1_EXTENDED",
                "close_8_3": close8,
                "close_vs_s1": round(f1, 2),
                "dist_20d_high": round(f2, 2),
                "G": round(g, 4),
                "entry_q": fnum(r.get("entry_quality_score")),
                "rr": round(rr, 2) if rr is not None else None,
                "room": r.get("entry_room_state"),
                "support": fnum(r.get("buy_zone_low")),
                "invalid": inv,
                "s1": s1,
                "extended_warning": bool(f2 >= -3.0),
                "near_s1_no_chase": bool(f1 >= -2.0),
            }
        )
    rows = [r for r in rows if r["code"] not in DATA_LIMITED_CODES]
    for r in rows:
        if r["code"] in NAME_OVERRIDES:
            r["name"] = NAME_OVERRIDES[r["code"]]
    rows.sort(key=lambda x: x["G"], reverse=True)
    for i, r in enumerate(rows):
        r["G_rank"] = i + 1
    top15 = rows[:15]

    # MANUAL_REVIEW <=5: DATA_LIMITED / PROVISIONAL / unmapped
    manual = [
        {"code": "600468", "name": "百利电气", "reason": "PROVISIONAL 7/20-24 (7/23 first launch invisible); 8/3 二波涨停已人工确认"},
        {"code": "600756", "name": "浪潮软件", "reason": "DATA_LIMITED: 7/9-7/24 CONFIRMED gap; 人工持仓 1200@15.494"},
    ]
    unmapped = ep[
        ep["execution_label"].isin(("B1_READY", "B2_READY", "B2_CONFIRMED"))
        & (ep["invalid_price"].isna() | ep["s1_price"].isna())
        & (ep["signal_date"].astype(str).str[:10] >= "2026-07-28")
        & (ep["signal_date"].astype(str).str[:10] <= "2026-07-31")
    ]
    seen = {m["code"] for m in manual}
    for _, r in unmapped.iterrows():
        code = str(r["code"])
        if code in seen or code not in eod_by:
            continue
        manual.append(
            {
                "code": code,
                "name": None,
                "reason": f"UNMAPPED levels (stage {r['execution_label']}); 8/3 close available -> manual review",
            }
        )
        seen.add(code)
        if len(manual) >= 5:
            break

    # forward observation skeleton (1d/3d outcomes to be filled after future sessions)
    forward = {
        "session": "2026-08-04",
        "pool": "HUMAN_WATCH_V1",
        "entries": [
            {
                "code": r["code"],
                "human_decision": None,
                "1d": {"actionable_window": None, "s1_first": None, "invalid_first": None, "mfe": None, "mae": None},
                "3d": {"actionable_window": None, "s1_first": None, "invalid_first": None, "mfe": None, "mae": None},
            }
            for r in top15
        ],
        "manual_review_codes": [m["code"] for m in manual],
    }
    (OUT_DIR / "top15.json").write_text(json.dumps(top15, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "manual_review.json").write_text(json.dumps(manual, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "forward_observation.json").write_text(json.dumps(forward, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "human_selection.json").write_text(
        json.dumps(
            {
                "session": "2026-08-04",
                "HUMAN_SELECTED": [],
                "HUMAN_REJECTED": [],
                "note": "populated by human; reasons recorded verbatim; never used to modify HUMAN_WATCH_V1",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"top15": top15, "manual": manual}


if __name__ == "__main__":
    run()
