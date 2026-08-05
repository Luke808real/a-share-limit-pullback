"""INTRADAY_SUCCESS_PATTERN_V01A — metric semantic fix (research-only).

Fixes V01 recovery-duration semantics:
- clock-time-from-open fields renamed (minutes_from_open_to_reclaim_*);
- new recovery-duration-from-low fields (minutes_from_low_to_reclaim_*);
- VWAP reclaim now amount-based (cumulative amount / cumulative volume) when
  amount exists, otherwise VWAP_PROXY (close-weighted) and explicitly labelled;
- new reclaim-acceptance / retest fields;
- OPENING_SHAKEOUT split into PIT pieces: OPENING_DRAWDOWN_EVENT,
  MORNING_RECLAIM_EVENT, EOD_SHAKEOUT_CONFIRMED (post-hoc only).

No new samples, no label changes, no threshold scan, no production changes.
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


def compute(s: pd.DataFrame, prev_close: float) -> dict:
    first = s.iloc[0]
    last = s.iloc[-1]
    op = float(first["open"])
    clo = float(last["close"])
    hi = float(s["high"].max())
    lo = float(s["low"].min())
    t_low = int(s.loc[s["low"].idxmin(), "tt"])
    t_high = int(s.loc[s["high"].idxmax(), "tt"])

    # VWAP: amount-based when amount is usable, else close-weighted proxy.
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
        if len(window) == 0:
            return None
        return int(window.loc[window["low"].idxmin(), "tt"])

    def minutes_from_low(reclaim_tt: int | None, low_tt: int | None) -> int | None:
        if reclaim_tt is None or low_tt is None:
            return None
        return reclaim_tt - low_tt

    rec_open = first_reclaim(op, t_low30)
    rec_prev = first_reclaim(prev_close, t_low30)
    low_open = relevant_low_tt(rec_open)
    low_prev = relevant_low_tt(rec_prev)

    below = s[(s["tt"] > 575) & s["vwap"].notna() & (s["close"] < s["vwap"])]
    first_below_tt = int(below.iloc[0]["tt"]) if len(below) else None
    rec_vwap = None
    if first_below_tt is not None:
        hit = s[(s["tt"] > first_below_tt) & s["vwap"].notna() & (s["close"] >= s["vwap"])]
        rec_vwap = int(hit.iloc[0]["tt"]) if len(hit) else None
    rec_vwap_after_low = None
    if rec_vwap is not None:
        hit = s[(s["tt"] > t_low) & s["vwap"].notna() & (s["close"] >= s["vwap"])]
        rec_vwap_after_low = int(hit.iloc[0]["tt"]) if len(hit) else None
    low_vwap = relevant_low_tt(rec_vwap_after_low)

    # acceptance windows
    def window_metrics(reclaim_tt: int | None, ref_price: float, ref_vwap: bool = False) -> dict:
        out = {
            "reclaim_then_break_again": None,
            "minutes_above_next_15m": None,
            "minutes_above_next_30m": None,
            "new_low_after_reclaim": None,
            "retest_depth_pct": None,
        }
        if reclaim_tt is None:
            return out
        after = s[s["tt"] >= reclaim_tt]
        if len(after) == 0:
            return out
        if ref_vwap:
            above = after["close"] >= after["vwap"]
        else:
            above = after["close"] >= ref_price
        out["reclaim_then_break_again"] = bool((~above).any())
        n15 = after[(after["tt"] <= reclaim_tt + 15)]
        n30 = after[(after["tt"] <= reclaim_tt + 30)]
        out["minutes_above_next_15m"] = int((n15["close"] >= ref_price).sum()) if not ref_vwap else None
        out["minutes_above_next_30m"] = int((n30["close"] >= ref_price).sum()) if not ref_vwap else None
        prior_min = float(s.loc[s["tt"] < reclaim_tt, "low"].min()) if (s["tt"] < reclaim_tt).any() else None
        post_min = float(after["low"].min())
        if prior_min is not None:
            out["new_low_after_reclaim"] = bool(post_min < prior_min - 1e-9)
            out["retest_depth_pct"] = round((post_min / prior_min - 1.0) * 100.0, 4)
        return out

    open_acc = window_metrics(rec_open, op)
    vwap_acc = window_metrics(rec_vwap, 0.0, ref_vwap=True)

    # vwap hold windows
    vwap_rebreak = None
    pct_above_15 = pct_above_30 = None
    hold_15 = hold_30 = None
    if rec_vwap is not None:
        after = s[s["tt"] >= rec_vwap]
        above = after["close"] >= after["vwap"]
        vwap_rebreak = int((above & ~above.shift(1, fill_value=True)).sum())
        n15 = after[after["tt"] <= rec_vwap + 15]
        n30 = after[after["tt"] <= rec_vwap + 30]
        if len(n15) >= 10:
            pct_above_15 = round(float((n15["close"] >= n15["vwap"]).mean() * 100.0), 2)
            hold_15 = bool((n15["close"] >= n15["vwap"]).all())
        if len(n30) >= 20:
            pct_above_30 = round(float((n30["close"] >= n30["vwap"]).mean() * 100.0), 2)
            hold_30 = bool((n30["close"] >= n30["vwap"]).all())

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
        "time_of_day_low": f"{t_low // 60:02d}:{t_low % 60:02d}",
        "time_of_day_high": f"{t_high // 60:02d}:{t_high % 60:02d}",
        "time_of_30m_low": f"{t_low30 // 60:02d}:{t_low30 % 60:02d}",
        # old fields, renamed: clock time from open
        "minutes_from_open_to_reclaim_open": rec_open - 570 if rec_open is not None else None,
        "minutes_from_open_to_reclaim_prev_close": rec_prev - 570 if rec_prev is not None else None,
        "minutes_from_open_to_reclaim_vwap": rec_vwap - 570 if rec_vwap is not None else None,
        # new fields: recovery duration from the relevant low
        "time_of_relevant_low_for_open": f"{low_open // 60:02d}:{low_open % 60:02d}" if low_open is not None else None,
        "time_of_open_reclaim": f"{rec_open // 60:02d}:{rec_open % 60:02d}" if rec_open is not None else None,
        "minutes_from_low_to_reclaim_open": minutes_from_low(rec_open, low_open),
        "time_of_relevant_low_for_prev_close": f"{low_prev // 60:02d}:{low_prev % 60:02d}" if low_prev is not None else None,
        "time_of_prev_close_reclaim": f"{rec_prev // 60:02d}:{rec_prev % 60:02d}" if rec_prev is not None else None,
        "minutes_from_low_to_reclaim_prev_close": minutes_from_low(rec_prev, low_prev),
        "first_vwap_reclaim_after_low": f"{rec_vwap_after_low // 60:02d}:{rec_vwap_after_low % 60:02d}" if rec_vwap_after_low is not None else None,
        "minutes_low_to_vwap_reclaim": minutes_from_low(rec_vwap_after_low, low_vwap),
        "vwap_rebreak_count_after_reclaim": vwap_rebreak,
        "pct_above_vwap_next_15m": pct_above_15,
        "pct_above_vwap_next_30m": pct_above_30,
        "hold_above_vwap_15m": hold_15,
        "hold_above_vwap_30m": hold_30,
        "reclaim_open_then_break_again": open_acc["reclaim_then_break_again"],
        "minutes_above_open_next_15m": open_acc["minutes_above_next_15m"],
        "minutes_above_open_next_30m": open_acc["minutes_above_next_30m"],
        "new_low_after_open_reclaim": open_acc["new_low_after_reclaim"],
        "new_low_after_vwap_reclaim": vwap_acc["new_low_after_reclaim"],
        "low_retest_depth_pct": open_acc["retest_depth_pct"],
        "time_below_vwap_pct": round(below_vwap, 2),
        "first_30m_volume_share_pct": round(v30, 2),
        "first_60m_volume_share_pct": round(v60, 2),
        "low_to_close_return_pct": round((clo / lo - 1.0) * 100.0, 4),
        "open_to_close_return_pct": round((clo / op - 1.0) * 100.0, 4),
        "close_location": round((clo - lo) / (hi - lo), 3) if hi > lo else None,
        "afternoon_return_pct": round(afternoon, 4) if afternoon is not None else None,
        "EARLY_LOW": t_low < 630,
        "OPENING_DRAWDOWN_EVENT": opening_dd,
        "MORNING_RECLAIM_EVENT": morning_reclaim,
        "EOD_SHAKEOUT_CONFIRMED": eod_confirm,
        "VWAP_KIND": vwap_kind,
        "n_bars": len(s),
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
    df.to_csv(OUT / "metrics_v01a.csv", index=False)
    df.to_csv(REPO_OUT / "metrics_v01a.csv", index=False)
    pd.set_option("display.width", 260)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
