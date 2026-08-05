"""INTRADAY_SUCCESS_PATTERN_V02A_5M (research-only).

Compares SUCCESS vs FAILED_BREAKOUT on S1-attack event days using 5m data
up to fixed checkpoints (09:45 / 10:00 / 10:30 / 11:30). All features are
point-in-time (no data after the checkpoint). No threshold scan, no outcome
redefinition, no production changes.

Memory-bounded: raw_5m parquet is loaded per symbol and released after use.
"""

from __future__ import annotations

import json
import statistics
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INTRADAY_DIR = ROOT / "research" / "intraday"
CACHE_5M = ROOT / "data/tmp/v02a-minute/raw_5m"
CASES_CSV = INTRADAY_DIR / "success_control_cases_v01b.csv"
MANIFEST_CSV = INTRADAY_DIR / "v02a_minute_manifest.csv"
OUT_CSV = INTRADAY_DIR / "metrics_v02a_5m.csv"
OUT_JSON = INTRADAY_DIR / "metrics_v02a_5m.json"

CHECKPOINTS = {"0945": 585, "1000": 600, "1030": 630, "1130": 690}
CHECKPOINT_ORDER = ["0945", "1000", "1030", "1130"]


def load_5m(symbol: str) -> pd.DataFrame:
    df = pd.read_parquet(CACHE_5M / f"{symbol}.parquet")
    df["ts"] = pd.to_datetime(df["day"])
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def session_bars(df: pd.DataFrame, d: str) -> pd.DataFrame:
    s = df[df["ts"].dt.date == date.fromisoformat(d)].sort_values("ts").reset_index(drop=True)
    s["tt"] = s["ts"].dt.hour * 60 + s["ts"].dt.minute
    return s


def transition_counts(close_vals: list[float], ref_vals: list[float]) -> dict:
    """Counts BELOW->ABOVE (reclaim) and ABOVE->BELOW (rebreak) transitions.

    Previous state is seeded from the first bar (no shift-NaN artifact).
    """
    reclaims = 0
    rebreaks = 0
    prev_above = close_vals[0] >= ref_vals[0]
    for close, ref in zip(close_vals[1:], ref_vals[1:], strict=False):
        cur_above = close >= ref
        if prev_above and not cur_above:
            rebreaks += 1
        elif not prev_above and cur_above:
            reclaims += 1
        prev_above = cur_above
    return {"reclaim_count": reclaims, "rebreak_count": rebreaks}


def first_index_after(condition: list[bool], start: int) -> int | None:
    for i in range(start, len(condition)):
        if condition[i]:
            return i
    return None


