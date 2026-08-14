"""FORWARD_PAPER_D0_BPOINT_V02_REFERENCE_REPAIR (research-only).

Semantic repair of the V01 prestart reference defects:
  DEFECT_1: V01 reference/dev scores used definition A (D0cum / D1 full-day);
            V02 uses the approved F (D0cum / D1 same-time) only.
  DEFECT_2: V01 reference JSON lacked per-component CDFs; V02 freezes sorted
            component values + percentile method (EMPIRICAL_MIDRANK_ECDF_V1).

V01 files are never modified. Reference builder never reads outcome fields.
No historical edge search, no weight/quartile/threshold optimisation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from bpoint_morphology_lib import midrank_ecdf_percentile, quiet_quartile_v02


ROOT = Path(__file__).resolve().parents[1]
FWD = ROOT / "research/bpoint/forward"
OUT = ROOT / "research/data-source-migration-v01"
OUT.mkdir(parents=True, exist_ok=True)
CACHE_5M = ROOT / "data/tmp/v02a-minute/raw_5m"
CHECKPOINTS = {"0945": 585, "1000": 600}
COMPONENTS = ["volume_pace", "abs_session_low", "session_range"]
V02_REFERENCE = FWD / "quiet_score_reference_v02.json"
V02_PROTOCOL = FWD / "FORWARD_PAPER_PROTOCOL_V02.json"
V02_MANIFEST = FWD / "FORWARD_EPOCH_1_V02_MANIFEST.json"


def sha(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps({k: v for k, v in obj.items() if k != "hash"}, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def load_sina(code: str) -> pd.DataFrame | None:
    p = CACHE_5M / f"{code}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df["ts"] = pd.to_datetime(df["day"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def cum_volume(df: pd.DataFrame, d: date, t: int) -> float | None:
    if df is None:
        return None
    s = df[df["ts"].dt.date == d]
    if not len(s):
        return None
    tt = s["ts"].dt.hour * 60 + s["ts"].dt.minute
    sub = s.loc[tt <= t, "volume"]
    return float(sub.sum()) if len(sub) else None


def load_daily() -> dict[str, pd.DataFrame]:
    can = pd.read_parquet(
        ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet",
        columns=["code", "trade_date", "close", "volume"],
    )
    can["trade_date"] = pd.to_datetime(can["trade_date"]).dt.date
    can["code"] = can["code"].astype(str).str.zfill(6)
    return {c: g.sort_values("trade_date").reset_index(drop=True) for c, g in can.groupby("code")}


def dev_rows() -> tuple[pd.DataFrame, pd.DataFrame]:
    # Membership = the 206 V01 development cases; read NO outcome column.
    feats = pd.read_parquet(
        ROOT / "research/bpoint/intraday/checkpoint_features_v01.parquet",
        columns=[
            "episode_id", "symbol", "candidate_date", "CHECKPOINT",
            "cum_volume", "session_low_pct_vs_prev_close", "session_range_pct",
            "session_low_price", "session_high_price",
        ],
    )
    feats["candidate_date"] = pd.to_datetime(feats["candidate_date"]).dt.date
    cases = feats.drop_duplicates(subset=["episode_id"])
    bars = load_daily()
    caches = {p.stem: load_sina(p.stem) for p in CACHE_5M.glob("*.parquet")}
    rows = []
    for _, c in cases.iterrows():
        code = c["symbol"]
        d0 = c["candidate_date"]
        bm = bars.get(code)
        if bm is None:
            continue
        dates = bm["trade_date"].tolist()
        if d0 not in dates:
            continue
        i = dates.index(d0)
        if i < 1:
            continue
        d1 = dates[i - 1]
        df = caches.get(code)
        for ck, t in CHECKPOINTS.items():
            d0v = cum_volume(df, d0, t)
            d1v = cum_volume(df, d1, t)
            sub = feats[(feats["episode_id"] == c["episode_id"]) & (feats["CHECKPOINT"] == ck)]
            if len(sub) == 0 or d0v is None or d1v is None or d1v == 0:
                continue
            r = sub.iloc[0]
            rows.append({
                "episode_id": c["episode_id"],
                "symbol": code,
                "candidate_date": d0.isoformat(),
                "CHECKPOINT": ck,
                "volume_pace": round(d0v / d1v, 10),
                "abs_session_low": round(abs(float(r["session_low_pct_vs_prev_close"])), 10),
                "session_range": round(float(r["session_range_pct"]), 10),
                "session_low_price": float(r["session_low_price"]),
                "session_high_price": float(r["session_high_price"]),
            })
    df = pd.DataFrame(rows)
    # eligibility: both checkpoints complete with all components
    per_case = df.groupby("episode_id")["CHECKPOINT"].nunique()
    eligible_ids = per_case[per_case == 2].index.tolist()
    eligible = df[df["episode_id"].isin(eligible_ids)].copy()
    all_ids = cases["episode_id"].tolist()
    excluded = [eid for eid in all_ids if eid not in eligible_ids]
    if len(eligible_ids) != 195:
        raise SystemExit(f"STOP_REFERENCE_BUILD_ERROR: eligible cases={len(eligible_ids)} != 195")
    return eligible, pd.DataFrame({"episode_id": excluded})


def build_reference(dev: pd.DataFrame) -> dict:
    ref = {
        "schema_version": "FORWARD_PAPER_D0_BPOINT_V02",
        "supersedes": "V01",
        "reason": "PRESTART_REFERENCE_SEMANTIC_DEFECT",
        "forward_rows_before_supersede": 0,
        "primary_volume_definition": "D0_CUM_VOLUME_TO_CHECKPOINT / D1_SAME_TIME_CUM_VOLUME",
        "eligibility_rule": (
            "V02_REFERENCE_ELIGIBLE = candidate has complete frozen intraday data "
            "required to calculate all three V02 primary components (VOLUME_PACE_PRIMARY, "
            "ABS_SESSION_LOW_VS_PREV_CLOSE, SESSION_RANGE_PCT) at BOTH 09:45 and 10:00; "
            "same membership for all components/checkpoints"
        ),
        "reference_n": int(dev["episode_id"].nunique()),
        "original_development_case_n": 206,
        "excluded_missing_intraday_n": 11,
        "membership_change_reason": "PRIMARY_VOLUME_SEMANTIC_REPAIR_REQUIRES_D1_SAME_TIME_DATA",
        "outcome_based_filtering": False,
        "cross_provider_reference_backfill": False,
        "percentile_method": "EMPIRICAL_MIDRANK_ECDF_V1",
        "quiet_score_formula": "mean(1-pct(VOLUME_PACE_PRIMARY), 1-pct(abs(SESSION_LOW_VS_PREV_CLOSE)), 1-pct(SESSION_RANGE_PCT)); equal weights",
        "components": {},
        "quiet_score_reference": {},
    }
    for ck in CHECKPOINTS:
        sub = dev[dev["CHECKPOINT"] == ck]
        comp = {}
        for col in COMPONENTS:
            vals = np.sort(sub[col].to_numpy(dtype=float))
            comp[col] = {
                "sorted_values": [round(float(v), 10) for v in vals],
                "n": int(len(vals)),
                "min": round(float(vals.min()), 10),
                "max": round(float(vals.max()), 10),
                "p25": round(float(np.quantile(vals, 0.25)), 10),
                "p50": round(float(np.quantile(vals, 0.50)), 10),
                "median": round(float(np.median(vals)), 10),
                "p75": round(float(np.quantile(vals, 0.75)), 10),
            }
        ref["components"][ck] = comp
        # scores with frozen component CDFs
        scores = []
        for _, r in sub.iterrows():
            pct = [
                midrank_ecdf_percentile(np.array(comp["volume_pace"]["sorted_values"]), r["volume_pace"]),
                midrank_ecdf_percentile(np.array(comp["abs_session_low"]["sorted_values"]), r["abs_session_low"]),
                midrank_ecdf_percentile(np.array(comp["session_range"]["sorted_values"]), r["session_range"]),
            ]
            scores.append(round(float(np.mean([1 - p for p in pct])), 10))
        scores = np.sort(np.array(scores))
        ref["quiet_score_reference"][ck] = {
            "sorted_quiet_scores": [round(float(v), 10) for v in scores],
            "Q25": round(float(np.quantile(scores, 0.25)), 10),
            "Q50": round(float(np.quantile(scores, 0.50)), 10),
            "Q75": round(float(np.quantile(scores, 0.75)), 10),
            "n": int(len(scores)),
            "quartile_rule": "score<=Q25->Q1; Q25<score<=Q50->Q2; Q50<score<=Q75->Q3; score>Q75->Q4",
        }
    return ref


def score_with_ref(ref: dict, ck: str, vp: float, shallow_abs: float, rng: float) -> float:
    comp = ref["components"][ck]
    pct = [
        midrank_ecdf_percentile(np.array(comp["volume_pace"]["sorted_values"]), vp),
        midrank_ecdf_percentile(np.array(comp["abs_session_low"]["sorted_values"]), shallow_abs),
        midrank_ecdf_percentile(np.array(comp["session_range"]["sorted_values"]), rng),
    ]
    return float(np.mean([1 - p for p in pct]))


def tdx_features(dev: pd.DataFrame) -> pd.DataFrame:
    from pytdx.hq import TdxHq_API
    from pytdx.params import TDXParams

    bars = load_daily()
    api = TdxHq_API()
    assert api.connect("180.153.18.170", 7709, time_out=5)
    cache = {}

    def market(code): return TDXParams.MARKET_SH if code.startswith("6") else TDXParams.MARKET_SZ

    def tdx_session(code, d):
        key = (code, d)
        if key in cache:
            return cache[key]
        out = []
        for b in api.get_security_bars(TDXParams.KLINE_TYPE_5MIN, market(code), code, 0, 800) or []:
            if date(b["year"], b["month"], b["day"]) == d:
                out.append((b["hour"] * 60 + b["minute"], float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]), float(b["vol"])))
        cache[key] = out
        return out

    rows = []
    for _, c in dev[["episode_id", "symbol", "candidate_date"]].drop_duplicates().iterrows():
        code = c["symbol"]
        d0 = date.fromisoformat(c["candidate_date"])
        bm = bars.get(code)
        if bm is None:
            continue
        dates = bm["trade_date"].tolist()
        if d0 not in dates:
            continue
        i = dates.index(d0)
        if i < 1:
            continue
        d1 = dates[i - 1]
        s0 = tdx_session(code, d0)
        s1 = tdx_session(code, d1)
        if len(s0) < 40 or len(s1) < 40:
            continue
        prev_close = float(bm.iloc[i - 1]["close"])
        open0 = s0[0][1]
        for ck, t in CHECKPOINTS.items():
            def agg(s, t):
                sub = [x for x in s if x[0] <= t]
                return sum(x[5] for x in sub), min(x[3] for x in sub), max(x[2] for x in sub)
            c0, lo0, hi0 = agg(s0, t)
            c1, _, _ = agg(s1, t)
            if c0 == 0 or c1 == 0:
                continue
            rows.append({
                "episode_id": c["episode_id"], "symbol": code, "candidate_date": c["candidate_date"],
                "CHECKPOINT": ck,
                "tdx_vp": c0 / c1,
                "tdx_shallow": (lo0 / prev_close - 1.0) * 100.0,
                "tdx_range": (hi0 - lo0) / open0 * 100.0,
                "tdx_low": lo0, "tdx_high": hi0,
            })
    api.disconnect()
    return pd.DataFrame(rows)


def main() -> None:
    dev, excluded = dev_rows()
    ref = build_reference(dev)
    ref["hash"] = sha(ref)
    json.dump(ref, open(V02_REFERENCE, "w"), ensure_ascii=False, indent=2, default=str)
    # reproducibility: runner path (JSON-only) vs builder path
    reloaded = json.load(open(V02_REFERENCE))
    repro_diffs = [
        abs(
            score_with_ref(ref, r["CHECKPOINT"], r["volume_pace"], r["abs_session_low"], r["session_range"])
            - score_with_ref(reloaded, r["CHECKPOINT"], r["volume_pace"], r["abs_session_low"], r["session_range"])
        )
        for _, r in dev.iterrows()
    ]
    repro_max = round(float(max(repro_diffs)), 12)
    print("SCORE_REPRODUCIBILITY_MAX_ABS_DIFF:", repro_max)
    dev.to_csv(OUT / "quiet_score_development_v02.csv", index=False)
    print("REFERENCE_V02_HASH:", ref["hash"])
    print("dev rows:", len(dev), "cases:", dev["episode_id"].nunique(), "per ck:", dev["CHECKPOINT"].value_counts().to_dict())

    # exclusion audit + outcome-count QA (post-freeze; builder never read outcome)
    feats_all = pd.read_parquet(
        ROOT / "research/bpoint/intraday/checkpoint_features_v01.parquet",
        columns=["episode_id", "symbol", "candidate_date", "outcome"],
    )
    feats_all["candidate_date"] = pd.to_datetime(feats_all["candidate_date"]).dt.date
    case_meta = feats_all.drop_duplicates(subset=["episode_id"])
    excl_rows = []
    for eid in excluded["episode_id"]:
        r = case_meta[case_meta["episode_id"] == eid]
        d0 = r.iloc[0]["candidate_date"]
        excl_rows.append({
            "episode_id": eid, "symbol": r.iloc[0]["symbol"],
            "candidate_date": d0.isoformat(), "d1_date": "2026-06-05",
            "missing_0945": True, "missing_1000": True,
            "exclusion_reason": "V02_REFERENCE_INELIGIBLE_MISSING_D1_SAME_TIME",
        })
    pd.DataFrame(excl_rows).to_csv(OUT / "reference_exclusion_audit_v02.csv", index=False)
    eligible_out = case_meta[case_meta["episode_id"].isin(dev["episode_id"].unique())]["outcome"].value_counts().to_dict()
    excluded_out = case_meta[case_meta["episode_id"].isin(excluded["episode_id"])]["outcome"].value_counts().to_dict()
    print("ELIGIBLE_OUTCOME_COUNTS:", eligible_out)
    print("EXCLUDED_OUTCOME_COUNTS:", excluded_out)

    # TDX parity on the max available TDX window (subset of dev)
    tdx = tdx_features(dev)
    tdx = tdx.merge(
        dev[["episode_id", "CHECKPOINT", "volume_pace", "abs_session_low", "session_range",
             "session_low_price", "session_high_price"]],
        on=["episode_id", "CHECKPOINT"], how="inner",
    )
    print("TDX_FROZEN_CASE_N:", tdx["episode_id"].nunique(), "rows:", len(tdx))
    parity = {}
    for ck in CHECKPOINTS:
        sub = tdx[tdx["CHECKPOINT"] == ck]
        ratio = sub["tdx_vp"] / sub["volume_pace"]
        low_diff = (sub["tdx_low"] - sub["session_low_price"]).abs()
        high_diff = (sub["tdx_high"] - sub["session_high_price"]).abs()
        range_diff = (sub["tdx_range"] - sub["session_range"]).abs()
        parity[ck] = {
            "volume_pace_median_ratio": round(float(ratio.median()), 4),
            "volume_pace_p25_p75": [round(float(ratio.quantile(0.25)), 4), round(float(ratio.quantile(0.75)), 4)],
            "session_low_exact_match_rate": round(float((low_diff == 0).mean()), 4),
            "session_low_max_abs_diff": round(float(low_diff.max()), 4),
            "session_low_median_abs_diff": round(float(low_diff.median()), 4),
            "session_high_exact_match_rate": round(float((high_diff == 0).mean()), 4),
            "session_high_max_abs_diff": round(float(high_diff.max()), 4),
            "session_high_median_abs_diff": round(float(high_diff.median()), 4),
            "session_range_median_abs_diff": round(float(range_diff.median()), 4),
            "session_range_max_abs_diff": round(float(range_diff.max()), 4),
        }
    # score + quartile parity using V02 component CDFs
    tdx["frozen_score"] = tdx.apply(lambda r: score_with_ref(ref, r["CHECKPOINT"], r["volume_pace"], r["abs_session_low"], r["session_range"]), axis=1)
    tdx["tdx_score"] = tdx.apply(lambda r: score_with_ref(ref, r["CHECKPOINT"], r["tdx_vp"], abs(r["tdx_shallow"]), r["tdx_range"]), axis=1)
    tdx["score_abs_diff"] = (tdx["tdx_score"] - tdx["frozen_score"]).abs()
    tdx["frozen_q"] = tdx.apply(lambda r: quiet_quartile_v02(r["frozen_score"], ref["quiet_score_reference"][r["CHECKPOINT"]]["Q25"], ref["quiet_score_reference"][r["CHECKPOINT"]]["Q50"], ref["quiet_score_reference"][r["CHECKPOINT"]]["Q75"]), axis=1)
    tdx["tdx_q"] = tdx.apply(lambda r: quiet_quartile_v02(r["tdx_score"], ref["quiet_score_reference"][r["CHECKPOINT"]]["Q25"], ref["quiet_score_reference"][r["CHECKPOINT"]]["Q50"], ref["quiet_score_reference"][r["CHECKPOINT"]]["Q75"]), axis=1)
    tdx["agree"] = tdx["frozen_q"] == tdx["tdx_q"]
    score_abs = tdx["score_abs_diff"]
    spearman = round(float(tdx["frozen_score"].rank().corr(tdx["tdx_score"].rank())), 4)
    continuous = {
        "median": round(float(score_abs.median()), 6),
        "p95": round(float(score_abs.quantile(0.95)), 6),
        "max": round(float(score_abs.max()), 6),
        "spearman_rank_corr": spearman,
    }
    # boundary audit for disagreements
    audit_rows = []
    for _, r in tdx[~tdx["agree"]].iterrows():
        qref = ref["quiet_score_reference"][r["CHECKPOINT"]]
        bounds = [qref["Q25"], qref["Q50"], qref["Q75"]]
        fd = min(abs(r["frozen_score"] - b) for b in bounds)
        td = min(abs(r["tdx_score"] - b) for b in bounds)
        raw_ok = (0.995 <= r["tdx_vp"] / r["volume_pace"] <= 1.005
                  and abs(r["tdx_low"] - r["session_low_price"]) <= 0.01
                  and abs(r["tdx_high"] - r["session_high_price"]) <= 0.01
                  and abs(r["tdx_range"] - r["session_range"]) <= 0.05)
        audit_rows.append({
            "code": r["symbol"], "candidate_date": r["candidate_date"], "CHECKPOINT": r["CHECKPOINT"],
            "frozen_score": round(r["frozen_score"], 6), "tdx_score": round(r["tdx_score"], 6),
            "abs_score_diff": round(r["score_abs_diff"], 6),
            "nearest_boundary": min(bounds, key=lambda b: min(abs(r["frozen_score"] - b), abs(r["tdx_score"] - b))),
            "frozen_dist_to_boundary": round(fd, 6), "tdx_dist_to_boundary": round(td, 6),
            "vp_ratio": round(float(r["tdx_vp"] / r["volume_pace"]), 5),
            "low_diff": round(float(abs(r["tdx_low"] - r["session_low_price"])), 4),
            "high_diff": round(float(abs(r["tdx_high"] - r["session_high_price"])), 4),
            "range_diff": round(float(abs(r["tdx_range"] - r["session_range"])), 4),
            "classification": "BOUNDARY_SENSITIVE" if raw_ok else "PROVIDER_MATERIAL_MISMATCH",
        })
    boundary_n = sum(1 for x in audit_rows if x["classification"] == "BOUNDARY_SENSITIVE")
    material_n = sum(1 for x in audit_rows if x["classification"] == "PROVIDER_MATERIAL_MISMATCH")
    json.dump({
        "tdx_frozen_case_n": int(tdx["episode_id"].nunique()),
        "checkpoints": parity,
        "quiet_score_continuous": continuous,
        "quartile_agreement_rate": round(float(tdx["agree"].mean()), 4),
        "boundary_sensitive_n": boundary_n,
        "provider_material_mismatch_n": material_n,
        "boundary_audit_rows": audit_rows,
    }, open(OUT / "v02_tdx_parity_full.json", "w"), ensure_ascii=False, indent=2, default=str)
    print(json.dumps({"parity": parity, "continuous": continuous,
                      "quartile_agreement": round(float(tdx["agree"].mean()), 4),
                      "boundary_sensitive_n": boundary_n, "material_n": material_n}, ensure_ascii=False, indent=2))

    volume_pass = all(
        0.995 <= parity[ck]["volume_pace_median_ratio"] <= 1.005 for ck in CHECKPOINTS
    )
    price_pass = all(
        parity[ck]["session_low_max_abs_diff"] <= 0.01
        and parity[ck]["session_high_max_abs_diff"] <= 0.01
        and parity[ck]["session_range_max_abs_diff"] <= 0.05
        for ck in CHECKPOINTS
    )
    score_pass = (
        continuous["median"] <= 0.005
        and continuous["p95"] <= 0.02
        and continuous["spearman_rank_corr"] >= 0.99
    )
    compat = "PASS_TDX_V02" if (volume_pass and price_pass and score_pass and material_n == 0) else "FAIL"

    protocol = {
        "protocol_version": "FORWARD_PAPER_D0_BPOINT_V02",
        "supersedes": "FORWARD_PAPER_D0_BPOINT_V01",
        "supersede_reason": "PRESTART_REFERENCE_SEMANTIC_DEFECT",
        "forward_rows_before_supersede": 0,
        "primary_checkpoints": ["09:45", "10:00"],
        "primary_features": ["VOLUME_PACE_PRIMARY", "SESSION_LOW_VS_PREV_CLOSE", "SESSION_RANGE_PCT"],
        "primary_volume_definition": "D0_CUM_VOLUME_TO_CHECKPOINT / D1_SAME_TIME_CUM_VOLUME",
        "volume_audit_columns_only": ["D0CUM/D1_FULL", "D0CUM/ANCHOR", "D0CUM/MEDIAN5"],
        "percentile_method": "EMPIRICAL_MIDRANK_ECDF_V1",
        "quiet_score_formula": "mean(1-pct(VOLUME_PACE_PRIMARY), 1-pct(abs(SESSION_LOW_VS_PREV_CLOSE)), 1-pct(SESSION_RANGE_PCT)); equal weights",
        "quartile_rule": "score<=Q25->Q1; Q25<score<=Q50->Q2; Q50<score<=Q75->Q3; score>Q75->Q4 (Q4=quietest)",
        "paper_entry_price_rule": "checkpoint last completed 5m bar close",
        "outcome_definition": "SUCCESS/FAILED_BREAKOUT/NO_LAUNCH/STRUCTURE_FAIL/UNKNOWN (3-session structural, frozen)",
        "interim_gate": {"SUCCESS_min": 10, "FAILED_BREAKOUT_min": 20},
        "decision_gate": {"SUCCESS_min": 30, "FAILED_BREAKOUT_min": 30, "trading_sessions_min": 20},
        "intraday_provider": "TDX_5M",
        "intraday_audit": "SINA_5M",
        "daily_provider": "TDX",
        "daily_confirmation": "TENCENT",
        "daily_audit_backup": "BAOSTOCK",
        "no_provider_fallback": True,
        "missing_volume_policy": "VOLUME_PACE_PRIMARY=NA, VOLUME_PRIMARY_STATUS=MISSING; no fallback",
        "missing_score_policy": "QUIET_SCORE=NA, QUIET_SCORE_STATUS=INCOMPLETE, QUIET_QUARTILE=NA",
        "corporate_action_policy": "CORPORATE_ACTION_AFFECTED=true -> QUIET_SCORE_STATUS=CORPORATE_ACTION_EXCLUDED",
        "reference_distribution_hash": ref["hash"],
        "forbidden": ["threshold scan", "weight change", "outcome redefinition", "historical backfill"],
    }
    protocol["hash"] = sha(protocol)
    json.dump(protocol, open(V02_PROTOCOL, "w"), ensure_ascii=False, indent=2)

    manifest = {
        "epoch_id": "FORWARD_EPOCH_1_V02",
        "supersedes": "FORWARD_EPOCH_1",
        "supersede_reason": "PRESTART_REFERENCE_SEMANTIC_DEFECT",
        "v01_forward_rows": 0,
        "original_development_case_n": 206,
        "reference_eligible_case_n": 195,
        "excluded_missing_intraday_n": 11,
        "membership_change_reason": "PRIMARY_VOLUME_SEMANTIC_REPAIR_REQUIRES_D1_SAME_TIME_DATA",
        "outcome_based_filtering": False,
        "cross_provider_reference_backfill": False,
        "eligibility_rule": ref["eligibility_rule"],
        "protocol_hash": protocol["hash"],
        "reference_distribution_hash": ref["hash"],
        "primary_volume_definition": "D0_CUM_VOLUME / D1_SAME_TIME_CUM_VOLUME",
        "percentile_method": "EMPIRICAL_MIDRANK_ECDF_V1",
        "intraday_provider": "TDX_5M",
        "daily_provider": "TDX",
        "daily_confirmation": "TENCENT",
        "historical_forward_backfill": False,
        "forward_reference_compatibility": compat,
        "provider_parity_metrics": {
            "volume_pace_0945": parity["0945"]["volume_pace_median_ratio"],
            "volume_pace_1000": parity["1000"]["volume_pace_median_ratio"],
            "quiet_score_abs_diff_median": continuous["median"],
            "quiet_score_rank_correlation": continuous["spearman_rank_corr"],
            "quartile_agreement_rate": round(float(tdx["agree"].mean()), 4),
            "provider_material_mismatch_n": material_n,
        },
    }
    manifest["hash"] = sha(manifest)
    json.dump(manifest, open(V02_MANIFEST, "w"), ensure_ascii=False, indent=2)

    audit_md = f"""# REFERENCE_REPAIR_AUDIT_V02

