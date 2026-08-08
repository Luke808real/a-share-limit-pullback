"""R8B — intraday acceptance execution V01 (frozen ASL 5m lake).

Strictly follows the frozen R8A contract: 4 checkpoints, F7-1..F7-4 PRIMARY,
Layer A (activation) / Layer B (acceptance) denominators separated, PIT
right-labeled slicing, no EOD leakage, no score, no threshold search.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "intraday_v01"))
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r8a_intraday_contract_v01 as r8a  # noqa: E402
import r8b_asl5m_dataset_readiness_v01 as rd  # noqa: E402

CANONICAL_DAILY_SNAPSHOT = (
    REPO_ROOT / "data" / "canonical" / "daily_bars"
    / "snap-2026-07-31-b5f84004de8a.parquet"
)


OUT_FEATURES = (
    REPO_ROOT / "research" / "second_launch" / "intraday_v01"
    / "r8b_intraday_checkpoint_features_v01.csv"
)
OUT_ACCEPTANCE = (
    REPO_ROOT / "research" / "second_launch" / "intraday_v01"
    / "r8b_intraday_acceptance_results_v01.csv"
)
OUT_ACTIVATION = (
    REPO_ROOT / "research" / "second_launch" / "intraday_v01"
    / "r8b_activation_results_v01.csv"
)

CHECKPOINTS = r8a.CHECKPOINTS
PRIMARY_FEATURES = ["breakout_hold_ratio", "vwap_acceptance_ratio",
                    "retest_depth", "false_break_duration"]


def _to_minute(t: Any) -> int:
    return int(t.hour) * 60 + int(t.minute)


def checkpoint_mask(bars: pd.DataFrame, checkpoint: str) -> np.ndarray:
    hh, mm = checkpoint.split(":")
    cutoff = int(hh) * 60 + int(mm)
    times = pd.to_datetime(bars["bar_time"]).dt.time
    return np.array([_to_minute(t) <= cutoff for t in times])


def checkpoint_bars(bars: pd.DataFrame, checkpoint: str) -> pd.DataFrame:
    return bars[checkpoint_mask(bars, checkpoint)].reset_index(drop=True)


def session_vwap(bars: pd.DataFrame) -> float:
    """Cumulative VWAP through the checkpoint (amount/volume, PIT)."""
    amt = pd.to_numeric(bars["amount"], errors="coerce").to_numpy()
    vol = pd.to_numeric(bars["volume"], errors="coerce").to_numpy()
    if vol.sum() <= 0 or np.isnan(amt).any():
        return float("nan")
    return float(amt.sum() / vol.sum())


def first_touch_index(bars: pd.DataFrame, s1: float) -> int | None:
    touched = np.flatnonzero(pd.to_numeric(
        bars["high"], errors="coerce").to_numpy() >= s1)
    return int(touched[0]) if len(touched) else None


def feature_row(
    episode: pd.Series, bars: pd.DataFrame, checkpoint: str,
    prev_close: float, d1_cum_vol: float,
) -> dict[str, Any]:
    """One episode x checkpoint feature row (PIT right-labeled)."""
    cb = checkpoint_bars(bars, checkpoint)
    s1 = float(episode["s1_price"])
    touch = first_touch_index(cb, s1)
    activated = touch is not None
    touch_time = str(cb.iloc[touch]["bar_time"]) if activated else ""
    if activated:
        window = cb.iloc[touch + 1:]
    else:
        window = cb.iloc[0:0]
    vwap = session_vwap(cb)
    closes = pd.to_numeric(window["close"], errors="coerce").to_numpy()
    lows = pd.to_numeric(window["low"], errors="coerce").to_numpy()
    highs = pd.to_numeric(window["high"], errors="coerce").to_numpy()
    cbc = pd.to_numeric(cb["close"], errors="coerce").to_numpy()
    cbh = pd.to_numeric(cb["high"], errors="coerce").to_numpy()
    cbl = pd.to_numeric(cb["low"], errors="coerce").to_numpy()
    cbo = pd.to_numeric(cb["open"], errors="coerce").to_numpy()
    if len(window) > 0:
        f7_1 = float(np.mean(closes >= s1))
        f7_3 = float(np.min(lows / s1 - 1.0))
        below = (closes < s1).astype(int)
        best = cur = 0
        for b in below:
            cur = cur + 1 if b else 0
            best = max(best, cur)
        f7_4 = int(best)
        f7_2 = float(np.mean(closes >= vwap)) if np.isfinite(vwap) else float("nan")
    else:
        f7_1 = f7_2 = f7_3 = float("nan")
        f7_4 = 0
    vol_d = pd.to_numeric(cb["volume"], errors="coerce").to_numpy().sum()
    d1_label = (
        float(vol_d / d1_cum_vol) if np.isfinite(d1_cum_vol)
        and d1_cum_vol > 0 else float("nan")
    )
    return {
        "episode_id": episode["episode_id"],
        "symbol": episode["symbol"],
        "event_date": episode["outcome_event_date"],
        "outcome": episode["current_outcome"],
        "checkpoint": checkpoint,
        "activated": activated,
        "activation_time": touch_time,
        "acceptance_eligible": activated,
        "breakout_hold_ratio": f7_1,
        "vwap_acceptance_ratio": f7_2,
        "retest_depth": f7_3,
        "false_break_duration": f7_4,
        "dist_to_s1": float(cbc[-1] / s1 - 1.0) if len(cbc) else float("nan"),
        "high_vs_s1": float(np.max(cbh) / s1 - 1.0) if len(cbh) else float("nan"),
        "vwap_distance": float(cbc[-1] / vwap - 1.0) if (
            len(cbc) and np.isfinite(vwap)) else float("nan"),
        "prev_close_state": float(cbc[-1] / prev_close - 1.0) if (
            len(cbc) and np.isfinite(prev_close) and prev_close > 0
        ) else float("nan"),
        "open_gap": float(cbo[0] / prev_close - 1.0) if (
            len(cbo) and np.isfinite(prev_close) and prev_close > 0
        ) else float("nan"),
        "opening_drawdown": float(np.min(cbl) / cbo[0] - 1.0) if len(cbo) else float("nan"),
        "high_progression": float(cbh[-1] / np.max(cbh)) if len(cbh) else float("nan"),
        "cum_volume_relative_d1": d1_label,
        "missing_reasons": "",
    }


def rank_biserial(auc: float) -> float:
    return 2.0 * auc - 1.0


def direction_of(auc: float) -> str:
    if not np.isfinite(auc):
        return "UNKNOWN"
    if auc > 0.5:
        return "POSITIVE"
    if auc < 0.5:
        return "NEGATIVE"
    return "NEUTRAL"


def or_2x2(
    a: int, b: int, c: int, d: int,
) -> dict[str, Any]:
    """Project-consistent OR (0.5 zero-cell correction), raw cells kept."""
    if min(a, b, c, d) <= 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    if b == 0 or d == 0:
        return {"or": float("nan"), "ci_low": float("nan"),
                "ci_high": float("nan")}
    log_or = np.log((a / b) / (c / d))
    se = np.sqrt(1.0 / a + 1.0 / b + 1.0 / c + 1.0 / d)
    return {"or": float(np.exp(log_or)),
            "ci_low": float(np.exp(log_or - 1.96 * se)),
            "ci_high": float(np.exp(log_or + 1.96 * se))}


def acceptance_stats(
    features: pd.DataFrame, checkpoint: str, feature: str,
) -> dict[str, Any]:
    sub = features[(features["checkpoint"] == checkpoint)
                   & features["acceptance_eligible"]]
    succ = sub[sub["outcome"] == "SUCCESS"]
    fail = sub[sub["outcome"] == "FAILED_BREAKOUT"]
    vals = pd.to_numeric(sub[feature], errors="coerce")
    labels = (sub["outcome"] == "SUCCESS").astype(int).to_numpy()
    finite = vals.notna().to_numpy()
    vs = vals.to_numpy()[finite]
    lbs = labels[finite]
    auc = r3a.binary_auc(vs, lbs) if len(np.unique(vs)) >= 2 else float("nan")
    return {
        "checkpoint": checkpoint,
        "feature": feature,
        "SUCCESS_N": len(succ),
        "FAILED_N": len(fail),
        "SUCCESS_mean": float(pd.to_numeric(succ[feature], errors="coerce").mean()),
        "FAILED_mean": float(pd.to_numeric(fail[feature], errors="coerce").mean()),
        "SUCCESS_median": float(pd.to_numeric(succ[feature], errors="coerce").median()),
        "FAILED_median": float(pd.to_numeric(fail[feature], errors="coerce").median()),
        "native_auc": auc,
        "direction": direction_of(auc),
        "rank_biserial": rank_biserial(auc) if np.isfinite(auc) else float("nan"),
    }


def activation_stats(
    features: pd.DataFrame, checkpoint: str,
) -> dict[str, Any]:
    sub = features[features["checkpoint"] == checkpoint]
    a = int((sub["outcome"] == "SUCCESS").sum())
    b = int((sub["outcome"] == "FAILED_BREAKOUT").sum())
    a_act = int((sub["activated"] & (sub["outcome"] == "SUCCESS")).sum())
    b_act = int((sub["activated"] & (sub["outcome"] == "FAILED_BREAKOUT")).sum())
    rate_a = a_act / a if a else float("nan")
    rate_b = b_act / b if b else float("nan")
    orr = or_2x2(a_act, a - a_act, b_act, b - b_act)
    sig = np.array([1] * a_act + [0] * (a - a_act) +
                   [1] * b_act + [0] * (b - b_act))
    lbs = np.array([1] * a + [0] * b)
    auc = r3a.binary_auc(sig, lbs) if len(np.unique(sig)) > 1 else float("nan")
    return {
        "checkpoint": checkpoint,
        "SUCCESS_N": a,
        "FAILED_N": b,
        "SUCCESS_activated_N": a_act,
        "SUCCESS_activated_rate": rate_a,
        "FAILED_activated_N": b_act,
        "FAILED_activated_rate": rate_b,
        "rate_difference": rate_a - rate_b,
        "or_value": orr["or"],
        "or_ci_low": orr["ci_low"],
        "or_ci_high": orr["ci_high"],
        "binary_auc": auc,
    }


def load_prev_close(
    codes: set[str],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    """Previous-session close and previous-session DATE per code from the
    frozen canonical daily bars (PIT: D-1 close known at D)."""
    canon = pd.read_parquet(
        CANONICAL_DAILY_SNAPSHOT,
        columns=["code", "trade_date", "close"],
        filters=[("code", "in", sorted(codes))],
    )
    canon["date"] = pd.to_datetime(canon["trade_date"]).dt.date
    canon["close"] = pd.to_numeric(canon["close"], errors="coerce")
    canon = canon.sort_values(["code", "date"])
    canon["prev_close"] = canon.groupby("code")["close"].shift(1)
    prev_close: dict[str, dict[str, float]] = {}
    prev_date: dict[str, dict[str, str]] = {}
    for code, g in canon.groupby("code"):
        pc = {}
        pd_ = {}
        dates = g["date"].tolist()
        closes = g["prev_close"].tolist()
        for i, d in enumerate(dates):
            pc[str(d)] = closes[i] if i > 0 else float("nan")
            pd_[str(d)] = str(dates[i - 1]) if i > 0 else ""
        prev_close[str(code)] = pc
        prev_date[str(code)] = pd_
    return prev_close, prev_date


def main() -> None:
    bars = rd.load_frozen_5m()
    assert rd.recompute_lock_sha(rd.curated_partitions()) == rd.DATASET_LOCK_SHA
    prov = pd.read_csv(rd.OUT_ASL5M_PROVENANCE, dtype={"symbol": str})
    prov["date"] = pd.to_datetime(prov["outcome_event_date"]).dt.date

    def canon(s: str) -> str:
        return s + (".SH" if s.startswith(
            ("600", "601", "603", "605", "688", "689")) else ".SZ")

    prov["asl_sym"] = prov["symbol"].astype(str).str.zfill(6).map(canon)
    bar_lookup = {
        (str(s), str(d)): g
        for (s, d), g in bars.groupby(
            ["symbol", pd.to_datetime(bars["trade_date"]).dt.date.astype(str)])
    }
    prev, prev_date = load_prev_close(
        set(prov["symbol"].astype(str).str.zfill(6)))
    # D1 cumulative volume per (symbol, D, checkpoint) from the frozen lake
    d1_cum: dict[tuple[str, str, str], float] = {}
    for _, ep in prov.iterrows():
        code = str(ep["symbol"]).zfill(6)
        pd1 = prev_date.get(code, {}).get(str(ep["date"]), "")
        if not pd1:
            continue
        g1 = bar_lookup.get((canon(code), pd1))
        if g1 is None:
            continue
        for cp in CHECKPOINTS:
            cb1 = checkpoint_bars(g1, cp)
            v = pd.to_numeric(cb1["volume"], errors="coerce").to_numpy().sum()
            d1_cum[(code, str(ep["date"]), cp)] = float(v)
    rows: list[dict[str, Any]] = []
    for _, ep in prov.iterrows():
        key = (ep["asl_sym"], str(ep["date"]))
        g = bar_lookup[key]
        pc = prev.get(str(ep["symbol"]).zfill(6), {}).get(str(ep["date"]), np.nan)
        for cp in CHECKPOINTS:
            d1v = d1_cum.get((str(ep["symbol"]).zfill(6), str(ep["date"]), cp),
                             float("nan"))
            rows.append(feature_row(ep, g, cp, pc, d1v))
    features = pd.DataFrame(rows)
    features = features.sort_values(
        ["episode_id", "checkpoint"]).reset_index(drop=True)
    features.to_csv(OUT_FEATURES, index=False)
    # stats
    acc = []
    for cp in CHECKPOINTS:
        for f in PRIMARY_FEATURES:
            acc.append(acceptance_stats(features, cp, f))
    pd.DataFrame(acc).to_csv(OUT_ACCEPTANCE, index=False)
    act = [activation_stats(features, cp) for cp in CHECKPOINTS]
    pd.DataFrame(act).to_csv(OUT_ACTIVATION, index=False)
    print("FEATURE_ROWS:", len(features))
    print(pd.DataFrame(acc)[
        ["checkpoint", "feature", "SUCCESS_N", "FAILED_N", "native_auc",
         "direction", "rank_biserial"]].round(4).to_string(index=False))
    print(pd.DataFrame(act)[
        ["checkpoint", "SUCCESS_activated_rate", "FAILED_activated_rate",
         "rate_difference", "or_value", "binary_auc"]].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
