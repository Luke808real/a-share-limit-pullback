"""NEXT SESSION WATCHLIST v0.1 (2026-08-03) — production plan + research radar.

Data cutoff = 2026-07-31 (last confirmed trading day). Next session = 2026-08-03
(human-declared). Production layer = frozen 8/3 final human watch decision sheet.
Research overlay = G (geometry-only) score at 7/31 close, standardized with the
locked DISCOVERY params from b_actionable_state_v01. RESEARCH_OVERLAY_ONLY.

Output: data/tmp/next-session-watchlist-v01/metrics.json
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
ASOF = date(2026, 7, 31)
OUT_DIR = DATA_ROOT / "tmp" / "next-session-watchlist-v01"
DECISION_SHEET = DATA_ROOT / "forward-paper" / "2026-08-03-final-human-watch" / "decision_sheet.json"
STATE_METRICS = DATA_ROOT / "tmp" / "b-actionable-state-v01" / "metrics.json"


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sheet = json.loads(DECISION_SHEET.read_text(encoding="utf-8"))
    state = json.loads(STATE_METRICS.read_text(encoding="utf-8"))
    params = state["FIT_PARAMS"]["G"]

    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    codes = sorted({str(r["code"]) for r in sheet})
    rows = []
    for code, bars in iter_canonical_code_bars(layout, snapshot, codes=codes):
        idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
        asof_idx = idx_by_date.get(ASOF)
        if asof_idx is None or not bars:
            continue
        bar_list = list(bars)
        close = float(bar_list[asof_idx].close)
        high20 = max(
            float(bar_list[i].high)
            for i in range(max(0, asof_idx - 19), asof_idx + 1)
        )
        sheet_rows = [r for r in sheet if str(r["code"]) == code]
        for r in sheet_rows:
            def fnum(v):
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            s1 = fnum(r.get("s1_price"))
            if s1 is None:
                continue
            f_close_vs_s1 = (close / s1 - 1) * 100
            f_dist_high20 = (close / high20 - 1) * 100
            g = statistics.fmean(
                [
                    (f_close_vs_s1 - params["close_vs_s1_pct"]["mean"])
                    / params["close_vs_s1_pct"]["std"],
                    (f_dist_high20 - params["dist_20d_high_pct"]["mean"])
                    / params["dist_20d_high_pct"]["std"],
                ]
            )
            rows.append(
                {
                    "code": code,
                    "name": r.get("name"),
                    "bucket": r.get("final_human_bucket"),
                    "execution_label": r.get("execution_label"),
                    "close": close,
                    "G_score": round(g, 4),
                    "preferred_entry": fnum(r.get("preferred_entry")),
                    "buy_zone_low": fnum(r.get("buy_zone_low")),
                    "buy_zone_high": fnum(r.get("buy_zone_high")),
                    "trigger": fnum(r.get("trigger_price")),
                    "invalid": fnum(r.get("invalid_price")),
                    "s1": s1,
                    "context_quality": r.get("context_quality"),
                    "support_class": r.get("support_class"),
                    "entry_timing": r.get("entry_timing"),
                    "price_volume": r.get("price_volume_interpretation"),
                }
            )
    rows.sort(key=lambda r: r["G_score"], reverse=True)
    n = len(rows)
    for i, r in enumerate(rows):
        r["G_rank"] = i + 1
        r["G_percentile"] = round(1 - i / n, 4)

    data_limited_codes = {"600756"}
    elig = [
        r
        for r in rows
        if r["bucket"] in ("CORE_B1", "B1_PULLBACK_WAIT", "B2_TRIGGER_WATCH")
        and r["code"] not in data_limited_codes
    ]
    primary = elig[:3]
    backup = elig[3:6]
    data_limited = [r for r in rows if r["code"] == "600756"]
    post_or_noentry = [
        r
        for r in rows
        if r["bucket"] in ("B2_POST_TRIGGER_WATCH", "DIAGNOSTIC_ONLY")
    ]

    metrics = {
        "title": "NEXT SESSION WATCHLIST v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "data_cutoff": "2026-07-31",
        "next_session": "2026-08-03",
        "evaluate_strategy_calls": 0,
        "overlay": "RESEARCH_OVERLAY_ONLY: G=geometry-only score at 7/31 close, "
        "locked discovery params; not a production rule; no buy-point precision",
        "scored_candidates": len(rows),
        "PRIMARY_WATCH": primary,
        "BACKUP_WATCH": backup,
        "DATA_LIMITED": data_limited,
        "POST_B_OR_NO_NEW_ENTRY": [
            {"code": r["code"], "bucket": r["bucket"], "G_rank": r["G_rank"]}
            for r in post_or_noentry
        ],
        "TOP_G_OVERALL": [
            {"code": r["code"], "bucket": r["bucket"], "G_rank": r["G_rank"], "G_score": r["G_score"]}
            for r in rows[:10]
        ],
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