V01 status: SUPERSEDED_PRESTART_REFERENCE_DEFECT (never started; ledger rows=0)
Defects: DEFECT_1 A-vs-F volume definition; DEFECT_2 missing component CDFs.
V01 files modified: false (hashes unchanged).

V02:
- original development case n = 206; reference eligible n = 195 (Architect
  exemption V02_DEVELOPMENT_MEMBERSHIP_EXCEPTION = APPROVED)
- excluded n = 11 (candidate_date 2026-06-08 / D1 2026-06-05 missing D1
  same-time 5m cumulative volume); reason =
  V02_REFERENCE_INELIGIBLE_MISSING_D1_SAME_TIME; no cross-provider backfill
- reference outcome fields read = 0
- excluded outcome counts = {excluded_out}
- eligible outcome counts = {eligible_out}
- no reference change based on outcome
- primary volume definition = D0_CUM / D1_SAME_TIME_CUM
- percentile method = EMPIRICAL_MIDRANK_ECDF_V1 (mid-rank ECDF, below->0, above->1)
- component CDF saved per checkpoint (sorted values/n/p25/p50/p75)
- equal weights, quartile rule frozen
- score reproducibility max abs diff = {repro_max}

TDX compatibility (n = {tdx['episode_id'].nunique()}):
- volume pace median ratio 09:45 = {parity['0945']['volume_pace_median_ratio']}; 10:00 = {parity['1000']['volume_pace_median_ratio']}
- session low/high/range max abs diff: {parity['0945']['session_low_max_abs_diff']} / {parity['0945']['session_high_max_abs_diff']} / {parity['0945']['session_range_max_abs_diff']}
- quiet score abs diff median/p95/max = {continuous['median']} / {continuous['p95']} / {continuous['max']}
- quiet score spearman = {continuous['spearman_rank_corr']}
- quartile agreement = {round(float(tdx['agree'].mean()), 4)} (reported; not a hard gate in V02)
- boundary-sensitive mismatches = {boundary_n}; provider-material mismatches = {material_n}

FORWARD_REFERENCE_COMPATIBILITY = {compat}
"""
    (OUT / "REFERENCE_REPAIR_AUDIT_V02.md").write_text(audit_md)
    print("PROTOCOL_V02_HASH:", protocol["hash"])
    print("EPOCH_V02_MANIFEST_HASH:", manifest["hash"])
    print("FORWARD_REFERENCE_COMPATIBILITY:", compat)


if __name__ == "__main__":
    main()
