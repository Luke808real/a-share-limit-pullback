"""VERIFY_V02A_MINUTE_DATA — pure data gate for the 146 V02A event days.

Fetches/caches Sina 1m (and 5m fallback evidence) per symbol, validates
session coverage for the OUTCOME_EVENT_DATE of each V02_EVENT_COHORT case,
builds v02a_minute_manifest.csv and V02A_MINUTE_DATA_VERIFICATION.md.

No features, no edge metrics, no threshold scan, no outcome changes.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INTRADAY_DIR = ROOT / "research" / "intraday"
CACHE_1M = ROOT / "data/tmp/v02a-minute/raw_1m"
CACHE_5M = ROOT / "data/tmp/v02a-minute/raw_5m"
CACHE_1M.mkdir(parents=True, exist_ok=True)
CACHE_5M.mkdir(parents=True, exist_ok=True)

V01B = INTRADAY_DIR / "success_control_cases_v01b.csv"
BARS_PATH = ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"
MANIFEST = INTRADAY_DIR / "v02a_minute_manifest.csv"

CHECKPOINTS = {"0945": 585, "1000": 600, "1030": 630, "1130": 690}


def fetch_symbol(symbol: str) -> dict:
    sym = f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"
    out = {}
    for label, period, cache_dir in (("1m", "1", CACHE_1M), ("5m", "5", CACHE_5M)):
        path = cache_dir / f"{symbol}.parquet"
        try:
            if path.exists():
                df = pd.read_parquet(path)
                out[label] = ("CACHED", df)
            else:
                df = ak.stock_zh_a_minute(symbol=sym, period=period, adjust="")
                df.to_parquet(path, index=False)
                out[label] = ("OK", df)
        except Exception as exc:
            out[label] = ("ERROR", f"{type(exc).__name__}:{str(exc)[:120]}")
    return out


def session_checks(df: pd.DataFrame, d: str, granule: str = "1m") -> dict:
    s = df[df["day"].astype(str).str.startswith(d)].copy()
    if len(s) == 0:
        return {"has_data": False, "bar_count": 0}
    s["ts"] = pd.to_datetime(s["day"])
    s["tt"] = s["ts"].dt.hour * 60 + s["ts"].dt.minute
    s = s.sort_values("ts").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        s[col] = pd.to_numeric(s[col], errors="coerce")
    if "amount" in s.columns:
        s["amount"] = pd.to_numeric(s["amount"], errors="coerce")
    first_tt = int(s["tt"].iloc[0])
    last_tt = int(s["tt"].iloc[-1])
    mono = bool(s["tt"].is_monotonic_increasing)
    dup = int(s["ts"].duplicated().sum())
    ohlc_ok = bool(
        (s["high"] >= s[["open", "close", "low"]].max(axis=1) - 1e-9).all()
        and (s["low"] <= s[["open", "close", "high"]].min(axis=1) + 1e-9).all()
        and (s["volume"] >= 0).all()
        and (s["amount"].fillna(0) >= 0).all()
    )
    max_gap = int(s["tt"].diff().max()) if len(s) > 1 else 999
    has = {k: bool((s["tt"] == t).any()) for k, t in CHECKPOINTS.items()}
    has_pm = bool(((s["tt"] >= 780) & (s["tt"] <= 899)).any())
    has_close = bool((s["tt"] == 900).any())
    if granule == "1m":
        first_ok, gap_max, min_bars = first_tt <= 571, 2, 235
    else:
        first_ok, gap_max, min_bars = first_tt <= 575, 5, 46
    ready = {}
    ready["0945"] = bool(has["0945"] and first_ok and s[s["tt"] <= 585]["tt"].diff().max() <= gap_max)
    ready["1000"] = bool(
        ready["0945"] and has["1000"] and s[s["tt"] <= 600]["tt"].diff().max() <= gap_max
    )
    ready["1030"] = bool(
        ready["1000"] and has["1030"] and s[s["tt"] <= 630]["tt"].diff().max() <= gap_max
    )
    ready["1130"] = bool(
        ready["1030"] and has["1130"] and s[s["tt"] <= 690]["tt"].diff().max() <= gap_max
    )
    full = bool(
        ready["1130"]
        and has_pm
        and has_close
        and s[s["tt"] >= 780]["tt"].diff().max() <= gap_max
        and len(s) >= min_bars
    )
    return {
        "has_data": True,
        "first_timestamp": s.iloc[0]["ts"].strftime("%Y-%m-%d %H:%M:%S"),
        "last_timestamp": s.iloc[-1]["ts"].strftime("%Y-%m-%d %H:%M:%S"),
        "bar_count": len(s),
        "monotonic": mono,
        "duplicate_ts": dup,
        "ohlc_valid": ohlc_ok,
        "max_gap_min": max_gap,
        "has_0945": has["0945"],
        "has_1000": has["1000"],
        "has_1030": has["1030"],
        "has_1130": has["1130"],
        "has_pm_session": has_pm,
        "has_close_session": has_close,
        "READY_0945": ready["0945"],
        "READY_1000": ready["1000"],
        "READY_1030": ready["1030"],
        "READY_1130": ready["1130"],
        "FULL_SESSION_COMPLETE": full,
        "READY_0945_5M": None,
        "READY_1000_5M": None,
        "READY_1030_5M": None,
        "READY_1130_5M": None,
        "FULL_SESSION_COMPLETE_5M": None,
        "minute_high": float(s["high"].max()) if len(s) else None,
        "minute_close": float(s.iloc[-1]["close"]) if len(s) else None,
        "minute_open": float(s.iloc[0]["open"]) if len(s) else None,
    }


def main() -> None:
    cases = pd.read_csv(V01B, dtype={"symbol": str})
    cohort = cases[cases["V02_EVENT_COHORT"] == True].copy()  # noqa: E712
    bars = pd.read_parquet(
        BARS_PATH, columns=["code", "trade_date", "open", "high", "low", "close", "volume"]
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
    bars["code"] = bars["code"].astype(str).str.zfill(6)
    bar_map = {(r.code, r.trade_date): r for r in bars.itertuples(index=False)}

    fetch_stats: dict[str, int] = {"1m_OK": 0, "1m_ERROR": 0, "5m_OK": 0, "5m_ERROR": 0}
    per_symbol: dict[str, dict] = {}
    for symbol in sorted(cohort["symbol"].unique()):
        res = fetch_symbol(symbol)
        per_symbol[symbol] = res
        for label, status in (("1m", res["1m"][0]), ("5m", res["5m"][0])):
            fetch_stats[f"{label}_{status}"] = fetch_stats.get(f"{label}_{status}", 0) + 1

    manifest_rows = []
    for _, c in cohort.iterrows():
        symbol = str(c["symbol"]).zfill(6)
        event_date = c["OUTCOME_EVENT_DATE"]
        s1 = float(c["s1_price"])
        bar = bar_map.get((symbol, date.fromisoformat(event_date)))
        daily_high = float(bar.high) if bar is not None else None
        daily_close = float(bar.close) if bar is not None else None
        daily_open = float(bar.open) if bar is not None else None
        daily_low = float(bar.low) if bar is not None else None
        daily_s1_ok = bool(daily_high is not None and daily_high >= s1 - 1e-9)

        res1 = per_symbol[symbol]["1m"]
        res5 = per_symbol[symbol]["5m"]
        if res1[0] == "OK" or res1[0] == "CACHED":
            chk = session_checks(res1[1], event_date, granule="1m")
            fetch_status = "OK"
        else:
            chk = {"has_data": False, "bar_count": 0}
            fetch_status = res1[0]
        if res5[0] in ("OK", "CACHED"):
            chk5 = session_checks(res5[1], event_date, granule="5m")
            five_status = "OK"
        else:
            chk5 = {"has_data": False, "bar_count": 0}
            five_status = res5[0]

        minute_high = chk.get("minute_high")
        mismatch = False
        mismatch_detail = ""
        if chk.get("has_data") and minute_high is not None:
            if daily_s1_ok and minute_high < s1 - 1e-6:
                mismatch = True
                mismatch_detail = "minute_high<s1 despite daily_high>=s1"
            elif daily_close is not None and chk.get("minute_close") is not None:
                close_diff = abs(chk["minute_close"] - daily_close) / daily_close * 100.0
                if close_diff > 0.5:
                    mismatch = True
                    mismatch_detail = f"close_diff_pct={close_diff:.2f}"
        manifest_rows.append(
            {
                "episode_id": c["episode_id"],
                "symbol": symbol,
                "outcome": c["outcome"],
                "OUTCOME_EVENT_DATE": event_date,
                "EVENT_SESSION_OFFSET": c["EVENT_SESSION_OFFSET"],
                "fetch_status": fetch_status,
                "bar_count": chk.get("bar_count", 0),
                "first_timestamp": chk.get("first_timestamp"),
                "last_timestamp": chk.get("last_timestamp"),
                "monotonic": chk.get("monotonic"),
                "duplicate_ts": chk.get("duplicate_ts"),
                "ohlc_valid": chk.get("ohlc_valid"),
                "max_gap_min": chk.get("max_gap_min"),
                "READY_0945": chk.get("READY_0945", False),
                "READY_1000": chk.get("READY_1000", False),
                "READY_1030": chk.get("READY_1030", False),
                "READY_1130": chk.get("READY_1130", False),
                "FULL_SESSION_COMPLETE": chk.get("FULL_SESSION_COMPLETE", False),
                "has_pm_session": chk.get("has_pm_session", False),
                "has_close_session": chk.get("has_close_session", False),
                "INTRADAY_DAILY_MISMATCH": mismatch,
                "mismatch_detail": mismatch_detail,
                "daily_high": daily_high,
                "minute_high": minute_high,
                "daily_close": daily_close,
                "minute_close": chk.get("minute_close"),
                "daily_s1_ok": daily_s1_ok,
                "data_source": "AKSHARE/SINA 1m" if chk.get("has_data") else "NONE",
                "5m_fetch_status": five_status,
                "5m_has_data": chk5.get("has_data", False),
                "5m_bar_count": chk5.get("bar_count", 0),
                "5M_READY_0945": chk5.get("READY_0945", False),
                "5M_READY_1000": chk5.get("READY_1000", False),
                "5M_READY_1030": chk5.get("READY_1030", False),
                "5M_READY_1130": chk5.get("READY_1130", False),
                "5M_FULL_SESSION_COMPLETE": chk5.get("FULL_SESSION_COMPLETE", False),
            }
        )

    manifest = pd.DataFrame(manifest_rows)
    manifest.to_csv(MANIFEST, index=False)

    def ready_count(outcome: str, ckpt: str) -> int:
        sub = manifest[manifest["outcome"] == outcome]
        return int(sub[f"READY_{ckpt}"].sum())

    rates = {}
    for ckpt in ("0945", "1000", "1030", "1130"):
        rates[ckpt] = {
            "success_n": ready_count("SUCCESS", ckpt),
            "failed_n": ready_count("FAILED_BREAKOUT", ckpt),
            "success_rate": round(ready_count("SUCCESS", ckpt) / 43, 4),
            "failed_rate": round(ready_count("FAILED_BREAKOUT", ckpt) / 103, 4),
        }
    imbalance = any(
        abs(r["success_rate"] - r["failed_rate"]) >= 0.10 for r in rates.values()
    )
    common = manifest[
        manifest["READY_0945"]
        & manifest["READY_1000"]
        & manifest["READY_1030"]
        & manifest["READY_1130"]
    ]
    common_success = int((common["outcome"] == "SUCCESS").sum())
    common_failed = int((common["outcome"] == "FAILED_BREAKOUT").sum())
    mismatch_n = int(manifest["INTRADAY_DAILY_MISMATCH"].sum())
    min_rate = min(
        [r["success_rate"] for r in rates.values()]
        + [r["failed_rate"] for r in rates.values()]
    )
    verified = (
        common_success >= 20
        and common_failed >= 20
        and not imbalance
        and min_rate >= 0.90
    )
    print("TOTAL_EVENT_CASES:", len(manifest))
    print("FETCH_SUCCESS(1m):", fetch_stats.get("1m_OK", 0) + fetch_stats.get("1m_CACHED", 0),
          "FETCH_FAILED(1m):", fetch_stats.get("1m_ERROR", 0))
    print("COMMON_SUCCESS_N:", common_success, "COMMON_FAILED_BREAKOUT_N:", common_failed)
    print("DAILY_INTRADAY_MISMATCH_N:", mismatch_n)
    print("rates:", json.dumps(rates))
    print("MISSINGNESS_IMBALANCE:", imbalance)
    print("MINUTE_DATA_VERIFIED:", verified)
    print("READY_FOR_INTRADAY_V02A:", verified)
    print("5m has_data by outcome:")
    print(pd.crosstab(manifest["outcome"], manifest["5m_has_data"]).to_string())
    print("5m full-session by outcome:")
    print(pd.crosstab(manifest["outcome"], manifest["5M_FULL_SESSION_COMPLETE"]).to_string())
    print(
        "5m full-ready counts:",
        int(((manifest["outcome"] == "SUCCESS") & manifest["5M_FULL_SESSION_COMPLETE"]).sum()),
        int(
            (
                (manifest["outcome"] == "FAILED_BREAKOUT")
                & manifest["5M_FULL_SESSION_COMPLETE"]
            ).sum()
        ),
    )
    print("fetch_stats:", fetch_stats)
    print("manifest rows:", len(manifest))


if __name__ == "__main__":
    main()
