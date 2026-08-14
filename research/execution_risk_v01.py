"""B1/B2 execution + position sizing research v0.1 (read-only, no strategy change).

Inputs (frozen):
  - corrected episodes parquet (SHA-256 66d5943f...)
  - Phase 2D.1A execution-reality episodes (T+1, 0/10/20/30bp friction)
  - canonical snapshot snap-2026-07-31-b5f84004de8a daily bars

No evaluate_strategy / replay / screen / provider calls.
Outputs: data/tmp/execution-risk-v01/{metrics.json, report.md}
"""

from __future__ import annotations

import json
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
EPISODES_PARQUET = EPISODES / "episodes.parquet"
EXEC_PARQUET = EPISODES / "execution-reality" / "execution_episodes.parquet"
OUT_DIR = DATA_ROOT / "tmp" / "execution-risk-v01"

HORIZONS = (1, 2, 3, 5, 8, 10)
MAX_HOLD = 10
FRICTION_BPS = (10, 20)
SPLIT_DATE = date(2025, 7, 1)


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = (len(values) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(values) - 1)
    frac = idx - lo
    return values[lo] * (1 - frac) + values[hi] * frac


def _stats(values: list[float]) -> dict:
    if not values:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "min": None,
            "max": None,
            "std": None,
        }
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "p10": round(_pct(values, 0.10), 4),
        "p25": round(_pct(values, 0.25), 4),
        "p75": round(_pct(values, 0.75), 4),
        "p90": round(_pct(values, 0.90), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "std": round(statistics.pstdev(values), 4),
    }


def _win_rate(values: list[float]) -> float | None:
    return round(sum(1 for v in values if v > 0) / len(values), 4) if values else None


def load_episodes() -> pd.DataFrame:
    ep = pd.read_parquet(EPISODES_PARQUET)
    ex = pd.read_parquet(EXEC_PARQUET)
    df = ep.merge(
        ex,
        on=[c for c in ep.columns if c in ex.columns],
        how="inner",
        suffixes=("", "_x"),
    )
    df = df[df["fill_status"] == "FILLED"]
    df = df[df["is_entry_candidate"] == True]  # noqa: E712
    df = df[df["s1_price"].notna() & df["invalid_price"].notna() & df["fill_price"].notna()]
    df = df[df["fill_date"].notna()]
    df = df.copy()
    for col in ("fill_date", "signal_date", "anchor_date", "resolution_date"):
        df[col] = pd.to_datetime(df[col]).dt.date
    for col in (
        "fill_price",
        "invalid_price",
        "s1_price",
        "b2_trigger_price",
        "entry_reference_price",
        "preferred_entry",
        "anchor_price",
    ):
        df[col] = pd.to_numeric(df[col].astype(str), errors="coerce")
    df["risk_pct"] = (df["fill_price"] - df["invalid_price"]) / df["fill_price"]
    return df


def mark_add_on(df: pd.DataFrame) -> pd.DataFrame:
    """B2 after a prior actionable B1 fill on the same (code, anchor_date)."""

    add_on: dict[tuple[str, date], set[date]] = defaultdict(set)
    for _, row in df[df["execution_label"] == "B1_READY"].iterrows():
        add_on[(row["code"], row["anchor_date"])].add(row["fill_date"])
    flags = []
    for _, row in df.iterrows():
        prior = add_on.get((row["code"], row["anchor_date"]), set())
        flags.append(
            row["execution_label"] != "B1_READY"
            and any(fd < row["fill_date"] for fd in prior)
        )
    df["b2_add_on"] = flags
    return df


def cohort_of(row) -> str:
    label = row["execution_label"]
    if label == "B1_READY":
        return "B1"
    if label == "B2_READY":
        return "B2_READY"
    return "B2_CONFIRMED"


def per_code_bars(layout, snapshot, codes):
    wanted = set(codes)
    for code, bars in iter_canonical_code_bars(layout, snapshot, codes=sorted(wanted)):
        yield code, bars


