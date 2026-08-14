"""FORWARD_PAPER_D0_BPOINT_V01 — pre-forward protocol + daily paper ledger runner.

RESEARCH_ONLY / FORWARD_ONLY. No production changes, no live trading, no
threshold optimisation. Historical 206 cases are used ONLY for the volume
semantic audit and the frozen Quiet Compression reference distribution.

Modes:
  default            pre-forward audit + write protocol/reference (this run)
  --date YYYY-MM-DD  freeze candidate universe before open
  --checkpoint HHMM  append 09:45/10:00 checkpoint snapshot (primary)
                     (other checkpoints allowed as observation only)
  --finalize         append structural outcome at D+3
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import baostock as bs

from bpoint_morphology_lib import rank_biserial


ROOT = Path(__file__).resolve().parents[1]
FWD_DIR = ROOT / "research/bpoint/forward"
FWD_DIR.mkdir(parents=True, exist_ok=True)
BARS_PATH = ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"
CACHE_5M = ROOT / "data/tmp/v02a-minute/raw_5m"
CHECKPOINTS_PRIMARY = ("0945", "1000")
CHECKPOINTS_OBS = ("1030", "1130", "1330", "1400", "1430")

PROTOCOL_VERSION = "FORWARD_PAPER_D0_BPOINT_V01"
PROTOCOL_VERSION_ACTIVE = "v01"


def sha256_file_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_5m(symbol: str) -> pd.DataFrame | None:
    p = CACHE_5M / f"{symbol}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df["ts"] = pd.to_datetime(df["day"])
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def daily_bars_by_code() -> dict[str, pd.DataFrame]:
    df = pd.read_parquet(BARS_PATH, columns=["code", "trade_date", "close", "volume"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["code"] = df["code"].astype(str).str.zfill(6)
    return {code: g.sort_values("trade_date").reset_index(drop=True) for code, g in df.groupby("code", sort=False)}


def volume_audit() -> dict:
    feats = pd.read_parquet(ROOT / "research/bpoint/intraday/checkpoint_features_v01.parquet")
    bars = daily_bars_by_code()
    rows = []
    cache = {p.stem: load_5m(p.stem) for p in CACHE_5M.glob("*.parquet")}
    for ck in ("0945", "1000"):
        sub = feats[feats["CHECKPOINT"] == ck].copy()
        for _, r in sub.iterrows():
            sym = r["symbol"]
            d0 = pd.Timestamp(r["candidate_date"]).date()
            cb = bars.get(sym)
            median5 = None
            d1_full = None
            if cb is not None:
                d0_idx = cb.index[cb["trade_date"] == d0]
                if len(d0_idx):
                    i = int(d0_idx[0])
                    prev5 = cb.iloc[max(0, i - 5) : i]
                    median5 = float(prev5["volume"].median()) if len(prev5) else None
            d1_date = None
            d1_cum = None
            if cb is not None:
                d0_idx = cb.index[cb["trade_date"] == d0]
                if len(d0_idx):
                    i = int(d0_idx[0])
                    d1_full = float(cb.iloc[i - 1]["volume"]) if i >= 1 else None
                    d1_date = cb.iloc[i - 1]["trade_date"] if i >= 1 else None
            d1_min = cache.get(sym)
            if d1_min is not None and d1_date is not None:
                s = d1_min[d1_min["ts"].dt.date == d1_date]
                if len(s):
                    s = s.sort_values("ts").reset_index(drop=True)
                    tt = s["ts"].dt.hour * 60 + s["ts"].dt.minute
                    if (tt <= int(ck)).any():
                        d1_cum = float(s.loc[tt <= int(ck), "volume"].sum())
            rows.append({
                "episode_id": r["episode_id"],
                "symbol": sym,
                "candidate_date": d0,
                "outcome": r["outcome"],
                "CHECKPOINT": ck,
                "A_D0cum_vs_D1full": r["cum_volume_vs_D1_ratio"],
                "B_D0cum_vs_anchorfull": r["cum_volume_vs_anchor_ratio"],
                "C_D0cum": r["cum_volume"],
                "D_D1full": d1_full,
                "E_anchorfull": r["anchor_volume"],
                "D0cum_vs_median5": (r["cum_volume"] / median5) if median5 else None,
                "D1full_vs_median5": (d1_full / median5) if median5 and d1_full else None,
                "F_D0cum_vs_D1_sametime": (r["cum_volume"] / d1_cum) if d1_cum else None,
                "D1_sametime_available": d1_cum is not None,
            })
    aud = pd.DataFrame(rows)
    aud.to_csv(FWD_DIR / "volume_audit_v01.csv", index=False)

    out = {}
    for ck in ("0945", "1000"):
        sub = aud[aud["CHECKPOINT"] == ck]
        ckout = {}
        for col in ("A_D0cum_vs_D1full", "B_D0cum_vs_anchorfull", "D0cum_vs_median5", "D1full_vs_median5", "F_D0cum_vs_D1_sametime"):
            med = {}
            rb = {}
            for g in ("SUCCESS", "FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"):
                vals = sub.loc[sub["outcome"] == g, col].dropna().to_numpy(dtype=float)
                med[g] = round(float(np.median(vals)), 4) if len(vals) else None
            for g in ("FAILED_BREAKOUT", "STRUCTURE_FAIL"):
                s = sub.loc[sub["outcome"] == "SUCCESS", col].dropna().to_numpy(dtype=float)
                c = sub.loc[sub["outcome"] == g, col].dropna().to_numpy(dtype=float)
                rb[g] = round(rank_biserial(s, c), 4) if len(s) >= 5 and len(c) >= 5 else None
            ckout[col] = {"medians": med, "rb": rb}
        ckout["F_coverage_n"] = int(sub["D1_sametime_available"].sum())
        out[ck] = ckout
    return out


def build_quiet_reference() -> dict:
    feats = pd.read_parquet(ROOT / "research/bpoint/intraday/checkpoint_features_v01.parquet")
    ref = {}
    for ck in ("0945", "1000"):
        sub = feats[feats["CHECKPOINT"] == ck]
        for col in ("cum_volume_vs_D1_ratio", "session_low_pct_vs_prev_close", "session_range_pct"):
            raw = sub[col].dropna().to_numpy(dtype=float)
            vals = np.sort(np.abs(raw) if col == "session_low_pct_vs_prev_close" else raw)
            ref[f"{ck}_{col}"] = {
                "min": float(vals.min()),
                "max": float(vals.max()),
                "quantiles": [round(float(np.quantile(vals, q)), 6) for q in np.arange(0.01, 1.0, 0.01)],
                "n": int(len(vals)),
            }
    # score uses percentile ranks (linear interpolation on dev quantiles)
    score_cols = {
        "0945": ["cum_volume_vs_D1_ratio", "session_low_pct_vs_prev_close", "session_range_pct"],
        "1000": ["cum_volume_vs_D1_ratio", "session_low_pct_vs_prev_close", "session_range_pct"],
    }
    rows = []
    for ck, cols in score_cols.items():
        sub = feats[feats["CHECKPOINT"] == ck].copy()
        for _, r in sub.iterrows():
            vp = r["cum_volume_vs_D1_ratio"]
            shallow = r["session_low_pct_vs_prev_close"]
            rng = r["session_range_pct"]
            if pd.isna(vp) or pd.isna(shallow) or pd.isna(rng):
                continue
            def pct_rank(col, val, inverse=False):
                qs = np.array(ref[f"{ck}_{col}"]["quantiles"])
                compare = abs(val) if col == "session_low_pct_vs_prev_close" else val
                p = float((qs <= compare).mean())
                return 1.0 - p if inverse else p
            # shallow: closer to 0 is better -> inverse percentile of abs(drawdown)
            score = np.mean([
                pct_rank("cum_volume_vs_D1_ratio", vp, inverse=True),
                pct_rank("session_low_pct_vs_prev_close", shallow, inverse=True),
                pct_rank("session_range_pct", rng, inverse=True),
            ])
            rows.append({"episode_id": r["episode_id"], "outcome": r["outcome"], "CHECKPOINT": ck, "quiet_score": round(float(score), 6)})
    scores = pd.DataFrame(rows)
    ref_out = {}
    for ck in ("0945", "1000"):
        vals = np.sort(scores.loc[scores["CHECKPOINT"] == ck, "quiet_score"].to_numpy())
        ref_out[ck] = {
            "n": int(len(vals)),
            "min": float(vals.min()),
            "max": float(vals.max()),
            "quantiles": [round(float(np.quantile(vals, q)), 6) for q in np.arange(0.01, 1.0, 0.01)],
            "quartile_boundaries": {
                "q1": round(float(np.quantile(vals, 0.25)), 6),
                "q2": round(float(np.quantile(vals, 0.50)), 6),
                "q3": round(float(np.quantile(vals, 0.75)), 6),
            },
        }
    ref_out["schema_version"] = PROTOCOL_VERSION
    return ref_out, scores


def build_protocol(audit: dict, volume_approved: bool) -> dict:
    volume_primary = "F_D0cum_vs_D1_sametime" if volume_approved == "VOLUME_PACE_SIGNAL_CONFIRMED" else "A_D0cum_vs_D1full"
    if volume_approved != "VOLUME_PACE_SIGNAL_CONFIRMED":
        volume_primary = "A_D0cum_vs_D1full_OVERRIDE_PENDING"
    proto = {
        "protocol_version": PROTOCOL_VERSION,
        "frozen_hypotheses": {
            "H1_lower_volume_pace_better": True,
            "H2_shallower_drawdown_better": True,
            "H3_smaller_range_better": True,
            "directions_frozen_before_start": True,
        },
        "layers": {
            "LAYER_A_B_POINT_QUALITY": ["VOLUME_PACE", "MAX_DRAWDOWN_FROM_PREV_CLOSE", "SESSION_RANGE"],
            "LAYER_B_ACTIVATION_STATE": ["SUPPORT_TOUCH", "SUPPORT_RECLAIM", "DIST_TO_S1", "S1_TOUCH", "PROBE"],
            "activation_never_enters_quality_score": True,
        },
        "volume_semantic_audit": audit,
        "volume_primary": volume_primary,
        "checkpoints_primary": list(CHECKPOINTS_PRIMARY),
        "checkpoints_observation_only": list(CHECKPOINTS_OBS),
        "quiet_score_formula": (
            "mean(inverse_percentile(VOLUME_PACE), inverse_percentile(abs(SESSION_LOW_VS_PREV_CLOSE)), inverse_percentile(SESSION_RANGE_PCT))"
            if volume_approved == "VOLUME_PACE_SIGNAL_CONFIRMED"
            else "mean(inverse_percentile(abs(SESSION_LOW_VS_PREV_CLOSE)), inverse_percentile(SESSION_RANGE_PCT)); VOLUME_EXCLUDED_PENDING_VALIDATION"
        ),
        "paper_entry_price_rule": "checkpoint last complete 5m bar close; no next-low/VWAP/intraday-low fill",
        "outcome_rule": "fixed 3-session structural outcome: SUCCESS/FAILED_BREAKOUT/NO_LAUNCH/STRUCTURE_FAIL/UNKNOWN (caseset V01B definitions, frozen)",
        "t_plus_1_execution_rule": "EXECUTION_LAYER_PENDING; reuse Phase 2D.1A execution-reality semantics when a forward-compatible resolver is approved; structural outcome only for now",
        "interim_gate": "SUCCESS>=10 and FAILED_BREAKOUT>=20 -> descriptive only",
        "decision_gate": "SUCCESS>=30 and FAILED_BREAKOUT>=30 and >=20 trading sessions",
        "candidate_freeze_rule": "before open: freeze D-1 frozen production/research-approved daily screen output; CANDIDATE_LIST_HASH stored; no intraday additions (NOT_ELIGIBLE_FOR_TODAY)",
        "no_threshold_optimization": True,
        "rejected_do_not_retune": [
            "VWAP_ACCEPTANCE", "DAMAGE_RECOVERY", "FAST_RECLAIM", "D0_PROBE_COUNT",
            "D0_NEW_LOW", "CLOSE_LOCATION", "RETURN_FROM_PREV_CLOSE", "MA_RECLAIM",
            "MORPHOLOGY_NEAREST_NEIGHBOR",
        ],
        "context_observation_only": ["D1_UPPER_SHADOW", "VWAP (VWAP_NOT_ENTRY_FEATURE=true)"],
        "protocol_immutable": True,
    }
    return proto


def write_ledger_schema() -> None:
    cand = pd.DataFrame(columns=[
        "run_date", "epoch_id", "candidate_list_hash", "candidate_source_hash",
        "source_snapshot", "code", "name", "setup_id", "anchor_date", "setup_stage",
        "support", "invalid", "s1", "d1_close", "d1_volume",
        "correction_status", "superseded_by", "correction_reason",
    ])
    ckpt = pd.DataFrame(columns=[
        "run_date", "epoch_id", "code", "checkpoint", "checkpoint_price", "cum_volume",
        "volume_pace_primary", "volume_primary_status", "session_low", "session_high",
        "session_low_vs_prev_close_pct", "session_range_pct", "price_to_support_pct",
        "price_to_s1_pct", "price_to_invalid_pct", "support_touched", "support_reclaimed",
        "s1_touched", "price_vs_vwap", "d1_upper_shadow", "quiet_score",
        "quiet_score_status", "quiet_quartile", "activation_state",
        "correction_status", "superseded_by", "correction_reason",
    ])
    outc = pd.DataFrame(columns=[
        "run_date", "epoch_id", "code", "outcome", "outcome_reason",
        "structural_horizon_sessions", "correction_status", "superseded_by",
        "correction_reason",
    ])
    for df, name in ((cand, "forward_candidates"), (ckpt, "forward_checkpoints"), (outc, "forward_outcomes")):
        path = FWD_DIR / f"{name}.parquet"
        if not path.exists():
            df.to_parquet(path, index=False)


def load_protocol_and_hashes() -> tuple[dict, str, str]:
    ver = PROTOCOL_VERSION_ACTIVE
    proto_path = FWD_DIR / ("FORWARD_PAPER_PROTOCOL_V02.json" if ver == "v02" else "FORWARD_PAPER_PROTOCOL_V01.json")
    ref_path = FWD_DIR / ("quiet_score_reference_v02.json" if ver == "v02" else "quiet_score_reference_v01.json")
    proto = json.load(open(proto_path))
    p2 = {k: v for k, v in proto.items() if k not in ("protocol_hash", "hash")}
    ph = sha256_file_text(json.dumps(p2, ensure_ascii=False, sort_keys=True))
    ref = json.load(open(ref_path))
    r2 = {k: v for k, v in ref.items() if k not in ("reference_distribution_hash", "hash")}
    rh = sha256_file_text(json.dumps(r2, ensure_ascii=False, sort_keys=True))
    return proto, ph, rh


def check_v02_runner() -> None:
    """Read-only V02 readiness check: load V02 artifacts + component CDFs."""
    global PROTOCOL_VERSION_ACTIVE
    PROTOCOL_VERSION_ACTIVE = "v02"
    proto, ph, rh = load_protocol_and_hashes()
    ref = json.load(open(FWD_DIR / "quiet_score_reference_v02.json"))
    if ph != (proto.get("protocol_hash") or proto.get("hash")) or rh != (ref.get("reference_distribution_hash") or ref.get("hash")):
        raise SystemExit("BLOCKED_FORWARD_RUNNER_V02: hash mismatch")
    man = json.load(open(FWD_DIR / "FORWARD_EPOCH_1_V02_MANIFEST.json"))
    for ck in ("0945", "1000"):
        for col in ("volume_pace", "abs_session_low", "session_range"):
            c = ref["components"][ck][col]
            assert c["n"] == 195 and len(c["sorted_values"]) == 195
        q = ref["quiet_score_reference"][ck]
        assert {"Q25", "Q50", "Q75"} <= set(q)
    print("FORWARD_RUNNER_V02_READY: V02 artifacts loaded, component CDFs 195x2, quartile boundaries ok")
    print("PROTOCOL_V02_HASH:", ph)
    print("REFERENCE_V02_HASH:", rh)
    print("EPOCH_V02_MANIFEST_HASH:", man.get("hash"))


def previous_trading_day(d: date) -> date | None:
    """Previous A-share trading day via Baostock trade calendar (cached)."""
    cache_path = FWD_DIR / "trade_calendar_cache.json"
    cache = {}
    if cache_path.exists():
        cache = json.load(open(cache_path))
    year = str(d.year)
    if year not in cache:
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            bs.login()
        rs = bs.query_trade_dates(start_date=f"{year}-01-01", end_date=f"{year}-12-31")
        trading = []
        while rs.next():
            row = rs.get_row_data()
            if row[1] == "1":
                trading.append(row[0])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            bs.logout()
        cache[year] = trading
        json.dump(cache, open(cache_path, "w"))
    prior = [x for x in cache[year] if date.fromisoformat(x) < d]
    return date.fromisoformat(prior[-1]) if prior else None


def freeze_candidates(date_str: str, dry_run: bool = False) -> pd.DataFrame:
    proto, ph, rh = load_protocol_and_hashes()
    if ph != (proto.get("protocol_hash") or proto.get("hash")) or rh != (proto.get("reference_distribution_hash") or proto.get("hash")):
        raise SystemExit("STOP_PROTOCOL_DRIFT")
    d = date.fromisoformat(date_str)
    states = sorted((ROOT / "data/screen/states").glob("*.json"))
    proc_dates = sorted(
        {json.load(open(p))["last_processed_date"] for p in states}
        - {None}
    )
    expected_d1 = previous_trading_day(d)
    if expected_d1 is None:
        raise SystemExit("STOP_NO_TRADE_CALENDAR")
    d1 = expected_d1.isoformat()
    if d1 not in proc_dates:
        raise SystemExit(
            f"STOP_D1_PRODUCTION_SCREEN_NOT_READY: expected D-1={d1}, "
            f"screen last_processed={proc_dates}"
        )
    candidates = []
    for p in states:
        st = json.load(open(p))
        if st.get("last_processed_date") != d1:
            continue
        sig = json.loads(st["signal_json"])
        if sig.get("setup_stage") not in ("B1_READY", "B2_READY", "B2_CONFIRMED"):
            continue
        invalid = sig.get("invalid_price")
        s1obj = sig.get("target_s1") or {}
        s1 = s1obj.get("s1_low") if isinstance(s1obj, dict) else None
        if invalid is None or s1 is None:
            continue
        support = sig.get("support")
        if isinstance(support, dict):
            support = support.get("center") or support.get("low")
        candidates.append({
            "run_date": date_str,
            "epoch_id": "FORWARD_EPOCH_1",
            "candidate_list_hash": "",
            "candidate_source_hash": "",
            "source_snapshot": st.get("snapshot_id"),
            "code": st["code"],
            "name": "",
            "setup_id": st["setup_id"],
            "anchor_date": (sig.get("anchor") or {}).get("trade_date") if isinstance(sig.get("anchor"), dict) else None,
            "setup_stage": sig["setup_stage"],
            "support": support,
            "invalid": invalid,
            "s1": s1,
            "d1_close": None,
            "d1_volume": None,
            "correction_status": None,
            "superseded_by": None,
            "correction_reason": None,
        })
    df = pd.DataFrame(candidates)
    if len(df):
        list_hash = sha256_file_text(json.dumps(df.sort_values("code").to_dict(orient="records"), ensure_ascii=False, sort_keys=True))
        df["candidate_list_hash"] = list_hash
        df["candidate_source_hash"] = proto.get("candidate_source_hash", "")
    if not dry_run:
        path = FWD_DIR / "forward_candidates.parquet"
        old = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        if len(old) and (old["run_date"] == date_str).any():
            raise SystemExit("ALREADY_FROZEN_FOR_DATE")
        pd.concat([old, df], ignore_index=True).to_parquet(path, index=False)
    return df


def append_checkpoint(date_str: str, ckpt: str, dry_run: bool = False) -> pd.DataFrame:
    if ckpt not in ("0945", "1000", "1030", "1130", "1330", "1400", "1430"):
        raise SystemExit(f"INVALID_CHECKPOINT:{ckpt}")
    path = FWD_DIR / "forward_candidates.parquet"
    cand = pd.read_parquet(path)
    todays = cand[cand["run_date"] == date_str]
    if len(todays) == 0:
        raise SystemExit("NO_FROZEN_CANDIDATES_FOR_DATE")
    ref = json.load(open(FWD_DIR / "quiet_score_reference_v01.json"))
    bars = daily_bars_by_code()
    rows = []
    for _, c in todays.iterrows():
        sym = c["code"]
        d0_min = load_5m(sym)
        d0_session = d0_min[d0_min["ts"].dt.date == date.fromisoformat(date_str)].sort_values("ts") if d0_min is not None else pd.DataFrame()
        d0_ok = False
        if len(d0_session):
            tt = d0_session["ts"].dt.hour * 60 + d0_session["ts"].dt.minute
            d0_ok = bool((tt <= int(ckpt)).any())
        cb = bars.get(sym)
        d1_date = None
        if cb is not None:
            idx = cb.index[cb["trade_date"] == date.fromisoformat(date_str)]
            if len(idx) and int(idx[0]) >= 1:
                d1_date = cb.iloc[int(idx[0]) - 1]["trade_date"]
        d1_min = load_5m(sym) if d1_date else None
        d1_cum = None
        if d1_min is not None:
            s1 = d1_min[d1_min["ts"].dt.date == d1_date].sort_values("ts")
            if len(s1):
                tt1 = s1["ts"].dt.hour * 60 + s1["ts"].dt.minute
                if (tt1 <= int(ckpt)).any():
                    d1_cum = float(s1.loc[tt1 <= int(ckpt), "volume"].sum())
        volume_primary = None
        volume_status = "MISSING"
        d0_cum = None
        price = None
        low = high = None
        if d0_ok and d1_cum is not None:
            sub = d0_session[d0_session["ts"].dt.hour * 60 + d0_session["ts"].dt.minute <= int(ckpt)]
            if len(sub) >= 10:
                d0_cum = float(sub["volume"].sum())
                volume_primary = round(d0_cum / d1_cum, 6)
                volume_status = "OK"
                price = float(sub.iloc[-1]["close"])
                low = float(sub["low"].min())
                high = float(sub["high"].max())
        d1_close = float(c["d1_close"]) if pd.notna(c["d1_close"]) else None
        session_low_vs_prev = round((low / d1_close - 1.0) * 100.0, 4) if low is not None and d1_close else None
        session_range = round((high - low) / (price or 1) * 100.0, 4) if high is not None and low is not None and price else None
        inputs_ok = volume_primary is not None and session_low_vs_prev is not None and session_range is not None
        score = None
        score_status = "OK" if inputs_ok else "INCOMPLETE"
        quartile = None
        if inputs_ok:
            ref_ck = ref[ckpt]
            def inv_pct(col, val):
                qs = np.array(ref_ck[f"{ckpt}_{col}"]["quantiles"])
                compare = abs(val) if col == "session_low_pct_vs_prev_close" else val
                return 1.0 - float((qs <= compare).mean())
            score = round(float(np.mean([
                inv_pct("cum_volume_vs_D1_ratio", volume_primary),
                inv_pct("session_low_pct_vs_prev_close", session_low_vs_prev),
                inv_pct("session_range_pct", session_range),
            ])), 6)
            q = ref_ck["quartile_boundaries"]
            quartile = "Q1" if score <= q["q1"] else ("Q2" if score <= q["q2"] else ("Q3" if score <= q["q3"] else "Q4"))
        rows.append({
            "run_date": date_str,
            "epoch_id": "FORWARD_EPOCH_1",
            "code": sym,
            "checkpoint": ckpt,
            "checkpoint_price": price,
            "cum_volume": d0_cum,
            "volume_pace_primary": volume_primary,
            "volume_primary_status": volume_status,
            "session_low": low,
            "session_high": high,
            "session_low_vs_prev_close_pct": session_low_vs_prev,
            "session_range_pct": session_range,
            "price_to_support_pct": None,
            "price_to_s1_pct": round((price / float(c["s1"]) - 1.0) * 100.0, 4) if price is not None and pd.notna(c["s1"]) else None,
            "price_to_invalid_pct": round((price / float(c["invalid"]) - 1.0) * 100.0, 4) if price is not None and pd.notna(c["invalid"]) else None,
            "support_touched": None,
            "support_reclaimed": None,
            "s1_touched": None,
            "price_vs_vwap": None,
            "d1_upper_shadow": None,
            "quiet_score": score,
            "quiet_score_status": score_status,
            "quiet_quartile": quartile,
            "activation_state": "NONE",
            "correction_status": None,
            "superseded_by": None,
            "correction_reason": None,
        })
    df = pd.DataFrame(rows)
    if not dry_run:
        path = FWD_DIR / "forward_checkpoints.parquet"
        old = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        pd.concat([old, df], ignore_index=True).to_parquet(path, index=False)
    return df


def finalize(date_str: str, dry_run: bool = False) -> pd.DataFrame:
    # Structural outcome at D+3; no fabrication. Ledger row added with PENDING_DATA
    # until daily bars for the horizon exist.
    rows = [{
        "run_date": date_str,
        "epoch_id": "FORWARD_EPOCH_1",
        "code": None,
        "outcome": None,
        "outcome_reason": "PENDING_DATA_D3_HORIZON",
        "structural_horizon_sessions": 3,
        "correction_status": None,
        "superseded_by": None,
        "correction_reason": None,
    }]
    df = pd.DataFrame(rows)
    if not dry_run:
        path = FWD_DIR / "forward_outcomes.parquet"
        old = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        pd.concat([old, df], ignore_index=True).to_parquet(path, index=False)
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--checkpoint", action="append", default=[])
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--freeze-candidates", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--protocol", choices=["v01", "v02"], default=None)
    args = parser.parse_args()
    if args.protocol is not None:
        global PROTOCOL_VERSION_ACTIVE
        PROTOCOL_VERSION_ACTIVE = args.protocol
        if args.protocol == "v02":
            check_v02_runner()

    if args.date is not None:
        if args.freeze_candidates:
            df = freeze_candidates(args.date, dry_run=args.dry_run)
            print(f"CANDIDATE_FREEZE_OK={args.dry_run == False}")  # noqa: E712
            print("CANDIDATE_LIST_HASH:", df["candidate_list_hash"].iloc[0] if len(df) else None)
            print("FROZEN_N:", len(df))
            if len(df):
                print(df[["code", "setup_stage", "invalid", "s1"]].head(10).to_string(index=False))
        elif args.checkpoint:
            for ck in args.checkpoint:
                df = append_checkpoint(args.date, ck, dry_run=args.dry_run)
                print(f"CHECKPOINT_{ck}_COMPLETE rows={len(df)} dry_run={args.dry_run}")
        elif args.finalize:
            df = finalize(args.date, dry_run=args.dry_run)
            print("FINALIZE rows:", len(df))
        else:
            raise SystemExit("MISSING_MODE: use --freeze-candidates / --checkpoint / --finalize")
        return

    audit = volume_audit()
    print("VOLUME_AUDIT:")
    print(json.dumps(audit, indent=2, default=str))

    # denominator confounding conclusion
    a0945 = audit["0945"]
    num_rb_f = a0945["D0cum_vs_median5"]["rb"]["FAILED_BREAKOUT"]
    num_rb_sf = a0945["D0cum_vs_median5"]["rb"]["STRUCTURE_FAIL"]
    den_rb_f = a0945["D1full_vs_median5"]["rb"]["FAILED_BREAKOUT"]
    den_rb_sf = a0945["D1full_vs_median5"]["rb"]["STRUCTURE_FAIL"]
    ratio_rb_f = a0945["A_D0cum_vs_D1full"]["rb"]["FAILED_BREAKOUT"]
    ratio_rb_sf = a0945["A_D0cum_vs_D1full"]["rb"]["STRUCTURE_FAIL"]
    numerator_drives = bool(num_rb_f is not None and num_rb_sf is not None and num_rb_f > 0.1 and num_rb_sf > 0.1)
    denominator_only = bool(
        (den_rb_f is not None and den_rb_f < -0.1 and den_rb_sf is not None and den_rb_sf < -0.1)
        and not numerator_drives
    )
    if numerator_drives:
        volume_approved = "VOLUME_PACE_SIGNAL_CONFIRMED"
    elif denominator_only:
        volume_approved = "VOLUME_DENOMINATOR_CONFOUNDED"
    else:
        volume_approved = "MIXED"
    print("VOLUME_CONCLUSION:", volume_approved)

    ref_path = FWD_DIR / "quiet_score_reference_v01.json"
    proto_path = FWD_DIR / "FORWARD_PAPER_PROTOCOL_V01.json"
    if proto_path.exists() and ref_path.exists():
        proto, proto_hash, ref_hash = load_protocol_and_hashes()
        print("PROTOCOL EXISTS; integrity verified:", proto_hash == proto.get("protocol_hash") and ref_hash == proto.get("reference_distribution_hash"))
    else:
        ref, scores = build_quiet_reference()
        with open(ref_path, "w") as fh:
            json.dump(ref, fh, ensure_ascii=False, indent=2, default=str)
        ref_hash = sha256_file_text(json.dumps({k: v for k, v in ref.items() if k != "reference_distribution_hash"}, ensure_ascii=False, sort_keys=True))
        ref["reference_distribution_hash"] = ref_hash
        with open(ref_path, "w") as fh:
            json.dump(ref, fh, ensure_ascii=False, indent=2, default=str)
        proto = build_protocol(audit, volume_approved)
        proto["reference_distribution_hash"] = ref_hash
        proto["forward_start_date"] = "PENDING_HUMAN_APPROVAL (next trading session after approval)"
        proto["candidate_list_hash"] = "COMPUTED_AT_FREEZE"
        proto["created_at"] = datetime.now().isoformat(timespec="seconds")
        proto_hash = sha256_file_text(json.dumps({k: v for k, v in proto.items() if k != "protocol_hash"}, ensure_ascii=False, sort_keys=True))
        proto["protocol_hash"] = proto_hash
        with open(proto_path, "w") as fh:
            json.dump(proto, fh, ensure_ascii=False, indent=2, default=str)
        scores.to_csv(FWD_DIR / "quiet_score_development_v01.csv", index=False)

    write_ledger_schema()

    summary = {
        "VOLUME_RATIO_EXACT_DEFINITION": {
            "NUMERATOR": "D0 cumulative volume up to checkpoint (5m bars)",
            "DENOMINATOR": "D-1 full-day volume",
            "CHECKPOINT": "09:45 / 10:00",
            "DATA_FREQUENCY": "5m (1m unavailable)",
        },
        "VOLUME_DENOMINATOR_AUDIT": {
            "conclusion": volume_approved,
            "num_rb_F_SF": [num_rb_f, num_rb_sf],
            "den_rb_F_SF": [den_rb_f, den_rb_sf],
            "ratio_rb_F_SF": [ratio_rb_f, ratio_rb_sf],
        },
        "APPROVED_VOLUME_PACE_PRIMARY": proto["volume_primary"],
        "QUIET_SCORE_FORMULA": proto["quiet_score_formula"],
        "REFERENCE_DISTRIBUTION_HASH": ref_hash,
        "CHECKPOINTS": list(CHECKPOINTS_PRIMARY),
        "FORWARD_START_DATE": proto["forward_start_date"],
        "CANDIDATE_FREEZE_RULE": proto["candidate_freeze_rule"],
        "PAPER_ENTRY_PRICE_RULE": proto["paper_entry_price_rule"],
        "OUTCOME_RULE": proto["outcome_rule"],
        "T_PLUS_1_EXECUTION_RULE": proto["t_plus_1_execution_rule"],
        "INTERIM_GATE": proto["interim_gate"],
        "DECISION_GATE": proto["decision_gate"],
        "PROTOCOL_HASH": proto_hash,
        "PRODUCTION_FILES_CHANGED": False,
    }
    with open(FWD_DIR / "forward_summary.csv", "w") as fh:
        fh.write("key,value\n")
        for k, v in summary.items():
            fh.write(f"{k},{json.dumps(v, ensure_ascii=False)}\n")
    print("PROTOCOL_HASH:", proto_hash)
    print("REFERENCE_HASH:", ref_hash)
    print("READY:", json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
