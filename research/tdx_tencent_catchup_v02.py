"""FORWARD_EPOCH_1_V02 canonical catch-up (ADR-008 pipeline, staged).

Fetch TDX (primary) + Tencent (confirmation) daily bars for 2026-08-03..
2026-08-05 (full universe), reconcile to CONFIRMED semantics, write staged
canonical catch-up parquet per trade_date under data/tmp/canonical-catchup-2026-08/.
No production snapshot publication (official pipeline integration pending).
No Forward ledger writes.
"""

from __future__ import annotations

import hashlib
import contextlib
import io
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import akshare as ak
from pytdx.hq import TdxHq_API
from pytdx.params import TDXParams
from concurrent.futures import ThreadPoolExecutor, as_completed


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/tmp/canonical-catchup-2026-08"
RAW_TDX = OUT / "raw_tdx"
RAW_TX = OUT / "raw_tencent"
for d in (OUT, RAW_TDX, RAW_TX):
    d.mkdir(parents=True, exist_ok=True)

SESSIONS = ["2026-08-03", "2026-08-04", "2026-08-05"]
TDX_SERVER = ("180.153.18.170", 7709)
TOL_OHLC = 0.01
TOL_VOL_RATIO = 0.005
INGEST_RUN = "CATCHUP_20260805_TDX_TENCENT"


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def market(code: str) -> int:
    return TDXParams.MARKET_SH if code.startswith(("6", "9")) else TDXParams.MARKET_SZ


def universe() -> list[str]:
    can = pd.read_parquet(
        ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet",
        columns=["code"],
    )
    codes = sorted(can["code"].astype(str).str.zfill(6).unique().tolist())
    keep = [c for c in codes if c[:1] in ("6", "0", "3")]
    return keep


def fetch_tdx_daily(codes: list[str]) -> list[dict]:
    api = TdxHq_API()
    assert api.connect(*TDX_SERVER, time_out=5)
    rows = []
    for code in codes:
        try:
            bars = api.get_security_bars(TDXParams.KLINE_TYPE_RI_K, market(code), code, 0, 5)
        except Exception:
            bars = None
        if not bars:
            continue
        for b in bars:
            d = f"{b['year']:04d}-{b['month']:02d}-{b['day']:02d}"
            if d not in SESSIONS:
                continue
            raw = json.dumps(dict(b), ensure_ascii=False, sort_keys=True).encode()
            rows.append({
                "code": code, "trade_date": d,
                "open": float(b["open"]), "high": float(b["high"]),
                "low": float(b["low"]), "close": float(b["close"]),
                "volume_lots": float(b["vol"]), "amount": float(b["amount"]),
                "raw_hash": sha_bytes(raw),
            })
    api.disconnect()
    return rows


def fetch_tencent_daily(codes: list[str]) -> list[dict]:
    rows = []
    todo = [c for c in codes if not (RAW_TX / f"{c}.parquet").exists()]
    print(f"tencent todo: {len(todo)} (cached {len(codes)-len(todo)})", flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch_one_tx, code): code for code in todo}
        done = 0
        for fut in as_completed(futures):
            out = fut.result()
            rows.extend(out)
            done += 1
            if done % 300 == 0:
                print(f"tencent progress {done}/{len(todo)}", flush=True)
    # include already cached
    for c in codes:
        cached = RAW_TX / f"{c}.parquet"
        if cached.exists():
            rows.extend(pd.read_parquet(cached).to_dict(orient="records"))
    return rows


def _fetch_one_tx(code: str) -> list[dict]:
    cached = RAW_TX / f"{code}.parquet"
    if cached.exists():
        return pd.read_parquet(cached).to_dict(orient="records")
    out = []
    for attempt in range(2):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                df = ak.stock_zh_a_hist_tx(symbol=code, start_date="20260803", end_date="20260805", adjust="")
            got = df
            break
        except Exception:
            time.sleep(1.0)
    else:
        got = None
    if got is not None and len(got):
        for _, r in got.iterrows():
            d = str(r["date"])
            if d not in SESSIONS:
                continue
            raw = json.dumps({k: str(v) for k, v in r.items()}, ensure_ascii=False, sort_keys=True).encode()
            out.append({
                "code": code, "trade_date": d,
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
                "volume_shares": float(r["volume"]), "amount": float(r["amount"]),
                "raw_hash": sha_bytes(raw),
            })
    if out:
        pd.DataFrame(out).to_parquet(cached, index=False)
    return out


