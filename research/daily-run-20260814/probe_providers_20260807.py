"""Pre-flight real-provider probe for 2026-08-07 (one code, read-only).

Verifies the three real inputs the daily pipeline uses are reachable before
starting the full run: TDX (TCP), Tencent (HTTP), BaoStock (HTTP).
"""
from __future__ import annotations

import json
from datetime import date

from limit_pullback.models.market import DailyBarsRequest
from limit_pullback.providers.baostock_daily import BaoStockDailyBarProvider
from limit_pullback.providers.tdx_daily import fetch_tdx_daily
from limit_pullback.providers.tencent_daily import fetch_tencent_daily

SESSION = date(2026, 8, 7)


def probe_baostock() -> dict:
    try:
        result = BaoStockDailyBarProvider().fetch_daily_bars(
            DailyBarsRequest(codes=("000001",), start_date=SESSION, end_date=SESSION)
        )
        bars = result.bars
        return {
            "provider": "baostock",
            "ok": True,
            "bars": len(bars),
            "first": (
                {
                    "code": bars[0].code,
                    "trade_date": bars[0].trade_date.isoformat(),
                    "close": str(bars[0].close),
                }
                if bars
                else None
            ),
            "quality_flags": list(result.quality_flags),
        }
    except Exception as exc:
        return {"provider": "baostock", "ok": False, "error": repr(exc)}


def probe_tencent() -> dict:
    try:
        rows, failures = fetch_tencent_daily(
            ["000001"], sessions=[SESSION], workers=1
        )
        return {
            "provider": "tencent",
            "ok": len(failures) == 0,
            "rows": len(rows),
            "first": (
                {
                    "code": rows[0].get("code"),
                    "trade_date": str(rows[0].get("trade_date")),
                    "close": str(rows[0].get("close")),
                }
                if rows
                else None
            ),
            "failures": [repr(f) for f in failures],
        }
    except Exception as exc:
        return {"provider": "tencent", "ok": False, "error": repr(exc)}


def probe_tdx() -> dict:
    try:
        rows, failures = fetch_tdx_daily(
            ["000001"], sessions=[SESSION], connect_timeout=5.0
        )
        return {
            "provider": "tdx",
            "ok": len(failures) == 0,
            "rows": len(rows),
            "first": (
                {
                    "code": rows[0].get("code"),
                    "trade_date": str(rows[0].get("trade_date")),
                    "close": str(rows[0].get("close")),
                }
                if rows
                else None
            ),
            "failures": [repr(f) for f in failures],
        }
    except Exception as exc:
        return {"provider": "tdx", "ok": False, "error": repr(exc)}


def main() -> int:
    results = [probe_baostock(), probe_tencent(), probe_tdx()]
    payload = {"session": SESSION.isoformat(), "probes": results}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
