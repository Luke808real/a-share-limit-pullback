"""INTRADAY_SUCCESS_PATTERN_V01B — metric implementation fix (research-only).

Fixes V01A implementation bugs:
1. VWAP acceptance metrics now anchor to POST_LOW_VWAP_RECLAIM
   (rec_vwap_after_low), not session-first reclaim.
2. VWAP_REBREAK = ABOVE -> BELOW transition (previous close >= vwap,
   current close < vwap); VWAP_RECLAIM_COUNT = BELOW -> ABOVE; names separated.
3. next-15m / next-30m windows are strictly the next 15 / 30 one-minute bars
   after the reclaim bar (anchor bar excluded), for both VWAP and open.

No new samples, no label changes, no threshold scan, no production change.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


OUT = Path("data/tmp/intraday-success-pattern-v01")
REPO_OUT = Path("research/intraday")

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


def load_session(symbol: str, d: str) -> pd.DataFrame:
    raw = pd.read_parquet(OUT / f"minute_sh{symbol}.parquet")
    raw["ts"] = pd.to_datetime(raw["day"])
    s = raw[raw["ts"].dt.date == date.fromisoformat(d)].sort_values("ts").reset_index(drop=True)
    s["tt"] = s["ts"].dt.hour * 60 + s["ts"].dt.minute
    for col in ("open", "high", "low", "close", "volume", "amount"):
        s[col] = pd.to_numeric(s[col], errors="coerce")
    return s


def idx_at(s: pd.DataFrame, tt: int | None) -> int | None:
    if tt is None:
        return None
    hit = s.index[s["tt"] == tt]
    return int(hit[0]) if len(hit) else None


def strict_window(s: pd.DataFrame, anchor_idx: int | None, n: int) -> pd.DataFrame:
    if anchor_idx is None:
        return s.iloc[0:0]
    return s.iloc[anchor_idx + 1 : anchor_idx + 1 + n]


def compute(s: pd.DataFrame, prev_close: float) -> dict:
    first = s.iloc[0]
    last = s.iloc[-1]
    op = float(first["open"])
    clo = float(last["close"])
    hi = float(s["high"].max())
    lo = float(s["low"].min())
    t_low = int(s.loc[s["low"].idxmin(), "tt"])
    t_high = int(s.loc[s["high"].idxmax(), "tt"])

    amount_ok = bool(s["amount"].notna().sum() > 100 and (s["amount"] > 0).sum() > 100)
    if amount_ok:
        vwap = (s["amount"].cumsum() / s["volume"].cumsum()).replace([np.inf, -np.inf], np.nan)
        vwap_kind = "VWAP_AMOUNT_BASED"
    else:
        vwap = ((s["close"] * s["volume"]).cumsum() / s["volume"].cumsum()).replace(
            [np.inf, -np.inf], np.nan
        )
        vwap_kind = "VWAP_PROXY_CLOSE_WEIGHTED"
    s["vwap"] = vwap.values

    m30 = s[s["tt"] <= 600]
    t_low30 = int(m30.loc[m30["low"].idxmin(), "tt"])
    dd_open = (float(m30["low"].min()) / op - 1.0) * 100.0
    dd_prev = (float(m30["low"].min()) / prev_close - 1.0) * 100.0

    def first_reclaim(target: float, after_tt: int) -> int | None:
        hit = s[(s["tt"] > after_tt) & (s["close"] >= target)]
        return None if len(hit) == 0 else int(hit.iloc[0]["tt"])

    def relevant_low_tt(before_tt: int | None) -> int | None:
        if before_tt is None:
            return None
        window = s[(s["tt"] >= 570) & (s["tt"] < before_tt)]
        return None if len(window) == 0 else int(window.loc[window["low"].idxmin(), "tt"])

    rec_open = first_reclaim(op, t_low30)
    rec_prev = first_reclaim(prev_close, t_low30)
    low_open = relevant_low_tt(rec_open)
    low_prev = relevant_low_tt(rec_prev)

    below = s[(s["tt"] > 575) & s["vwap"].notna() & (s["close"] < s["vwap"])]
    first_below_tt = int(below.iloc[0]["tt"]) if len(below) else None
    session_first_reclaim = None
    if first_below_tt is not None:
        hit = s[(s["tt"] > first_below_tt) & s["vwap"].notna() & (s["close"] >= s["vwap"])]
        session_first_reclaim = int(hit.iloc[0]["tt"]) if len(hit) else None

    # POST_LOW_VWAP_RECLAIM anchor
    post_low_reclaim = None
    if session_first_reclaim is not None:
        hit = s[(s["tt"] > t_low) & s["vwap"].notna() & (s["close"] >= s["vwap"])]
        post_low_reclaim = int(hit.iloc[0]["tt"]) if len(hit) else None
    low_vwap = relevant_low_tt(post_low_reclaim)
    anchor_idx = idx_at(s, post_low_reclaim)

    vwap_reclaim_count = vwap_rebreak_count = None
    pct_above_15 = pct_above_30 = None
    bars_above_15 = bars_above_30 = None
    hold_15 = hold_30 = None
    new_low_post_low = None
    if anchor_idx is not None:
        after = s.iloc[anchor_idx + 1 :].copy()
        above = after["close"] >= after["vwap"]
        prev_above = after["close"].shift(1) >= after["vwap"].shift(1)
        vwap_reclaim_count = int(((~prev_above.fillna(False)) & above).sum())
        vwap_rebreak_count = int((prev_above.fillna(True) & ~above).sum())
        w15 = strict_window(s, anchor_idx, 15)
        w30 = strict_window(s, anchor_idx, 30)
        if len(w15) == 15:
            bars_above_15 = int((w15["close"] >= w15["vwap"]).sum())
            pct_above_15 = round(bars_above_15 / 15 * 100.0, 2)
            hold_15 = bool(bars_above_15 == 15)
        if len(w30) == 30:
            bars_above_30 = int((w30["close"] >= w30["vwap"]).sum())
            pct_above_30 = round(bars_above_30 / 30 * 100.0, 2)
            hold_30 = bool(bars_above_30 == 30)
        prior_min = float(s.loc[s.index < anchor_idx, "low"].min())
        post_min = float(after["low"].min()) if len(after) else None
        if post_min is not None:
            new_low_post_low = bool(post_min < prior_min - 1e-9)

    # open reclaim acceptance (strict windows too)
    open_idx = idx_at(s, rec_open)
    open_break_again = None
    bars_above_open_15 = bars_above_open_30 = None
    pct_above_open_15 = pct_above_open_30 = None
    new_low_after_open = None
    low_retest_depth = None
    if open_idx is not None:
        after = s.iloc[open_idx + 1 :]
        open_break_again = bool((after["close"] < op).any()) if len(after) else None
        w15 = strict_window(s, open_idx, 15)
        w30 = strict_window(s, open_idx, 30)
        if len(w15) == 15:
            bars_above_open_15 = int((w15["close"] >= op).sum())
            pct_above_open_15 = round(bars_above_open_15 / 15 * 100.0, 2)
        if len(w30) == 30:
            bars_above_open_30 = int((w30["close"] >= op).sum())
            pct_above_open_30 = round(bars_above_open_30 / 30 * 100.0, 2)
        prior_min = float(s.loc[s.index < open_idx, "low"].min())
        post_min = float(after["low"].min()) if len(after) else None
        if post_min is not None:
            new_low_after_open = bool(post_min < prior_min - 1e-9)
            low_retest_depth = round((post_min / prior_min - 1.0) * 100.0, 4)

    below_vwap = float((s["vwap"].notna() & (s["close"] < s["vwap"])).mean() * 100.0)
    total_v = float(s["volume"].sum())
    v30 = float(s.loc[s["tt"] <= 600, "volume"].sum()) / total_v * 100.0
    v60 = float(s.loc[s["tt"] <= 630, "volume"].sum()) / total_v * 100.0

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

    opening_dd = dd_open <= -1.0
    morning_reclaim = False
    if opening_dd:
        morning_hit = s[(s["tt"] > t_low30) & (s["tt"] <= 690) & (s["close"] >= op)]
        morning_reclaim = len(morning_hit) > 0
    eod_confirm = opening_dd and clo >= op and rec_open is not None

    return {
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
        "LOW_TIME": f"{t_low // 60:02d}:{t_low % 60:02d}",
        "time_of_day_high": f"{t_high // 60:02d}:{t_high % 60:02d}",
        "time_of_30m_low": f"{t_low30 // 60:02d}:{t_low30 % 60:02d}",
        "OPEN_RECLAIM_TIME": f"{rec_open // 60:02d}:{rec_open % 60:02d}" if rec_open is not None else None,
        "LOW_TO_OPEN_RECLAIM_MIN": rec_open - low_open if rec_open is not None and low_open is not None else None,
        "PREV_CLOSE_RECLAIM_TIME": f"{rec_prev // 60:02d}:{rec_prev % 60:02d}" if rec_prev is not None else None,
        "LOW_TO_PREV_CLOSE_RECLAIM_MIN": rec_prev - low_prev if rec_prev is not None and low_prev is not None else None,
        "PREV_CLOSE_RECLAIM": rec_prev is not None,
        "SESSION_FIRST_VWAP_RECLAIM_TIME": f"{session_first_reclaim // 60:02d}:{session_first_reclaim % 60:02d}" if session_first_reclaim is not None else None,
        "POST_LOW_VWAP_RECLAIM_TIME": f"{post_low_reclaim // 60:02d}:{post_low_reclaim % 60:02d}" if post_low_reclaim is not None else None,
        "LOW_TO_POST_LOW_VWAP_RECLAIM_MIN": post_low_reclaim - low_vwap if post_low_reclaim is not None and low_vwap is not None else None,
        "VWAP_RECLAIM_COUNT_AFTER_POST_LOW": vwap_reclaim_count,
        "VWAP_REBREAK_COUNT_AFTER_POST_LOW": vwap_rebreak_count,
        "BARS_ABOVE_VWAP_NEXT_15M": bars_above_15,
        "PCT_ABOVE_VWAP_NEXT_15M": pct_above_15,
        "BARS_ABOVE_VWAP_NEXT_30M": bars_above_30,
        "PCT_ABOVE_VWAP_NEXT_30M": pct_above_30,
        "HOLD_ABOVE_VWAP_15M": hold_15,
        "HOLD_ABOVE_VWAP_30M": hold_30,
        "NEW_LOW_AFTER_POST_LOW_RECLAIM": new_low_post_low,
        "OPEN_RECLAIM_THEN_BREAK_AGAIN": open_break_again,
        "BARS_ABOVE_OPEN_NEXT_15M": bars_above_open_15,
        "PCT_ABOVE_OPEN_NEXT_15M": pct_above_open_15,
        "BARS_ABOVE_OPEN_NEXT_30M": bars_above_open_30,
        "PCT_ABOVE_OPEN_NEXT_30M": pct_above_open_30,
        "NEW_LOW_AFTER_OPEN_RECLAIM": new_low_after_open,
        "LOW_RETEST_DEPTH_PCT": low_retest_depth,
        "TIME_BELOW_VWAP_PCT": round(below_vwap, 2),
        "FIRST_30M_VOLUME_SHARE_PCT": round(v30, 2),
        "FIRST_60M_VOLUME_SHARE_PCT": round(v60, 2),
        "LOW_TO_CLOSE_RETURN_PCT": round((clo / lo - 1.0) * 100.0, 4),
        "OPEN_TO_CLOSE_RETURN_PCT": round((clo / op - 1.0) * 100.0, 4),
        "CLOSE_LOCATION": round((clo - lo) / (hi - lo), 3) if hi > lo else None,
        "AFTERNOON_RETURN_PCT": round(afternoon, 4) if afternoon is not None else None,
        "EARLY_LOW": t_low < 630,
        "OPENING_DRAWDOWN_EVENT": opening_dd,
        "MORNING_RECLAIM_EVENT": morning_reclaim,
        "EOD_SHAKEOUT_CONFIRMED": eod_confirm,
        "VWAP_KIND": vwap_kind,
        "N_BARS": len(s),
    }


def main() -> None:
    rows = []
    for case in CASES:
        s = load_session(case["symbol"], case["event_date"])
        feat = compute(s, case["prev_close"])
        feat.update(
            symbol=case["symbol"],
            name=case["name"],
            event_date=case["event_date"],
            role=case["role"],
            group=case["group"],
        )
        rows.append(feat)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "metrics_v01b.csv", index=False)
    df.to_csv(REPO_OUT / "metrics_v01b.csv", index=False)
    focus = [
        "symbol",
        "event_date",
        "LOW_TIME",
        "LOW_TO_OPEN_RECLAIM_MIN",
        "POST_LOW_VWAP_RECLAIM_TIME",
        "LOW_TO_POST_LOW_VWAP_RECLAIM_MIN",
        "VWAP_RECLAIM_COUNT_AFTER_POST_LOW",
        "VWAP_REBREAK_COUNT_AFTER_POST_LOW",
        "BARS_ABOVE_VWAP_NEXT_15M",
        "PCT_ABOVE_VWAP_NEXT_15M",
        "BARS_ABOVE_VWAP_NEXT_30M",
        "PCT_ABOVE_VWAP_NEXT_30M",
        "NEW_LOW_AFTER_POST_LOW_RECLAIM",
        "PREV_CLOSE_RECLAIM",
        "AFTERNOON_RETURN_PCT",
        "CLOSE_LOCATION",
        "OPENING_DRAWDOWN_EVENT",
        "MORNING_RECLAIM_EVENT",
        "EOD_SHAKEOUT_CONFIRMED",
    ]
    pd.set_option("display.width", 260)
    print(df[focus].to_string(index=False))
    print("\nALL COLUMNS:")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
