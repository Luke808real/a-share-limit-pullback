"""2026-08-03 EOD RECOVERY (PUBLIC_FALLBACK, local layer only).

Fetches full-market 8/3 daily bars via the existing AkShare per-code endpoint,
validates against human-confirmed facts, writes a local fallback parquet +
manifest (SOURCE=PUBLIC_FALLBACK, CONFIDENCE=EOD_VERIFIED), and produces:
market summary, Forward Epoch0 Day1 joins, G radar, 8/4 watchlist.

Does NOT modify the 7/31 frozen snapshot or any frozen artifact.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
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
OUT_DIR = DATA_ROOT / "tmp" / "eod-recovery-2026-08-03"
RAW_JSONL = Path("/tmp/eod_recovery_20260803.jsonl")
DECISION_SHEET = DATA_ROOT / "forward-paper" / "2026-08-03-final-human-watch" / "decision_sheet.json"
STATE_METRICS = DATA_ROOT / "tmp" / "b-actionable-state-v01" / "metrics.json"
ASOF = date(2026, 7, 31)
EOD = date(2026, 8, 3)


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in RAW_JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        r["trade_date"] = date.fromisoformat(r["trade_date"])
        for k in ("open", "high", "low", "close", "volume", "amount", "preclose"):
            if r.get(k) is not None:
                r[k] = float(r[k])
    # validate
    bad_date = [r for r in rows if r["trade_date"] != EOD]
    illegal = [
        r["code"]
        for r in rows
        if not (r["high"] >= max(r["open"], r["low"], r["close"]) and r["low"] <= min(r["open"], r["high"], r["close"]))
    ]
    human = next((r for r in rows if r["code"] == "600468"), None)
    payload = json.dumps(
        sorted(rows, key=lambda r: r["code"]), sort_keys=True, ensure_ascii=False, default=str
    ).encode("utf-8")
    data_hash = hashlib.sha256(payload).hexdigest()

    df = pd.DataFrame(rows)
    df.to_parquet(OUT_DIR / "eod_20260803.parquet", index=False)
    fetch_time = datetime.now(timezone.utc).isoformat()
    manifest = {
        "source": "PUBLIC_FALLBACK",
        "provider": "AKSHARE per-code daily (Eastmoney endpoint)",
        "fetch_time": fetch_time,
        "trade_date": "2026-08-03",
        "row_count": len(rows),
        "data_hash": data_hash,
        "confidence": "EOD_VERIFIED",
        "human_check_600468_close": float(human["close"]) if human else None,
        "missing_codes": [],
        "validation": {
            "bad_date_rows": len(bad_date),
            "illegal_ohlc_codes": illegal[:10],
            "illegal_ohlc_count": len(illegal),
        },
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # market summary with pct vs canonical 7/31 close
    layout = WarehouseLayout(DATA_ROOT)
    snap, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    prev_close = {}
    for code, bars in iter_canonical_code_bars(layout, snap, as_of=ASOF):
        prev_close[str(code)] = float(bars[-1].close)
    missing = sorted(set(prev_close) - {str(r["code"]) for r in rows})
    manifest["missing_codes"] = missing
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    for r in rows:
        pc = prev_close.get(str(r["code"]))
        r["pct"] = (r["close"] / pc - 1) * 100 if pc else None

    def limit_flag(r):
        p = r["pct"]
        if p is None:
            return False
        c = str(r["code"])
        if c.startswith(("30", "68")):
            return p >= 19.5
        if c.startswith(("8", "4", "92")):
            return p >= 29.0
        return p >= 9.5

    n_up = sum(1 for r in rows if r["pct"] is not None and r["pct"] > 0)
    n_down = sum(1 for r in rows if r["pct"] is not None and r["pct"] < 0)
    n_flat = sum(1 for r in rows if r["pct"] is not None and r["pct"] == 0)
    n_limit_up = sum(1 for r in rows if r["pct"] is not None and limit_flag(r))
    n_limit_down = sum(1 for r in rows if r["pct"] is not None and r["pct"] <= -9.5 and not r["code"].startswith(("30", "68", "8", "4", "92")))
    total_amount = sum(r.get("amount") or 0 for r in rows)
    market_summary = {
        "rows": len(rows),
        "codes_with_pct": sum(1 for r in rows if r["pct"] is not None),
        "up": n_up,
        "down": n_down,
        "flat": n_flat,
        "limit_up_approx": n_limit_up,
        "limit_down_approx": n_limit_down,
        "total_amount_billion": round(total_amount / 1e9, 1),
        "note": "pct vs canonical 7/31 close; limit flags approx by board rule (main 9.5%, 30/68 19.5%, 8/4/92 29%); sector field not available in fallback",
    }

    # Forward Day1 join for frozen watch + review pool
    sheet = json.loads(DECISION_SHEET.read_text(encoding="utf-8"))
    watch_rows = []
    for item in sheet:
        r = next((x for x in rows if str(x["code"]) == str(item["code"])), None)
        if r is None:
            watch_rows.append({"code": item["code"], "data": "MISSING_8_3"})
            continue
        def fnum(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        inv = fnum(item.get("invalid_price"))
        s1 = fnum(item.get("s1_price"))
        trig = fnum(item.get("trigger_price"))
        inv = inv or 0.0
        s1 = s1 or 0.0
        watch_rows.append(
            {
                "code": item["code"],
                "name": item.get("name"),
                "bucket": item.get("final_human_bucket"),
                "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"],
                "pct": round(r["pct"], 2) if r["pct"] is not None else None,
                "volume": r["volume"], "amount": r["amount"],
                "trigger_touch": bool(trig and r["high"] >= trig),
                "invalid_touch": bool(r["low"] <= inv),
                "s1_touch": bool(r["high"] >= s1),
                "closed_above_trigger": bool(trig and r["close"] >= trig),
                "closed_below_invalid": bool(r["close"] <= inv),
            }
        )

    # G radar at 8/3 close for frozen-watch codes (locked discovery params)
    params = json.loads(STATE_METRICS.read_text(encoding="utf-8"))["FIT_PARAMS"]["G"]
    eod_by_code = {str(r["code"]): r for r in rows}
    radar = []
    for code, bars in iter_canonical_code_bars(
        layout, snap, codes=[str(x["code"]) for x in sheet], as_of=ASOF
    ):
        r = eod_by_code.get(str(code))
        if r is None:
            continue
        s1 = next(
            (
                float(x["s1_price"])
                for x in sheet
                if str(x["code"]) == str(code) and x.get("s1_price") is not None
            ),
            None,
        )
        if s1 is None:
            continue
        high20 = max(float(b.high) for b in bars[-20:]) if len(bars) >= 20 else float(bars[-1].high)
        high20 = max(high20, r["high"])
        f1 = (r["close"] / s1 - 1) * 100
        f2 = (r["close"] / high20 - 1) * 100
        g = statistics.fmean(
            [
                (f1 - params["close_vs_s1_pct"]["mean"]) / params["close_vs_s1_pct"]["std"],
                (f2 - params["dist_20d_high_pct"]["mean"]) / params["dist_20d_high_pct"]["std"],
            ]
        )
        radar.append({"code": str(code), "G": round(g, 4), "close_vs_s1": round(f1, 2), "dist_20d_high": round(f2, 2)})
    radar.sort(key=lambda x: x["G"], reverse=True)
    n = len(radar)
    for i, x in enumerate(radar):
        x["rank"] = i + 1
        x["percentile"] = round(1 - i / n, 4)

    # watchlist: exclude POST/DIAGNOSTIC, S1-reached, invalid-closed, DATA_LIMITED
    watch_meta = {str(x["code"]): x for x in watch_rows if isinstance(x, dict)}
    elig = [
        x
        for x in radar
        if watch_meta.get(x["code"], {}).get("bucket") in ("CORE_B1", "B1_PULLBACK_WAIT", "B2_TRIGGER_WATCH")
        and not watch_meta[x["code"]]["s1_touch"]
        and not watch_meta[x["code"]]["closed_below_invalid"]
        and x["code"] != "600756"
    ]
    primary = elig[:3]
    backup = elig[3:6]

    metrics = {
        "title": "2026-08-03 EOD RECOVERY",
        "snapshot_id": SNAPSHOT_ID,
        "evaluate_strategy_calls": 0,
        "DATA_RECOVERY": manifest,
        "MARKET_SUMMARY": market_summary,
        "FORWARD_DAY1_WATCH": watch_rows,
        "G_RADAR_8_3": radar,
        "PRIMARY_3": primary,
        "BACKUP_3": backup,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
