"""RESEARCH-ONLY B1 CONFIRMATION ENTRY v0.1 — signal-session definition.

Frozen confirmation conditions (signal session = B1_READY signal day):
  C1 = signal-day low > original invalid
  C2 = C1 AND signal-day close >= MA5 (MA computed through signal day)
Confirmation info is only available after signal-session close.
Earliest entry = next trading day (the original B1 fill day), filled by the
existing buy-zone rules; invalid / S1 / buy zone / MA unchanged.
Execution reuse: canonical conservative resolver (relabel_execution_episode).

Baseline = original canonical B1 on the same 720 unique first-actionable
anchors. Anchor-level expectancy counts unconfirmed/unfilled anchors as 0R.

Output: data/tmp/b1-confirmation-entry-signal-v01/metrics.json
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pandas as pd

from limit_pullback.execution_reality import (
    _fill_day_states,
    _friction_values,
    _quantize_pct,
    _resolve_execution,
    _return_values,
)
from limit_pullback.models.enums import FillType
from limit_pullback.models.execution_reality import ExecutionRealityEpisode
from limit_pullback.screen.canonical import (
    iter_canonical_code_bars,
    load_canonical_metadata,
)
from limit_pullback.warehouse.layout import WarehouseLayout
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
OUT_DIR = DATA_ROOT / "tmp" / "b1-confirmation-entry-signal-v01"
SPLIT_DATE = __import__("datetime").date(2025, 7, 1)
NEAR_S1_FRACTION = 0.98  # production near_s1_distance=0.02


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


def resolve_fill(exec_payload: dict, bars, fill_date, fill_price, fill_type):
    """Run the canonical conservative resolver on a (possibly updated) fill.

    Mirrors relabel_execution_episode's exact computation path (same private
    helpers, same OHLC ordering), without the frozen-field assertion that would
    reject a research-only fill override.
    """

    payload = dict(exec_payload)
    payload["fill_date"] = fill_date
    payload["fill_price"] = fill_price
    payload["fill_type"] = fill_type
    event = ExecutionRealityEpisode.model_validate(payload)
    invalid = event.invalid_price
    s1 = event.s1_price
    fill_idx = next(
        i for i, b in enumerate(bars) if b.trade_date == fill_date
    )
    stop_state, _ = _fill_day_states(event, bars[fill_idx])
    strict, conservative, _, _, _ = _resolve_execution(
        event,
        bars,
        fill_index=fill_idx,
        fill_day_stop_state=stop_state,
        price_limits=None,
    )
    risk_abs = fill_price - invalid
    risk_pct = _quantize_pct(risk_abs / fill_price)
    cons_pct, _ = _return_values(
        fill_price=fill_price, risk_abs=risk_abs, exit_value=conservative
    )
    cons_fr = _friction_values(gross_pct=cons_pct, risk_pct=risk_pct)
    return {
        "R_10bp": float(cons_fr["net_execution_R_10bp"])
        if cons_fr["net_execution_R_10bp"] is not None
        else None,
        "R_20bp": float(cons_fr["net_execution_R_20bp"])
        if cons_fr["net_execution_R_20bp"] is not None
        else None,
        "exit_type": conservative.exit_type,
        "status": conservative.status,
    }


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_episodes()
    ex = pd.read_parquet(EPISODES_DIR / "execution-reality" / "execution_episodes.parquet")
    ex_by_key = {
        (str(r["code"]), str(r["signal_date"])[:10]): r
        for _, r in ex.iterrows()
    }
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
            sig_idx = idx_by_date.get(row["signal_date"])
            fill_idx = idx_by_date.get(row["fill_date"])
            if sig_idx is None or fill_idx is None or fill_idx != sig_idx + 1:
                continue
            invalid = float(row["invalid_price"])
            s1 = float(row["s1_price"])
            sig_bar = bar_list[sig_idx]
            fill_bar = bar_list[fill_idx]
            ma5 = statistics.fmean(
                float(bar_list[i].close)
                for i in range(max(0, sig_idx - 4), sig_idx + 1)
            )
            c1 = float(sig_bar.low) > invalid
            c2 = c1 and float(sig_bar.close) >= ma5
            f["c1_eligible"] = bool(c1)
            f["c2_eligible"] = bool(c2)
            f["canonical_R_10bp"] = (
                float(row["conservative_net_execution_R_10bp"])
                if pd.notna(row["conservative_net_execution_R_10bp"])
                else None
            )
            f["canonical_R_20bp"] = (
                float(row["conservative_net_execution_R_20bp"])
                if pd.notna(row["conservative_net_execution_R_20bp"])
                else None
            )
            f["exec_status"] = row["conservative_execution_status"]
            f["exit_type"] = row["conservative_execution_exit_type"]
            if f["first_hit"] in ("S1_FIRST", "INVALID_FIRST") and f["exec_status"] == "RESOLVED":
                f["label"] = "WINNER" if f["first_hit"] == "S1_FIRST" else "LOSER"
            else:
                f["label"] = f["first_hit"]

            # entry-day fill decision (earliest entry = next trading day)
            bz_high = (
                float(row["buy_zone_high"])
                if pd.notna(row["buy_zone_high"])
                else None
            )
            no, nl, oh = float(fill_bar.open), float(fill_bar.low), float(fill_bar.high)
            entry_info = {
                "open_below_invalid": bool(no <= invalid),
                "open_near_or_above_s1": bool(oh >= s1 * NEAR_S1_FRACTION),
                "open_above_zone": bool(bz_high is not None and no > bz_high),
            }
            fill = {"status": "NO_FILL", "reason": "NOT_ELIGIBLE", "price": None, "kind": None}
            if c1:
                if no <= invalid:
                    fill = {"status": "NO_FILL", "reason": "OPEN_BELOW_INVALID", "price": None, "kind": None}
                elif bz_high is not None and no <= bz_high:
                    fill = {"status": "FILLED", "reason": None, "price": no, "kind": "OPEN_FILL"}
                elif bz_high is not None and nl <= bz_high:
                    fill = {"status": "FILLED", "reason": None, "price": bz_high, "kind": "TOUCH_FILL"}
                else:
                    fill = {"status": "NO_FILL", "reason": "NO_ZONE_TOUCH", "price": None, "kind": None}
            f["entry_info"] = entry_info
            f["fill"] = fill

            # canonical resolver reuse (payload built once per episode)
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
            f["_exec_payload"] = payload
            if payload is not None:
                reg = resolve_fill(
                    payload,
                    bar_list,
                    fill_date=row["fill_date"],
                    fill_price=Decimal(str(row["fill_price"])),
                    fill_type=FillType(str(row["fill_type"])),
                )
                f["_regression_diff_10bp"] = (
                    abs(reg["R_10bp"] - f["canonical_R_10bp"])
                    if reg["R_10bp"] is not None and f["canonical_R_10bp"] is not None
                    else None
                )

            for variant, eligible in (("C1", c1), ("C2", c2)):
                if not eligible:
                    f[f"{variant}_fill_status"] = "NOT_ELIGIBLE"
                    f[f"{variant}_R_10bp"] = None
                    f[f"{variant}_R_20bp"] = None
                    f[f"{variant}_exit_type"] = None
                    continue
                if fill["status"] != "FILLED":
                    f[f"{variant}_fill_status"] = "NO_FILL"
                    f[f"{variant}_R_10bp"] = None
                    f[f"{variant}_R_20bp"] = None
                    f[f"{variant}_exit_type"] = None
                    continue
                if payload is None:
                    f[f"{variant}_fill_status"] = "NO_EXEC_ROW"
                    f[f"{variant}_R_10bp"] = None
                    f[f"{variant}_R_20bp"] = None
                    f[f"{variant}_exit_type"] = None
                    continue
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
                f[f"{variant}_fill_status"] = "FILLED"
                f[f"{variant}_R_10bp"] = out["R_10bp"]
                f[f"{variant}_R_20bp"] = out["R_20bp"]
                f[f"{variant}_exit_type"] = out["exit_type"]
            recs.append(f)

    main = [r for r in recs if r["label"] in ("WINNER", "LOSER")]
    assert len(main) == 720, len(main)
    diffs = [r["_regression_diff_10bp"] for r in main if r.get("_regression_diff_10bp") is not None]

    def anchor_summary(recs_, rkey, exit_key, elig_key=None):
        filled = [r for r in recs_ if r.get(rkey) is not None]
        all_vals = [r.get(rkey) if r.get(rkey) is not None else 0.0 for r in recs_]
        return {
            "anchors": len(recs_),
            "confirmed": len([r for r in recs_ if r.get(elig_key)]) if elig_key else None,
            "filled": len(filled),
            "no_fill_or_0R": len(recs_) - len(filled),
            "fill_rate": round(len(filled) / len(recs_), 4),
            "filled_R": stats([r[rkey] for r in filled]),
            "anchor_level_expectancy": stats(all_vals),
            "target_exit_rate_filled": round(
                sum(1 for r in filled if r.get(exit_key) in ("TARGET", "GAP_TARGET")) / len(filled),
                4,
            ) if filled else None,
            "t1_blocked_rate_filled": round(
                sum(1 for r in filled if r.get(exit_key) == "STOP_TRIGGERED_T1_BLOCKED") / len(filled),
                4,
            ) if filled else None,
            "gap_stop_rate_filled": round(
                sum(1 for r in filled if r.get(exit_key) == "GAP_STOP") / len(filled),
                4,
            ) if filled else None,
        }

    variants = {}
    for variant in ("C1", "C2"):
        rkey = f"{variant}_R_10bp"
        exit_key = f"{variant}_exit_type"
        variants[variant] = anchor_summary(
            main, rkey, exit_key, f"{variant.lower()}_eligible"
        )
        filled = [r for r in main if r.get(f"{variant}_fill_status") == "FILLED"]
        hazard = defaultdict(int)
        kinds = defaultdict(int)
        for r in filled:
            hazard[str(r.get(f"{variant}_exit_type"))] += 1
            kinds[str(r["fill"]["kind"])] += 1
        variants[variant]["hazard_filled"] = dict(hazard)
        variants[variant]["next_day_fill_kind"] = dict(kinds)
        variants[variant]["entry_miss_reasons"] = {
            reason: sum(1 for r in main if str(r["fill"]["reason"]) == reason)
            for reason in ("OPEN_BELOW_INVALID", "NO_ZONE_TOUCH", "NOT_ELIGIBLE")
        }
        variants[variant]["open_near_or_above_s1_count"] = sum(
            1 for r in main if r["entry_info"]["open_near_or_above_s1"]
        )
        variants[variant]["open_below_invalid_count"] = sum(
            1 for r in main if r["entry_info"]["open_below_invalid"]
        )
        variants[variant]["open_above_zone_count"] = sum(
            1 for r in main if r["entry_info"]["open_above_zone"]
        )
        variants[variant]["20bp_stress_anchor_mean"] = stats(
            [r.get(f"{variant}_R_20bp") if r.get(f"{variant}_R_20bp") is not None else 0.0 for r in main]
        )["mean"]
        variants[variant]["classification"] = {
            "avoided_losers": sum(
                1 for r in main if r["label"] == "LOSER" and r.get(f"{variant}_fill_status") != "FILLED"
            ),
            "missed_winners": sum(
                1 for r in main if r["label"] == "WINNER" and r.get(f"{variant}_fill_status") != "FILLED"
            ),
            "retained_winners": sum(
                1 for r in main if r["label"] == "WINNER" and r.get(f"{variant}_fill_status") == "FILLED"
            ),
            "retained_losers": sum(
                1 for r in main if r["label"] == "LOSER" and r.get(f"{variant}_fill_status") == "FILLED"
            ),
        }
        for period in ("DISCOVERY", "VALIDATION"):
            sub = [r for r in main if r["period"] == period]
            variants[variant][period] = anchor_summary(
                sub, rkey, exit_key, f"{variant.lower()}_eligible"
            )
            variants[variant][f"{period}_baseline_anchor_mean"] = stats(
                [r["canonical_R_10bp"] for r in sub]
            )["mean"]
        for year in (2024, 2025, 2026):
            sub = [r for r in main if r.get("fill_year") == year]
            variants[variant][str(year)] = anchor_summary(
                sub, rkey, exit_key, f"{variant.lower()}_eligible"
            )
            variants[variant][f"{year}_baseline_anchor_mean"] = stats(
                [r["canonical_R_10bp"] for r in sub]
            )["mean"]

    metrics = {
        "title": "RESEARCH-ONLY B1 CONFIRMATION ENTRY v0.1 (signal-session definition)",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "RESEARCH_ONLY",
        "definition": {
            "C1": "signal-day low > original invalid",
            "C2": "C1 AND signal-day close >= MA5",
            "entry": "next trading day (original fill day), existing buy-zone rules",
            "execution": "canonical conservative resolver (relabel_execution_episode)",
            "anchor_level": "unconfirmed/unfilled = 0R",
        },
        "BASELINE_anchor_level_10bp": round(
            statistics.fmean([r["canonical_R_10bp"] for r in main]), 4
        ),
        "BASELINE_anchor_level_20bp": round(
            statistics.fmean([r["canonical_R_20bp"] for r in main if r["canonical_R_20bp"] is not None]), 4
        ),
        "RESOLVER_REGRESSION": {
            "n": len(diffs),
            "max_abs_diff_10bp": round(max(diffs), 6) if diffs else None,
            "mean_abs_diff_10bp": round(statistics.fmean(diffs), 6) if diffs else None,
        },
        "VARIANTS": variants,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