def checkpoint_features(s: pd.DataFrame, t: int, prev_close: float, s1: float) -> dict:
    sub = s[s["tt"] <= t].reset_index(drop=True)
    open_ = float(sub.iloc[0]["open"])
    cur_close = float(sub.iloc[-1]["close"])
    highs = sub["high"].tolist()
    lows = sub["low"].tolist()
    closes = sub["close"].tolist()
    vols = sub["volume"].tolist()
    amounts = sub["amount"].tolist()
    tts = sub["tt"].tolist()

    cum_amt = np.cumsum(amounts)
    cum_vol = np.cumsum(vols)
    vwap_vals = np.divide(cum_amt, cum_vol, out=np.full(len(cum_vol), np.nan), where=cum_vol != 0)
    vwap_t = float(vwap_vals[-1])

    max_high = float(max(highs))
    min_low = float(min(lows))
    low_idx = int(sub["low"].idxmin())
    low_tt = int(tts[low_idx])

    above_vwap = [c >= v for c, v in zip(closes, vwap_vals.tolist(), strict=False)]
    vw_trans = transition_counts(closes, vwap_vals.tolist())
    vw_below_first = first_index_after([not a for a in above_vwap], 1)
    vw_first_reclaim = None
    if vw_below_first is not None:
        vw_first_reclaim = first_index_after(above_vwap, vw_below_first + 1)
    vw_second_reclaim = None
    if vw_first_reclaim is not None:
        first_rebreak = first_index_after(
            [not a for a in above_vwap], vw_first_reclaim + 1
        )
        if first_rebreak is not None:
            vw_second_reclaim = first_index_after(above_vwap, first_rebreak + 1)

    s1_above = [c >= s1 for c in closes]
    s1_touch = [h >= s1 for h in highs]
    s1_touched = any(s1_touch)
    s1_first_touch = first_index_after(s1_touch, 0)
    s1_first_touch_tt = tts[s1_first_touch] if s1_first_touch is not None else None
    s1_rebreak_count = None
    s1_reclaim_count = None
    s1_second_reclaim = None
    if s1_first_touch is not None:
        # state machine after the first touch (seeded from the touch bar's state)
        prev_above = s1_above[s1_first_touch]
        rebreaks = 0
        reclaims = 0
        seen_rebreak = False
        second_reclaim_seen = False
        for above in s1_above[s1_first_touch + 1 :]:
            if prev_above and not above:
                rebreaks += 1
                seen_rebreak = True
            elif not prev_above and above:
                reclaims += 1
                if seen_rebreak and not second_reclaim_seen:
                    second_reclaim_seen = True
            prev_above = above
        s1_rebreak_count = rebreaks
        s1_reclaim_count = reclaims
        s1_second_reclaim = second_reclaim_seen

    open_above = [c >= open_ for c in closes]
    open_below_first = first_index_after([not a for a in open_above], 1)
    open_reclaimed = False
    if open_below_first is not None:
        open_reclaimed = first_index_after(open_above, open_below_first + 1) is not None

    new_low_after_open_reclaim = None
    if open_below_first is not None and open_reclaimed:
        reclaim_idx = first_index_after(open_above, open_below_first + 1)
        assert reclaim_idx is not None
        post_min = min(lows[reclaim_idx + 1 :]) if reclaim_idx + 1 < len(lows) else None
        new_low_after_open_reclaim = bool(
            post_min is not None and post_min < min_low - 1e-9
        )

    # previous-checkpoint progression (relative to 09:45)
    ckpt_prev = CHECKPOINTS["0945"] if t > CHECKPOINTS["0945"] else None
    high_prog = low_prog = None
    if ckpt_prev is not None:
        prev_sub = s[(s["tt"] >= ckpt_prev) & (s["tt"] < t)]
        if len(prev_sub):
            high_prog = round((max_high / float(prev_sub["high"].max()) - 1.0) * 100.0, 4)
            low_prog = round((min_low / float(prev_sub["low"].min()) - 1.0) * 100.0, 4)

    return {
        "OPEN_GAP_PCT": round((open_ / prev_close - 1.0) * 100.0, 4),
        "DRAWDOWN_FROM_OPEN_PCT": round((min_low / open_ - 1.0) * 100.0, 4),
        "DRAWDOWN_FROM_PREV_CLOSE_PCT": round((min_low / prev_close - 1.0) * 100.0, 4),
        "CURRENT_RETURN_FROM_OPEN_PCT": round((cur_close / open_ - 1.0) * 100.0, 4),
        "CURRENT_RETURN_FROM_PREV_CLOSE_PCT": round((cur_close / prev_close - 1.0) * 100.0, 4),
        "VWAP_STATE": "ABOVE" if cur_close >= vwap_t else "BELOW",
        "DIST_TO_VWAP_PCT": round((cur_close / vwap_t - 1.0) * 100.0, 4),
        "VWAP_FIRST_RECLAIMED": vw_first_reclaim is not None,
        "VWAP_SECOND_RECLAIMED": vw_second_reclaim is not None,
        "VWAP_REBREAK_COUNT": vw_trans["rebreak_count"],
        "VWAP_RECLAIM_COUNT": vw_trans["reclaim_count"],
        "PREV_CLOSE_STATE": "ABOVE" if cur_close >= prev_close else "BELOW",
        "DIST_TO_PREV_CLOSE_PCT": round((cur_close / prev_close - 1.0) * 100.0, 4),
        "S1_STATE": "ABOVE" if cur_close >= s1 else "BELOW",
        "DIST_TO_S1_PCT": round((cur_close / s1 - 1.0) * 100.0, 4),
        "S1_TOUCHED_BY_CHECKPOINT": s1_touched,
        "S1_FIRST_TOUCH_MIN": s1_first_touch_tt - 570 if s1_first_touch_tt is not None else None,
        "MINUTES_SINCE_S1_TOUCH": t - s1_first_touch_tt if s1_first_touch_tt is not None else None,
        "S1_REBREAK_AFTER_TOUCH": bool(s1_rebreak_count) if s1_first_touch is not None else False,
        "S1_REBREAK_COUNT": s1_rebreak_count if s1_first_touch is not None else 0,
        "S1_RECLAIM_COUNT": s1_reclaim_count if s1_first_touch is not None else 0,
        "S1_SECOND_RECLAIMED": bool(s1_second_reclaim) if s1_first_touch is not None else False,
        "OPEN_SHAKE_RECLAIMED": open_reclaimed,
        "OPEN_RECLAIMED_NOW": cur_close >= open_,
        "NEW_LOW_AFTER_OPEN_RECLAIM": new_low_after_open_reclaim,
        "HIGH_FROM_OPEN_PCT": round((max_high / open_ - 1.0) * 100.0, 4),
        "LOW_FROM_OPEN_PCT": round((min_low / open_ - 1.0) * 100.0, 4),
        "TIME_OF_MORNING_LOW_MIN": low_tt - 570,
        "HIGH_PROGRESSION_PCT": high_prog,
        "LOW_PROGRESSION_PCT": low_prog,
        "CUM_VOLUME": float(sum(vols)),
        "CUM_VOLUME_VS_CANDIDATE_DAY_SAME_FRACTION": None,  # no PIT candidate-day minute data
    }