def reconcile(tdx_rows: list[dict], tx_rows: list[dict], prev_close_map: dict) -> list[dict]:
    tx_by = {(r["code"], r["trade_date"]): r for r in tx_rows}
    out = []
    for r in tdx_rows:
        key = (r["code"], r["trade_date"])
        t = tx_by.get(key)
        tdx_vol = r["volume_lots"] * 100.0
        tx_unit = None
        if t is None:
            status = "PROVISIONAL"
            conflict = ""
        else:
            ohlc_ok = all(abs(r[k] - t[k]) <= TOL_OHLC for k in ("open", "high", "low", "close"))
            # unit-agnostic Tencent volume: match TDX shares with ×1 or ×100
            v = t["volume_shares"]
            ratio_shares = tdx_vol / v if v else None
            ratio_lots = tdx_vol / (v * 100.0) if v else None
            if ratio_shares is not None and abs(ratio_shares - 1.0) <= TOL_VOL_RATIO:
                vol_ok, ratio, tx_unit = True, ratio_shares, "SHARES"
            elif ratio_lots is not None and abs(ratio_lots - 1.0) <= TOL_VOL_RATIO:
                vol_ok, ratio, tx_unit = True, ratio_lots, "LOTS"
            else:
                vol_ok, ratio, tx_unit = False, ratio_shares, "UNKNOWN"
            if ohlc_ok and vol_ok:
                status = "CONFIRMED"
                conflict = ""
            else:
                status = "CONFLICTED"
                conflict = f"ohlc={ohlc_ok};vol_ratio={ratio if ratio is not None else 'NA'}"
        out.append({
            "code": r["code"], "trade_date": r["trade_date"],
            "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
            "preclose": prev_close_map.get(r["code"]),
            "volume": tdx_vol, "amount": r["amount"],
            "pct_change": round((r["close"] / prev_close_map[r["code"]] - 1.0) * 100.0, 4) if prev_close_map.get(r["code"]) else None,
            "selected_provider": "TDX",
            "confirmation_provider": "TENCENT" if t is not None else None,
            "tencent_volume_unit": tx_unit,
            "reconciliation_status": status,
            "reconciliation_detail": conflict,
            "source_row_hash": r["raw_hash"],
            "price_domain": "RAW_UNADJUSTED",
            "corporate_action_affected": False,
            "provider": "TDX", "server": TDX_SERVER[0],
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ingest_run_id": INGEST_RUN,
        })
    return out


def main() -> None:
    codes = universe()
    print("UNIVERSE_N:", len(codes), flush=True)
    # prior close map from 7/31 canonical
    can = pd.read_parquet(
        ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet",
        columns=["code", "trade_date", "close"],
    )
    can["trade_date"] = pd.to_datetime(can["trade_date"]).dt.date
    last = can[can["trade_date"] == date(2026, 7, 31)]
    prev_close_map = dict(zip(last["code"].astype(str).str.zfill(6), last["close"].astype(float), strict=False))

    tdx_path = OUT / "raw_tdx_full.parquet"
    if tdx_path.exists():
        tdx_rows = pd.read_parquet(tdx_path).to_dict(orient="records")
    else:
        tdx_rows = fetch_tdx_daily(codes)
        pd.DataFrame(tdx_rows).to_parquet(tdx_path, index=False)
    print("TDX rows:", len(tdx_rows), flush=True)

    tx_rows = fetch_tencent_daily(codes)
    print("TENCENT rows:", len(tx_rows), flush=True)
    pd.DataFrame(tx_rows).to_parquet(OUT / "raw_tencent_full.parquet", index=False)

    reconciled = reconcile(tdx_rows, tx_rows, prev_close_map)
    df = pd.DataFrame(reconciled)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    manifest = {}
    for d in SESSIONS:
        present = set(df.loc[df["trade_date"] == date.fromisoformat(d), "code"])
        missing = [c for c in codes if c not in present]
        rows = df[df["trade_date"] == date.fromisoformat(d)].to_dict(orient="records")
        for c in missing:
            rows.append({
                "code": c, "trade_date": date.fromisoformat(d),
                "open": None, "high": None, "low": None, "close": None,
                "preclose": prev_close_map.get(c),
                "volume": None, "amount": None, "pct_change": None,
                "selected_provider": None, "confirmation_provider": None,
                "tencent_volume_unit": None,
                "reconciliation_status": "INCOMPLETE", "reconciliation_detail": "both_providers_missing",
                "source_row_hash": None, "price_domain": "RAW_UNADJUSTED",
                "corporate_action_affected": False,
                "provider": None, "server": None,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ingest_run_id": INGEST_RUN,
            })
        sub = pd.DataFrame(rows)
        sub.to_parquet(OUT / f"{d}.parquet", index=False)
        counts = sub["reconciliation_status"].value_counts().to_dict()
        manifest[d] = {
            "universe_n": len(codes),
            "tdx_present_n": int((sub["selected_provider"] == "TDX").sum()),
            "tencent_present_n": int(sub["confirmation_provider"].notna().sum()),
            "confirmed_n": int(counts.get("CONFIRMED", 0)),
            "provisional_n": int(counts.get("PROVISIONAL", 0)),
            "conflicted_n": int(counts.get("CONFLICTED", 0)),
            "incomplete_n": int(counts.get("INCOMPLETE", 0)),
            "quarantined_n": 0,
            "ohlc_mismatch_n": int(sub["reconciliation_detail"].astype(str).str.contains("ohlc=False").sum()),
            "volume_mismatch_n": int(sub["reconciliation_detail"].astype(str).str.contains("vol_ratio").sum()),
            "tencent_unit_counts": sub["tencent_volume_unit"].value_counts().to_dict(),
        }
        print(d, counts, flush=True)
    json.dump({
        "ingest_run_id": INGEST_RUN,
        "sessions": SESSIONS,
        "provider": {"daily_primary": "TDX", "daily_confirm": "TENCENT"},
        "daily_qa": manifest,
        "staged_only": True,
        "production_snapshot_published": False,
    }, open(OUT / "manifest.json", "w"), ensure_ascii=False, indent=2)
    print("STAGED_CATCHUP_WRITTEN", flush=True)


if __name__ == "__main__":
    main()
