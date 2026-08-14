"""B1 ENTRY SELECTION ATTRIBUTION v0.1 (research-only, no strategy change).

HYPOTHESIS: pre-entry structure (first attack, pullback quality, support/trend,
extension, reclaim) explains why some B1 episodes hit S1 first while most hit
invalid first.

Inputs (frozen):
  - corrected episodes SHA 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093
  - execution-reality episodes (canonical conservative 10bp)
  - snapshot snap-2026-07-31-b5f84004de8a daily bars

No evaluate_strategy / replay / screen / provider calls.
Output: data/tmp/entry-attribution-v01/metrics.json
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from limit_pullback.screen.canonical import (
    iter_canonical_code_bars,
    load_canonical_metadata,
)
from limit_pullback.warehouse.layout import WarehouseLayout


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
EPISODES = (
    DATA_ROOT
    / "outcome-study"
    / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome"
)
OUT_DIR = DATA_ROOT / "tmp" / "entry-attribution-v01"
SPLIT_DATE = date(2025, 7, 1)
MAX_HOLD = 10
PRE_WINDOW = 20


def load_episodes() -> pd.DataFrame:
    ep = pd.read_parquet(EPISODES / "episodes.parquet")
    ex = pd.read_parquet(EPISODES / "execution-reality" / "execution_episodes.parquet")
    df = ep.merge(ex, on=[c for c in ep.columns if c in ex.columns], how="inner")
    df = df[
        (df["fill_status"] == "FILLED")
        & (df["is_entry_candidate"] == True)  # noqa: E712
        & (df["execution_label"] == "B1_READY")
    ]
    df = df[df["fill_date"].notna() & df["s1_price"].notna() & df["invalid_price"].notna()]
    df = df.copy()
    for col in ("fill_date", "signal_date", "anchor_date"):
        df[col] = pd.to_datetime(df[col]).dt.date
    for col in ("fill_price", "invalid_price", "s1_price", "support_center", "anchor_price"):
        df[col] = pd.to_numeric(df[col].astype(str), errors="coerce")
    return df


def _pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    idx = (len(s) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    f = idx - lo
    return s[lo] * (1 - f) + s[hi] * f


def stats(vals):
    vals = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if len(vals) < 2:
        return None
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 4),
        "median": round(statistics.median(vals), 4),
        "p10": round(_pct(vals, 0.10), 4),
        "p90": round(_pct(vals, 0.90), 4),
        "std": round(statistics.pstdev(vals), 4),
    }


def cohens_d(a, b):
    a = [v for v in a if v is not None]
    b = [v for v in b if v is not None]
    if len(a) < 2 or len(b) < 2:
        return None
    sa = statistics.pstdev(a)
    sb = statistics.pstdev(b)
    pooled = math.sqrt((sa * sa + sb * sb) / 2)
    if pooled == 0:
        return None
    return round((statistics.fmean(a) - statistics.fmean(b)) / pooled, 3)


def odds_ratio(rate_w, rate_l):
    if rate_w in (None, 0, 1) or rate_l in (None, 0, 1):
        return None
    return round((rate_w / (1 - rate_w)) / (rate_l / (1 - rate_l)), 3)


def compute_episode_features(row, bars, idx_by_date):
    """All features use data <= signal_date (decision date); entry = fill price."""

    anchor_idx = idx_by_date.get(row["anchor_date"])
    sig_idx = idx_by_date.get(row["signal_date"])
    if anchor_idx is None or sig_idx is None or sig_idx < anchor_idx:
        return None
    fill_price = float(row["fill_price"])
    invalid = float(row["invalid_price"])
    s1 = float(row["s1_price"])
    feats = {
        "code": row["code"],
        "setup_id": row["setup_id"],
        "anchor_date": row["anchor_date"].isoformat(),
        "signal_date": row["signal_date"].isoformat(),
        "fill_date": row["fill_date"].isoformat(),
        "fill_price": fill_price,
        "invalid": invalid,
        "s1": s1,
        "fill_year": row["signal_date"].year,
        "period": "DISCOVERY" if row["signal_date"] < SPLIT_DATE else "VALIDATION",
    }

    def close(i):
        return float(bars[i].close)

    def ma(n, idx):
        if idx + 1 < n:
            return None
        return sum(close(i) for i in range(idx - n + 1, idx + 1)) / n

    def vol_ma20(idx):
        if idx < 20:
            return None
        return sum(float(bars[i].volume) for i in range(idx - 20, idx)) / 20

    sig_close = close(sig_idx)
    ma5, ma10, ma20, ma30 = ma(5, sig_idx), ma(10, sig_idx), ma(20, sig_idx), ma(30, sig_idx)
    feats["close_ma5_pct"] = (sig_close / ma5 - 1) * 100 if ma5 else None
    feats["close_ma10_pct"] = (sig_close / ma10 - 1) * 100 if ma10 else None
    feats["close_ma20_pct"] = (sig_close / ma20 - 1) * 100 if ma20 else None
    feats["close_ma30_pct"] = (sig_close / ma30 - 1) * 100 if ma30 else None
    for n in (5, 10, 20, 30):
        m_now = ma(n, sig_idx)
        m_prev = ma(n, max(0, sig_idx - 3))
        feats[f"ma{n}_slope_pct"] = (m_now / m_prev - 1) * 100 if m_now and m_prev else None
    feats["ma20_up"] = bool(feats["ma20_slope_pct"] and feats["ma20_slope_pct"] >= 0)
    feats["ma30_up"] = bool(feats["ma30_slope_pct"] and feats["ma30_slope_pct"] >= 0)
    feats["reclaim_ma5"] = bool(ma5 and sig_close >= ma5)
    feats["reclaim_ma10"] = bool(ma10 and sig_close >= ma10)
    feats["reclaim_ma20"] = bool(ma20 and sig_close >= ma20)
    feats["high20"] = max(float(bars[i].high) for i in range(max(0, sig_idx - 19), sig_idx + 1))
    feats["entry_ma20_pct"] = (fill_price / ma20 - 1) * 100 if ma20 else None
    feats["entry_high20_pct"] = (fill_price / feats["high20"] - 1) * 100
    anchor_close = float(bars[anchor_idx].close)
    anchor_high = float(bars[anchor_idx].high)
    feats["entry_anchor_close_pct"] = (fill_price / anchor_close - 1) * 100
    feats["entry_anchor_high_pct"] = (fill_price / anchor_high - 1) * 100
    if pd.notna(row["support_center"]) and row["support_center"]:
        feats["entry_support_center_pct"] = (fill_price / float(row["support_center"]) - 1) * 100

    # A. FIRST ATTACK in the 20 sessions before the formal limit-up anchor
    pre = list(range(max(0, anchor_idx - PRE_WINDOW), anchor_idx))
    pre_pcts = []
    pre_vol2x_days = 0
    consec_vol_attack = False
    for i in pre:
        pct = (close(i) / float(bars[i].preclose) - 1) * 100
        pre_pcts.append(pct)
        vm = vol_ma20(i)
        if vm and float(bars[i].volume) >= 2 * vm:
            pre_vol2x_days += 1
    day7 = any(p >= 7 for p in pre_pcts)
    cum2 = any(
        pre_pcts[j] + pre_pcts[j + 1] >= 10 for j in range(len(pre_pcts) - 1)
    )
    for j in range(len(pre) - 1):
        vm_j = vol_ma20(pre[j])
        vm_j1 = vol_ma20(pre[j + 1])
        if (
            vm_j
            and vm_j1
            and float(bars[pre[j]].volume) >= 2 * vm_j
            and float(bars[pre[j + 1]].volume) >= 2 * vm_j1
            and pre_pcts[j] > 0
            and pre_pcts[j + 1] > 0
        ):
            consec_vol_attack = True
    feats["pre_day7"] = bool(day7)
    feats["pre_cum2"] = bool(cum2)
    feats["pre_vol2x"] = pre_vol2x_days > 0
    feats["pre_consec_vol_attack"] = consec_vol_attack
    feats["pre_attack_present"] = bool((day7 or cum2) and pre_vol2x_days > 0)

    # B. PULLBACK QUALITY: anchor(day+1)..signal
    post = list(range(anchor_idx + 1, sig_idx + 1))
    if post:
        lows = [float(bars[i].low) for i in post]
        feats["pullback_max_dd_pct"] = (min(lows) / anchor_high - 1) * 100
        anchor_vol = float(bars[anchor_idx].volume)
        vols = [float(bars[i].volume) for i in post]
        feats["vol_post_anchor_ratio"] = statistics.fmean(vols) / anchor_vol if anchor_vol else None
        post_max = max(vols)
        feats["recent_vol_ratio"] = (statistics.fmean(vols[-5:]) / post_max) if len(vols) >= 5 else None
        up_v = [v for i, v in zip(post, vols) if close(i) >= float(bars[i].preclose)]
        dn_v = [v for i, v in zip(post, vols) if close(i) < float(bars[i].preclose)]
        feats["down_up_vol_ratio"] = (statistics.fmean(dn_v) / statistics.fmean(up_v)) if up_v and dn_v else None
        shrink = run = 0
        for j in range(1, len(vols)):
            run = run + 1 if vols[j] < vols[j - 1] else 0
            shrink = max(shrink, run)
        feats["consec_shrink_days"] = shrink
        big_vol_down = 0
        for i in post:
            vm = vol_ma20(i)
            if vm and float(bars[i].volume) >= 2 * vm and close(i) < float(bars[i].preclose):
                big_vol_down += 1
        feats["big_vol_down_days"] = big_vol_down
    feats["days_since_anchor"] = len(post)

    # E. ATTACK -> WASHOUT -> RECLAIM (attack = first pre-attack day else anchor)
    attack_idx = None
    for i in pre:
        if (close(i) / float(bars[i].preclose) - 1) * 100 >= 7:
            attack_idx = i
            break
    if attack_idx is None and feats["pre_cum2"]:
        attack_idx = pre[0]
    if attack_idx is None:
        attack_idx = anchor_idx
    attack_high = float(bars[attack_idx].high)
    win = list(range(attack_idx + 1, sig_idx + 1))
    if win:
        feats["attack_high_dd_pct"] = (min(float(bars[i].low) for i in win) / attack_high - 1) * 100
        pre_vm = vol_ma20(attack_idx) or 1
        rolls = []
        for j in range(len(win) - 4):
            rolls.append(
                statistics.fmean(float(bars[win[j + k]].volume) for k in range(5))
                / pre_vm
            )
        feats["washout_min_vol_ratio"] = min(rolls) if rolls else None
        mid = (attack_high + float(bars[attack_idx].low)) / 2
        feats["reclaim_attack_mid"] = bool(sig_close >= mid)
        platform = max(float(bars[i].high) for i in win[:-1]) if len(win) > 1 else None
        feats["reclaim_platform"] = bool(platform and sig_close >= platform)

    # path label: first of S1 / invalid within 10 sessions after fill (T+1)
    fill_idx = idx_by_date.get(row["fill_date"])
    t_s1 = t_inv = None
    if fill_idx is not None:
        for idx in range(fill_idx + 1, min(len(bars), fill_idx + MAX_HOLD + 1)):
            if t_s1 is None and float(bars[idx].high) >= s1:
                t_s1 = idx - fill_idx
            if t_inv is None and float(bars[idx].low) <= invalid:
                t_inv = idx - fill_idx
            if t_s1 is not None and t_inv is not None:
                break
    if t_s1 is not None and t_inv is not None:
        feats["first_hit"] = "S1_FIRST" if t_s1 < t_inv else ("INVALID_FIRST" if t_inv < t_s1 else "SAME_DAY")
    elif t_s1 is not None:
        feats["first_hit"] = "S1_FIRST"
    elif t_inv is not None:
        feats["first_hit"] = "INVALID_FIRST"
    else:
        feats["first_hit"] = "NONE_10D"
    feats["time_to_s1"] = t_s1
    feats["time_to_invalid"] = t_inv
    return feats


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_episodes()
    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, row in df.iterrows():
        by_code[row["code"]].append(row)

    all_feats = []
    for code, bars in iter_canonical_code_bars(
        layout, snapshot, codes=sorted(by_code.keys())
    ):
        if not bars or code not in by_code:
            continue
        idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
        for row in by_code[code]:
            feats = compute_episode_features(row, bars, idx_by_date)
            if feats is None:
                continue
            r = float(row["conservative_net_execution_R_10bp"]) if pd.notna(
                row["conservative_net_execution_R_10bp"]
            ) else None
            feats["canonical_R_10bp"] = r
            feats["exec_status"] = row["conservative_execution_status"]
            all_feats.append(feats)

    main = [
        f for f in all_feats
        if f["first_hit"] in ("S1_FIRST", "INVALID_FIRST") and f["exec_status"] == "RESOLVED"
    ]
    for f in main:
        f["label"] = "WINNER" if f["first_hit"] == "S1_FIRST" else "LOSER"
    other = [f for f in all_feats if f not in main]
    other_summary = {
        "SAME_DAY": sum(1 for f in other if f["first_hit"] == "SAME_DAY"),
        "NONE_10D": sum(1 for f in other if f["first_hit"] == "NONE_10D"),
        "non_resolved": sum(1 for f in other if f["exec_status"] != "RESOLVED"),
    }

    metrics: dict = {
        "title": "B1 ENTRY SELECTION ATTRIBUTION v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "DESCRIPTIVE_OBSERVE_ONLY",
        "cohort": "B1_READY actionable filled",
        "n_all": len(all_feats),
        "n_main": len(main),
        "n_winner": sum(1 for f in main if f["label"] == "WINNER"),
        "n_loser": sum(1 for f in main if f["label"] == "LOSER"),
        "excluded": other_summary,
    }

    cont_features = [
        "close_ma5_pct", "close_ma10_pct", "close_ma20_pct", "close_ma30_pct",
        "ma5_slope_pct", "ma10_slope_pct", "ma20_slope_pct",
        "entry_anchor_close_pct", "entry_anchor_high_pct", "entry_high20_pct",
        "entry_ma20_pct", "entry_support_center_pct",
        "pullback_max_dd_pct", "vol_post_anchor_ratio", "recent_vol_ratio",
        "down_up_vol_ratio", "consec_shrink_days", "big_vol_down_days",
        "days_since_anchor", "attack_high_dd_pct", "washout_min_vol_ratio",
    ]
    bin_features = [
        "pre_day7", "pre_cum2", "pre_vol2x", "pre_consec_vol_attack", "pre_attack_present",
        "ma20_up", "ma30_up", "reclaim_ma5", "reclaim_ma10", "reclaim_ma20",
        "reclaim_attack_mid", "reclaim_platform",
    ]

    table = {}
    for key in cont_features:
        w = [f[key] for f in main if f["label"] == "WINNER" and f.get(key) is not None]
        l = [f[key] for f in main if f["label"] == "LOSER" and f.get(key) is not None]
        sw, sl = stats(w), stats(l)
        med_diff = (sw["median"] - sl["median"]) if sw and sl else None
        d = cohens_d(w, l)
        row = {
            "winner": sw,
            "loser": sl,
            "median_diff": round(med_diff, 4) if med_diff is not None else None,
            "cohens_d": d,
        }
        dirs = {}
        for period in ("DISCOVERY", "VALIDATION"):
            wp = [f[key] for f in main if f["label"] == "WINNER" and f["period"] == period and f.get(key) is not None]
            lp = [f[key] for f in main if f["label"] == "LOSER" and f["period"] == period and f.get(key) is not None]
            swp, slp = stats(wp), stats(lp)
            if swp and slp and swp["median"] != slp["median"]:
                dirs[period] = "WINNER_HIGHER" if swp["median"] > slp["median"] else "WINNER_LOWER"
        row["direction"] = dirs
        row["stable_direction"] = (
            len(dirs) == 2 and dirs["DISCOVERY"] == dirs["VALIDATION"]
        )
        table[key] = row

    for key in bin_features:
        rw = sum(1 for f in main if f["label"] == "WINNER" and f.get(key))
        rl = sum(1 for f in main if f["label"] == "LOSER" and f.get(key))
        nw = sum(1 for f in main if f["label"] == "WINNER")
        nl = sum(1 for f in main if f["label"] == "LOSER")
        rate_w, rate_l = rw / nw, rl / nl
        row = {
            "winner_rate": round(rate_w, 4),
            "loser_rate": round(rate_l, 4),
            "rate_diff": round(rate_w - rate_l, 4),
            "odds_ratio": odds_ratio(rate_w, rate_l),
            "direction": {},
            "stable_direction": False,
        }
        dirs = {}
        for period in ("DISCOVERY", "VALIDATION"):
            mp = [f for f in main if f["period"] == period]
            nwp = sum(1 for f in mp if f["label"] == "WINNER")
            nlp = sum(1 for f in mp if f["label"] == "LOSER")
            rwp = sum(1 for f in mp if f["label"] == "WINNER" and f.get(key))
            rlp = sum(1 for f in mp if f["label"] == "LOSER" and f.get(key))
            if nwp and nlp:
                rw_p, rl_p = rwp / nwp, rlp / nlp
                if rw_p != rl_p:
                    dirs[period] = "WINNER_HIGHER" if rw_p > rl_p else "WINNER_LOWER"
        row["direction"] = dirs
        row["stable_direction"] = len(dirs) == 2 and dirs.get("DISCOVERY") == dirs.get("VALIDATION")
        table[key] = row
    metrics["FEATURE_TABLE"] = table

    # PRE_ATTACK_PRESENT vs ABSENT (focus)
    pa = {}
    for present in (True, False):
        sub = [f for f in main if f["pre_attack_present"] == present]
        s1_first = sum(1 for f in sub if f["first_hit"] == "S1_FIRST")
        inv_first = sum(1 for f in sub if f["first_hit"] == "INVALID_FIRST")
        pa[str(present)] = {
            "n": len(sub),
            "s1_first_rate": round(s1_first / len(sub), 4) if sub else None,
            "invalid_first_rate": round(inv_first / len(sub), 4) if sub else None,
            "canonical_mean_R": round(
                statistics.fmean([f["canonical_R_10bp"] for f in sub if f["canonical_R_10bp"] is not None]), 4
            ) if sub else None,
        }
        for period in ("DISCOVERY", "VALIDATION"):
            sp = [f for f in sub if f["period"] == period]
            pa[str(present)][period] = {
                "n": len(sp),
                "s1_first_rate": round(
                    sum(1 for f in sp if f["first_hit"] == "S1_FIRST") / len(sp), 4
                ) if sp else None,
                "mean_R": round(
                    statistics.fmean([f["canonical_R_10bp"] for f in sp if f["canonical_R_10bp"] is not None]), 4
                ) if sp else None,
            }
    metrics["PRE_ATTACK"] = pa

    # CASE STUDY: 10 typical winners / losers near group median R
    cases = {}
    for label in ("WINNER", "LOSER"):
        sub = [f for f in main if f["label"] == label]
        rs = sorted(f["canonical_R_10bp"] for f in sub if f["canonical_R_10bp"] is not None)
        med = statistics.median(rs)
        picked = sorted(sub, key=lambda f: abs((f["canonical_R_10bp"] or 0) - med))[:10]
        cases[label] = [
            {
                "code": f["code"],
                "anchor_date": f["anchor_date"],
                "entry_date": f["fill_date"],
                "entry": f["fill_price"],
                "invalid": f["invalid"],
                "s1": f["s1"],
                "R_10bp": f["canonical_R_10bp"],
                "first_hit": f["first_hit"],
                "structure": {
                    "first_attack": {
                        "day7": f["pre_day7"],
                        "cum2": f["pre_cum2"],
                        "vol2x": f["pre_vol2x"],
                        "consec": f["pre_consec_vol_attack"],
                        "present": f["pre_attack_present"],
                    },
                    "pullback": {
                        "max_dd_pct": f.get("pullback_max_dd_pct"),
                        "days": f.get("days_since_anchor"),
                        "vol_post_anchor": f.get("vol_post_anchor_ratio"),
                        "recent_vol": f.get("recent_vol_ratio"),
                        "big_vol_down": f.get("big_vol_down_days"),
                    },
                    "support": {
                        "ma20_up": f.get("ma20_up"),
                        "entry_support_center_pct": f.get("entry_support_center_pct"),
                        "reclaim_ma5": f.get("reclaim_ma5"),
                        "reclaim_ma10": f.get("reclaim_ma10"),
                        "reclaim_ma20": f.get("reclaim_ma20"),
                    },
                    "ma_state": {
                        "close_ma5_pct": f.get("close_ma5_pct"),
                        "close_ma10_pct": f.get("close_ma10_pct"),
                        "close_ma20_pct": f.get("close_ma20_pct"),
                        "close_ma30_pct": f.get("close_ma30_pct"),
                    },
                    "extension": {
                        "entry_anchor_close_pct": f.get("entry_anchor_close_pct"),
                        "entry_anchor_high_pct": f.get("entry_anchor_high_pct"),
                        "entry_high20_pct": f.get("entry_high20_pct"),
                        "entry_ma20_pct": f.get("entry_ma20_pct"),
                    },
                    "reclaim": {
                        "attack_high_dd_pct": f.get("attack_high_dd_pct"),
                        "washout_min_vol_ratio": f.get("washout_min_vol_ratio"),
                        "reclaim_attack_mid": f.get("reclaim_attack_mid"),
                        "reclaim_platform": f.get("reclaim_platform"),
                    },
                },
            }
            for f in picked
        ]
    metrics["CASE_STUDY"] = cases

    # CURRENT 5 mapping (fixed entries/anchors from 7/31 premarket card)
    current5 = [
        {"code": "603980", "anchor": "2026-07-28", "asof": "2026-07-31", "entry": 6.73, "invalid": 6.23, "s1": 7.02},
        {"code": "600756", "anchor": "2026-07-28", "asof": "2026-07-31", "entry": 16.52, "invalid": 15.66, "s1": 16.99},
        {"code": "603232", "anchor": "2026-07-28", "asof": "2026-07-31", "entry": 15.50, "invalid": 13.79, "s1": 16.68},
        {"code": "601858", "anchor": "2026-07-29", "asof": "2026-07-31", "entry": 20.61, "invalid": 18.71, "s1": 21.72},
        {"code": "603185", "anchor": "2026-07-30", "asof": "2026-07-31", "entry": 16.08, "invalid": 15.29, "s1": 17.05},
    ]
    c5 = []
    for item in current5:
        anchor = date.fromisoformat(item["anchor"])
        asof = date.fromisoformat(item["asof"])
        for code, bars in iter_canonical_code_bars(layout, snapshot, codes=[item["code"]]):
            idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
            a = idx_by_date.get(anchor)
            s = idx_by_date.get(asof)
            if a is None or s is None:
                continue
            fake = pd.Series(
                {
                    "anchor_date": anchor,
                    "signal_date": asof,
                    "fill_date": asof,
                    "fill_price": item["entry"],
                    "invalid_price": item["invalid"],
                    "s1_price": item["s1"],
                    "support_center": None,
                    "anchor_price": None,
                    "code": code,
                    "setup_id": code,
                }
            )
            feats = compute_episode_features(fake, bars, idx_by_date)
            if feats:
                c5.append(
                    {
                        "code": code,
                        "first_attack": {
                            "day7": feats["pre_day7"],
                            "cum2": feats["pre_cum2"],
                            "vol2x": feats["pre_vol2x"],
                            "present": feats["pre_attack_present"],
                        },
                        "pullback": {
                            "max_dd_pct": feats.get("pullback_max_dd_pct"),
                            "days": feats.get("days_since_anchor"),
                            "vol_post_anchor": feats.get("vol_post_anchor_ratio"),
                            "recent_vol": feats.get("recent_vol_ratio"),
                            "big_vol_down": feats.get("big_vol_down_days"),
                        },
                        "support": {
                            "ma20_up": feats.get("ma20_up"),
                            "reclaim_ma5": feats.get("reclaim_ma5"),
                            "reclaim_ma10": feats.get("reclaim_ma10"),
                            "reclaim_ma20": feats.get("reclaim_ma20"),
                        },
                        "extension": {
                            "entry_anchor_close_pct": feats.get("entry_anchor_close_pct"),
                            "entry_high20_pct": feats.get("entry_high20_pct"),
                            "entry_ma20_pct": feats.get("entry_ma20_pct"),
                        },
                        "reclaim": {
                            "attack_high_dd_pct": feats.get("attack_high_dd_pct"),
                            "reclaim_attack_mid": feats.get("reclaim_attack_mid"),
                        },
                    }
                )
    metrics["CURRENT_5"] = c5

    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