def standardized_diff(success: pd.Series, failed: pd.Series) -> float | None:
    s = success.dropna()
    f = failed.dropna()
    if len(s) < 2 or len(f) < 2:
        return None
    pooled = np.sqrt((s.std(ddof=1) ** 2 + f.std(ddof=1) ** 2) / 2.0)
    if pooled == 0:
        return None
    return float((s.mean() - f.mean()) / pooled)


def main() -> None:
    cases = pd.read_csv(CASES_CSV, dtype={"symbol": str})
    manifest = pd.read_csv(MANIFEST_CSV, dtype={"symbol": str})
    cohort = cases.merge(
        manifest[
            [
                "episode_id",
                "5M_FULL_SESSION_COMPLETE",
                "5M_OPEN_DIFF_PCT",
                "5M_HIGH_DIFF_PCT",
                "5M_LOW_DIFF_PCT",
                "5M_CLOSE_DIFF_PCT",
                "5M_OHLC_VALID",
            ]
        ],
        on="episode_id",
        how="inner",
        validate="one_to_one",
    )
    cohort = cohort[
        cohort["outcome"].isin(["SUCCESS", "FAILED_BREAKOUT"])
        & cohort["5M_FULL_SESSION_COMPLETE"]
    ].copy()
    final_success = int((cohort["outcome"] == "SUCCESS").sum())
    final_failed = int((cohort["outcome"] == "FAILED_BREAKOUT").sum())
    print("FINAL_COHORT_SUCCESS_N:", final_success)
    print("FINAL_COHORT_FAILED_N:", final_failed)

    # ---- FINAL DATA GATE ----
    gate = {}
    for col in ("5M_OPEN_DIFF_PCT", "5M_HIGH_DIFF_PCT", "5M_LOW_DIFF_PCT", "5M_CLOSE_DIFF_PCT"):
        vals = cohort[col].dropna().abs()
        gate[col] = {
            "MAX_ABS_DIFF": round(float(vals.max()), 4) if len(vals) else None,
            "MEDIAN_ABS_DIFF": round(float(vals.median()), 4) if len(vals) else None,
        }
    s1_mismatch_n = 0
    ohlc_invalid_n = 0
    checkpoint_missing_n = 0
    for _, c in cohort.iterrows():
        s = session_bars(load_5m(str(c["symbol"]).zfill(6)), c["OUTCOME_EVENT_DATE"])
        if not c["5M_OHLC_VALID"]:
            ohlc_invalid_n += 1
        if float(s["high"].max()) < float(c["s1_price"]) - 1e-6:
            s1_mismatch_n += 1
        for t in CHECKPOINTS.values():
            if int((s["tt"] == t).sum()) != 1:
                checkpoint_missing_n += 1
    gate["S1_TOUCH_MISMATCH_N"] = s1_mismatch_n
    gate["OHLC_INVALID_N"] = ohlc_invalid_n
    gate["CHECKPOINT_MISSING_N"] = checkpoint_missing_n
    gate["DATA_GATE_STATUS"] = (
        "PASS"
        if (
            s1_mismatch_n == 0
            and ohlc_invalid_n == 0
            and checkpoint_missing_n == 0
            and all(
                v["MAX_ABS_DIFF"] is not None and v["MAX_ABS_DIFF"] <= 1.0
                for v in gate.values()
                if isinstance(v, dict)
            )
        )
        else "STOP"
    )
    print("DATA_GATE_STATUS:", gate["DATA_GATE_STATUS"])
    print(json.dumps(gate, indent=2, default=str))
    if gate["DATA_GATE_STATUS"] != "PASS":
        raise SystemExit("STOP: final data gate failed; no features computed.")

    # ---- FEATURES ----
    rows = []
    for _, c in cohort.iterrows():
        s = session_bars(load_5m(str(c["symbol"]).zfill(6)), c["OUTCOME_EVENT_DATE"])
        prev_close = float(c["candidate_close"])
        s1 = float(c["s1_price"])
        for ckpt, t in CHECKPOINTS.items():
            feat = checkpoint_features(s, t, prev_close, s1)
            rows.append(
                {
                    "episode_id": c["episode_id"],
                    "symbol": str(c["symbol"]).zfill(6),
                    "outcome": c["outcome"],
                    "OUTCOME_EVENT_DATE": c["OUTCOME_EVENT_DATE"],
                    "EVENT_SESSION_OFFSET": c["EVENT_SESSION_OFFSET"],
                    "CHECKPOINT": ckpt,
                    **feat,
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False)

    # ---- COMPARISON ----
    summary = {}
    numeric_feats = [
        "OPEN_GAP_PCT",
        "DRAWDOWN_FROM_OPEN_PCT",
        "DRAWDOWN_FROM_PREV_CLOSE_PCT",
        "CURRENT_RETURN_FROM_OPEN_PCT",
        "CURRENT_RETURN_FROM_PREV_CLOSE_PCT",
        "DIST_TO_VWAP_PCT",
        "DIST_TO_PREV_CLOSE_PCT",
        "DIST_TO_S1_PCT",
        "S1_FIRST_TOUCH_MIN",
        "MINUTES_SINCE_S1_TOUCH",
        "VWAP_REBREAK_COUNT",
        "VWAP_RECLAIM_COUNT",
        "S1_REBREAK_COUNT",
        "HIGH_FROM_OPEN_PCT",
        "LOW_FROM_OPEN_PCT",
        "TIME_OF_MORNING_LOW_MIN",
        "HIGH_PROGRESSION_PCT",
        "LOW_PROGRESSION_PCT",
        "CUM_VOLUME",
    ]
    cat_feats = {
        "VWAP_STATE": "ABOVE",
        "PREV_CLOSE_STATE": "ABOVE",
        "S1_STATE": "ABOVE",
        "S1_TOUCHED_BY_CHECKPOINT": True,
        "VWAP_FIRST_RECLAIMED": True,
        "VWAP_SECOND_RECLAIMED": True,
        "S1_REBREAK_AFTER_TOUCH": True,
        "S1_SECOND_RECLAIMED": True,
        "OPEN_SHAKE_RECLAIMED": True,
        "OPEN_RECLAIMED_NOW": True,
        "NEW_LOW_AFTER_OPEN_RECLAIM": True,
    }
    for ckpt in CHECKPOINT_ORDER:
        sub = out[out["CHECKPOINT"] == ckpt]
        s_g = sub[sub["outcome"] == "SUCCESS"]
        f_g = sub[sub["outcome"] == "FAILED_BREAKOUT"]
        summary[ckpt] = {"success_n": len(s_g), "failed_n": len(f_g)}
        for feat in numeric_feats:
            s_med = s_g[feat].median()
            f_med = f_g[feat].median()
            d = standardized_diff(s_g[feat], f_g[feat])
            summary[ckpt][feat] = {
                "success_median": round(float(s_med), 4) if pd.notna(s_med) else None,
                "failed_median": round(float(f_med), 4) if pd.notna(f_med) else None,
                "success_iqr": (
                    [round(float(s_g[feat].quantile(0.25)), 4), round(float(s_g[feat].quantile(0.75)), 4)]
                    if len(s_g) else None
                ),
                "failed_iqr": (
                    [round(float(f_g[feat].quantile(0.25)), 4), round(float(f_g[feat].quantile(0.75)), 4)]
                    if len(f_g) else None
                ),
                "std_diff": round(d, 3) if d is not None else None,
            }
        for feat, pos in cat_feats.items():
            sr = round(float((s_g[feat] == pos).mean()), 4) if len(s_g) else None
            fr = round(float((f_g[feat] == pos).mean()), 4) if len(f_g) else None
            summary[ckpt][feat + "_rate"] = {
                "success_rate": sr,
                "failed_rate": fr,
                "rate_diff": round(sr - fr, 4) if sr is not None and fr is not None else None,
            }
    with open(OUT_JSON, "w") as fh:
        json.dump({"cohort": {"success_n": final_success, "failed_n": final_failed}, "gate": gate, "checkpoints": summary}, fh, ensure_ascii=False, indent=2, default=str)
    print("metrics written:", OUT_CSV, OUT_JSON)
    print("rows:", len(out), "checkpoints per outcome sample check:")
    print(pd.crosstab(out["CHECKPOINT"], out["outcome"]).to_string())


if __name__ == "__main__":
    main()