def _simulate_fractions(
    bars,
    fill_idx: int,
    fill_price: float,
    invalid: float,
    s1: float,
    *,
    trigger: float | None,
    fill_type: str,
    fractions: tuple[tuple[float, str], ...],
    time_stop_day: int | None = None,
    failed_breakout: bool = False,
    max_hold_days: int | None = None,
) -> list[dict]:
    """Simulate weighted fractions with T+1 daily-bar rules (conservative).

    fraction kind: "S1" (target S1), "S2" (research proxy target),
    "STRUCT" (no price target; structural invalid stop / max-hold close).
    - sell starts day fill+1; fill-day invalid touch exits all at day+1 open;
    - fill-day known targets only for OPEN/GAP/TRIGGER fills;
    - same-day invalid + target -> conservative stop-first at invalid;
    - max hold MAX_HOLD sessions.
    """

    hold_days = max_hold_days or MAX_HOLD
    end = min(len(bars), fill_idx + hold_days + 1)
    fill_bar = bars[fill_idx]
    s2_proxy = s1 + (fill_price - invalid)
    target_px = {"S1": s1, "S2": s2_proxy}
    # fill-day stop: T+1 blocked -> exit next open (conservative)
    if float(fill_bar.low) <= invalid:
        if fill_idx + 1 < len(bars):
            px = float(bars[fill_idx + 1].open)
            return [
                {
                    "frac": f,
                    "kind": k,
                    "exit_day": 1,
                    "exit_price": px,
                    "exit_type": "FILL_DAY_STOP_T1_BLOCKED",
                    "gross_pct": px / fill_price - 1,
                }
                for f, k in fractions
            ]
        return [
            {"frac": f, "kind": k, "exit_day": None, "exit_price": None, "exit_type": "CENSORED", "gross_pct": None}
            for f, k in fractions
        ]
    # NOTE: fill-day S1/S2 touch is NOT an exit (T+1 cannot sell on fill day;
    # Phase 2D.1A reports it as MISSED_SAME_DAY_TARGET_T1 / ORDER_UNKNOWN).
    # Exit scan starts at fill day + 1.
    max_high = 0.0
    breakout_exit_next: int | None = None
    results: list[dict] = []
    unresolved = {k: f for f, k in fractions}
    for idx in range(fill_idx + 1, end):
        bar = bars[idx]
        day = idx - fill_idx
        o, h, l, c = (float(bar.open), float(bar.high), float(bar.low), float(bar.close))
        max_high = max(max_high, h)
        if breakout_exit_next is None and failed_breakout and trigger is not None:
            if c < trigger:
                breakout_exit_next = idx + 1
        if time_stop_day is not None and day == time_stop_day:
            mfe_r = (max_high - fill_price) / (fill_price - invalid) if fill_price > invalid else 0
            if h < s1 and mfe_r < 0.5:
                results += [
                    {
                        "frac": f,
                        "kind": k,
                        "exit_day": day,
                        "exit_price": c,
                        "exit_type": f"TIME_STOP_{time_stop_day}",
                        "gross_pct": c / fill_price - 1,
                    }
                    for f, k in fractions
                    if k in unresolved
                ]
                unresolved = {}
                break
        hit_invalid = l <= invalid
        hit_s1 = h >= s1
        if o <= invalid:
            results += [
                {
                    "frac": f,
                    "kind": k,
                    "exit_day": day,
                    "exit_price": o,
                    "exit_type": "GAP_STOP",
                    "gross_pct": o / fill_price - 1,
                }
                for f, k in fractions
                if k in unresolved
            ]
            unresolved = {}
            break
        if o >= s1:
            results += [
                {
                    "frac": f,
                    "kind": k,
                    "exit_day": day,
                    "exit_price": s1,
                    "exit_type": "GAP_TARGET",
                    "gross_pct": s1 / fill_price - 1,
                }
                for f, k in fractions
                if k in unresolved
            ]
            unresolved = {}
            break
        if hit_invalid:
            results += [
                {
                    "frac": f,
                    "kind": k,
                    "exit_day": day,
                    "exit_price": invalid,
                    "exit_type": "STOP_FIRST" if (hit_s1 or (hit_s1 and "S2" in unresolved)) else "STOP",
                    "gross_pct": invalid / fill_price - 1,
                }
                for f, k in fractions
                if k in unresolved
            ]
            unresolved = {}
            break
        if breakout_exit_next is not None and idx >= breakout_exit_next:
            if idx < len(bars):
                px = float(bars[idx].open)
                results += [
                    {
                        "frac": f,
                        "kind": k,
                        "exit_day": day,
                        "exit_price": px,
                        "exit_type": "FAILED_BREAKOUT",
                        "gross_pct": px / fill_price - 1,
                    }
                    for f, k in fractions
                    if k in unresolved
                ]
                unresolved = {}
                break
        for kind in ("S1", "S2"):
            if kind not in unresolved:
                continue
            tp = target_px[kind]
            if h >= tp:
                results.append(
                    {
                        "frac": unresolved[kind],
                        "kind": kind,
                        "exit_day": day,
                        "exit_price": tp,
                        "exit_type": f"TARGET_{kind}",
                        "gross_pct": tp / fill_price - 1,
                    }
                )
                del unresolved[kind]
        if not unresolved:
            break
    if unresolved:
        last = min(len(bars), fill_idx + hold_days)
        px = float(bars[last].close) if last < len(bars) else fill_price
        results += [
            {
                "frac": f,
                "kind": k,
                "exit_day": last - fill_idx,
                "exit_price": px,
                "exit_type": "MAX_HOLD",
                "gross_pct": px / fill_price - 1,
            }
            for f, k in fractions
            if k in unresolved
        ]
    return results


def _combined_net_R(fraction_results: list[dict], risk_pct: float, bp: int) -> float | None:
    if not fraction_results or any(r["gross_pct"] is None for r in fraction_results):
        return None
    gross = sum(r["frac"] * r["gross_pct"] for r in fraction_results)
    net_pct = gross - bp / 10000
    return net_pct / risk_pct if risk_pct else None


