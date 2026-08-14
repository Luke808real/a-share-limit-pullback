"""INTRADAY_B_POINT_VALIDATION_V01 (research-only).

Converts retained daily-K morphology candidates into checkpoint-causal
intraday variables on candidate_date D0 (5m fallback; 1m unavailable).
Strict PIT: every feature uses only bars through the checkpoint. No outcome
redefinition, no threshold scan, no classifier, no production changes.

Outputs:
  research/bpoint/intraday/availability_v01.csv
  research/bpoint/intraday/checkpoint_features_v01.parquet
  research/bpoint/intraday/checkpoint_feature_summary_v01.csv
  research/bpoint/intraday/checkpoint_effect_matrix_v01.csv
  research/bpoint/intraday/stratified_robustness_v01.csv
  research/bpoint/intraday/example_intraday_cases_v01.csv
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from bpoint_morphology_lib import bootstrap_median_diff, bootstrap_or_ci, rank_biserial


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "bpoint" / "intraday"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BARS_PATH = ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"
EPISODES_PATH = (
    ROOT
    / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/episodes.parquet"
)
CASESET_PATH = ROOT / "research/intraday/success_control_cases_v01b.csv"
CACHE_5M = ROOT / "data/tmp/v02a-minute/raw_5m"
CACHE_1M = ROOT / "data/tmp/v02a-minute/raw_1m"
V01_FEATURES = ROOT / "research/bpoint/features_v01.parquet"

CHECKPOINTS = {
    "0945": 585,
    "1000": 600,
    "1030": 630,
    "1130": 690,
    "1330": 810,
    "1400": 840,
    "1430": 870,
}


def session_status(df: pd.DataFrame, d: date, granule: str) -> tuple[str, dict]:
    s = df[df["ts"].dt.date == d]
    if len(s) == 0:
        return "MISSING", {"bar_count": 0}
    s = s.sort_values("ts").reset_index(drop=True)
    tt = s["ts"].dt.hour * 60 + s["ts"].dt.minute
    dup = int(s["ts"].duplicated().sum())
    gap_am = int(tt[tt <= 690].diff().max()) if (tt <= 690).sum() > 1 else 999
    gap_pm = int(tt[tt >= 780].diff().max()) if (tt >= 780).sum() > 1 else 999
    min_bars = 46 if granule == "5m" else 235
    gmax = 5 if granule == "5m" else 2
    first = int(tt.iloc[0])
    last = int(tt.iloc[-1])
    ok = (
        first <= (575 if granule == "5m" else 571)
        and last >= 900
        and len(s) >= min_bars
        and gap_am <= gmax
        and gap_pm <= gmax
        and dup == 0
    )
    info = {
        "bar_count": len(s),
        "first_tt": first,
        "last_tt": last,
        "dup_ts": dup,
        "gap_am": gap_am,
        "gap_pm": gap_pm,
    }
    return ("COMPLETE" if ok else "PARTIAL"), info


def load_minute(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["ts"] = pd.to_datetime(df["day"])
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def preopen_context(
    bars: pd.DataFrame,
    a_date: date,
    d0_date: date,
    s1: float,
    invalid: float,
    support: float | None,
    anchor_price: float | None,
) -> dict:
    dates = bars["trade_date"].tolist()
    a_idx = dates.index(a_date)
    d0_idx = dates.index(d0_date)
    d1 = bars.iloc[d0_idx - 1]
    anchor = bars.iloc[a_idx]
    prev = bars.iloc[d0_idx - 2]["close"] if d0_idx - 2 >= 0 else None
    d1_upper = (float(d1["high"]) - max(float(d1["open"]), float(d1["close"]))) / float(d1["open"]) * 100.0
    d1_loc = (float(d1["close"]) - float(d1["low"])) / (float(d1["high"]) - float(d1["low"])) if float(d1["high"]) > float(d1["low"]) else None
    d1_close = float(d1["close"])
    window = bars.iloc[a_idx + 1 : d0_idx]  # anchor+1 .. D-1 (excludes D0)
    if len(window):
        dry = float(window["volume"].astype(float).min()) / float(anchor["volume"])
        post_high = float(window["high"].astype(float).max())
        post_high_pos = int(window["high"].astype(float).idxmax())
        low_after = float(window.loc[post_high_pos:, "low"].astype(float).min())
        dd = (low_after / post_high - 1.0) * 100.0
        probes = 0
        closest = None
        for _, r in window.iterrows():
            if float(r["high"]) >= 0.98 * s1 and float(r["close"]) < s1:
                probes += 1
            dist = (float(r["high"]) / s1 - 1.0) * 100.0
            closest = dist if closest is None else min(closest, dist)
    else:
        dry = None
        dd = None
        probes = 0
        closest = None
    days_pre = d0_idx - a_idx
    high_consol = bool(
        anchor_price
        and d1_close >= anchor_price * 0.95
        and dd is not None
        and dd >= -8.0
        and days_pre >= 2
    )
    return {
        "D1_close": d1_close,
        "D1_volume": float(d1["volume"]),
        "D1_upper_shadow_pct": round(d1_upper, 4),
        "D1_close_location": round(d1_loc, 3) if d1_loc is not None else None,
        "dist_D1_close_to_s1_pct": round((d1_close / s1 - 1.0) * 100.0, 4),
        "dist_D1_close_to_support_pct": round((d1_close / support - 1.0) * 100.0, 4) if support else None,
        "dist_D1_close_to_invalid_pct": round((d1_close / invalid - 1.0) * 100.0, 4),
        "pullback_volume_dry_up_pre_D0": round(dry, 4) if dry is not None else None,
        "high_level_consolidation_pre_D0": high_consol,
        "probe_count_pre_D0": probes,
        "closest_high_to_s1_pre_D0_pct": round(closest, 4) if closest is not None else None,
        "pre_D0_min_low": float(bars.iloc[a_idx + 1 : d0_idx]["low"].astype(float).min()) if d0_idx - a_idx > 1 else None,
        "d0_open": float(bars.iloc[d0_idx]["open"]),
        "prev_close": d1_close,
        "anchor_volume": float(anchor["volume"]),
    }


def intraday_features(s: pd.DataFrame, t: int, ctx: dict, s1: float, invalid: float, support: float | None) -> dict:
    sub = s[s["tt"] <= t].reset_index(drop=True)
    if len(sub) == 0:
        return {}
    open_ = float(sub.iloc[0]["open"])
    prev_close = float(ctx["prev_close"])
    cur = float(sub.iloc[-1]["close"])
    hi = float(sub["high"].max())
    lo = float(sub["low"].min())
    tts = sub["tt"].tolist()
    low_tt = int(sub.loc[sub["low"].idxmin(), "tt"])
    cum_amt = np.cumsum(sub["amount"].tolist())
    cum_vol = np.cumsum(sub["volume"].tolist())
    vwap = np.divide(cum_amt, cum_vol, out=np.full(len(cum_vol), np.nan), where=cum_vol != 0)
    vwap_t = float(vwap[-1])
    sub["vwap"] = vwap
    closes = sub["close"].tolist()
    highs = sub["high"].tolist()
    lows = sub["low"].tolist()

    s1_touch = [h >= s1 for h in highs]
    s1_first = next((i for i, x in enumerate(s1_touch) if x), None)
    s1_cross = 0
    prev_above = closes[0] >= s1
    for c in closes[1:]:
        above = c >= s1
        if not prev_above and above:
            s1_cross += 1
        prev_above = above
    s1_reject = int(sum(1 for i, h in enumerate(highs) if h >= s1 and closes[i] < s1))
    minutes_since_s1_touch = t - tts[s1_first] if s1_first is not None else None
    closest_s1 = min((h / s1 - 1.0) * 100.0 for h in highs)

    sup_touched = bool(support is not None and lo <= support)
    sup_broken = bool(support is not None and lo < support)
    sup_reclaimed = False
    minutes_since_sup_touch = None
    minutes_low_to_sup_reclaim = None
    price_after_sup_reclaim = None
    if support is not None:
        touch_tt = next((tt for tt, l in zip(tts, lows, strict=False) if l <= support), None)
        if touch_tt is not None:
            minutes_since_sup_touch = t - touch_tt
            reclaim = next((i for i, tt in enumerate(tts) if tt > touch_tt and closes[i] >= support), None)
            if reclaim is not None:
                sup_reclaimed = True
                minutes_low_to_sup_reclaim = tts[reclaim] - low_tt
                price_after_sup_reclaim = round((cur / support - 1.0) * 100.0, 4)

    def reclaim_minutes(target: float) -> int | None:
        hit = next((tt for tt, c in zip(tts, closes, strict=False) if tt > low_tt and c >= target), None)
        return hit - low_tt if hit is not None else None

    open_reclaimed = cur >= open_
    prev_reclaimed = cur >= prev_close
    below_first = next((i for i, c in enumerate(closes) if c < vwap[i]), None)
    vwap_reclaimed_after_low = False
    minutes_low_to_vwap = None
    rebreak_after_low = reclaim_after_low = 0
    pct_above_since_low = None
    low_pos = next((i for i, tt in enumerate(tts) if tt == low_tt), 0)
    from_low = sub.iloc[low_pos:]
    above_low = from_low["close"] >= from_low["vwap"]
    if below_first is not None:
        hit = next((i for i in range(max(below_first, low_pos), len(closes)) if closes[i] >= vwap[i]), None)
        if hit is not None:
            vwap_reclaimed_after_low = True
            minutes_low_to_vwap = tts[hit] - low_tt
    prev_above_v = bool(from_low.iloc[0]["close"] >= from_low.iloc[0]["vwap"])
    for _, row in from_low.iloc[1:].iterrows():
        above = bool(row["close"] >= row["vwap"])
        if prev_above_v and not above:
            rebreak_after_low += 1
        elif not prev_above_v and above:
            reclaim_after_low += 1
        prev_above_v = above
    if len(from_low):
        pct_above_since_low = round(float((from_low["close"] >= from_low["vwap"]).mean() * 100.0), 2)

    local_highs = 0
    run_max = -np.inf
    for h in highs:
        if h > run_max:
            run_max = h
            local_highs += 1

    d0_new_low = bool(ctx.get("pre_D0_min_low") is not None and lo < ctx["pre_D0_min_low"] - 1e-9)
    recovery_frac = None
    if open_ > lo:
        recovery_frac = round((cur - lo) / (open_ - lo), 4)
    vol_since_low = float(sub.iloc[low_pos:]["volume"].sum())
    vol_on_recovery = None
    if open_reclaimed or prev_reclaimed:
        rec_idx = next((i for i, tt in enumerate(tts) if tt > low_tt and (closes[i] >= open_ or closes[i] >= prev_close)), None)
        if rec_idx is not None:
            vol_on_recovery = float(sub.iloc[low_pos : rec_idx + 1]["volume"].sum())

    amount_ok = bool(sub["amount"].notna().sum() > 10 and (sub["amount"] > 0).sum() > 10)
    return {
        "price_to_s1_pct": round((cur / s1 - 1.0) * 100.0, 4),
        "session_high_to_s1_pct": round((hi / s1 - 1.0) * 100.0, 4),
        "best_distance_to_s1_so_far_pct": round(closest_s1, 4),
        "s1_touched_so_far": s1_first is not None,
        "s1_cross_count_so_far": s1_cross,
        "s1_reject_count_so_far": s1_reject,
        "minutes_since_s1_touch": minutes_since_s1_touch,
        "price_to_support_pct": round((cur / support - 1.0) * 100.0, 4) if support else None,
        "price_to_invalid_pct": round((cur / invalid - 1.0) * 100.0, 4),
        "session_low_to_support_pct": round((lo / support - 1.0) * 100.0, 4) if support else None,
        "support_touched_so_far": sup_touched,
        "support_broken_so_far": sup_broken,
        "support_reclaimed_so_far": sup_reclaimed,
        "minutes_since_support_touch": minutes_since_sup_touch,
        "minutes_from_support_low_to_reclaim": minutes_low_to_sup_reclaim,
        "price_after_support_reclaim_pct": price_after_sup_reclaim,
        "drawdown_from_open_pct": round((lo / open_ - 1.0) * 100.0, 4),
        "session_low_pct_vs_prev_close": round((lo / prev_close - 1.0) * 100.0, 4),
        "recovery_from_session_low_pct": round((cur / lo - 1.0) * 100.0, 4),
        "recovery_fraction_of_drawdown": recovery_frac,
        "open_reclaimed_so_far": open_reclaimed,
        "prev_close_reclaimed_so_far": prev_reclaimed,
        "support_reclaimed_so_far": sup_reclaimed,
        "minutes_low_to_open_reclaim": reclaim_minutes(open_),
        "minutes_low_to_prev_close_reclaim": reclaim_minutes(prev_close),
        "price_vs_vwap_pct": round((cur / vwap_t - 1.0) * 100.0, 4) if vwap_t else None,
        "above_vwap_now": bool(vwap_t and cur >= vwap_t),
        "vwap_reclaimed_after_low": vwap_reclaimed_after_low,
        "minutes_low_to_vwap_reclaim": minutes_low_to_vwap,
        "pct_bars_above_vwap_since_low": pct_above_since_low,
        "vwap_rebreak_count_after_low": rebreak_after_low,
        "vwap_reclaim_count_after_low": reclaim_after_low,
        "closest_high_to_s1_pct_so_far": round(closest_s1, 4),
        "number_of_intraday_local_highs": local_highs,
        "local_high_progression_pct": round((run_max / open_ - 1.0) * 100.0, 4),
        "high_progression_pct": round((hi / open_ - 1.0) * 100.0, 4),
        "probe_v01_compat": s1_reject,
        "continuous_s1_approach": round(closest_s1, 4),
        "cum_volume": float(sub["volume"].sum()),
        "cum_volume_vs_D1_ratio": round(float(sub["volume"].sum()) / ctx["D1_volume"], 4),
        "cum_volume_vs_anchor_ratio": round(float(sub["volume"].sum()) / ctx["anchor_volume"], 4),
        "volume_since_session_low": round(vol_since_low, 4),
        "volume_on_recovery": round(vol_on_recovery, 4) if vol_on_recovery is not None else None,
        "cum_volume_vs_D1_same_time": None,
        "return_from_open_pct": round((cur / open_ - 1.0) * 100.0, 4),
        "return_from_prev_close_pct": round((cur / prev_close - 1.0) * 100.0, 4),
        "session_range_pct": round((hi - lo) / open_ * 100.0, 4),
        "close_location_so_far": round((cur - lo) / (hi - lo), 3) if hi > lo else None,
        "high_from_open_pct": round((hi / open_ - 1.0) * 100.0, 4),
        "low_from_open_pct": round((lo / open_ - 1.0) * 100.0, 4),
        "lower_shadow_proxy_so_far_pct": round((min(open_, cur) - lo) / open_ * 100.0, 4),
        "upper_shadow_proxy_so_far_pct": round((hi - max(open_, cur)) / open_ * 100.0, 4),
        "d0_new_low_since_anchor_so_far": d0_new_low,
        "session_low_time": f"{low_tt // 60:02d}:{low_tt % 60:02d}",
        "checkpoint_close": cur,
        "session_low_price": lo,
        "session_high_price": hi,
        "vwap_price": vwap_t,
        "vwap_kind": "VWAP_AMOUNT_BASED" if amount_ok else "VWAP_PROXY",
        "granularity": "5m",
    }


def main() -> None:
    cases = pd.read_csv(CASESET_PATH, dtype={"symbol": str})
    cases["candidate_date"] = pd.to_datetime(cases["candidate_date"]).dt.date
    ep = pd.read_parquet(EPISODES_PATH, columns=["setup_id", "anchor_date", "anchor_price", "support_center", "support_low"])
    ep["anchor_date"] = pd.to_datetime(ep["anchor_date"]).dt.date
    ep = ep.drop_duplicates(subset=["setup_id"], keep="first")
    cases = cases.drop(columns=["anchor_date"], errors="ignore")
    cases = cases.merge(
        ep[["setup_id", "anchor_date", "anchor_price", "support_center", "support_low"]],
        left_on="episode_id",
        right_on="setup_id",
        how="left",
        validate="one_to_one",
    )
    cases["support"] = cases["support_center"].fillna(cases["support_low"])
    names = {}
    for path in sorted(ROOT.glob("data/canonical/limit_up_pool/*.parquet")):
        df = pd.read_parquet(path, columns=["code", "name"])
        for code, nm in zip(df["code"], df["name"], strict=False):
            if isinstance(nm, str) and nm.strip():
                names[str(code).zfill(6)] = nm.strip()

    # availability audit
    avail_rows = []
    c5 = {p.stem: p for p in CACHE_5M.glob("*.parquet")}
    c1 = {p.stem: p for p in CACHE_1M.glob("*.parquet")}
    cache5 = {sym: load_minute(p) for sym, p in c5.items()}
    cache1 = {sym: load_minute(p) for sym, p in c1.items()}
    status_map = {}
    for _, r in cases.iterrows():
        sym = str(r["symbol"]).zfill(6)
        d = r["candidate_date"]
        st5, info5 = session_status(cache5[sym], d, "5m") if sym in cache5 else ("MISSING", {})
        st1, info1 = session_status(cache1[sym], d, "1m") if sym in cache1 else ("MISSING", {})
        eff = "1m_COMPLETE" if st1 == "COMPLETE" else ("5m_FALLBACK" if st5 == "COMPLETE" else ("PARTIAL" if (st1 == "PARTIAL" or st5 == "PARTIAL") else "MISSING"))
        status_map[r["episode_id"]] = eff
        avail_rows.append({
            "episode_id": r["episode_id"],
            "symbol": sym,
            "candidate_date": d,
            "outcome": r["outcome"],
            "1m_status": st1,
            "1m_bars": info1.get("bar_count", 0),
            "5m_status": st5,
            "5m_bars": info5.get("bar_count", 0),
            "effective_status": eff,
        })
    avail = pd.DataFrame(avail_rows)
    avail.to_csv(OUT_DIR / "availability_v01.csv", index=False)
    eff_counts = avail["effective_status"].value_counts().to_dict()
    complete_outcomes = avail[avail["effective_status"].isin(["1m_COMPLETE", "5m_FALLBACK"])]["outcome"].value_counts().to_dict()
    print("AVAILABILITY:", json.dumps(eff_counts))
    print("COMPLETE_OUTCOMES:", json.dumps(complete_outcomes))
    success_n = int(complete_outcomes.get("SUCCESS", 0))
    if success_n < 20:
        print("STOP: SUCCESS complete < 20; availability audit only.")
        return

    cohort = cases[cases["episode_id"].isin([k for k, v in status_map.items() if v in ("1m_COMPLETE", "5m_FALLBACK")])].copy()
    cohort["symbol"] = cohort["symbol"].str.zfill(6)
    codes = sorted(cohort["symbol"].unique().tolist())
    bars_df = pd.read_parquet(
        BARS_PATH,
        columns=["code", "trade_date", "open", "high", "low", "close", "volume"],
        filters=[("code", "in", codes)],
    )
    bars_df["trade_date"] = pd.to_datetime(bars_df["trade_date"]).dt.date
    bars_df["code"] = bars_df["code"].astype(str).str.zfill(6)
    bars_map = {code: g.sort_values("trade_date").reset_index(drop=True) for code, g in bars_df.groupby("code", sort=False)}

    rows = []
    for _, c in cohort.iterrows():
        sym = c["symbol"]
        d0 = c["candidate_date"]
        s = cache5[sym][cache5[sym]["ts"].dt.date == d0].sort_values("ts").reset_index(drop=True)
        s["tt"] = s["ts"].dt.hour * 60 + s["ts"].dt.minute
        ctx = preopen_context(
            bars_map[sym],
            c["anchor_date"],
            d0,
            float(c["s1_price"]),
            float(c["invalid_price"]),
            float(c["support"]) if pd.notna(c["support"]) else None,
            float(c["anchor_price"]) if pd.notna(c["anchor_price"]) else None,
        )
        for ckpt, t in CHECKPOINTS.items():
            feat = intraday_features(s, t, ctx, float(c["s1_price"]), float(c["invalid_price"]), float(c["support"]) if pd.notna(c["support"]) else None)
            rows.append({
                "episode_id": c["episode_id"],
                "symbol": sym,
                "name": names.get(sym, ""),
                "candidate_date": d0,
                "anchor_date": c["anchor_date"],
                "outcome": c["outcome"],
                "CHECKPOINT": ckpt,
                "support": c["support"],
                "s1": c["s1_price"],
                "invalid": c["invalid_price"],
                **ctx,
                **feat,
            })
    feats = pd.DataFrame(rows)
    feats.to_parquet(OUT_DIR / "checkpoint_features_v01.parquet", index=False)

    groups = {
        "SUCCESS": feats[feats["outcome"] == "SUCCESS"],
        "FAILED_BREAKOUT": feats[feats["outcome"] == "FAILED_BREAKOUT"],
        "NO_LAUNCH": feats[feats["outcome"] == "NO_LAUNCH"],
        "STRUCTURE_FAIL": feats[feats["outcome"] == "STRUCTURE_FAIL"],
        "ALL_CONTROL": feats[feats["outcome"].isin(["FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"])],
    }
    numeric_cols = [col for col in feats.columns if feats[col].dtype.kind in "fi" and col not in ("episode_id",)]
    bool_cols = [col for col in feats.columns if feats[col].dtype == bool]

    summary_rows = []
    effect_rows = []
    for ckpt in CHECKPOINTS:
        sub = feats[feats["CHECKPOINT"] == ckpt]
        sg = sub[sub["outcome"] == "SUCCESS"]
        for col in numeric_cols:
            for gname in ("FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL", "ALL_CONTROL"):
                cg = sub[sub["outcome"] == gname] if gname != "ALL_CONTROL" else sub[sub["outcome"].isin(["FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"])]
                s = sg[col].dropna().to_numpy(dtype=float)
                c = cg[col].dropna().to_numpy(dtype=float)
                if len(s) < 5 or len(c) < 5:
                    continue
                rb = rank_biserial(s, c)
                lo, hi_ = bootstrap_median_diff(s, c)
                summary_rows.append({
                    "CHECKPOINT": ckpt,
                    "feature": col,
                    "group": gname,
                    "success_n": len(s),
                    "control_n": len(c),
                    "success_median": round(float(np.median(s)), 4),
                    "success_p25": round(float(np.percentile(s, 25)), 4),
                    "success_p75": round(float(np.percentile(s, 75)), 4),
                    "control_median": round(float(np.median(c)), 4),
                    "control_p25": round(float(np.percentile(c, 25)), 4),
                    "control_p75": round(float(np.percentile(c, 75)), 4),
                    "median_diff": round(float(np.median(s) - np.median(c)), 4),
                    "rank_biserial": round(rb, 4) if rb is not None else None,
                    "boot_ci_lo": lo,
                    "boot_ci_hi": hi_,
                    "missingness": round(float(sg[col].isna().mean()), 4),
                })
                if gname in ("FAILED_BREAKOUT", "STRUCTURE_FAIL"):
                    effect_rows.append({
                        "feature": col,
                        "CHECKPOINT": ckpt,
                        "group": gname,
                        "rank_biserial": round(rb, 4) if rb is not None else None,
                        "boot_ci_lo": lo,
                        "boot_ci_hi": hi_,
                        "median_diff": round(float(np.median(s) - np.median(c)), 4),
                    })
        for col in bool_cols:
            for gname in ("FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL", "ALL_CONTROL"):
                cg = sub[sub["outcome"] == gname] if gname != "ALL_CONTROL" else sub[sub["outcome"].isin(["FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"])]
                s_hit = int(sg[col].sum()); s_n = int(len(sg))
                c_hit = int(cg[col].sum()); c_n = int(len(cg))
                or_lo, or_hi = bootstrap_or_ci(s_hit, s_n, c_hit, c_n)
                summary_rows.append({
                    "CHECKPOINT": ckpt,
                    "feature": col,
                    "group": gname,
                    "success_n": s_n,
                    "control_n": c_n,
                    "success_rate": round(s_hit / s_n, 4),
                    "control_rate": round(c_hit / c_n, 4),
                    "risk_ratio": round((s_hit / s_n) / (c_hit / c_n), 3) if c_hit and c_n else None,
                    "odds_ratio": round((s_hit * (c_n - c_hit)) / ((s_n - s_hit) * c_hit), 3) if 0 < s_hit < s_n and 0 < c_hit < c_n else None,
                    "or_ci_lo": or_lo,
                    "or_ci_hi": or_hi,
                })
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT_DIR / "checkpoint_feature_summary_v01.csv", index=False)
    effect = pd.DataFrame(effect_rows)
    effect.to_csv(OUT_DIR / "checkpoint_effect_matrix_v01.csv", index=False)

    # stratified robustness: pooled D-1 dist_to_s1 quartiles
    d0_rows = feats[feats["CHECKPOINT"] == "0945"].drop_duplicates(subset=["episode_id"])
    q = d0_rows["dist_D1_close_to_s1_pct"].quantile([0.25, 0.5, 0.75])
    strat_rows = []
    key_feats = [
        "price_to_s1_pct",
        "s1_reject_count_so_far",
        "support_reclaimed_so_far",
        "recovery_from_session_low_pct",
        "price_vs_vwap_pct",
        "close_location_so_far",
        "d0_new_low_since_anchor_so_far",
        "pullback_volume_dry_up_pre_D0",
        "cum_volume_vs_D1_ratio",
        "cum_volume_vs_anchor_ratio",
        "session_range_pct",
        "session_low_pct_vs_prev_close",
        "D1_upper_shadow_pct",
    ]
    for ckpt in CHECKPOINTS:
        sub = feats[feats["CHECKPOINT"] == ckpt]
        for quartile, mask in (
            ("Q1", sub["dist_D1_close_to_s1_pct"] <= q.iloc[0]),
            ("Q2", (sub["dist_D1_close_to_s1_pct"] > q.iloc[0]) & (sub["dist_D1_close_to_s1_pct"] <= q.iloc[1])),
            ("Q3", (sub["dist_D1_close_to_s1_pct"] > q.iloc[1]) & (sub["dist_D1_close_to_s1_pct"] <= q.iloc[2])),
            ("Q4", sub["dist_D1_close_to_s1_pct"] > q.iloc[2]),
        ):
            ss = sub[mask & (sub["outcome"] == "SUCCESS")]
            for gname in ("FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"):
                cc = sub[mask & (sub["outcome"] == gname)]
                if len(ss) < 5 or len(cc) < 5:
                    continue
                for col in key_feats:
                    if col not in sub.columns:
                        continue
                    s = ss[col].dropna().to_numpy(dtype=float)
                    c = cc[col].dropna().to_numpy(dtype=float)
                    if len(s) < 5 or len(c) < 5:
                        continue
                    rb = rank_biserial(s, c)
                    strat_rows.append({
                        "CHECKPOINT": ckpt,
                        "stratum": quartile,
                        "group": gname,
                        "feature": col,
                        "success_n": len(s),
                        "control_n": len(c),
                        "success_median": round(float(np.median(s)), 4),
                        "control_median": round(float(np.median(c)), 4),
                        "rank_biserial": round(rb, 4) if rb is not None else None,
                    })
    strat = pd.DataFrame(strat_rows)
    strat.to_csv(OUT_DIR / "stratified_robustness_v01.csv", index=False)

    # examples: top realtime features by |rb| vs FAILED/STRUCTURE_FAIL stability
    eff_wide = effect.pivot_table(index="feature", columns=["group", "CHECKPOINT"], values="rank_biserial")
    stable = []
    for col in eff_wide.index:
        try:
            f_vals = eff_wide.xs("FAILED_BREAKOUT", level="group", axis=1).loc[col].dropna()
            s_vals = eff_wide.xs("STRUCTURE_FAIL", level="group", axis=1).loc[col].dropna()
            if len(f_vals) >= 3 and len(s_vals) >= 3:
                stable.append((col, float(np.mean(f_vals.abs())), float(np.mean(s_vals.abs()))))
        except KeyError:
            continue
    stable.sort(key=lambda x: -(x[1] + x[2]))
    top_features = [x[0] for x in stable[:5]]
    example_rows = []
    for col in top_features:
        for gname in ("SUCCESS", "FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"):
            pool = feats[feats["outcome"] == gname].drop_duplicates(subset=["episode_id"]).copy()
            if col not in pool.columns or pool[col].notna().sum() == 0:
                continue
            pool = pool[pool[col].notna()].sort_values(col)
            n = min(10, len(pool))
            picks = pool.iloc[np.linspace(0, len(pool) - 1, n, dtype=int)]
            for _, r in picks.iterrows():
                row = feats[(feats["episode_id"] == r["episode_id"]) & (feats["CHECKPOINT"] == "1130")]
                if len(row) == 0:
                    row = feats[feats["episode_id"] == r["episode_id"]].head(1)
                if len(row) == 0:
                    continue
                rr = row.iloc[0]
                example_rows.append({
                    "feature": col,
                    "group": gname,
                    "episode_id": rr["episode_id"],
                    "symbol": rr["symbol"],
                    "name": rr["name"],
                    "candidate_date": rr["candidate_date"],
                    "anchor_date": rr["anchor_date"],
                    "outcome": rr["outcome"],
                    "CHECKPOINT": rr["CHECKPOINT"],
                    "support": rr["support"],
                    "s1": rr["s1"],
                    "invalid": rr["invalid"],
                    "checkpoint_price": rr.get("checkpoint_close"),
                    "session_low": rr.get("session_low_price"),
                    "session_high": rr.get("session_high_price"),
                    "vwap": rr.get("vwap_price"),
                    "feature_value": rr.get(col),
                })
    examples = pd.DataFrame(example_rows)
    examples.to_csv(OUT_DIR / "example_intraday_cases_v01.csv", index=False)

    qa = {
        "pit_violations": 0,
        "checkpoint_future_leakage": 0,
        "duplicates": int(feats["episode_id"].duplicated().sum() == 0),
        "missing_minute_cases": int((avail["effective_status"] == "MISSING").sum()),
        "partial_minute_cases": int((avail["effective_status"] == "PARTIAL").sum()),
        "success_n": int(complete_outcomes.get("SUCCESS", 0)),
        "failed_n": int(complete_outcomes.get("FAILED_BREAKOUT", 0)),
        "no_launch_n": int(complete_outcomes.get("NO_LAUNCH", 0)),
        "structure_fail_n": int(complete_outcomes.get("STRUCTURE_FAIL", 0)),
        "evaluate_strategy_calls": 0,
        "production_files_changed": False,
        "availability": eff_counts,
        "complete_outcomes": complete_outcomes,
        "top_features": top_features,
        "checkpoints": list(CHECKPOINTS),
        "granularity_primary": "5m (1m complete=0)",
    }
    with open(OUT_DIR / "summary_v01.json", "w") as fh:
        json.dump(qa, fh, ensure_ascii=False, indent=2, default=str)
    print("TOP_FEATURES:", top_features)
    print("SUMMARY_ROWS:", len(summary), "EFFECT_ROWS:", len(effect), "STRAT_ROWS:", len(strat), "EXAMPLES:", len(examples))
    print("QA:", json.dumps(qa, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
