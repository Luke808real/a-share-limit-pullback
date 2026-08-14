"""B1 ENTRY GEOMETRY RESEARCH v0.1 (research-only, no strategy change).

Population: all unique ENTRY_CANDIDATE anchors (first B1 signal per anchor).
Earliest usable price = next-day OPEN. Frozen levels: buy zone / invalid / S1.

State map (next open only, no intraday info):
  OPEN_LE_INVALID / INVALID_LT_OPEN_LT_ZONE_LOW / OPEN_IN_BUY_ZONE /
  ZONE_HIGH_LT_OPEN_LT_S1 / OPEN_GE_S1

Executions:
  G0 = canonical buy-zone execution (baseline, simulated on the same universe)
  G1 = next-open valid: invalid < open < S1 -> buy at open, else no trade
  G2 = strength routed: open > zone_high and open < S1 -> buy at open,
       otherwise fall back to G0 rules
All fills reuse the canonical conservative T+1 resolver (same invalid/S1).

Output: data/tmp/b1-entry-geometry-v01/metrics.json
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


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
EPISODES_DIR = (
    DATA_ROOT
    / "outcome-study"
    / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome"
)
OUT_DIR = DATA_ROOT / "tmp" / "b1-entry-geometry-v01"
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


def path_stats(sub):
    paths = [r["path"] for r in sub if r.get("path") and r["path"] != "NO_LEVELS"]
    out = {
        "n": len(sub),
        "n_path_valid": len(paths),
        "path_counts": {p: paths.count(p) for p in ("S1_FIRST", "INVALID_FIRST", "SAME_DAY", "NONE")},
        "s1_first_rate": round(paths.count("S1_FIRST") / len(paths), 4) if paths else None,
        "invalid_first_rate": round(paths.count("INVALID_FIRST") / len(paths), 4) if paths else None,
    }
    for k in (3, 5, 10):
        out[f"mfe_{k}d"] = stats([r.get(f"mfe_{k}d") for r in sub])
        out[f"mae_{k}d"] = stats([r.get(f"mae_{k}d") for r in sub])
    return out


def anchor_summary(recs, rkey, exit_key, fill_key):
    filled = [r for r in recs if r.get(fill_key) == "FILLED"]
    all_vals = [r.get(rkey) if r.get(rkey) is not None else 0.0 for r in recs]
    return {
        "candidate_anchors": len(recs),
        "filled": len(filled),
        "no_trade": len(recs) - len(filled),
        "fill_rate": round(len(filled) / len(recs), 4) if recs else None,
        "filled_R": stats([r[rkey] for r in filled]),
        "anchor_level_expectancy": stats(all_vals),
        "target_rate_filled": round(
            sum(1 for r in filled if r.get(exit_key) in ("TARGET", "GAP_TARGET")) / len(filled), 4
        ) if filled else None,
        "t1_blocked_rate_filled": round(
            sum(1 for r in filled if r.get(exit_key) == "STOP_TRIGGERED_T1_BLOCKED") / len(filled), 4
        ) if filled else None,
        "gap_stop_rate_filled": round(
            sum(1 for r in filled if r.get(exit_key) == "GAP_STOP") / len(filled), 4
        ) if filled else None,
    }


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ep = pd.read_parquet(EPISODES_DIR / "episodes.parquet")
    ex = pd.read_parquet(EPISODES_DIR / "execution-reality" / "execution_episodes.parquet")
    b1 = ep[ep["execution_label"] == "B1_READY"].copy()
    for col in ("signal_date", "anchor_date"):
        b1[col] = pd.to_datetime(b1[col]).dt.date
    for col in ("invalid_price", "s1_price", "buy_zone_high", "buy_zone_low", "fill_price"):
        b1[col] = pd.to_numeric(b1[col].astype(str), errors="coerce")
    b1["is_entry_candidate"] = b1["is_entry_candidate"].astype(bool)
    b1 = b1.sort_values(["code", "anchor_date", "signal_date"])
    first = b1.groupby(["code", "anchor_date"], as_index=False).first()
    cand = first[first["is_entry_candidate"]].copy()
    print("entry-candidate anchors:", len(cand))

    ex_by_key = {
        (str(r["code"]), str(r["signal_date"])[:10]): r
        for _, r in ex.iterrows()
    }
    layout = WarehouseLayout(DATA_ROOT)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, r in cand.iterrows():
        by_code[str(r["code"])].append(r)

    recs = []
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
            bz_low = float(row["buy_zone_low"]) if pd.notna(row["buy_zone_low"]) else None
            bz_high = float(row["buy_zone_high"]) if pd.notna(row["buy_zone_high"]) else None
            if invalid is None or s1 is None or bz_low is None or bz_high is None:
                continue
            if sig_idx + 1 >= len(bar_list):
                continue
            nxt = bar_list[sig_idx + 1]
            no = float(nxt.open)
            nl = float(nxt.low)
            sig_close = float(bar_list[sig_idx].close)

            rec = {
                "code": code,
                "signal_date": row["signal_date"].isoformat(),
                "period": "DISCOVERY" if row["signal_date"] < SPLIT_DATE else "VALIDATION",
                "year": row["signal_date"].year,
                "invalid": invalid,
                "s1": s1,
                "bz_low": bz_low,
                "bz_high": bz_high,
                "next_open": no,
                "next_low": nl,
                "entry_date": nxt.trade_date,
            }
            if no <= invalid:
                rec["open_state"] = "OPEN_LE_INVALID"
            elif invalid < no < bz_low:
                rec["open_state"] = "INVALID_LT_OPEN_LT_ZONE_LOW"
            elif bz_low <= no <= bz_high:
                rec["open_state"] = "OPEN_IN_BUY_ZONE"
            elif bz_high < no < s1:
                rec["open_state"] = "ZONE_HIGH_LT_OPEN_LT_S1"
            else:
                rec["open_state"] = "OPEN_GE_S1"

            # structural path from signal close (PIT, no trade)
            t_s1 = t_inv = None
            for idx in range(sig_idx + 1, min(len(bar_list), sig_idx + 11)):
                b = bar_list[idx]
                if t_s1 is None and float(b.high) >= s1:
                    t_s1 = idx - sig_idx
                if t_inv is None and float(b.low) <= invalid:
                    t_inv = idx - sig_idx
                if t_s1 is not None and t_inv is not None:
                    break
            if t_s1 is not None and t_inv is not None:
                rec["path"] = (
                    "S1_FIRST" if t_s1 < t_inv else ("INVALID_FIRST" if t_inv < t_s1 else "SAME_DAY")
                )
            elif t_s1 is not None:
                rec["path"] = "S1_FIRST"
            elif t_inv is not None:
                rec["path"] = "INVALID_FIRST"
            else:
                rec["path"] = "NONE"
            for k in (3, 5, 10):
                if sig_idx + k < len(bar_list):
                    seg = bar_list[sig_idx + 1 : sig_idx + k + 1]
                    rec[f"mfe_{k}d"] = max(float(b.high) for b in seg) / sig_close - 1
                    rec[f"mae_{k}d"] = min(float(b.low) for b in seg) / sig_close - 1

            ex_row = ex_by_key.get((code, str(row["signal_date"])[:10]))
            payload = None
            if ex_row is not None:
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
            rec["_payload"] = payload

            # G0 canonical buy-zone rules
            if no <= invalid:
                g0 = None
            elif no <= bz_high:
                g0 = {"price": no, "kind": "OPEN_FILL"}
            elif nl <= bz_high:
                g0 = {"price": bz_high, "kind": "TOUCH_FILL"}
            else:
                g0 = None
            # G1 next-open valid
            g1 = {"price": no, "kind": "OPEN_FILL"} if invalid < no < s1 else None
            # G2 strength routed: open above zone (and < S1) -> open fill; else G0
            if no > bz_high and no < s1:
                g2 = {"price": no, "kind": "OPEN_FILL", "strength_route": True}
            else:
                g2 = g0
            rec["_g"] = {"G0": g0, "G1": g1, "G2": g2}

            for variant in ("G0", "G1", "G2"):
                g = rec["_g"][variant]
                if g is None or payload is None:
                    rec[f"{variant}_fill_status"] = "NO_TRADE"
                    rec[f"{variant}_R_10bp"] = None
                    rec[f"{variant}_R_20bp"] = None
                    rec[f"{variant}_exit"] = None
                    continue
                out = resolve_fill(
                    payload,
                    bar_list,
                    fill_date=rec["entry_date"],
                    fill_price=Decimal(str(g["price"])),
                    fill_type=(
                        FillType.OPEN_FILL
                        if g["kind"] == "OPEN_FILL"
                        else FillType.INTRADAY_TOUCH_FILL
                    ),
                )
                if out["R_10bp"] is None:
                    rec[f"{variant}_fill_status"] = "CENSORED"
                    rec[f"{variant}_R_10bp"] = None
                    rec[f"{variant}_R_20bp"] = None
                    rec[f"{variant}_exit"] = out["exit_type"]
                    continue
                rec[f"{variant}_fill_status"] = "FILLED"
                rec[f"{variant}_R_10bp"] = out["R_10bp"]
                rec[f"{variant}_R_20bp"] = out["R_20bp"]
                rec[f"{variant}_exit"] = out["exit_type"]
            recs.append(rec)

    print("processed candidate anchors:", len(recs))

    # 1. next-open state map
    state_map = {}
    for st in ("OPEN_LE_INVALID", "INVALID_LT_OPEN_LT_ZONE_LOW", "OPEN_IN_BUY_ZONE", "ZONE_HIGH_LT_OPEN_LT_S1", "OPEN_GE_S1"):
        sub = [r for r in recs if r["open_state"] == st]
        row = path_stats(sub)
        for period in ("DISCOVERY", "VALIDATION"):
            sp = [r for r in sub if r["period"] == period]
            paths = [r["path"] for r in sp if r.get("path") and r["path"] != "NO_LEVELS"]
            row[period] = {
                "n": len(sp),
                "s1_first_rate": round(paths.count("S1_FIRST") / len(paths), 4) if paths else None,
            }
        for year in (2024, 2025, 2026):
            sp = [r for r in sub if r["year"] == year]
            paths = [r["path"] for r in sp if r.get("path") and r["path"] != "NO_LEVELS"]
            row[str(year)] = {
                "n": len(sp),
                "s1_first_rate": round(paths.count("S1_FIRST") / len(paths), 4) if paths else None,
            }
        state_map[st] = row

    # 2-4. G0/G1/G2 summaries
    variants = {}
    for variant in ("G0", "G1", "G2"):
        rkey = f"{variant}_R_10bp"
        exit_key = f"{variant}_exit"
        fill_key = f"{variant}_fill_status"
        variants[variant] = anchor_summary(recs, rkey, exit_key, fill_key)
        variants[variant]["20bp_stress_anchor_mean"] = stats(
            [r.get(f"{variant}_R_20bp") if r.get(f"{variant}_R_20bp") is not None else 0.0 for r in recs]
        )["mean"]
        for period in ("DISCOVERY", "VALIDATION"):
            sub = [r for r in recs if r["period"] == period]
            variants[variant][period] = anchor_summary(sub, rkey, exit_key, fill_key)
        for year in (2024, 2025, 2026):
            sub = [r for r in recs if r["year"] == year]
            variants[variant][str(year)] = anchor_summary(sub, rkey, exit_key, fill_key)

    # regression: G0 simulated filled should equal canonical 747 and match R
    g0_filled = [r for r in recs if r["G0_fill_status"] == "FILLED"]
    regression = {
        "G0_simulated_filled": len(g0_filled),
        "canonical_actionable_filled": 747,
    }

    # 5. G2 strength-route vs G0 fell-to-zone
    strength_new = [
        r for r in recs
        if r["G2_fill_status"] == "FILLED"
        and r["_g"]["G2"] is not None
        and r["_g"]["G2"].get("strength_route")
    ]
    g0_zone_fills = [
        r for r in recs
        if r["G0_fill_status"] == "FILLED"
        and r["_g"]["G0"] is not None
        and r["_g"]["G0"].get("kind") == "TOUCH_FILL"
    ]
    strength_check = {
        "G2_OPEN_ABOVE_ZONE_FILLS": {
            "n": len(strength_new),
            "filled_R_10bp": stats([r["G2_R_10bp"] for r in strength_new]),
            "target_rate": round(
                sum(1 for r in strength_new if r["G2_exit"] in ("TARGET", "GAP_TARGET")) / len(strength_new), 4
            ) if strength_new else None,
        },
        "G0_FELL_TO_ZONE_TOUCH_FILLS": {
            "n": len(g0_zone_fills),
            "filled_R_10bp": stats([r["G0_R_10bp"] for r in g0_zone_fills]),
            "target_rate": round(
                sum(1 for r in g0_zone_fills if r["G0_exit"] in ("TARGET", "GAP_TARGET")) / len(g0_zone_fills), 4
            ) if g0_zone_fills else None,
        },
    }

    metrics = {
        "title": "B1 ENTRY GEOMETRY RESEARCH v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "FORWARD_TEST_CANDIDATE_ONLY_IF_POSITIVE",
        "NEXT_OPEN_STATE_MAP": state_map,
        "VARIANTS": variants,
        "REGRESSION": regression,
        "STRENGTH_CHECK": strength_check,
        "gap_away_81_benchmark_note": (
            "GAP_AWAY_NO_FILL (n=81, S1-first 64.9%) is a post-hoc descriptive benchmark only; "
            "never used as an entry condition (no intraday-low-based entries)."
        ),
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
