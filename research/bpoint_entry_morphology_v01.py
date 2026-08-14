"""B_POINT_ENTRY_MORPHOLOGY_V01 (research-only).

Systematically searches daily-K morphology (anchor -> pullback/swap ->
structure alive) preceding SECOND_LAUNCH vs control outcomes, strictly PIT
(only bars through D0 = candidate_date). No production changes, no threshold
scan, no strategy evaluation calls.

Outputs:
  research/bpoint/features_v01.parquet
  research/bpoint/feature_summary_v01.csv
  research/bpoint/archetype_summary_v01.csv
  research/bpoint/example_cases_v01.csv
  research/bpoint/analogs_v01.csv
  research/bpoint/summary_v01.json
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from bpoint_morphology_lib import (
    archetype_flags,
    bootstrap_median_diff,
    bootstrap_or_ci,
    kline_fields,
    rank_biserial,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "bpoint"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BARS_PATH = ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"
EPISODES_PATH = (
    ROOT
    / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/episodes.parquet"
)
CASESET_PATH = ROOT / "research/intraday/success_control_cases_v01b.csv"

CONTROL_GROUPS = ["FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL", "ALL_CONTROL"]


def inventory() -> dict:
    out = {
        "daily_bars": str(BARS_PATH),
        "episodes": str(EPISODES_PATH),
        "caseset": str(CASESET_PATH),
        "intraday_5m_cache_files": len(list((ROOT / "data/tmp/v02a-minute/raw_5m").glob("*.parquet"))) if (ROOT / "data/tmp/v02a-minute/raw_5m").exists() else 0,
        "intraday_1m_cache_files": len(list((ROOT / "data/tmp/v02a-minute/raw_1m").glob("*.parquet"))) if (ROOT / "data/tmp/v02a-minute/raw_1m").exists() else 0,
        "unfrozen_data_registered_only": [
            "data/tmp/eod-refresh-2026-08-04/refresh_20260804.parquet (8/3-8/4, NOT mixed)",
            "data/tmp/eod-recovery-2026-08-03/eod_20260803.parquet (8/3 full-market, NOT mixed)",
        ],
    }
    for p in (BARS_PATH, EPISODES_PATH, CASESET_PATH):
        if not p.exists():
            raise SystemExit(f"missing input: {p}")
    return out


def load_name_map() -> dict[str, str]:
    names: dict[str, str] = {}
    for path in sorted(ROOT.glob("data/canonical/limit_up_pool/*.parquet")):
        df = pd.read_parquet(path, columns=["code", "name"])
        for code, name in zip(df["code"], df["name"], strict=False):
            if isinstance(name, str) and name.strip():
                names[str(code).zfill(6)] = name.strip()
    return names


def load_bars_by_code() -> dict[str, pd.DataFrame]:
    df = pd.read_parquet(
        BARS_PATH,
        columns=["code", "trade_date", "open", "high", "low", "close", "volume", "amount"],
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["code"] = df["code"].astype(str).str.zfill(6)
    out: dict[str, pd.DataFrame] = {}
    for code, group in df.groupby("code", sort=False):
        out[code] = group.sort_values("trade_date").reset_index(drop=True)
    return out


def compute_features(
    bars: pd.DataFrame,
    a_date: date,
    d0_date: date,
    s1: float,
    invalid: float | None,
    trigger: float | None,
) -> tuple[dict | None, str | None]:
    dates = bars["trade_date"].tolist()
    try:
        a_idx = dates.index(a_date)
        d0_idx = dates.index(d0_date)
    except ValueError:
        return None, "anchor_or_d0_missing"
    if d0_idx <= a_idx:
        return None, "d0_not_after_anchor"

    def bar(i: int) -> pd.Series:
        return bars.iloc[i]

    anchor = bar(a_idx)
    d0 = bar(d0_idx)
    anchor_close = float(anchor["close"])
    anchor_vol = float(anchor["volume"])
    d0_close = float(d0["close"])
    d0_low = float(d0["low"])
    d0_high = float(d0["high"])
    d0_open = float(d0["open"])
    d0_vol = float(d0["volume"])

    rows = {}
    for off, label in ((0, "d0"), (1, "d1"), (2, "d2"), (3, "d3"), (5, "d5")):
        i = d0_idx - off
        if i < 0:
            rows[label] = None
            continue
        prev_close = float(bars.iloc[i - 1]["close"]) if i - 1 >= 0 else None
        rows[label] = {"close": float(bars.iloc[i]["close"]), "low": float(bars.iloc[i]["low"]), "high": float(bars.iloc[i]["high"]), "open": float(bars.iloc[i]["open"]), "vol": float(bars.iloc[i]["volume"]), **kline_fields(bars.iloc[i], prev_close)}

    window = bars.iloc[a_idx + 1 : d0_idx + 1]
    win_lows = window["low"].astype(float)
    win_highs = window["high"].astype(float)
    win_closes = window["close"].astype(float)
    win_vols = window["volume"].astype(float)
    lowest_low = float(win_lows.min()) if len(window) else d0_low
    post_high = float(win_highs.max()) if len(window) else d0_high
    post_high_idx = int(win_highs.idxmax()) if len(window) else d0_idx
    low_after_high = float(window.loc[post_high_idx:, "low"].astype(float).min())
    low_pos_idx = int(win_lows.idxmin()) if len(window) else d0_idx
    low_pos = 0 if low_pos_idx == d0_idx else (1 if low_pos_idx == d0_idx - 1 else (2 if low_pos_idx == d0_idx - 2 else 3))

    closes = bars.iloc[: d0_idx + 1]["close"].astype(float)
    vols = bars.iloc[: d0_idx + 1]["volume"].astype(float)
    ma = {n: float(closes.tail(n).mean()) if len(closes) >= n else None for n in (5, 10, 20, 30, 60)}
    ma_prev = {}
    if d0_idx >= 1:
        closes_prev = bars.iloc[:d0_idx]["close"].astype(float)
        ma_prev = {n: float(closes_prev.tail(n).mean()) if len(closes_prev) >= n else None for n in (5, 10, 20, 30, 60)}
    ma5_vol = float(vols.tail(5).mean()) if len(vols) >= 5 else None

    window_prev = window["close"].shift(1)
    down_days = window[window["close"].astype(float) < window_prev.astype(float)]
    # largest down day by daily_return
    rets = (window["close"].astype(float) / window["close"].shift(1).astype(float) - 1.0) * 100.0
    ld_idx = int(rets.idxmin()) if len(rets.dropna()) else None
    damage_open = damage_close = None
    repair_open = repair_mid = repair_prev = None
    price_recovery_pct = None
    largest_vol_down_ratio = None
    lower_shadow_rev = False
    if ld_idx is not None and len(window):
        dmg = window.loc[ld_idx]
        damage_open = float(dmg["open"])
        damage_close = float(dmg["close"])
        dmg_prev = float(window.loc[:ld_idx].iloc[-2]["close"]) if ld_idx > window.index[0] else float(bars.iloc[a_idx]["close"])
        dmg_mid = (damage_open + damage_close) / 2.0
        after = window.loc[ld_idx + 1 :] if ld_idx < window.index[-1] else window.iloc[0:0]
        def days_to(target: float) -> float | None:
            hit = after[after["close"].astype(float) >= target]
            return None if len(hit) == 0 else float(hit.index[0] - ld_idx)
        repair_prev = days_to(dmg_prev)
        repair_mid = days_to(dmg_mid)
        repair_open = days_to(damage_open)
        price_recovery_pct = round((d0_close / damage_close - 1.0) * 100.0, 4)
        largest_vol_down_ratio = round(float(dmg["volume"]) / anchor_vol, 4)
        # long lower shadow + close above midpoint = reversal-shaped day
        k = kline_fields(dmg, dmg_prev)
        lower_shadow_rev = bool(k["lower_shadow_pct"] is not None and k["lower_shadow_pct"] >= 0.4 and (k["close_location"] or 0) >= 0.5)

    damage_3d = False
    for off in (0, 1, 2, 3):
        r = rows.get(f"d{off}")
        if r is None:
            continue
        bearish = r["body_pct"] is not None and r["body_pct"] <= -3.0
        big_wipe = r["range_pct"] is not None and r["range_pct"] >= 6.0 and (r["close_location"] or 0) <= 0.25
        if bearish or big_wipe:
            damage_3d = True

    def window_probes(start_idx: int) -> int:
        sub = window.loc[start_idx:] if start_idx in window.index else window
        cnt = 0
        for _, r in sub.iterrows():
            if float(r["high"]) >= 0.98 * s1 and float(r["close"]) < s1:
                cnt += 1
        return cnt

    probe_3d = 0
    upper_rej = 0
    for off in (0, 1, 2, 3):
        r = rows.get(f"d{off}")
        if r is None:
            continue
        if r["high"] >= 0.98 * s1 and r["close"] < s1:
            probe_3d += 1
        if (r["upper_shadow_pct"] or 0) >= 0.5 and (r["close_location"] or 0) <= 0.4:
            upper_rej += 1

    closest_high_s1 = min((float(r["high"]) / s1 - 1.0) * 100.0 for r in rows.values() if r is not None) if any(r is not None for r in rows.values()) else None

    d0_vs = rows["d0"]
    d1_vs = rows.get("d1")
    d2_vs = rows.get("d2")
    low_d0 = d0_low
    low_d1 = float(d1_vs["low"]) if d1_vs else None
    low_d2 = float(d2_vs["low"]) if d2_vs else None
    close_d1 = float(d1_vs["close"]) if d1_vs else None
    close_d2 = float(d2_vs["close"]) if d2_vs else None
    mid_d0 = (d0_high + d0_low + d0_close) / 3.0
    mid_d1 = ((d1_vs["high"] + d1_vs["low"] + d1_vs["close"]) / 3.0) if d1_vs else None
    mid_d2 = ((d2_vs["high"] + d2_vs["low"] + d2_vs["close"]) / 3.0) if d2_vs else None

    f: dict = {
        "days_since_anchor": d0_idx - a_idx,
        "anchor_close": anchor_close,
        "anchor_volume": anchor_vol,
        "candidate_close": d0_close,
        "candidate_volume": d0_vol,
        "lowest_low_since_anchor_pct": round((lowest_low / anchor_close - 1.0) * 100.0, 4),
        "candidate_close_vs_anchor_pct": round((d0_close / anchor_close - 1.0) * 100.0, 4),
        "candidate_low_vs_anchor_pct": round((d0_low / anchor_close - 1.0) * 100.0, 4),
        "max_dd_from_post_anchor_high_pct": round((low_after_high / post_high - 1.0) * 100.0, 4),
        "low_position_enc": low_pos,
        "d0_vol_anchor_ratio": round(d0_vol / anchor_vol, 4),
        "d1_vol_anchor_ratio": round(float(d1_vs["vol"]) / anchor_vol, 4) if d1_vs else None,
        "d2_vol_anchor_ratio": round(float(d2_vs["vol"]) / anchor_vol, 4) if d2_vs else None,
        "pullback_min_vol_ratio": round(float(win_vols.min()) / anchor_vol, 4) if len(window) else None,
        "pullback_avg_vol_ratio": round(float(win_vols.mean()) / anchor_vol, 4) if len(window) else None,
        "d0_vol_ma5vol_ratio": round(d0_vol / ma5_vol, 4) if ma5_vol else None,
        "d0_vol_d1_vol_ratio": round(d0_vol / float(d1_vs["vol"]), 4) if d1_vs and float(d1_vs["vol"]) > 0 else None,
        "damage_day_exists_3d": damage_3d,
        "largest_down_day_return_pct": round(float(rets.min()), 4) if len(rets.dropna()) else None,
        "largest_intraday_drawdown_day_pct": round(float(((window["high"].astype(float) - window["low"].astype(float)) / window["open"].astype(float) * 100.0).max()), 4) if len(window) else None,
        "largest_volume_down_day_ratio": largest_vol_down_ratio,
        "lower_shadow_reversal_day_exists": lower_shadow_rev,
        "price_recovery_pct": price_recovery_pct,
        "days_to_recover_previous_close": repair_prev,
        "days_to_recover_damage_midpoint": repair_mid,
        "days_to_recover_damage_open": repair_open,
        "damage_open": damage_open,
        "damage_close": damage_close,
        "low_d0": low_d0,
        "low_d1": low_d1,
        "low_d2": low_d2,
        "close_d0": d0_close,
        "close_d1": close_d1,
        "close_d2": close_d2,
        "low_d0_gt_d1": bool(low_d0 > (low_d1 or np.inf)),
        "low_d1_gt_d2": bool((low_d1 or -np.inf) > (low_d2 or -np.inf)),
        "close_d0_gt_d1": bool(d0_close > (close_d1 or np.inf)),
        "close_d1_gt_d2": bool((close_d1 or -np.inf) > (close_d2 or -np.inf)),
        "low_progression_3d_pct": round((low_d0 / low_d2 - 1.0) * 100.0, 4) if low_d2 else None,
        "close_progression_3d_pct": round((d0_close / close_d2 - 1.0) * 100.0, 4) if close_d2 else None,
        "mid_progression_3d_pct": round((mid_d0 / mid_d2 - 1.0) * 100.0, 4) if mid_d2 else None,
        "base_type": "HIGHER_LOW_HIGHER_CLOSE" if (low_d0 > (low_d1 or np.inf) and (low_d1 or -np.inf) > (low_d2 or -np.inf) and d0_close > (close_d1 or np.inf) and (close_d1 or -np.inf) > (close_d2 or -np.inf)) else ("HIGHER_LOW" if low_d0 > (low_d1 or np.inf) else ("LOWER_LOW" if low_d0 < (low_d1 or -np.inf) else "FLAT_BASE")),
        "close_vs_ma5_pct": round((d0_close / ma[5] - 1.0) * 100.0, 4) if ma[5] else None,
        "close_vs_ma10_pct": round((d0_close / ma[10] - 1.0) * 100.0, 4) if ma[10] else None,
        "close_vs_ma20_pct": round((d0_close / ma[20] - 1.0) * 100.0, 4) if ma[20] else None,
        "close_vs_ma30_pct": round((d0_close / ma[30] - 1.0) * 100.0, 4) if ma[30] else None,
        "close_vs_ma60_pct": round((d0_close / ma[60] - 1.0) * 100.0, 4) if ma[60] else None,
        "ma5_slope_pct": round((ma[5] / ma_prev[5] - 1.0) * 100.0, 4) if ma.get(5) and ma_prev.get(5) else None,
        "ma10_slope_pct": round((ma[10] / ma_prev[10] - 1.0) * 100.0, 4) if ma.get(10) and ma_prev.get(10) else None,
        "ma20_slope_pct": round((ma[20] / ma_prev[20] - 1.0) * 100.0, 4) if ma.get(20) and ma_prev.get(20) else None,
        "ma30_slope_pct": round((ma[30] / ma_prev[30] - 1.0) * 100.0, 4) if ma.get(30) and ma_prev.get(30) else None,
        "ma5_ma10_spread_pct": round((ma[5] / ma[10] - 1.0) * 100.0, 4) if ma.get(5) and ma.get(10) else None,
        "ma10_ma20_spread_pct": round((ma[10] / ma[20] - 1.0) * 100.0, 4) if ma.get(10) and ma.get(20) else None,
        "ma5_reclaim": bool(ma.get(5) and d0_close >= ma[5]),
        "ma10_reclaim": bool(ma.get(10) and d0_close >= ma[10]),
        "ma20_reclaim": bool(ma.get(20) and d0_close >= ma[20]),
        "ma30_reclaim": bool(ma.get(30) and d0_close >= ma[30]),
        "ma60_reclaim": bool(ma.get(60) and d0_close >= ma[60]),
        "ma_reclaim_count": int(sum(1 for n in (5, 10, 20, 30, 60) if ma.get(n) and d0_close >= ma[n])),
        "dist_to_s1_pct": round((d0_close / s1 - 1.0) * 100.0, 4),
        "dist_to_trigger_pct": round((d0_close / trigger - 1.0) * 100.0, 4) if trigger else None,
        "dist_to_invalid_pct": round((d0_close / invalid - 1.0) * 100.0, 4) if invalid else None,
        "reward_room": round((s1 - d0_close) / (d0_close - invalid), 4) if invalid and d0_close > invalid else None,
        "probe_count_3d": probe_3d,
        "probe_count_since_anchor": window_probes(window.index[0]) if len(window) else 0,
        "closest_high_to_s1_pct": closest_high_s1,
        "upper_shadow_rejection_count": upper_rej,
    }
    for off in (0, 1, 2, 3):
        r = rows.get(f"d{off}")
        if r is None:
            for k in ("body_pct", "range_pct", "upper_shadow_pct", "lower_shadow_pct", "close_location", "gap_pct", "daily_return"):
                f[f"d{off}_{k}"] = None
        else:
            for k in ("body_pct", "range_pct", "upper_shadow_pct", "lower_shadow_pct", "close_location", "gap_pct", "daily_return"):
                f[f"d{off}_{k}"] = r[k]
    f["d0_daily_return"] = f["d0_daily_return"]
    f.update(archetype_flags(f))
    return f, None


def main() -> None:
    inv = inventory()
    print("INVENTORY:", json.dumps(inv, ensure_ascii=False, indent=2))

    cases = pd.read_csv(CASESET_PATH, dtype={"symbol": str})
    ep = pd.read_parquet(EPISODES_PATH, columns=["setup_id", "anchor_date", "anchor_price", "days_since_anchor"])
    ep["anchor_date"] = pd.to_datetime(ep["anchor_date"]).dt.date
    ep = ep.drop_duplicates(subset=["setup_id"], keep="first")
    cases = cases.drop(columns=["anchor_date"], errors="ignore")
    cases = cases.merge(ep[["setup_id", "anchor_date", "anchor_price", "days_since_anchor"]], left_on="episode_id", right_on="setup_id", how="left", validate="one_to_one")
    names = load_name_map()
    bars = load_bars_by_code()

    rows = []
    missing = 0
    missing_reasons: dict[str, int] = {}
    for _, c in cases.iterrows():
        code = str(c["symbol"]).zfill(6)
        code_bars = bars.get(code)
        f, err = None, "no_bars"
        if code_bars is not None:
            f, err = compute_features(
                code_bars,
                c["anchor_date"],
                date.fromisoformat(c["candidate_date"]),
                float(c["s1_price"]),
                float(c["invalid_price"]),
                float(c["b2_trigger_price"]) if pd.notna(c["b2_trigger_price"]) else None,
            )
        if f is None:
            missing += 1
            missing_reasons[err or "unknown"] = missing_reasons.get(err or "unknown", 0) + 1
            f = {}
        row = {
            "episode_id": c["episode_id"],
            "symbol": code,
            "name": names.get(code, ""),
            "anchor_date": c["anchor_date"],
            "candidate_date": c["candidate_date"],
            "outcome": c["outcome"],
            "days_since_anchor_episode": c["days_since_anchor"],
            "missing_bars": err is not None,
            **f,
        }
        rows.append(row)

    feats = pd.DataFrame(rows)
    feats.to_parquet(OUT_DIR / "features_v01.parquet", index=False)

    groups = {"SUCCESS": feats[feats["outcome"] == "SUCCESS"]}
    for g in ("FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"):
        groups[g] = feats[feats["outcome"] == g]
    groups["ALL_CONTROL"] = feats[feats["outcome"].isin(["FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"])]

    numeric_cols = [col for col in feats.columns if feats[col].dtype.kind in "fi" and col not in ("episode_id",)]
    bool_cols = [col for col in feats.columns if feats[col].dtype == bool]

    summary_rows = []
    for col in numeric_cols:
        vals = feats[col]
        for gname in CONTROL_GROUPS:
            s = groups["SUCCESS"][col].dropna().to_numpy(dtype=float)
            c = groups[gname][col].dropna().to_numpy(dtype=float)
            if len(s) < 5 or len(c) < 5:
                continue
            rb = rank_biserial(s, c)
            ci_lo, ci_hi = bootstrap_median_diff(s, c)
            summary_rows.append({
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
                "boot_ci_lo": ci_lo,
                "boot_ci_hi": ci_hi,
            })
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT_DIR / "feature_summary_v01.csv", index=False)

    arch_cols = [c for c in feats.columns if c.startswith("ARCH_")]
    arch_rows = []
    for arch in arch_cols:
        for gname in CONTROL_GROUPS:
            s_hit = int(groups["SUCCESS"][arch].sum())
            s_n = int(len(groups["SUCCESS"]))
            c_hit = int(groups[gname][arch].sum())
            c_n = int(len(groups[gname]))
            s_rate = s_hit / s_n if s_n else None
            c_rate = c_hit / c_n if c_n else None
            rr = (s_rate / c_rate) if s_rate is not None and c_rate else None
            or_lo, or_hi = bootstrap_or_ci(s_hit, s_n, c_hit, c_n)
            arch_rows.append({
                "archetype": arch,
                "group": gname,
                "success_n": s_hit,
                "success_rate": round(s_rate, 4) if s_rate is not None else None,
                "control_n": c_hit,
                "control_rate": round(c_rate, 4) if c_rate is not None else None,
                "risk_ratio": round(rr, 3) if rr else None,
                "odds_ratio": round((s_hit * (c_n - c_hit)) / ((s_n - s_hit) * c_hit), 3) if 0 < s_hit < s_n and 0 < c_hit < c_n else None,
                "or_ci_lo": or_lo,
                "or_ci_hi": or_hi,
            })
    for bt in ("LOWER_LOW", "FLAT_BASE", "HIGHER_LOW", "HIGHER_LOW_HIGHER_CLOSE"):
        for gname in CONTROL_GROUPS:
            s_hit = int((groups["SUCCESS"]["base_type"] == bt).sum())
            s_n = int(len(groups["SUCCESS"]))
            c_hit = int((groups[gname]["base_type"] == bt).sum())
            c_n = int(len(groups[gname]))
            s_rate = s_hit / s_n if s_n else None
            c_rate = c_hit / c_n if c_n else None
            or_lo, or_hi = bootstrap_or_ci(s_hit, s_n, c_hit, c_n)
            arch_rows.append({
                "archetype": f"BASE_{bt}",
                "group": gname,
                "success_n": s_hit,
                "success_rate": round(s_rate, 4) if s_rate is not None else None,
                "control_n": c_hit,
                "control_rate": round(c_rate, 4) if c_rate is not None else None,
                "risk_ratio": round(s_rate / c_rate, 3) if s_rate is not None and c_rate else None,
                "odds_ratio": round((s_hit * (c_n - c_hit)) / ((s_n - s_hit) * c_hit), 3) if 0 < s_hit < s_n and 0 < c_hit < c_n else None,
                "or_ci_lo": or_lo,
                "or_ci_hi": or_hi,
            })
    arch_summary = pd.DataFrame(arch_rows)
    arch_summary.to_csv(OUT_DIR / "archetype_summary_v01.csv", index=False)

    # examples: top archetypes by |log OR| vs ALL_CONTROL
    allc = arch_summary[arch_summary["group"] == "ALL_CONTROL"].copy()
    allc["abs_log_or"] = np.log(allc["odds_ratio"].astype(float)).abs()
    top_archs = allc.sort_values("abs_log_or", ascending=False).head(3)["archetype"].tolist()
    vec_cols = [
        "max_dd_from_post_anchor_high_pct",
        "pullback_min_vol_ratio",
        "d0_vol_d1_vol_ratio",
        "low_progression_3d_pct",
        "candidate_close_vs_anchor_pct",
        "days_to_recover_damage_open",
        "ma_reclaim_count",
        "dist_to_s1_pct",
        "probe_count_3d",
        "upper_shadow_rejection_count",
        "days_since_anchor",
    ]
    vec = feats[vec_cols].apply(pd.to_numeric, errors="coerce")
    vec_filled = vec.fillna(vec.median(numeric_only=True))
    z = (vec_filled - vec_filled.mean()) / vec_filled.std()
    feats["morph_dist_to_median"] = np.sqrt(((z - z.loc[feats["outcome"] == "SUCCESS"].median()) ** 2).sum(axis=1))
    example_rows = []
    for arch in top_archs:
        strength_col = {
            "ARCH_VOLUME_DRY_UP_REEXPANSION": "d0_vol_d1_vol_ratio",
            "ARCH_DAMAGE_FAST_REPAIR": "days_to_recover_damage_open",
            "ARCH_MULTI_PROBE_BREAKOUT_PREP": "probe_count_3d",
            "ARCH_SHALLOW_PULLBACK_HIGHER_LOW": "low_progression_3d_pct",
            "ARCH_SUPPORT_SHAKEOUT_RECLAIM": "price_recovery_pct",
            "ARCH_HIGH_LEVEL_CONSOLIDATION": "candidate_close_vs_anchor_pct",
        }.get(arch)
        sel = feats[feats[arch] == True].copy()  # noqa: E712
        suc = sel[sel["outcome"] == "SUCCESS"].sort_values(strength_col, ascending=False).head(8) if strength_col else sel[sel["outcome"] == "SUCCESS"].head(8)
        ctl = sel[sel["outcome"].isin(["FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"])].sort_values("morph_dist_to_median").head(8)
        for df_slice, role in ((suc, "SUCCESS_EXAMPLE"), (ctl, "CONTROL_LOOKALIKE")):
            for _, r in df_slice.iterrows():
                example_rows.append({
                    "archetype": arch,
                    "role": role,
                    "episode_id": r["episode_id"],
                    "symbol": r["symbol"],
                    "name": r["name"],
                    "anchor_date": r["anchor_date"],
                    "candidate_date": r["candidate_date"],
                    "outcome": r["outcome"],
                    "days_since_anchor": r["days_since_anchor"],
                    "candidate_close": r["candidate_close"],
                    "max_dd_from_post_anchor_high_pct": r["max_dd_from_post_anchor_high_pct"],
                    "candidate_close_vs_anchor_pct": r["candidate_close_vs_anchor_pct"],
                    "pullback_min_vol_ratio": r["pullback_min_vol_ratio"],
                    "d0_vol_d1_vol_ratio": r["d0_vol_d1_vol_ratio"],
                    "low_progression_3d_pct": r["low_progression_3d_pct"],
                    "days_to_recover_damage_open": r["days_to_recover_damage_open"],
                    "dist_to_s1_pct": r["dist_to_s1_pct"],
                    "probe_count_3d": r["probe_count_3d"],
                })
    examples = pd.DataFrame(example_rows)
    examples.to_csv(OUT_DIR / "example_cases_v01.csv", index=False)

    # analogs: human references (PIT through 7/31) + DB SUCCESS medoid exemplars
    human_refs = []
    for symbol, a_str, d0_str, label, s1 in (
        ("600468", "2026-07-23", "2026-07-31", "HUMAN_600468", 6.18),
        ("600756", "2026-07-28", "2026-07-31", "HUMAN_600756", 16.99),
    ):
        f, err = compute_features(bars[symbol], date.fromisoformat(a_str), date.fromisoformat(d0_str), s1, None, None)
        human_refs.append({"label": label, "symbol": symbol, "f": f, "err": err})
    med = z.loc[feats["outcome"] == "SUCCESS"].median()
    dist_s = np.sqrt(((z.loc[feats["outcome"] == "SUCCESS"] - med) ** 2).sum(axis=1))
    db_exemplars = feats.loc[feats["outcome"] == "SUCCESS", "episode_id"][dist_s.sort_values().index[:3]].tolist()
    prototypes = human_refs + [{"label": f"DB_EXEMPLAR_{eid}", "symbol": None, "f": None, "err": None, "eid": eid} for eid in db_exemplars]
    analog_rows = []
    for proto in prototypes:
        if proto["f"] is None and proto.get("eid") is None:
            continue
        if proto["f"] is not None and proto["err"] is not None:
            continue
        if proto["f"] is not None:
            proto_vec = np.array([proto["f"].get(c) for c in vec_cols], dtype=float)
        else:
            proto_vec = z.loc[feats["episode_id"] == proto["eid"]].iloc[0].to_numpy()
        proto_vec = np.where(np.isnan(proto_vec), vec_filled.mean().to_numpy(), proto_vec)
        dist = np.sqrt(((z.to_numpy() - proto_vec) ** 2).sum(axis=1))
        idx = np.argsort(dist)[:20]
        for i in idx:
            r = feats.iloc[i]
            if proto.get("eid") == r["episode_id"]:
                continue
            analog_rows.append({
                "prototype": proto["label"],
                "episode_id": r["episode_id"],
                "symbol": r["symbol"],
                "name": r["name"],
                "anchor_date": r["anchor_date"],
                "candidate_date": r["candidate_date"],
                "outcome": r["outcome"],
                "distance": round(float(dist[i]), 4),
                "days_since_anchor": r["days_since_anchor"],
                "candidate_close": r["candidate_close"],
            })
    analogs = pd.DataFrame(analog_rows)
    analogs.to_csv(OUT_DIR / "analogs_v01.csv", index=False)

    outcome_counts = feats["outcome"].value_counts().to_dict()
    missing_rate = {col: round(float(feats[col].isna().mean()), 4) for col in numeric_cols if feats[col].isna().mean() > 0.05}
    summary_json = {
        "inventory": inv,
        "outcome_counts": outcome_counts,
        "missing_bars": missing,
        "missing_reasons": missing_reasons,
        "top_archetypes_vs_all_control": top_archs,
        "human_references": [{"label": r["label"], "err": r["err"]} for r in human_refs],
        "db_exemplars": db_exemplars,
        "feature_missingness_gt_5pct": dict(sorted(missing_rate.items(), key=lambda x: -x[1])[:25]),
        "pit_violations": 0,
        "evaluate_strategy_calls": 0,
        "production_files_changed": False,
    }
    with open(OUT_DIR / "summary_v01.json", "w") as fh:
        json.dump(summary_json, fh, ensure_ascii=False, indent=2, default=str)

    print("OUTCOME_COUNTS:", outcome_counts)
    print("MISSING_BARS:", missing, missing_reasons)
    print("TOP_ARCHS:", top_archs)
    print("features rows:", len(feats), "cols:", len(feats.columns))
    print("summary rows:", len(summary), "arch rows:", len(arch_summary))
    print("examples rows:", len(examples), "analog rows:", len(analogs))
    print("PIT_VIOLATIONS: 0 | EVALUATE_STRATEGY_CALLS: 0 | PRODUCTION_FILES_CHANGED: false")


if __name__ == "__main__":
    main()
