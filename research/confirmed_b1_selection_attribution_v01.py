"""CONFIRMED B1 SELECTION ATTRIBUTION v0.1 (research-only).

Explains why C1-confirmed-and-filled B1 entries still mostly fail. All features
are known at the confirmation (signal) session close; no next-session info.

C1 frozen = signal-day low > original invalid; next-day entry uses the original
buy zone / invalid / S1.

Inputs: corrected episodes 66d5943f..., snapshot b5f84004de8a.
Output: data/tmp/confirmed-b1-selection-attribution-v01/metrics.json
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pandas as pd

from limit_pullback.models.enums import FillType
from limit_pullback.screen.canonical import (
    iter_canonical_code_bars,
    load_canonical_metadata,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from research.b1_confirmation_entry_signal_v01 import resolve_fill
from research.entry_attribution_v01 import compute_episode_features, load_episodes


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
EPISODES_DIR = (
    DATA_ROOT
    / "outcome-study"
    / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome"
)
OUT_DIR = DATA_ROOT / "tmp" / "confirmed-b1-selection-attribution-v01"
SPLIT_DATE = __import__("datetime").date(2025, 7, 1)


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
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 4),
        "median": round(statistics.median(vals), 4),
        "p10": round(_pct(vals, 0.10), 4),
        "p90": round(_pct(vals, 0.90), 4),
    }


def cohens_d(a, b):
    a = [v for v in a if v is not None]
    b = [v for v in b if v is not None]
    if len(a) < 2 or len(b) < 2:
        return None
    pooled = math.sqrt((statistics.pstdev(a) ** 2 + statistics.pstdev(b) ** 2) / 2)
    if pooled == 0:
        return None
    return round((statistics.fmean(a) - statistics.fmean(b)) / pooled, 3)


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ex = pd.read_parquet(EPISODES_DIR / "execution-reality" / "execution_episodes.parquet")
    ex_by_key = {
        (str(r["code"]), str(r["signal_date"])[:10]): r
        for _, r in ex.iterrows()
    }
    df = load_episodes()
    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, row in df.iterrows():
        by_code[row["code"]].append(row)

    recs = []
    for code, bars in iter_canonical_code_bars(
        layout, snapshot, codes=sorted(by_code.keys())
    ):
        if not bars or code not in by_code:
            continue
        idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
        bar_list = list(bars)
        for row in by_code[code]:
            f = compute_episode_features(row, bars, idx_by_date)
            if f is None:
                continue
            f["exec_status"] = row["conservative_execution_status"]
            f["canonical_R_10bp"] = (
                float(row["conservative_net_execution_R_10bp"])
                if pd.notna(row["conservative_net_execution_R_10bp"])
                else None
            )
            if f["first_hit"] in ("S1_FIRST", "INVALID_FIRST") and f["exec_status"] == "RESOLVED":
                f["label"] = "WINNER" if f["first_hit"] == "S1_FIRST" else "LOSER"
            else:
                f["label"] = f["first_hit"]
            sig_idx = idx_by_date.get(row["signal_date"])
            fill_idx = idx_by_date.get(row["fill_date"])
            if sig_idx is None or fill_idx is None or fill_idx != sig_idx + 1:
                continue
            invalid = float(row["invalid_price"])
            s1 = float(row["s1_price"])
            bz_high = (
                float(row["buy_zone_high"])
                if pd.notna(row["buy_zone_high"])
                else None
            )
            bz_low = (
                float(row["buy_zone_low"])
                if pd.notna(row["buy_zone_low"])
                else None
            )
            sb = bar_list[sig_idx]
            o, h, l, c = (float(sb.open), float(sb.high), float(sb.low), float(sb.close))
            pc = float(sb.preclose)
            vol = float(sb.volume)
            prev_vol = float(bar_list[sig_idx - 1].volume) if sig_idx >= 1 else None
            ma5c = statistics.fmean(float(bar_list[i].close) for i in range(max(0, sig_idx - 4), sig_idx + 1))
            ma10c = statistics.fmean(float(bar_list[i].close) for i in range(max(0, sig_idx - 9), sig_idx + 1))
            ma20c = statistics.fmean(float(bar_list[i].close) for i in range(max(0, sig_idx - 19), sig_idx + 1))
            vol5 = statistics.fmean(float(bar_list[i].volume) for i in range(max(0, sig_idx - 4), sig_idx + 1))
            vol20 = statistics.fmean(float(bar_list[i].volume) for i in range(max(0, sig_idx - 19), sig_idx + 1))
            anchor_bar = bar_list[idx_by_date.get(row["anchor_date"])]
            anchor_center = (float(anchor_bar.high) + float(anchor_bar.low)) / 2
            high20 = max(float(bar_list[i].high) for i in range(max(0, sig_idx - 19), sig_idx + 1))
            rng = h - l

            feats = {
                "code": code,
                "signal_date": str(row["signal_date"])[:10],
                "period": f["period"],
                "fill_year": f["fill_year"],
                "days_since_anchor": f.get("days_since_anchor"),
                "close_loc": (c - l) / rng if rng else None,
                "daily_return_pct": (c / pc - 1) * 100,
                "body_pct": abs(c - o) / pc * 100,
                "upper_wick_pct": (h - max(o, c)) / pc * 100,
                "lower_wick_pct": (min(o, c) - l) / pc * 100,
                "range_pct": rng / pc * 100,
                "close_vs_zone_center_pct": (
                    (c - (bz_low + bz_high) / 2) / ((bz_low + bz_high) / 2) * 100
                    if bz_low and bz_high
                    else None
                ),
                "close_vs_invalid_pct": (c / invalid - 1) * 100,
                "close_vs_s1_pct": (c / s1 - 1) * 100,
                "close_vs_anchor_center_pct": (c / anchor_center - 1) * 100,
                "close_vs_ma5_pct": (c / ma5c - 1) * 100,
                "close_vs_ma10_pct": (c / ma10c - 1) * 100,
                "close_vs_ma20_pct": (c / ma20c - 1) * 100,
                "vol_vs_prev": vol / prev_vol if prev_vol else None,
                "vol_vs_ma5": vol / vol5,
                "vol_vs_ma20": vol / vol20,
                "dist_20d_high_pct": (c / high20 - 1) * 100,
                "turnover": float(sb.turnover_rate) if sb.turnover_rate is not None else None,
                "upside_to_s1_pct": (s1 / c - 1) * 100,
                "downside_to_invalid_pct": (c / invalid - 1) * 100,
                "rr_from_confirmation_close": ((s1 - c) / (c - invalid)) if c > invalid else None,
            }
            feats["c1_eligible"] = bool(l > invalid)
            feats["baseline_label"] = f["label"]
            feats["baseline_R_10bp"] = f["canonical_R_10bp"]
            feats["next_open"] = float(bar_list[fill_idx].open)
            feats["invalid"] = invalid
            feats["bz_high"] = bz_high

            # C1 fill on next session (same as frozen C1 definition)
            fill = None
            if feats["c1_eligible"]:
                nb = bar_list[fill_idx]
                no, nl = float(nb.open), float(nb.low)
                if no <= invalid:
                    fill = {"status": "NO_FILL", "reason": "OPEN_BELOW_INVALID", "price": None, "kind": None}
                elif bz_high is not None and no <= bz_high:
                    fill = {"status": "FILLED", "price": no, "kind": "OPEN_FILL"}
                elif bz_high is not None and nl <= bz_high:
                    fill = {"status": "FILLED", "price": bz_high, "kind": "TOUCH_FILL"}
                else:
                    fill = {"status": "NO_FILL", "reason": "NO_ZONE_TOUCH", "price": None, "kind": None}
            else:
                fill = {"status": "NO_FILL", "reason": "NOT_ELIGIBLE", "price": None, "kind": None}
            feats["fill"] = fill

            if fill["status"] == "FILLED":
                ex_row = ex_by_key.get((code, str(row["signal_date"])[:10]))
                payload = {}
                for k, v in ex_row.to_dict().items():
                    if isinstance(v, float):
                        payload[k] = None if math.isnan(v) else str(v)
                    elif isinstance(v, str) and v.startswith(("[", "{")):
                        try:
                            payload[k] = json.loads(v)
                        except Exception:
                            payload[k] = v
                    else:
                        payload[k] = v
                out = resolve_fill(
                    payload,
                    bar_list,
                    fill_date=row["fill_date"],
                    fill_price=Decimal(str(fill["price"])),
                    fill_type=(
                        FillType.OPEN_FILL
                        if fill["kind"] == "OPEN_FILL"
                        else FillType.INTRADAY_TOUCH_FILL
                    ),
                )
                feats["c1_R_10bp"] = out["R_10bp"]
                feats["c1_exit"] = out["exit_type"]
                # path label after C1 fill (first of S1/invalid from fill+1)
                t_s1 = t_inv = None
                for idx in range(fill_idx + 1, min(len(bar_list), fill_idx + 11)):
                    b = bar_list[idx]
                    if t_s1 is None and float(b.high) >= s1:
                        t_s1 = idx - fill_idx
                    if t_inv is None and float(b.low) <= invalid:
                        t_inv = idx - fill_idx
                    if t_s1 is not None and t_inv is not None:
                        break
                if t_s1 is not None and t_inv is not None:
                    feats["c1_label"] = "WINNER" if t_s1 < t_inv else "LOSER"
                elif t_s1 is not None:
                    feats["c1_label"] = "WINNER"
                elif t_inv is not None:
                    feats["c1_label"] = "LOSER"
                else:
                    feats["c1_label"] = "OTHER"
            else:
                feats["c1_R_10bp"] = None
                feats["c1_exit"] = None
                feats["c1_label"] = None
            recs.append(feats)

    main = [r for r in recs if r["fill"]["status"] == "FILLED"]
    w = [r for r in main if r["c1_label"] == "WINNER"]
    l = [r for r in main if r["c1_label"] == "LOSER"]
    other = [r for r in main if r["c1_label"] not in ("WINNER", "LOSER")]

    cont = [
        "close_loc", "daily_return_pct", "body_pct", "upper_wick_pct", "lower_wick_pct",
        "range_pct", "close_vs_zone_center_pct", "close_vs_invalid_pct", "close_vs_s1_pct",
        "close_vs_anchor_center_pct", "close_vs_ma5_pct", "close_vs_ma10_pct",
        "close_vs_ma20_pct", "vol_vs_prev", "vol_vs_ma5", "vol_vs_ma20", "turnover",
        "dist_20d_high_pct", "days_since_anchor",
        "upside_to_s1_pct", "downside_to_invalid_pct", "rr_from_confirmation_close",
    ]
    table = {}
    for key in cont:
        wv = [r[key] for r in w if r.get(key) is not None]
        lv = [r[key] for r in l if r.get(key) is not None]
        sw, sl = stats(wv), stats(lv)
        med_diff = (sw["median"] - sl["median"]) if sw and sl else None
        row = {
            "winner": sw,
            "loser": sl,
            "median_diff": round(med_diff, 4) if med_diff is not None else None,
            "cohens_d": cohens_d(wv, lv),
        }
        dirs = {}
        for period in ("DISCOVERY", "VALIDATION"):
            wp = [r[key] for r in w if r["period"] == period and r.get(key) is not None]
            lp = [r[key] for r in l if r["period"] == period and r.get(key) is not None]
            swp, slp = stats(wp), stats(lp)
            if swp and slp and swp["median"] != slp["median"]:
                dirs[period] = "W_HIGHER" if swp["median"] > slp["median"] else "W_LOWER"
        row["direction"] = dirs
        row["stable_direction"] = len(dirs) == 2 and dirs.get("DISCOVERY") == dirs.get("VALIDATION")
        for year in (2024, 2025, 2026):
            wy = [r[key] for r in w if r["fill_year"] == year and r.get(key) is not None]
            ly = [r[key] for r in l if r["fill_year"] == year and r.get(key) is not None]
            swy, sly = stats(wy), stats(ly)
            row[str(year)] = {
                "w_median": swy["median"] if swy else None,
                "l_median": sly["median"] if sly else None,
                "n": (swy["n"] if swy else 0, sly["n"] if sly else 0),
            }
        table[key] = row

    # missed winners: baseline winners that C1 did not fill
    missed = [r for r in recs if r["baseline_label"] == "WINNER" and r["fill"]["status"] != "FILLED"]
    missed_reasons = defaultdict(int)
    for r in missed:
        missed_reasons[str(r["fill"]["reason"])] += 1
    missed_open_above_zone = sum(
        1
        for r in missed
        if r["bz_high"] is not None and r["next_open"] > r["bz_high"]
    )
    missed_open_below_invalid = sum(
        1 for r in missed if r["next_open"] <= r["invalid"]
    )
    miss_summary = {
        "n": len(missed),
        "reasons": dict(missed_reasons),
        "next_open_above_zone_share": round(missed_open_above_zone / len(missed), 4) if missed else None,
        "next_open_below_invalid_share": round(missed_open_below_invalid / len(missed), 4) if missed else None,
        "note": "all misses are NOT_ELIGIBLE under frozen C1 (signal-day low<=invalid); "
        "OPEN_BELOW_INVALID / NO_ZONE_TOUCH do not occur because every eligible anchor filled on the original fill day.",
    }

    # execution geometry comparison
    geometry = {
        key: {"winner": stats([r[key] for r in w if r.get(key) is not None]),
              "loser": stats([r[key] for r in l if r.get(key) is not None])}
        for key in ("upside_to_s1_pct", "downside_to_invalid_pct", "rr_from_confirmation_close")
    }

    metrics = {
        "title": "CONFIRMED B1 SELECTION ATTRIBUTION v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "DESCRIPTIVE_OBSERVE_ONLY",
        "n_filled": len(main),
        "n_winner": len(w),
        "n_loser": len(l),
        "n_other": len(other),
        "FEATURE_TABLE": table,
        "MISSED_WINNERS": miss_summary,
        "RETAINED": {
            "winners": len(w),
            "losers": len(l),
        },
        "EXECUTION_GEOMETRY": geometry,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
