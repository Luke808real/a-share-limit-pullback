"""BUILD RESEARCH B_ACTIONABLE STATE v0.1 (research-only radar, no buy point).

Target (frozen from prior research):
  B_ACTIONABLE_WINDOW_3D_TARGET = future label within 3 sessions:
    high >= 0.98*S1 OR new 20d high OR max single-day gain >= 5%.

Baselines (fixed, no new features, no threshold scan):
  G = GEOMETRY_ONLY : close_vs_s1, dist_20d_high
  Q = QUALITY_ONLY  : close_loc, close_vs_ma5, daily_return, pullback_depth
  C = COMBINED      : G + Q

Score = equal-weight mean of discovery-standardized z-scores. Discovery-only
fit, locked and applied to VALIDATION (locked decile bins).

Output: data/tmp/b-actionable-state-v01/metrics.json
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
OUT_DIR = DATA_ROOT / "tmp" / "b-actionable-state-v01"
SPLIT_DATE = __import__("datetime").date(2025, 7, 1)
NEAR_S1 = 0.98
EXPANSION_GAIN = 0.05

G_FEATURES = ["close_vs_s1_pct", "dist_20d_high_pct"]
Q_FEATURES = ["close_loc", "close_vs_ma5_pct", "daily_return_pct", "anchor_to_sig_dd_pct"]
C_FEATURES = G_FEATURES + Q_FEATURES


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
            sb = bar_list[sig_idx]
            o, h, l, c = (float(sb.open), float(sb.high), float(sb.low), float(sb.close))
            pc = float(sb.preclose)
            rng = h - l
            ma5 = statistics.fmean(float(bar_list[i].close) for i in range(max(0, sig_idx - 4), sig_idx + 1))
            high20 = max(float(bar_list[i].high) for i in range(max(0, sig_idx - 19), sig_idx + 1))
            anchor_high = float(bar_list[idx_by_date[row["anchor_date"]]].high)
            rec = {
                "code": code,
                "signal_date": row["signal_date"].isoformat(),
                "period": "DISCOVERY" if row["signal_date"] < SPLIT_DATE else "VALIDATION",
                "year": row["signal_date"].year,
                "old_candidate": bool(row["is_entry_candidate"]),
                "old_fill_status": str(row["fill_status"]),
                "mapped": bool(invalid is not None and s1 is not None),
                "daily_return_pct": (c / pc - 1) * 100,
                "close_loc": (c - l) / rng if rng else None,
            }
            if not rec["mapped"]:
                rows.append(rec)
                continue
            rec.update(
                {
                    "close_vs_s1_pct": (c / s1 - 1) * 100,
                    "dist_20d_high_pct": (c / high20 - 1) * 100,
                    "close_vs_ma5_pct": (c / ma5 - 1) * 100,
                    "anchor_to_sig_dd_pct": (l / anchor_high - 1) * 100,
                }
            )
            win = list(range(sig_idx + 1, min(len(bar_list), sig_idx + 4)))
            if not win:
                rec["actionable_target"] = None
                rows.append(rec)
                continue
            max_high = max(float(bar_list[i].high) for i in win)
            rec["actionable_target"] = bool(
                max_high >= NEAR_S1 * s1
                or max_high > high20
                or max(
                    float(bar_list[i].close) / float(bar_list[i].preclose) - 1
                    for i in win
                )
                >= EXPANSION_GAIN
            )
            rows.append(rec)

    mapped = [r for r in rows if r["mapped"]]
    unmapped = [r for r in rows if not r["mapped"]]

    # 1. coverage audit
    coverage = {
        "mapped": len(mapped),
        "unmapped": len(unmapped),
        "by_year": {
            str(y): {
                "mapped": sum(1 for r in rows if r["year"] == y and r["mapped"]),
                "unmapped": sum(1 for r in rows if r["year"] == y and not r["mapped"]),
            }
            for y in (2024, 2025, 2026)
        },
        "candidate_share": {
            "mapped": round(sum(1 for r in mapped if r["old_candidate"]) / len(mapped), 4),
            "unmapped": round(sum(1 for r in unmapped if r["old_candidate"]) / len(unmapped), 4),
        },
        "daily_return_pct": {
            "mapped": stats([r["daily_return_pct"] for r in mapped]),
            "unmapped": stats([r["daily_return_pct"] for r in unmapped]),
        },
        "close_loc": {
            "mapped": stats([r["close_loc"] for r in mapped]),
            "unmapped": stats([r["close_loc"] for r in unmapped]),
        },
        "bias_note": (
            "unmapped = B1 signals without frozen invalid/S1 levels (plan levels "
            "not formed); compared on basic signal features; see candidate share."
        ),
    }

    # 2-4. scores: discovery-only standardization + locked decile bins
    disc = [r for r in mapped if r["period"] == "DISCOVERY"]
    fit = {}
    for feats_name, feats in (("G", G_FEATURES), ("Q", Q_FEATURES), ("C", C_FEATURES)):
        params = {}
        for fname in feats:
            vals = [r[fname] for r in disc if r.get(fname) is not None]
            params[fname] = {"mean": statistics.fmean(vals), "std": statistics.pstdev(vals) or 1}
        fit[feats_name] = params

    def score_of(r, feats_name):
        params = fit[feats_name]
        vals = []
        for fname in G_FEATURES if feats_name == "G" else (Q_FEATURES if feats_name == "Q" else C_FEATURES):
            v = r.get(fname)
            if v is None:
                return None
            p = params[fname]
            vals.append((v - p["mean"]) / p["std"])
        return statistics.fmean(vals) if vals else None

    for r in mapped:
        for feats_name in ("G", "Q", "C"):
            r[f"score_{feats_name}"] = score_of(r, feats_name)

    disc_scores = {
        feats_name: sorted(r[f"score_{feats_name}"] for r in disc if r[f"score_{feats_name}"] is not None)
        for feats_name in ("G", "Q", "C")
    }
    decile_bins = {}
    for feats_name, svals in disc_scores.items():
        cuts = [_pct(svals, q) for q in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)]
        decile_bins[feats_name] = cuts

    def decile_of(score, feats_name):
        if score is None:
            return None
        cuts = decile_bins[feats_name]
        d = 10
        for i, cut in enumerate(cuts):
            if score <= cut:
                d = i + 1
                break
        return d

    for r in mapped:
        for feats_name in ("G", "Q", "C"):
            r[f"decile_{feats_name}"] = decile_of(r[f"score_{feats_name}"], feats_name)

    def performance(sub, feats_name, decile_key=None):
        rows_ = [
            r
            for r in sub
            if r[f"decile_{feats_name}"] is not None
            and r.get("actionable_target") is not None
        ]
        if not rows_:
            return None
        base_rate = sum(1 for r in rows_ if r["actionable_target"]) / len(rows_)
        deciles = {}
        for d in range(1, 11):
            dd = [r for r in rows_ if r[f"decile_{feats_name}"] == d]
            deciles[str(d)] = {
                "n": len(dd),
                "actionable_rate": round(sum(1 for r in dd if r["actionable_target"]) / len(dd), 4) if dd else None,
            }
        top10 = [r for r in rows_ if r[f"decile_{feats_name}"] == 10]
        top20 = [r for r in rows_ if r[f"decile_{feats_name}"] >= 9]
        act_top10 = sum(1 for r in top10 if r["actionable_target"])
        act_top20 = sum(1 for r in top20 if r["actionable_target"])
        return {
            "n": len(rows_),
            "baseline_rate": round(base_rate, 4),
            "deciles": deciles,
            "top10_rate": round(act_top10 / len(top10), 4) if top10 else None,
            "top10_lift": round((act_top10 / len(top10)) / base_rate, 3) if top10 and base_rate else None,
            "top20_rate": round(act_top20 / len(top20), 4) if top20 else None,
            "top20_lift": round((act_top20 / len(top20)) / base_rate, 3) if top20 and base_rate else None,
            "top10_precision": round(act_top10 / len(top10), 4) if top10 else None,
            "top10_coverage_of_actionable": round(act_top10 / sum(1 for r in rows_ if r["actionable_target"]), 4) if rows_ else None,
        }

    perf = {}
    for feats_name in ("G", "Q", "C"):
        perf[feats_name] = {"ALL": performance(mapped, feats_name)}
        for period in ("DISCOVERY", "VALIDATION"):
            perf[feats_name][period] = performance([r for r in mapped if r["period"] == period], feats_name)
        for year in (2024, 2025, 2026):
            perf[feats_name][str(year)] = performance([r for r in mapped if r["year"] == year], feats_name)

    # 6. old gate score distribution
    old_gate = {}
    for label, sub in (
        ("NON_ENTRY_CANDIDATE", [r for r in mapped if not r["old_candidate"]]),
        ("ENTRY_CANDIDATE", [r for r in mapped if r["old_candidate"]]),
        ("FILLED", [r for r in mapped if r["old_candidate"] and r["old_fill_status"] == "FILLED"]),
        ("NO_FILL", [r for r in mapped if r["old_candidate"] and r["old_fill_status"] == "NO_FILL"]),
    ):
        old_gate[label] = {
            "n": len(sub),
            "combined_score_median": stats([r["score_C"] for r in sub])["median"],
            "top_decile_share": round(
                sum(1 for r in sub if r["decile_C"] == 10) / len(sub), 4
            ) if sub else None,
        }

    # 7. validation cases: high-score typical
    val = [r for r in mapped if r["period"] == "VALIDATION"]
    cases = {}
    for target in (True, False):
        sub = [r for r in val if r["decile_C"] == 10 and r["actionable_target"] == target]
        med = statistics.median([r["score_C"] for r in sub])
        picked = sorted(sub, key=lambda r: abs(r["score_C"] - med))[:10]
        cases["ACTIONABLE" if target else "NOT_ACTIONABLE"] = [
            {
                "code": r["code"],
                "signal_date": r["signal_date"],
                "score_C": round(r["score_C"], 3),
                "actionable": r["actionable_target"],
                "features": {
                    k: round(r[k], 3)
                    for k in ("close_vs_s1_pct", "dist_20d_high_pct", "close_loc", "close_vs_ma5_pct", "daily_return_pct", "anchor_to_sig_dd_pct")
                },
            }
            for r in picked
        ]

    # 8. current five mapping (only final step; features at latest B1 signal close)
    current5 = [
        {"code": "603980", "signal": "2026-07-30"},
        {"code": "600756", "signal": "2026-07-29"},
        {"code": "603232", "signal": "2026-07-29"},
        {"code": "601858", "signal": "2026-07-30"},
        {"code": "603185", "signal": "2026-07-30"},
    ]
    cur = []
    for item in current5:
        match = next(
            (
                r
                for r in mapped
                if r["code"] == item["code"] and r["signal_date"] == item["signal"]
            ),
            None,
        )
        if match is None:
            cur.append({"code": item["code"], "mapped": False})
            continue
        ranked = sorted(mapped, key=lambda r: (r["score_C"] if r["score_C"] is not None else -999))
        pct = ranked.index(match) / len(ranked)
        cur.append(
            {
                "code": item["code"],
                "G_score": round(match["score_G"], 3),
                "Q_score": round(match["score_Q"], 3),
                "C_score": round(match["score_C"], 3),
                "C_percentile": round(pct, 4),
            }
        )

    metrics = {
        "title": "BUILD RESEARCH B_ACTIONABLE STATE v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "RESEARCH_ONLY",
        "target": "B_ACTIONABLE_WINDOW_3D_TARGET (future label; not a live state)",
        "COVERAGE_AUDIT": coverage,
        "SCORE_PERFORMANCE": perf,
        "OLD_GATE_SCORES": old_gate,
        "VALIDATION_CASES": cases,
        "CURRENT_FIVE": cur,
        "model_note": (
            "equal-weight mean of discovery-standardized z-scores; discovery-only fit; "
            "locked decile bins applied to validation/years; no hyperparameter tuning."
        ),
        "FIT_PARAMS": {
            name: {
                fname: {"mean": round(p["mean"], 6), "std": round(p["std"], 6)}
                for fname, p in params.items()
            }
            for name, params in fit.items()
        },
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
