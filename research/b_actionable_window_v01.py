"""B ACTIONABLE WINDOW RESEARCH v0.1 (research-only, no production change).

Unit: every unique B1 signal (code + anchor_date lifecycle). Outcome is a
research-only "B ACTIONABLE WINDOW" label (not a fill/entry label):

  ACTIONABLE_WINDOW_3D = within the next 3 sessions, any of:
    - high >= 0.98 * S1            (production near_s1_distance = 0.02)
    - new 20-session high          (factual, vs pre-signal 20d high)
    - expansion: max single-day gain >= +5%   (fixed descriptive marker)

Legacy gate labels (ENTRY_CANDIDATE / FILLED / NO_FILL / NON_CANDIDATE) are
kept only for coverage comparison. All features are known at signal close (PIT).

Output: data/tmp/b-actionable-window-v01/metrics.json
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
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
EPISODES_DIR = (
    DATA_ROOT
    / "outcome-study"
    / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome"
)
OUT_DIR = DATA_ROOT / "tmp" / "b-actionable-window-v01"
SPLIT_DATE = __import__("datetime").date(2025, 7, 1)
NEAR_S1 = 0.98
EXPANSION_GAIN = 0.05


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
    ep = pd.read_parquet(EPISODES_DIR / "episodes.parquet")
    b1 = ep[ep["execution_label"] == "B1_READY"].copy()
    for col in ("signal_date", "anchor_date"):
        b1[col] = pd.to_datetime(b1[col]).dt.date
    for col in ("invalid_price", "s1_price"):
        b1[col] = pd.to_numeric(b1[col].astype(str), errors="coerce")
    b1["fill_status"] = b1["fill_status"].astype(str)
    b1["is_entry_candidate"] = b1["is_entry_candidate"].astype(bool)
    b1 = b1.sort_values(["code", "anchor_date", "signal_date"])
    first = b1.groupby(["code", "anchor_date"], as_index=False).first()
    print("unique B1 signals:", len(first))

    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, r in first.iterrows():
        by_code[str(r["code"])].append(r)

    rows = []
    for code, bars in iter_canonical_code_bars(
        layout, snapshot, codes=sorted(by_code.keys())
    ):
        if not bars or code not in by_code:
            continue
        idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
        bar_list = list(bars)
        for row in by_code[code]:
            sig_idx = idx_by_date.get(row["signal_date"])
            if sig_idx is None:
                continue
            invalid = float(row["invalid_price"]) if pd.notna(row["invalid_price"]) else None
            s1 = float(row["s1_price"]) if pd.notna(row["s1_price"]) else None
            if invalid is None or s1 is None:
                continue
            sb = bar_list[sig_idx]
            o, h, l, c = (float(sb.open), float(sb.high), float(sb.low), float(sb.close))
            pc = float(sb.preclose)
            vol = float(sb.volume)
            rng = h - l
            ma5 = statistics.fmean(float(bar_list[i].close) for i in range(max(0, sig_idx - 4), sig_idx + 1))
            ma10 = statistics.fmean(float(bar_list[i].close) for i in range(max(0, sig_idx - 9), sig_idx + 1))
            vol5 = statistics.fmean(float(bar_list[i].volume) for i in range(max(0, sig_idx - 4), sig_idx + 1))
            vol20 = statistics.fmean(float(bar_list[i].volume) for i in range(max(0, sig_idx - 19), sig_idx + 1))
            high20 = max(float(bar_list[i].high) for i in range(max(0, sig_idx - 19), sig_idx + 1))
            anchor_high = float(bar_list[idx_by_date[row["anchor_date"]]].high)
            rec = {
                "code": code,
                "signal_date": row["signal_date"].isoformat(),
                "period": "DISCOVERY" if row["signal_date"] < SPLIT_DATE else "VALIDATION",
                "year": row["signal_date"].year,
                "old_candidate": bool(row["is_entry_candidate"]),
                "old_fill_status": str(row["fill_status"]),
                "invalid": invalid,
                "s1": s1,
                # signal-strength family
                "daily_return_pct": (c / pc - 1) * 100,
                "body_pct": abs(c - o) / pc * 100,
                "close_loc": (c - l) / rng if rng else None,
                # target geometry
                "close_vs_s1_pct": (c / s1 - 1) * 100,
                "dist_20d_high_pct": (c / high20 - 1) * 100,
                # pullback / compression
                "days_since_anchor": (sig_idx - idx_by_date[row["anchor_date"]]),
                "anchor_to_sig_dd_pct": (l / anchor_high - 1) * 100,
                "range_pct": rng / pc * 100,
                # MA state
                "close_vs_ma5_pct": (c / ma5 - 1) * 100,
                "close_vs_ma10_pct": (c / ma10 - 1) * 100,
                # volume structure
                "vol_vs_prev": vol / float(bar_list[sig_idx - 1].volume) if sig_idx >= 1 else None,
                "vol_vs_ma5": vol / vol5,
                "vol_vs_ma20": vol / vol20,
            }
            # outcome window sig+1..sig+3 (primary), MFE/MAE 1/3/5
            win = list(range(sig_idx + 1, min(len(bar_list), sig_idx + 4)))
            if win:
                max_high = max(float(bar_list[i].high) for i in win)
                min_low = min(float(bar_list[i].low) for i in win)
                rec["near_s1_3d"] = bool(max_high >= NEAR_S1 * s1)
                rec["new_high_3d"] = bool(max_high > high20)
                rec["expansion_3d"] = bool(
                    max(
                        float(bar_list[i].close) / float(bar_list[i].preclose) - 1
                        for i in win
                    )
                    >= EXPANSION_GAIN
                )
                rec["actionable_window_3d"] = bool(
                    rec["near_s1_3d"] or rec["new_high_3d"] or rec["expansion_3d"]
                )
                # first touch within 3d
                t_s1 = t_inv = None
                for i in win:
                    if t_s1 is None and float(bar_list[i].high) >= s1:
                        t_s1 = i - sig_idx
                    if t_inv is None and float(bar_list[i].low) <= invalid:
                        t_inv = i - sig_idx
                    if t_s1 is not None and t_inv is not None:
                        break
                rec["first_touch_3d"] = (
                    "S1" if t_s1 is not None and (t_inv is None or t_s1 < t_inv)
                    else ("INVALID" if t_inv is not None and (t_s1 is None or t_inv < t_s1)
                          else ("SAME" if t_s1 is not None and t_inv is not None else "NONE"))
                )
            else:
                rec["actionable_window_3d"] = None
                rec["first_touch_3d"] = None
            for k in (1, 3, 5):
                if sig_idx + k < len(bar_list):
                    seg = bar_list[sig_idx + 1 : sig_idx + k + 1]
                    rec[f"mfe_{k}d"] = max(float(b.high) for b in seg) / c - 1
                    rec[f"mae_{k}d"] = min(float(b.low) for b in seg) / c - 1
            rows.append(rec)

    valid = [r for r in rows if r.get("actionable_window_3d") is not None]
    act = [r for r in valid if r["actionable_window_3d"]]
    notact = [r for r in valid if not r["actionable_window_3d"]]

    # 1. feature attribution: actionable vs not
    cont = [
        "daily_return_pct", "body_pct", "close_loc", "close_vs_s1_pct",
        "dist_20d_high_pct", "days_since_anchor", "anchor_to_sig_dd_pct",
        "range_pct", "close_vs_ma5_pct", "close_vs_ma10_pct",
        "vol_vs_prev", "vol_vs_ma5", "vol_vs_ma20",
    ]
    table = {}
    for key in cont:
        av = [r[key] for r in act if r.get(key) is not None]
        nv = [r[key] for r in notact if r.get(key) is not None]
        sa, sn = stats(av), stats(nv)
        row = {
            "actionable": sa,
            "not_actionable": sn,
            "median_diff": round((sa["median"] - sn["median"]), 4) if sa and sn else None,
            "cohens_d": cohens_d(av, nv),
        }
        dirs = {}
        for period in ("DISCOVERY", "VALIDATION"):
            ap = [r[key] for r in act if r["period"] == period and r.get(key) is not None]
            np_ = [r[key] for r in notact if r["period"] == period and r.get(key) is not None]
            sap, snp = stats(ap), stats(np_)
            if sap and snp and sap["median"] != snp["median"]:
                dirs[period] = "ACT_HIGHER" if sap["median"] > snp["median"] else "ACT_LOWER"
        row["direction"] = dirs
        row["stable_direction"] = len(dirs) == 2 and dirs.get("DISCOVERY") == dirs.get("VALIDATION")
        table[key] = row

    # 2. actionable share and old-gate coverage
    act_rate = round(len(act) / len(valid), 4) if valid else None
    old_gate = {}
    for label, sub in (
        ("NON_ENTRY_CANDIDATE", [r for r in valid if not r["old_candidate"]]),
        ("ENTRY_CANDIDATE", [r for r in valid if r["old_candidate"]]),
        ("FILLED", [r for r in valid if r["old_candidate"] and r["old_fill_status"] == "FILLED"]),
        ("NO_FILL", [r for r in valid if r["old_candidate"] and r["old_fill_status"] == "NO_FILL"]),
        ("CANCEL_GAP_INVALID", [r for r in valid if r["old_candidate"] and r["old_fill_status"] == "CANCEL_GAP_INVALID"]),
    ):
        sub_act = [r for r in sub if r["actionable_window_3d"]]
        old_gate[label] = {
            "n": len(sub),
            "actionable_share": round(len(sub_act) / len(sub), 4) if sub else None,
            "share_of_all_actionable": round(len(sub_act) / len(act), 4) if act else None,
        }

    # 3. stability of actionable rate + key features
    stability = {}
    for period in ("DISCOVERY", "VALIDATION"):
        sp = [r for r in valid if r["period"] == period]
        stability[period] = {
            "n": len(sp),
            "actionable_rate": round(sum(1 for r in sp if r["actionable_window_3d"]) / len(sp), 4),
        }
    for year in (2024, 2025, 2026):
        sp = [r for r in valid if r["year"] == year]
        stability[str(year)] = {
            "n": len(sp),
            "actionable_rate": round(sum(1 for r in sp if r["actionable_window_3d"]) / len(sp), 4),
        }

    # 4. what precedes failure (invalid-first within 3d)
    fail3 = [r for r in valid if r.get("first_touch_3d") == "INVALID"]
    s1first3 = [r for r in valid if r.get("first_touch_3d") == "S1"]
    precedes_failure = {}
    precedes_window = {}
    for key in cont:
        precedes_failure[key] = {
            "failure_3d": stats([r[key] for r in fail3 if r.get(key) is not None]),
            "all": stats([r[key] for r in valid if r.get(key) is not None]),
        }
        precedes_window[key] = {
            "actionable": stats([r[key] for r in act if r.get(key) is not None]),
            "all": stats([r[key] for r in valid if r.get(key) is not None]),
        }

    metrics = {
        "title": "B ACTIONABLE WINDOW RESEARCH v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "DESCRIPTIVE_OBSERVE_ONLY",
        "definition": {
            "actionable_window_3d": "high>=0.98*S1 OR new 20d high OR max single-day gain>=5% within 3 sessions",
            "legacy_labels": "reference only, not outcome labels",
        },
        "n_valid": len(valid),
        "n_actionable": len(act),
        "actionable_rate": act_rate,
        "first_touch_3d_counts": {p: sum(1 for r in valid if r.get("first_touch_3d") == p) for p in ("S1", "INVALID", "SAME", "NONE")},
        "FEATURE_TABLE": table,
        "OLD_GATE_COVERAGE": old_gate,
        "STABILITY": stability,
        "PRECEDES_FAILURE": precedes_failure,
        "PRECEDES_ACTIONABLE": precedes_window,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
