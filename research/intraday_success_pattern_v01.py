"""INTRADAY_SUCCESS_PATTERN_V01 — compute intraday path features for curated cases.

Research-only. Reads 1-minute bars from AKShare (sina) for the event dates
listed in the case set and writes metrics.csv + raw minute parquet to
data/tmp/intraday-success-pattern-v01/.

No production / frozen / threshold changes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd


OUT = Path("data/tmp/intraday-success-pattern-v01")
OUT.mkdir(parents=True, exist_ok=True)

CASES = [
    {
        "symbol": "600468",
        "name": "百利电气",
        "event_date": "2026-08-03",
        "role": "SECOND_LAUNCH_SUCCESS",
        "group": "SUCCESS",
        "prev_close": 5.65,
    },
    {
        "symbol": "601858",
        "name": "中国科传",
        "event_date": "2026-08-03",
        "role": "SECOND_LAUNCH_SUCCESS",
        "group": "SUCCESS",
        "prev_close": 19.78,
    },
    {
        "symbol": "600756",
        "name": "浪潮软件",
        "event_date": "2026-08-03",
        "role": "OBSERVATION_FAST_RECLAIM",
        "group": "OBSERVATION",
        "prev_close": 16.33,
    },
    {
        "symbol": "600756",
        "name": "浪潮软件",
        "event_date": "2026-08-04",
        "role": "OBSERVATION_HOLD_DAY",
        "group": "OBSERVATION",
        "prev_close": 16.59,
    },
]

BUCKETS = [
    (570, 600, "09:30-10:00"),
    (600, 630, "10:00-10:30"),
    (630, 660, "10:30-11:00"),
    (660, 690, "11:00-11:30"),
    (780, 810, "13:00-13:30"),
    (810, 840, "13:30-14:00"),
    (840, 870, "14:00-14:30"),
    (870, 900, "14:30-15:00"),
]


def fetch_minute(symbol: str) -> pd.DataFrame:
    df = ak.stock_zh_a_minute(symbol=symbol, period="1", adjust="")
    df["ts"] = pd.to_datetime(df["day"])
    return df


def features(df: pd.DataFrame, d: str, prev_close: float) -> tuple[dict | None, str | None]:
    s = df[df["ts"].dt.date == date.fromisoformat(d)].sort_values("ts").reset_index(drop=True)
    if len(s) < 60:
        return None, f"INCOMPLETE:{len(s)}bars"
    s["tt"] = s["ts"].dt.hour * 60 + s["ts"].dt.minute
    first = s.iloc[0]
    last = s.iloc[-1]
    op = float(first["open"])
    clo = float(last["close"])
    hi = float(s["high"].max())
    lo = float(s["low"].min())
    cp = s["close"].astype(float)
    vol = s["volume"].astype(float)
    cum_pv = (cp * vol).cumsum()
    cum_v = vol.cumsum()
    vwap = (cum_pv / cum_v).replace([np.inf, -np.inf], np.nan)
    s["vwap"] = vwap.values
    t_low = int(s.loc[s["low"].idxmin(), "tt"])
    t_high = int(s.loc[s["high"].idxmax(), "tt"])
    m30 = s[s["tt"] <= 600]
    t_low30 = int(m30.loc[m30["low"].idxmin(), "tt"])
    dd_open = (float(m30["low"].min()) / op - 1.0) * 100.0
    dd_prev = (float(m30["low"].min()) / prev_close - 1.0) * 100.0
    after = s[s["tt"] > t_low30]

    def first_close_after(target: float) -> int | None:
        hit = after[after["close"].astype(float) >= target]
        return None if len(hit) == 0 else int(hit.iloc[0]["tt"] - 570)

    rec_open = first_close_after(op)
    rec_prev = first_close_after(prev_close)
    below = s[(s["tt"] > 575) & (s["vwap"].notna()) & (s["close"].astype(float) < s["vwap"])]
    rec_vwap = None
    if len(below):
        hit = s[
            (s["tt"] > below.iloc[0]["tt"])
            & (s["vwap"].notna())
            & (s["close"].astype(float) >= s["vwap"])
        ]
        rec_vwap = None if len(hit) == 0 else int(hit.iloc[0]["tt"] - 570)
    below_vwap = float((s["vwap"].notna() & (s["close"].astype(float) < s["vwap"])).mean() * 100.0)
    total_v = float(vol.sum())
    v30 = float(vol[s["tt"] <= 600].sum()) / total_v * 100.0
    v60 = float(vol[s["tt"] <= 630].sum()) / total_v * 100.0

    def close_at(t: int) -> float | None:
        hit = s[s["tt"] == t]
        if len(hit):
            return float(hit.iloc[0]["close"])
        later = s[s["tt"] >= t]
        return float(later.iloc[0]["close"]) if len(later) else None

    c1130 = close_at(690)
    c0935 = close_at(575)
    c0945 = close_at(585)
    c1000 = close_at(600)
    afternoon = (clo / c1130 - 1.0) * 100.0 if c1130 else None
    mor_ret = (c1130 / lo - 1.0) * 100.0 if c1130 else None
    shakeout = dd_open <= -1.0 and clo >= op and rec_open is not None
    return (
        {
            "symbol": None,
            "name": None,
            "event_date": d,
            "role": None,
            "group": None,
            "prev_close": prev_close,
            "open": op,
            "high": hi,
            "low": lo,
            "close": clo,
            "open_gap_pct": round((op / prev_close - 1.0) * 100.0, 4),
            "return_5m_pct": round((c0935 / op - 1.0) * 100.0, 4) if c0935 else None,
            "return_15m_pct": round((c0945 / op - 1.0) * 100.0, 4) if c0945 else None,
            "return_30m_pct": round((c1000 / op - 1.0) * 100.0, 4) if c1000 else None,
            "max_dd_from_open_30m_pct": round(dd_open, 4),
            "max_dd_from_prev_close_30m_pct": round(dd_prev, 4),
            "time_of_day_low": f"{t_low // 60:02d}:{t_low % 60:02d}",
            "time_of_day_high": f"{t_high // 60:02d}:{t_high % 60:02d}",
            "time_of_30m_low": f"{t_low30 // 60:02d}:{t_low30 % 60:02d}",
            "minutes_to_recover_open": rec_open,
            "minutes_to_recover_prev_close": rec_prev,
            "minutes_to_reclaim_vwap": rec_vwap,
            "time_below_vwap_pct": round(below_vwap, 2),
            "first_30m_volume_share_pct": round(v30, 2),
            "first_60m_volume_share_pct": round(v60, 2),
            "low_to_close_return_pct": round((clo / lo - 1.0) * 100.0, 4),
            "open_to_close_return_pct": round((clo / op - 1.0) * 100.0, 4),
            "close_location": round((clo - lo) / (hi - lo), 3) if hi > lo else None,
            "morning_low_to_1130_return_pct": round(mor_ret, 4) if mor_ret is not None else None,
            "afternoon_return_pct": round(afternoon, 4) if afternoon is not None else None,
            "EARLY_LOW": t_low < 630,
            "OPENING_SHAKEOUT": shakeout,
            "FAST_RECLAIM": bool(shakeout and rec_open is not None and rec_open <= 60),
            "VWAP_RECLAIM": rec_vwap is not None,
            "n_bars": len(s),
        },
        None,
    )


def main() -> None:
    frames: dict[str, pd.DataFrame] = {}
    rows: list[dict] = []
    notes: dict[str, str] = {}
    for case in CASES:
        sym = f"sh{case['symbol']}"
        if sym not in frames:
            frames[sym] = fetch_minute(sym)
        feat, err = features(frames[sym], case["event_date"], case["prev_close"])
        if feat is None:
            notes[f"{case['symbol']}-{case['event_date']}"] = err or "NO_FEATURES"
            continue
        feat.update(
            symbol=case["symbol"],
            name=case["name"],
            role=case["role"],
            group=case["group"],
        )
        rows.append(feat)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "metrics.csv", index=False)
    for sym, fdf in frames.items():
        fdf.to_parquet(OUT / f"minute_{sym}.parquet", index=False)
    print(df.to_string(index=False))
    print("notes:", notes)
    print("\n=== 30-min bucket paths ===")
    for case in CASES:
        sym = f"sh{case['symbol']}"
        d = case["event_date"]
        s = frames[sym]
        s = s[s["ts"].dt.date == date.fromisoformat(d)].sort_values("ts").reset_index(drop=True)
        s["tt"] = s["ts"].dt.hour * 60 + s["ts"].dt.minute
        print(
            f"\n{case['symbol']} {d} "
            f"(O{float(s.iloc[0]['open']):.2f} L{float(s['low'].min()):.2f} "
            f"H{float(s['high'].max()):.2f} C{float(s.iloc[-1]['close']):.2f})"
        )
        for a, b, label in BUCKETS:
            bdf = s[(s["tt"] >= a) & (s["tt"] < b)]
            if len(bdf):
                bdf = bdf.copy()
                for col in ("open", "high", "low", "close", "volume"):
                    bdf[col] = pd.to_numeric(bdf[col], errors="coerce")
                print(
                    f"  {label}: O{float(bdf.iloc[0]['open']):.2f} "
                    f"H{float(bdf['high'].max()):.2f} L{float(bdf['low'].min()):.2f} "
                    f"C{float(bdf.iloc[-1]['close']):.2f} "
                    f"V{float(bdf['volume'].sum()) / 1e4:.0f}万"
                )


if __name__ == "__main__":
    main()
