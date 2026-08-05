"""INTRADAY_SUCCESS_PATTERN_V01C — final metric correctness fix.

Fixes remaining V01B issues:
1. VWAP transition counting after POST_LOW anchor seeds previous state from the
   anchor's real state (anchor close >= vwap); no shift-NaN reclaim artifact.
2. POST_LOW_VWAP state classification: NEVER_LOST vs LOST_THEN_RECLAIMED
   (reclaim time only defined by a real BELOW -> ABOVE transition).
3. PREV_CLOSE_ACCEPTANCE fields: reclaim time kept, plus rebreak count,
   strict next-15/30-bar windows, hold flags, final close state,
   time-above share after first reclaim, second reclaim time.
4. AFTERNOON_RETURN renamed PM_RETURN; no expansion threshold invented.

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


def vwap_transitions_after(s: pd.DataFrame, anchor_idx: int) -> tuple[list[int], list[int]]:
    """Return (reclaim_times, rebreak_times) strictly after anchor.

    Previous state is seeded from the anchor bar's real state (close >= vwap by
    definition of the anchor). A reclaim is BELOW -> ABOVE; a rebreak is
    ABOVE -> BELOW. Bars with NaN vwap are skipped without state change.
    """
    anchor = s.iloc[anchor_idx]
    prev_above = float(anchor["close"]) >= float(anchor["vwap"])
    reclaims: list[int] = []
    rebreaks: list[int] = []
    for _, row in s.iloc[anchor_idx + 1 :].iterrows():
        v = row["vwap"]
        if pd.isna(v):
            continue
        cur_above = float(row["close"]) >= float(v)
        if prev_above and not cur_above:
            rebreaks.append(int(row["tt"]))
        elif not prev_above and cur_above:
            reclaims.append(int(row["tt"]))
        prev_above = cur_above
    return reclaims, rebreaks


def prev_close_transitions_after(
    s: pd.DataFrame, anchor_idx: int, prev_close: float
) -> tuple[list[int], list[int]]:
    """Same state-machine for prev-close reclaim/rebreak after first reclaim."""
    anchor = s.iloc[anchor_idx]
    prev_above = float(anchor["close"]) >= prev_close
    reclaims: list[int] = []
    rebreaks: list[int] = []
    for _, row in s.iloc[anchor_idx + 1 :].iterrows():
        cur_above = float(row["close"]) >= prev_close
        if prev_above and not cur_above:
            rebreaks.append(int(row["tt"]))
        elif not prev_above and cur_above:
            reclaims.append(int(row["tt"]))
        prev_above = cur_above
    return reclaims, rebreaks


def compute(s: pd.DataFrame, prev_close: float) -> dict:
    first = s.iloc[0]
    last = s.iloc[-1]
    op = float(first["open"])
    clo = float(last["close"])
    hi = float(s["high"].max())
    lo = float(s["low"].min())
    t_low = int(s.loc[s["low"].idxmin(), "tt"])
    t_high = int(s.loc[s["high"].idxmax(), "tt"])
    low_idx = idx_at(s, t_low)

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
    low_open = relevant_low_tt(rec_open)
    rec_prev = first_reclaim(prev_close, t_low30)
    low_prev = relevant_low_tt(rec_prev)

    # --- POST_LOW_VWAP state classification ---
    post_low_state = None
    post_low_reclaim_time = None
    post_low_reclaims: list[int] = []
    post_low_rebreaks: list[int] = []
    if low_idx is not None:
        after_low = s.iloc[low_idx + 1 :]
        below_after_low = after_low[after_low["vwap"].notna() & (after_low["close"] < after_low["vwap"])]
        if len(below_after_low) == 0:
            post_low_state = "POST_LOW_VWAP_NEVER_LOST"
        else:
            # first BELOW -> ABOVE transition after the low
            low_bar = s.iloc[low_idx]
            prev_above = (
                float(low_bar["close"]) >= float(low_bar["vwap"])
                if not pd.isna(low_bar["vwap"])
                else True
            )
            for _, row in after_low.iterrows():
                v = row["vwap"]
                if pd.isna(v):
                    continue
                cur_above = float(row["close"]) >= float(v)
                if not prev_above and cur_above:
                    post_low_reclaim_time = int(row["tt"])
                    break
                prev_above = cur_above
            post_low_state = (
                "POST_LOW_VWAP_LOST_THEN_RECLAIMED"
                if post_low_reclaim_time is not None
                else "POST_LOW_VWAP_LOST_NOT_RECLAIMED"
            )
            if post_low_reclaim_time is not None:
                anchor_idx = idx_at(s, post_low_reclaim_time)
                post_low_reclaims, post_low_rebreaks = vwap_transitions_after(s, anchor_idx)

    # VWAP acceptance anchored at post-low reclaim
    post_low_anchor_idx = idx_at(s, post_low_reclaim_time)
    bars_above_vwap_15 = bars_above_vwap_30 = None
    pct_above_vwap_15 = pct_above_vwap_30 = None
    hold_vwap_15 = hold_vwap_30 = None
    new_low_after_post_low = None
    if post_low_anchor_idx is not None:
        w15 = strict_window(s, post_low_anchor_idx, 15)
        w30 = strict_window(s, post_low_anchor_idx, 30)
        if len(w15) == 15:
            bars_above_vwap_15 = int((w15["close"] >= w15["vwap"]).sum())
            pct_above_vwap_15 = round(bars_above_vwap_15 / 15 * 100.0, 2)
            hold_vwap_15 = bool(bars_above_vwap_15 == 15)
        if len(w30) == 30:
            bars_above_vwap_30 = int((w30["close"] >= w30["vwap"]).sum())
            pct_above_vwap_30 = round(bars_above_vwap_30 / 30 * 100.0, 2)
            hold_vwap_30 = bool(bars_above_vwap_30 == 30)
        prior_min = float(s.loc[s.index < post_low_anchor_idx, "low"].min())
        post_min = float(s.loc[s.index > post_low_anchor_idx, "low"].min())
        new_low_after_post_low = bool(post_min < prior_min - 1e-9)

    # --- PREV_CLOSE_ACCEPTANCE ---
    prev_idx = idx_at(s, rec_prev)
    prev_rebreak_count = None
    second_prev_reclaim = None
    bars_above_prev_15 = bars_above_prev_30 = None
    pct_above_prev_15 = pct_above_prev_30 = None
    hold_prev_15 = hold_prev_30 = None
    final_close_above_prev = bool(clo >= prev_close)
    time_above_prev_pct = None
    if prev_idx is not None:
        reclaims_pc, rebreaks_pc = prev_close_transitions_after(s, prev_idx, prev_close)
        prev_rebreak_count = len(rebreaks_pc)
        second_prev_reclaim = reclaims_pc[0] if reclaims_pc else None
        w15 = strict_window(s, prev_idx, 15)
        w30 = strict_window(s, prev_idx, 30)
        if len(w15) == 15:
            bars_above_prev_15 = int((w15["close"] >= prev_close).sum())
            pct_above_prev_15 = round(bars_above_prev_15 / 15 * 100.0, 2)
            hold_prev_15 = bool(bars_above_prev_15 == 15)
        if len(w30) == 30:
            bars_above_prev_30 = int((w30["close"] >= prev_close).sum())
            pct_above_prev_30 = round(bars_above_prev_30 / 30 * 100.0, 2)
            hold_prev_30 = bool(bars_above_prev_30 == 30)
        from_reclaim = s.iloc[prev_idx:]
        time_above_prev_pct = round(
            float((from_reclaim["close"] >= prev_close).mean() * 100.0), 2
        )

    # --- open acceptance (strict windows, V01B semantics) ---
    open_idx = idx_at(s, rec_open)
    open_break_again = None
    bars_above_open_15 = bars_above_open_30 = None
    pct_above_open_15 = pct_above_open_30 = None
    if open_idx is not None:
        after_open = s.iloc[open_idx + 1 :]
        open_break_again = bool((after_open["close"] < op).any()) if len(after_open) else None
        w15 = strict_window(s, open_idx, 15)
        w30 = strict_window(s, open_idx, 30)
        if len(w15) == 15:
            bars_above_open_15 = int((w15["close"] >= op).sum())
            pct_above_open_15 = round(bars_above_open_15 / 15 * 100.0, 2)
        if len(w30) == 30:
            bars_above_open_30 = int((w30["close"] >= op).sum())
            pct_above_open_30 = round(bars_above_open_30 / 30 * 100.0, 2)

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
    pm_return = (clo / c1130 - 1.0) * 100.0 if c1130 else None

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
        "POST_LOW_VWAP_STATE": post_low_state,
        "POST_LOW_VWAP_RECLAIM_TIME": f"{post_low_reclaim_time // 60:02d}:{post_low_reclaim_time % 60:02d}" if post_low_reclaim_time is not None else None,
        "VWAP_RECLAIM_COUNT_AFTER_POST_LOW": len(post_low_reclaims),
        "VWAP_REBREAK_COUNT_AFTER_POST_LOW": len(post_low_rebreaks),
        "BARS_ABOVE_VWAP_NEXT_15M": bars_above_vwap_15,
        "PCT_ABOVE_VWAP_NEXT_15M": pct_above_vwap_15,
        "BARS_ABOVE_VWAP_NEXT_30M": bars_above_vwap_30,
        "PCT_ABOVE_VWAP_NEXT_30M": pct_above_vwap_30,
        "HOLD_ABOVE_VWAP_15M": hold_vwap_15,
        "HOLD_ABOVE_VWAP_30M": hold_vwap_30,
        "NEW_LOW_AFTER_POST_LOW_RECLAIM": new_low_after_post_low,
        "FIRST_PREV_CLOSE_RECLAIM_TIME": f"{rec_prev // 60:02d}:{rec_prev % 60:02d}" if rec_prev is not None else None,
        "LOW_TO_PREV_CLOSE_RECLAIM_MIN": rec_prev - low_prev if rec_prev is not None and low_prev is not None else None,
        "PREV_CLOSE_REBREAK_COUNT": prev_rebreak_count,
        "SECOND_PREV_CLOSE_RECLAIM_TIME": f"{second_prev_reclaim // 60:02d}:{second_prev_reclaim % 60:02d}" if second_prev_reclaim is not None else None,
        "BARS_ABOVE_PREV_CLOSE_NEXT_15M": bars_above_prev_15,
        "PCT_ABOVE_PREV_CLOSE_NEXT_15M": pct_above_prev_15,
        "BARS_ABOVE_PREV_CLOSE_NEXT_30M": bars_above_prev_30,
        "PCT_ABOVE_PREV_CLOSE_NEXT_30M": pct_above_prev_30,
        "PREV_CLOSE_HOLD_15M": hold_prev_15,
        "PREV_CLOSE_HOLD_30M": hold_prev_30,
        "FINAL_CLOSE_ABOVE_PREV_CLOSE": final_close_above_prev,
        "TIME_ABOVE_PREV_CLOSE_AFTER_FIRST_RECLAIM_PCT": time_above_prev_pct,
        "OPEN_RECLAIM_THEN_BREAK_AGAIN": open_break_again,
        "BARS_ABOVE_OPEN_NEXT_15M": bars_above_open_15,
        "PCT_ABOVE_OPEN_NEXT_15M": pct_above_open_15,
        "BARS_ABOVE_OPEN_NEXT_30M": bars_above_open_30,
        "PCT_ABOVE_OPEN_NEXT_30M": pct_above_open_30,
        "TIME_BELOW_VWAP_PCT": round(below_vwap, 2),
        "FIRST_30M_VOLUME_SHARE_PCT": round(v30, 2),
        "FIRST_60M_VOLUME_SHARE_PCT": round(v60, 2),
        "LOW_TO_CLOSE_RETURN_PCT": round((clo / lo - 1.0) * 100.0, 4),
        "OPEN_TO_CLOSE_RETURN_PCT": round((clo / op - 1.0) * 100.0, 4),
        "CLOSE_LOCATION": round((clo - lo) / (hi - lo), 3) if hi > lo else None,
        "PM_RETURN_PCT": round(pm_return, 4) if pm_return is not None else None,
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
    df.to_csv(OUT / "metrics_v01c.csv", index=False)
    df.to_csv(REPO_OUT / "metrics_v01c.csv", index=False)
    focus = [
        "symbol",
        "event_date",
        "LOW_TIME",
        "LOW_TO_OPEN_RECLAIM_MIN",
        "POST_LOW_VWAP_STATE",
        "POST_LOW_VWAP_RECLAIM_TIME",
        "VWAP_RECLAIM_COUNT_AFTER_POST_LOW",
        "VWAP_REBREAK_COUNT_AFTER_POST_LOW",
        "PCT_ABOVE_VWAP_NEXT_15M",
        "PCT_ABOVE_VWAP_NEXT_30M",
        "NEW_LOW_AFTER_POST_LOW_RECLAIM",
        "FIRST_PREV_CLOSE_RECLAIM_TIME",
        "PREV_CLOSE_REBREAK_COUNT",
        "SECOND_PREV_CLOSE_RECLAIM_TIME",
        "PCT_ABOVE_PREV_CLOSE_NEXT_15M",
        "PCT_ABOVE_PREV_CLOSE_NEXT_30M",
        "PREV_CLOSE_HOLD_15M",
        "PREV_CLOSE_HOLD_30M",
        "FINAL_CLOSE_ABOVE_PREV_CLOSE",
        "TIME_ABOVE_PREV_CLOSE_AFTER_FIRST_RECLAIM_PCT",
        "PM_RETURN_PCT",
        "CLOSE_LOCATION",
    ]
    pd.set_option("display.width", 300)
    print(df[focus].to_string(index=False))


if __name__ == "__main__":
    main()