def _sim_mode(
    bar_list,
    fill_idx: int,
    fill_price: float,
    invalid: float,
    s1: float,
    *,
    trigger: float | None,
    fill_type: str,
    mode: str,
    param: int | None = None,
) -> dict:
    risk_pct = (fill_price - invalid) / fill_price
    if mode == "P1":
        fracs = ((1.0, "S1"),)
        extra = {}
    elif mode == "P2":
        fracs = ((0.5, "S1"), (0.5, "STRUCT"))
        extra = {}
    elif mode == "P3":
        fracs = ((1 / 3, "S1"), (1 / 3, "S2"), (1 / 3, "STRUCT"))
        extra = {}
    elif mode == "FAILED_BREAKOUT":
        fracs = ((1.0, "S1"),)
        extra = {"failed_breakout": True}
    elif mode == "TIME_STOP":
        fracs = ((1.0, "S1"),)
        extra = {"time_stop_day": param}
    elif mode == "P4":
        fracs = ((1.0, "STRUCT"),)
        extra = {"max_hold_days": param}
    else:
        raise ValueError(mode)
    out = _simulate_fractions(
        bar_list,
        fill_idx,
        fill_price,
        invalid,
        s1,
        trigger=trigger,
        fill_type=fill_type,
        fractions=fracs,
        **extra,
    )
    first = min((r["exit_day"] for r in out if r["exit_day"] is not None), default=None)
    types = sorted({r["exit_type"] for r in out})
    return {
        "exit_day": first,
        "exit_types": types,
        "gross_pct": _combined_net_R(out, risk_pct, 0),
        "net_R_10bp": _combined_net_R(out, risk_pct, 10),
        "net_R_20bp": _combined_net_R(out, risk_pct, 20),
        "raw": out,
    }
    # window exhausted
    last = min(len(bars), fill_idx + MAX_HOLD)
    px = float(bars[last].close) if last < len(bars) else fill_price
    return {
        "exit_day": last - fill_idx,
        "exit_price": px,
        "exit_type": "MAX_HOLD",
        "gross_pct": px / fill_price - 1,
    }


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_episodes()
    df = mark_add_on(df)
    df["cohort"] = df.apply(cohort_of, axis=1)

    layout = WarehouseLayout(DATA_ROOT)
    snapshot, pool_records, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    pool_open_count = {
        (p.code, p.trade_date): int(p.open_count)
        for p in pool_records
        if p.open_count is not None
    }

    horizon_rows = []
    sim_rows = []
    codes = sorted(df["code"].unique())
    by_code: dict[str, list] = defaultdict(list)
    for _, row in df.iterrows():
        by_code[row["code"]].append(row)

    for code, bars in per_code_bars(layout, snapshot, codes):
        if not bars or code not in by_code:
            continue
        idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
        bar_list = list(bars)
        for row in by_code[code]:
            fill_date = row["fill_date"]
            fill_idx = idx_by_date.get(fill_date)
            if fill_idx is None:
                continue
            fill_price = float(row["fill_price"])
            invalid = float(row["invalid_price"])
            s1 = float(row["s1_price"])
            trigger = (
                float(row["b2_trigger_price"])
                if pd.notna(row["b2_trigger_price"])
                else None
            )
            fill_type = str(row["fill_type"])
            risk = fill_price - invalid
            if risk <= 0:
                continue
            rec = {
                "code": code,
                "setup_id": row["setup_id"],
                "cohort": row["cohort"],
                "b2_add_on": bool(row["b2_add_on"]),
                "fill_date": fill_date,
                "fill_price": fill_price,
                "invalid": invalid,
                "s1": s1,
                "risk_pct": (risk / fill_price),
                "fill_type": fill_type,
                "execution_label": row["execution_label"],
            }
            # horizon metrics: sessions 1..k after fill (no same-day assumption)
            hrec = dict(rec)
            for k in HORIZONS:
                if fill_idx + k < len(bar_list):
                    seg = bar_list[fill_idx + 1 : fill_idx + k + 1]
                    ret = float(bar_list[fill_idx + k].close) / fill_price - 1
                    mfe = max(float(b.high) for b in seg) / fill_price - 1
                    mae = min(float(b.low) for b in seg) / fill_price - 1
                    hrec[f"ret_{k}d"] = ret
                    hrec[f"mfe_{k}d"] = mfe
                    hrec[f"mae_{k}d"] = mae
            # time-to-hit within max hold
            t_s1 = t_inv = None
            for idx in range(fill_idx + 1, min(len(bar_list), fill_idx + MAX_HOLD + 1)):
                b = bar_list[idx]
                if t_s1 is None and float(b.high) >= s1:
                    t_s1 = idx - fill_idx
                if t_inv is None and float(b.low) <= invalid:
                    t_inv = idx - fill_idx
                if t_s1 is not None and t_inv is not None:
                    break
            hrec["time_to_s1"] = t_s1
            hrec["time_to_invalid"] = t_inv
            if t_s1 is not None and t_inv is not None:
                hrec["first_hit"] = "S1" if t_s1 < t_inv else ("INVALID" if t_inv < t_s1 else "SAME_DAY")
            elif t_s1 is not None:
                hrec["first_hit"] = "S1_ONLY"
            elif t_inv is not None:
                hrec["first_hit"] = "INVALID_ONLY"
            else:
                hrec["first_hit"] = "NONE_10D"
            horizon_rows.append(hrec)

            # exit-rule variants (P1 = structural baseline all-at-S1)
            for mode, param in (
                ("P1", None),
                ("FAILED_BREAKOUT", None),
                ("TIME_STOP_3", 3),
                ("TIME_STOP_5", 5),
                ("P2", None),
                ("P3", None),
                ("P4_H5", 5),
                ("P4_H8", 8),
                ("P4_H10", 10),
            ):
                out = _sim_mode(
                    bar_list,
                    fill_idx,
                    fill_price,
                    invalid,
                    s1,
                    trigger=trigger,
                    fill_type=fill_type,
                    mode="TIME_STOP" if mode.startswith("TIME_STOP") else (
                        "P4" if mode.startswith("P4") else mode
                    ),
                    param=param,
                )
                if out["gross_pct"] is None:
                    continue
                sim_rows.append(
                    {
                        **rec,
                        "mode": mode,
                        "param": param,
                        "exit_day": out["exit_day"],
                        "exit_type": ",".join(out["exit_types"]),
                        "net_R_10bp": out["net_R_10bp"],
                        "net_R_20bp": out["net_R_20bp"],
                    }
                )

    hdf = pd.DataFrame(horizon_rows)
    sdf = pd.DataFrame(sim_rows)
    for col in [c for c in hdf.columns if c.startswith(("ret_", "mfe_", "mae_"))]:
        hdf[col] = pd.to_numeric(hdf[col], errors="coerce")
    for col in ["risk_pct", "exit_day", "net_R_10bp", "net_R_20bp"]:
        sdf[col] = pd.to_numeric(sdf[col], errors="coerce")

    # ---- net R helpers (friction subtracted once per trade) ----
    def net_r(df_, mode, bp=10):
        sub = df_[df_["mode"] == mode].copy()
        col = "net_R_10bp" if bp == 10 else "net_R_20bp"
        return sub.rename(columns={col: "net_R"})

    metrics: dict = {
        "title": "B1/B2 EXECUTION + POSITION SIZING RESEARCH v0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "note_s2": "S2 is an event flag (S2_EXHAUSTED) in frozen strategy; no S2 price target exists. "
        "P3 uses RESEARCH_ONLY S2 proxy = S1 + 1R.",
        "cohort_counts": df.groupby("cohort").size().to_dict(),
        "b2_add_on_counts": {
            f"{k[0]}:add_on={k[1]}": v
            for k, v in df[df["cohort"] != "B1"].groupby(["cohort", "b2_add_on"]).size().to_dict().items()
        },
        "fill_type_counts": df["fill_type"].value_counts().to_dict(),
    }

    # C. horizons + time-to-hit
    hmetrics = {}
    for cohort in ("B1", "B2_READY", "B2_CONFIRMED", "B2_ALL"):
        sub = hdf if cohort != "B2_ALL" else hdf[hdf["cohort"] != "B1"]
        if cohort != "B2_ALL":
            sub = sub[sub["cohort"] == cohort]
        out: dict = {}
        for k in HORIZONS:
            vals = sub[f"ret_{k}d"].dropna()
            out[f"ret_{k}d"] = _stats(vals.tolist())
            out[f"mfe_{k}d"] = _stats(sub[f"mfe_{k}d"].dropna().tolist())
            out[f"mae_{k}d"] = _stats(sub[f"mae_{k}d"].dropna().tolist())
        s1hits = sub[sub["time_to_s1"].notna()]
        invhits = sub[sub["time_to_invalid"].notna()]
        out["time_to_s1"] = _stats(s1hits["time_to_s1"].tolist())
        out["time_to_invalid"] = _stats(invhits["time_to_invalid"].tolist())
        out["s1_hit_rate_10d"] = round(len(s1hits) / len(sub), 4) if len(sub) else None
        out["invalid_hit_rate_10d"] = round(len(invhits) / len(sub), 4) if len(sub) else None
        out["first_hit"] = sub["first_hit"].value_counts().to_dict()
        hmetrics[cohort] = out
    metrics["C_horizons"] = hmetrics

    # D/E. exit-rule comparison (10bp and 20bp)
    sim_metrics = {}
    for cohort in ("B1", "B2_READY", "B2_CONFIRMED", "B2_ALL"):
        sub0 = sdf if cohort != "B2_ALL" else sdf[sdf["cohort"] != "B1"]
        if cohort != "B2_ALL":
            sub0 = sub0[sub0["cohort"] == cohort]
        out = {}
        for mode in sorted(sub0["mode"].unique()):
            m = net_r(sub0, mode, 10)
            m20 = net_r(sub0, mode, 20)
            st = _stats(m["net_R"].dropna().tolist())
            st["win_rate"] = _win_rate(m["net_R"].dropna().tolist())
            st["n"] = int(m["net_R"].notna().sum())
            st20 = _stats(m20["net_R"].dropna().tolist())
            st20["win_rate"] = _win_rate(m20["net_R"].dropna().tolist())
            st20["n"] = int(m20["net_R"].notna().sum())
            st["mean_20bp"] = st20["mean"]
            st["median_20bp"] = st20["median"]
            st["exit_types"] = m["exit_type"].value_counts().head(6).to_dict()
            st["avg_exit_day"] = round(m["exit_day"].mean(), 2) if len(m) else None
            out[mode] = st
        sim_metrics[cohort] = out
    metrics["DE_exit_rules"] = sim_metrics

    # METRIC AUDIT: reconcile simulator P1 with frozen execution-reality P1
    audit = {}
    status_map = df.set_index(["code", "fill_date"])[
        "conservative_execution_status"
    ].to_dict()
    for cohort in ("B1", "B2_ALL"):
        canon_rows = (
            df[df["cohort"] == cohort]
            if cohort != "B2_ALL"
            else df[df["cohort"].isin(("B2_READY", "B2_CONFIRMED"))]
        )
        canon = canon_rows["conservative_net_execution_R_10bp"].dropna().astype(float)
        cohort_mask = (
            sdf["cohort"] == cohort
            if cohort != "B2_ALL"
            else sdf["cohort"].isin(("B2_READY", "B2_CONFIRMED"))
        )
        p1 = sdf[cohort_mask & (sdf["mode"] == "P1")].copy()
        p1["resolved"] = p1.apply(
            lambda r: status_map.get((r["code"], r["fill_date"])) == "RESOLVED", axis=1
        )
        p1_all = p1["net_R_10bp"].dropna().astype(float)
        p1_res = p1.loc[p1["resolved"], "net_R_10bp"].dropna().astype(float)
        audit[cohort] = {
            "canonical_execution_reality_conservative_10bp_mean_R": round(
                canon.mean(), 4
            ),
            "canonical_n_resolved": int(canon.notna().sum()),
            "simulator_P1_aligned_mean_R_all_filled": round(p1_all.mean(), 4)
            if len(p1_all)
            else None,
            "simulator_P1_n_all_filled": int(len(p1_all)),
            "simulator_P1_aligned_mean_R_resolved_only": round(p1_res.mean(), 4)
            if len(p1_res)
            else None,
            "simulator_P1_n_resolved_only": int(len(p1_res)),
            "reconciliation_note": (
                "Canonical number is the unique aligned P1 number: same-day stop-first, "
                "GAP_STOP at open, fill-day T+1 rules, 10bp single friction, 10-session window, "
                "unresolved (AMBIGUOUS/CENSORED/TIMEOUT) excluded. Simulator residual comes only "
                "from including unresolved episodes at max-hold close."
            ),
        }
    metrics["METRIC_AUDIT"] = audit

    # F. B1/B2 allocation evidence (execution reality, conservative + strict, 10bp)
    alloc = {}
    for label in ("B1", "B2_READY", "B2_CONFIRMED", "B2_ALL"):
        sub = df if label == "B2_ALL" else df[df["cohort"] == label]
        if label == "B2_ALL":
            sub = df[df["cohort"] != "B1"]
        for rcol, rname in (
            ("conservative_net_execution_R_10bp", "conservative_10bp"),
            ("net_execution_R_10bp", "strict_10bp"),
            ("conservative_net_execution_R_20bp", "conservative_20bp"),
        ):
            vals = sub[rcol].dropna().astype(float)
            st = _stats(vals.tolist())
            st["win_rate"] = _win_rate(vals.tolist())
            alloc.setdefault(label, {})[rname] = st
        b1 = sub[sub["cohort"] == "B1"]
        b2 = sub[sub["cohort"] != "B1"]
        if label == "B1":
            alloc[label]["b2_add_on_following_b1"] = {
                "count": int(df[df["b2_add_on"]].shape[0]),
                "share_of_b2": round(df[df["b2_add_on"]].shape[0] / max(1, (df["cohort"] != "B1").sum()), 4),
            }
        if label == "B2_ALL":
            ao = df[df["b2_add_on"]]
            so = df[(df["cohort"] != "B1") & (~df["b2_add_on"])]
            for rcol in ("conservative_net_execution_R_10bp", "net_execution_R_10bp"):
                st_a = _stats(ao[rcol].dropna().astype(float).tolist())
                st_a["win_rate"] = _win_rate(ao[rcol].dropna().astype(float).tolist())
                st_s = _stats(so[rcol].dropna().astype(float).tolist())
                st_s["win_rate"] = _win_rate(so[rcol].dropna().astype(float).tolist())
                alloc[label][f"add_on_{rcol}"] = st_a
                alloc[label][f"standalone_{rcol}"] = st_s
    metrics["F_allocation"] = alloc

    # I. chronological split (key metrics by year + discovery/validation)
    df["fill_year"] = df["fill_date"].apply(lambda d: d.year)
    df["period"] = df["fill_date"].apply(lambda d: "DISCOVERY" if d < SPLIT_DATE else "VALIDATION")
    split = {}
    for cohort in ("B1", "B2_READY", "B2_CONFIRMED", "B2_ALL"):
        sub = df if cohort == "B2_ALL" else df[df["cohort"] == cohort]
        if cohort == "B2_ALL":
            sub = df[df["cohort"] != "B1"]
        out = {}
        for period in ("DISCOVERY", "VALIDATION"):
            p = sub[sub["period"] == period]
            vals = p["conservative_net_execution_R_10bp"].dropna().astype(float)
            st = _stats(vals.tolist())
            st["win_rate"] = _win_rate(vals.tolist())
            st["n"] = int(p.shape[0])
            st["filled_n"] = int(vals.notna().sum())
            out[period] = st
        for year in (2024, 2025, 2026):
            y = sub[sub["fill_year"] == year]
            vals = y["conservative_net_execution_R_10bp"].dropna().astype(float)
            st = _stats(vals.tolist())
            st["win_rate"] = _win_rate(vals.tolist())
            st["n"] = int(y.shape[0])
            st["filled_n"] = int(vals.notna().sum())
            out[str(year)] = st
        split[cohort] = out
    metrics["I_split"] = split

    metrics["EDGE_GATING"] = edge_gating(df, hdf, pool_open_count)

    # G. position sizing (sequential proxy on resolved conservative 10bp R)
    sizing = {}
    sim_df = df[df["conservative_execution_status"] == "RESOLVED"].sort_values("fill_date")
    strict_df = df[df["strict_execution_status"] == "RESOLVED"].sort_values("fill_date")
    for risk_budget in (250, 500, 750, 1000):
        for cap in (0.20, 0.30, 0.40):
            key = f"risk{risk_budget}_cap{int(cap*100)}"
            for variant, base in (("conservative", sim_df), ("strict", strict_df)):
                equity = 100000.0
                peak = 100000.0
                max_dd = 0.0
                streak = 0
                max_streak = 0
                pnls = []
                exposures = []
                risk_abs_series = []
                rcol = "conservative_net_execution_R_10bp" if variant == "conservative" else "net_execution_R_10bp"
                for _, row in base.iterrows():
                    r = (
                        float(row[rcol])
                    )
                    if pd.isna(r):
                        continue
                    rpct = float(row["risk_pct"])
                    notional = min(risk_budget / rpct, cap * 100000)
                    eff_risk = min(risk_budget, cap * 100000 * rpct)
                    pnl = r * eff_risk
                    equity += pnl
                    pnls.append(pnl)
                    exposures.append(notional / 100000)
                    risk_abs_series.append(eff_risk)
                    peak = max(peak, equity)
                    max_dd = max(max_dd, peak - equity)
                    streak = streak + 1 if pnl < 0 else 0
                    max_streak = max(max_streak, streak)
                sizing.setdefault(key, {})[variant] = {
                    "n": len(pnls),
                    "total_pnl": round(sum(pnls), 2),
                    "final_equity": round(equity, 2),
                    "fixed_principal_proxy_max_cumulative_loss_rmb": round(max_dd, 2),
                    "fixed_principal_proxy_max_cumulative_loss_pct": round(max_dd / 100000 * 100, 2),
                    "consecutive_losses_max": max_streak,
                    "avg_exposure_pct": round(statistics.fmean(exposures) * 100, 2) if exposures else None,
                    "peak_exposure_pct": round(max(exposures) * 100, 2) if exposures else None,
                    "per_trade_vol_rmb": round(statistics.pstdev(pnls), 2) if pnls else None,
                    "avg_risk_rmb": round(statistics.fmean(risk_abs_series), 2) if risk_abs_series else None,
                    "proxy_worst_single_loss_share": round(min(0, min(pnls)) / 100000, 4) if pnls else None,
                    "proxy_note": "FIXED_PRINCIPAL_SEQUENTIAL_PROXY: one position at a time, fixed 100k base, "
                    "not a real portfolio backtest; max cumulative loss is NOT portfolio maxDD/risk-of-ruin",
                }
    metrics["G_sizing"] = sizing

    # G2. cohort-specific sizing at one representative policy
    cohort_sizing = {}
    for cohort, base in (
        ("B1_ONLY", sim_df[sim_df["cohort"] == "B1"]),
        ("B2_ONLY", sim_df[sim_df["cohort"] != "B1"]),
    ):
        equity = 100000.0
        peak = 100000.0
        max_dd = 0.0
        streak = 0
        max_streak = 0
        pnls = []
        for _, row in base.iterrows():
            r = float(row["conservative_net_execution_R_10bp"])
            rpct = float(row["risk_pct"])
            notional = min(500 / rpct, 0.30 * 100000)
            eff_risk = min(500, 0.30 * 100000 * rpct)
            pnl = r * eff_risk
            equity += pnl
            pnls.append(pnl)
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            streak = streak + 1 if pnl < 0 else 0
            max_streak = max(max_streak, streak)
        cohort_sizing[cohort] = {
            "n": len(pnls),
            "total_pnl": round(sum(pnls), 2),
            "fixed_principal_proxy_max_cumulative_loss_pct": round(max_dd / 100000 * 100, 2),
            "consecutive_losses_max": max_streak,
            "policy": "risk500_cap30",
            "proxy_note": "FIXED_PRINCIPAL_SEQUENTIAL_PROXY (not a real portfolio)",
        }
    metrics["G2_sizing_by_cohort"] = cohort_sizing

    metrics["G3_sizing_disclaimer"] = {
        "model": "FIXED_PRINCIPAL_SEQUENTIAL_PROXY",
        "not_portfolio_backtest": True,
        "not_risk_of_ruin": True,
        "detail": "100k fixed base, one episode at a time in fill-date order; equity may go below zero; "
        "reported cumulative loss is a proxy only.",
    }

    # H. apply recommended policy to the current 5 stocks
    current = [
        {
            "code": "603980",
            "name": "吉华集团",
            "stage": "B2_READY",
            "entry": 6.73,
            "invalid": 6.23,
            "s1": 7.02,
            "note": "B2 trigger entry; B1 zone 6.26-6.31",
        },
        {
            "code": "603185",
            "name": "弘元绿能",
            "stage": "B1_READY",
            "entry": 16.08,
            "invalid": 15.29,
            "s1": 17.05,
            "note": "B1 preferred entry; B2 trigger 16.37",
        },
        {
            "code": "601858",
            "name": "中国科传",
            "stage": "B2_READY",
            "entry": 20.61,
            "invalid": 18.71,
            "s1": 21.72,
            "note": "B2 trigger entry",
        },
        {
            "code": "600756",
            "name": "浪潮软件",
            "stage": "B2_READY",
            "entry": 16.52,
            "invalid": 15.66,
            "s1": 16.99,
            "note": "DATA_LIMITED 7/9-7/24 CONFIRMED gap",
        },
        {
            "code": "603232",
            "name": "格尔软件",
            "stage": "B2_CONFIRMED",
            "entry": 15.50,
            "invalid": 13.79,
            "s1": 16.68,
            "note": "POST_TRIGGER / NO_NEW_ENTRY",
        },
    ]
    policy = {"risk_budget": 500, "cap": 0.30}
    applied = []
    for item in current:
        rpct = (item["entry"] - item["invalid"]) / item["entry"]
        notional = min(policy["risk_budget"] / rpct, policy["cap"] * 100000)
        shares = int(notional // item["entry"] // 100) * 100
        applied.append(
            {
                **item,
                "risk_pct": round(rpct * 100, 2),
                "risk_budget_rmb": policy["risk_budget"],
                "notional_capped_rmb": round(notional, 0),
                "shares_100_lot": shares,
            }
        )
    metrics["H_current5"] = applied

    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


def edge_gating(df: pd.DataFrame, hdf: pd.DataFrame, pool_open_count: dict) -> dict:
    """Predefined-subgroup edge gating (no new thresholds beyond production ones)."""

    d = df.copy()
    d["entry_q"] = pd.to_numeric(d["entry_quality_score"].astype(str), errors="coerce")
    d["setup_q"] = pd.to_numeric(d["setup_quality_score"].astype(str), errors="coerce")
    d["rr"] = (d["s1_price"] - d["fill_price"]) / (d["fill_price"] - d["invalid_price"])
    d["near_s1"] = (d["s1_price"] - d["fill_price"]) / d["fill_price"]
    d["anchor_open_count"] = d.apply(
        lambda r: pool_open_count.get((r["code"], r["anchor_date"])), axis=1
    )
    d["anchor_sealed"] = d["anchor_open_count"] == 0
    d["anchor_opened"] = d["anchor_open_count"] > 0
    d["fill_year"] = d["fill_date"].apply(lambda x: x.year)
    d["period"] = d["fill_date"].apply(lambda x: "DISCOVERY" if x < SPLIT_DATE else "VALIDATION")

    h = hdf.copy()
    h["s1_first"] = h["first_hit"].isin(("S1", "S1_ONLY"))
    h["invalid_first"] = h["first_hit"].isin(("INVALID", "INVALID_ONLY"))
    hmap = (
        h.drop_duplicates(["code", "fill_date"])
        .set_index(["code", "fill_date"])[["s1_first", "invalid_first"]]
    )
    d = d.join(hmap, on=["code", "fill_date"])

    def gates(dd: pd.DataFrame) -> list[tuple[str, pd.Series]]:
        base = pd.Series(True, index=dd.index)
        out = [("ALL", base)]
        out += [
            ("ENTRY_Q_GE80", dd["entry_q"] >= 80),
            ("ENTRY_Q_LT80", dd["entry_q"] < 80),
            ("SETUP_Q_GE80", dd["setup_q"] >= 80),
            ("SETUP_Q_LT80", dd["setup_q"] < 80),
            ("ROOM_SUFFICIENT", dd["entry_room_state"] == "SUFFICIENT"),
            ("ROOM_THIN", dd["entry_room_state"] == "THIN"),
            ("RR_GE1_5", dd["rr"] >= 1.5),
            ("RR_LT1_5", dd["rr"] < 1.5),
            ("NEAR_S1_LE2PCT", dd["near_s1"] <= 0.02),
            ("NEAR_S1_GT2PCT", dd["near_s1"] > 0.02),
            ("ANCHOR_SEALED", dd["anchor_sealed"]),
            ("ANCHOR_OPENED", dd["anchor_opened"]),
            ("DQ_OK", dd["data_quality"] == "OK"),
        ]
        return out

    cohort_results: dict = {}
    for cohort in ("B1", "B2_READY", "B2_CONFIRMED"):
        base = d[d["cohort"] == cohort]
        groups = gates(base)
        if cohort == "B1":
            groups += [
                ("ENTRY80_SETUP80", (base["entry_q"] >= 80) & (base["setup_q"] >= 80)),
                ("ENTRY80_ROOM_SUFF", (base["entry_q"] >= 80) & (base["entry_room_state"] == "SUFFICIENT")),
                ("SETUP80_ROOM_SUFF", (base["setup_q"] >= 80) & (base["entry_room_state"] == "SUFFICIENT")),
                (
                    "ENTRY80_SETUP80_ROOM_SUFF",
                    (base["entry_q"] >= 80)
                    & (base["setup_q"] >= 80)
                    & (base["entry_room_state"] == "SUFFICIENT"),
                ),
                ("ENTRY80_RR1_5", (base["entry_q"] >= 80) & (base["rr"] >= 1.5)),
                ("SETUP80_RR1_5", (base["setup_q"] >= 80) & (base["rr"] >= 1.5)),
                ("ROOM_SUFF_RR1_5", (base["entry_room_state"] == "SUFFICIENT") & (base["rr"] >= 1.5)),
            ]
        out = {}
        for name, mask in groups:
            sub = base[mask]
            vals = sub["conservative_net_execution_R_10bp"].dropna().astype(float)
            st = _stats(vals.tolist())
            st["win_rate"] = _win_rate(vals.tolist())
            st["n_episodes"] = int(len(sub))
            st["n_resolved"] = int(vals.notna().sum())
            st["s1_first_rate"] = round(sub["s1_first"].mean(), 4) if len(sub) else None
            st["invalid_first_rate"] = round(sub["invalid_first"].mean(), 4) if len(sub) else None
            for period in ("DISCOVERY", "VALIDATION"):
                p = sub[sub["period"] == period]
                pv = p["conservative_net_execution_R_10bp"].dropna().astype(float)
                ps = _stats(pv.tolist())
                ps["win_rate"] = _win_rate(pv.tolist())
                ps["n_episodes"] = int(len(p))
                ps["n_resolved"] = int(pv.notna().sum())
                st[period] = ps
            for year in (2024, 2025, 2026):
                y = sub[sub["fill_year"] == year]
                yv = y["conservative_net_execution_R_10bp"].dropna().astype(float)
                st[str(year)] = {
                    "n_episodes": int(len(y)),
                    "n_resolved": int(yv.notna().sum()),
                    "mean": _stats(yv.tolist())["mean"],
                    "median": _stats(yv.tolist())["median"],
                }
            disc = st["DISCOVERY"]
            val = st["VALIDATION"]
            year_med = [st[str(y)]["median"] for y in (2024, 2025, 2026) if st[str(y)]["median"] is not None]
            passed = (
                disc.get("mean") is not None
                and val.get("mean") is not None
                and disc["mean"] > 0
                and val["mean"] > 0
                and disc["n_resolved"] >= 30
                and val["n_resolved"] >= 30
                and sum(1 for m in year_med if m and m > 0) >= 2
            )
            observe = (
                not passed
                and disc.get("mean") is not None
                and val.get("mean") is not None
                and (disc["mean"] > 0 or val["mean"] > 0)
                and disc["n_resolved"] >= 20
                and val["n_resolved"] >= 20
            )
            st["gate"] = "EDGE_SUPPORTED" if passed else ("OBSERVE_ONLY" if observe else "REJECT")
            out[name] = st
        cohort_results[cohort] = out
    return cohort_results


if __name__ == "__main__":
    run()
