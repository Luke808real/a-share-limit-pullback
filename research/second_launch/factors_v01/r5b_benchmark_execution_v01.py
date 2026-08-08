"""R5B — external benchmark execution V01 (B4-B7 on the frozen 8,682 cohort).

Strictly reuses the R5A frozen contract (research/reports/
SECOND_LAUNCH_FACTOR_R5A_EXTERNAL_BENCHMARK_CONTRACT_V01.md). Descriptive
research only: no threshold change, no F3/F6 combination, no ML, no R6.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r5a_benchmark_contract_v01 as r5a  # noqa: E402


OUT_SIGNALS = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r5b_benchmark_episode_signals_v01.csv"
)
OUT_RESULTS_3D = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r5b_benchmark_results_3d_v01.csv"
)
OUT_RESULTS_5D = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r5b_benchmark_results_5d_v01.csv"
)
OUT_FAILURE = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r5b_benchmark_failure_profile_v01.csv"
)

EXECUTION_SET = ["B4", "B5", "B6", "B7"]
B4_MIN, B4_MAX = 2, 5
B5_DEPTH = -0.04
B6_RATIO = 0.85
B7_LOOKBACK = 60
CA_TOL = 0.005
# Float-noise tolerance at the frozen boundary equality (prices are 2dp fen:
# a genuine off-boundary value differs by >= ~1e-4, far above 1e-9).
BOUNDARY_EPS = 1e-9

OUTCOME_LABELS = ["SUCCESS", "FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL",
                  "UNKNOWN"]


def input_gate() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Frozen input gate (R5B may read outcome labels). Fail closed."""
    if r3a.sha256_file(r3a.FEATURE_CSV) != r3a.EXPECTED_FEATURE_SHA256:
        raise RuntimeError("feature CSV SHA mismatch (fail closed)")
    if r3a.sha256_file(r3a.OUTCOME_CSV) != r3a.EXPECTED_OUTCOME_SHA256:
        raise RuntimeError("outcome CSV SHA mismatch (fail closed)")
    if r3a.sha256_file(r5a.CANONICAL_SNAPSHOT) != r5a.SNAPSHOT_SHA:
        raise RuntimeError("canonical daily snapshot SHA mismatch (fail closed)")
    feat = pd.read_csv(r3a.FEATURE_CSV, dtype={"symbol": str})
    out = pd.read_csv(r3a.OUTCOME_CSV, dtype={"symbol": str})
    if len(feat) != 8682 or len(out) != 8682:
        raise RuntimeError(f"row counts {len(feat)}/{len(out)} != 8682/8682")
    if feat["episode_id"].duplicated().any() or out["episode_id"].duplicated().any():
        raise RuntimeError("duplicate episode_id (fail closed)")
    if set(feat["episode_id"]) != set(out["episode_id"]):
        raise RuntimeError("episode_id sets not 1:1 exact (fail closed)")
    m = feat.merge(out, on="episode_id", suffixes=("_f", "_o"))
    for col in ["anchor_date", "candidate_date", "symbol"]:
        if not (m[f"{col}_f"] == m[f"{col}_o"]).all():
            raise RuntimeError(f"identity binding mismatch on {col} (fail closed)")
    if not (out["feature_snapshot_id"] == r3a.EXPECTED_FEATURE_SNAPSHOT_ID).all():
        raise RuntimeError("feature_snapshot_id binding mismatch (fail closed)")
    return feat, out


def registry_gate() -> None:
    """Frozen R5A registry: execution set is exactly B4-B7 READY."""
    status = {r["benchmark_id"]: r["status"] for r in r5a.REGISTRY}
    for bid in EXECUTION_SET:
        if status[bid] != "READY":
            raise RuntimeError(f"{bid} status != READY (fail closed)")
    for bid in ("B1", "B2", "B3"):
        if status[bid] != "UNDERDEFINED":
            raise RuntimeError(f"{bid} not UNDERDEFINED (fail closed)")
    if status["B8"] != "DATA_UNAVAILABLE":
        raise RuntimeError("B8 not DATA_UNAVAILABLE (fail closed)")


def load_canonical_gated(codes: set[str]) -> pd.DataFrame:
    """Gated canonical read limited to cohort codes (bounded memory)."""
    if r3a.sha256_file(r5a.CANONICAL_SNAPSHOT) != r5a.SNAPSHOT_SHA:
        raise RuntimeError("canonical daily snapshot SHA mismatch (fail closed)")
    df = pd.read_parquet(
        r5a.CANONICAL_SNAPSHOT,
        columns=["code", "trade_date", "open", "high", "low", "close",
                 "preclose", "volume", "dataset_snapshot_id"],
        filters=[("code", "in", sorted(codes))],
    )
    ids = set(df["dataset_snapshot_id"].astype(str).unique())
    if ids != {r3a.EXPECTED_FEATURE_SNAPSHOT_ID}:
        raise RuntimeError(f"snapshot binding mismatch {sorted(ids)}")
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    for c in ["open", "high", "low", "close", "preclose", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values(["code", "trade_date"]).reset_index(drop=True)


def b4_signal(days_since_t0: pd.Series) -> tuple[pd.Series, pd.Series]:
    """B4: 2 <= days_since_t0 <= 5 (frozen)."""
    d = pd.to_numeric(days_since_t0, errors="coerce")
    eligible = d.notna()
    signal = eligible & (d >= B4_MIN) & (d <= B4_MAX)
    return eligible, signal


def b5_signal(close_t0: float, close_d: float) -> bool:
    """B5: close_D / close_T0 - 1 >= -0.04 (exact equality is signal)."""
    return close_d / close_t0 - 1.0 >= B5_DEPTH - BOUNDARY_EPS


def b6_signal(volume_t0: float, volume_d: float) -> bool:
    """B6: volume_D / volume_T0 <= 0.85 (exact equality is signal)."""
    return volume_d / volume_t0 <= B6_RATIO + BOUNDARY_EPS


def b7_reference_high(pre_t0_highs: np.ndarray) -> float | None:
    """B7 reference: max(high, last min(60, available) sessions before T0).
    None when no pre-T0 session (NO_REFERENCE)."""
    if len(pre_t0_highs) == 0:
        return None
    window = pre_t0_highs[-B7_LOOKBACK:]
    return float(np.nanmax(window))


def or_2x2(
    a: int, b: int, c: int, d: int,
) -> dict[str, Any]:
    """Odds ratio (SUCCESS vs KNOWN_NON_SUCCESS, signal vs non-signal).

    Zero-cell policy consistent with r3a.odds_ratio_ci: 0.5 correction with
    haldane flag; raw cells always reported (never silent crash).
    """
    cells = dict(signal_success=int(a), signal_nonsuccess=int(b),
                 nonsignal_success=int(c), nonsignal_nonsuccess=int(d))
    if min(a, b, c, d) <= 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
        corrected = True
    else:
        corrected = False
    if b == 0 or d == 0:
        return {"or": float("nan"), "ci_low": float("nan"),
                "ci_high": float("nan"), "zero_cell_corrected": corrected,
                **cells}
    log_or = math.log((a / b) / (c / d))
    se = math.sqrt(1.0 / a + 1.0 / b + 1.0 / c + 1.0 / d)
    return {"or": float(math.exp(log_or)),
            "ci_low": float(math.exp(log_or - 1.96 * se)),
            "ci_high": float(math.exp(log_or + 1.96 * se)),
            "zero_cell_corrected": corrected, **cells}


def binary_auc_signal(signal: np.ndarray, labels: np.ndarray) -> Any:
    """Binary AUC; constant signal -> NOT_IDENTIFIABLE_CONSTANT_SIGNAL."""
    if int(signal.sum()) == 0 or int(signal.sum()) == len(signal):
        return "NOT_IDENTIFIABLE_CONSTANT_SIGNAL"
    return r3a.binary_auc(signal, labels)


def classify_benchmark(
    rate_sig: float, rate_non: float, or_value: Any, auc: Any,
) -> str:
    """Pre-registered classification (R5A contract section 12)."""
    if not np.isfinite(rate_sig) or not np.isfinite(rate_non):
        return "DATA_LIMITED"
    if not isinstance(or_value, float) or not isinstance(auc, float):
        return "DATA_LIMITED"
    if np.isnan(or_value) or np.isnan(auc):
        return "DATA_LIMITED"
    if rate_sig > rate_non and or_value > 1.0 and auc > 0.5:
        return "POSITIVE_BENCHMARK"
    if rate_sig < rate_non and or_value < 1.0 and auc < 0.5:
        return "NEGATIVE_BENCHMARK"
    return "NEUTRAL_BENCHMARK"


def rate_of(df: pd.DataFrame, label: str, denom: int) -> float:
    n = int((df["outcome"] == label).sum())
    return n / denom if denom > 0 else float("nan")


def benchmark_row(
    signals: pd.DataFrame,
    outcome: pd.DataFrame,
    benchmark_id: str,
    sample_mask: np.ndarray,
    target: str,
) -> dict[str, Any]:
    """One benchmark x one sample x one target metrics row."""
    sig_col = f"{benchmark_id}_signal"
    elig_col = f"{benchmark_id}_eligible"
    known = outcome[target].to_numpy() != "UNKNOWN"
    data_elig = sample_mask & signals[elig_col].to_numpy().astype(bool)
    out = outcome[target].to_numpy()
    labels = (out == "SUCCESS").astype(int)
    m = data_elig & known
    sig = signals[sig_col].to_numpy().astype(bool)[m]
    lbs = labels[m]
    n_known = int(m.sum())
    signal_n = int(sig.sum())
    non_signal_n = n_known - signal_n
    sig_succ = int((lbs[sig] == 1).sum())
    nonsig_succ = int((lbs[~sig] == 1).sum())
    sig_rate_raw = sig_succ / signal_n if signal_n else float("nan")
    nonsig_rate_raw = (
        nonsig_succ / non_signal_n if non_signal_n else float("nan")
    )
    row: dict[str, Any] = {
        "benchmark_id": benchmark_id,
        "sample": "OWN" if sample_mask.all() else "COMMON",
        "target": target,
        "data_eligible_n": int(data_elig.sum()),
        "outcome_known_n": n_known,
        "unknown_n": int((data_elig & ~known).sum()),
        "signal_n": signal_n,
        "non_signal_n": non_signal_n,
        "signal_success_n": sig_succ,
        "signal_success_rate": round(sig_rate_raw, 4),
        "nonsignal_success_n": nonsig_succ,
        "nonsignal_success_rate": round(nonsig_rate_raw, 4),
        "signal_fb_rate": float("nan"), "signal_nl_rate": float("nan"),
        "signal_sf_rate": float("nan"),
        "nonsignal_fb_rate": float("nan"), "nonsignal_nl_rate": float("nan"),
        "nonsignal_sf_rate": float("nan"),
    }
    for grp, mask in (("signal", sig), ("nonsignal", ~sig)):
        if int(mask.sum()) == 0:
            continue
        g = pd.DataFrame({"outcome": out[m][mask]})
        row[f"{grp}_fb_rate"] = round(rate_of(g, "FAILED_BREAKOUT", len(g)), 4)
        row[f"{grp}_nl_rate"] = round(rate_of(g, "NO_LAUNCH", len(g)), 4)
        row[f"{grp}_sf_rate"] = round(rate_of(g, "STRUCTURE_FAIL", len(g)), 4)
    orr = or_2x2(
        sig_succ, signal_n - sig_succ,
        nonsig_succ, non_signal_n - nonsig_succ,
    )
    row["cell_signal_success"] = orr["signal_success"]
    row["cell_signal_nonsuccess"] = orr["signal_nonsuccess"]
    row["cell_nonsignal_success"] = orr["nonsignal_success"]
    row["cell_nonsignal_nonsuccess"] = orr["nonsignal_nonsuccess"]
    row["or_value"] = orr["or"]
    row["or_ci_low"] = orr["ci_low"]
    row["or_ci_high"] = orr["ci_high"]
    row["or_zero_cell_corrected"] = orr["zero_cell_corrected"]
    auc = binary_auc_signal(sig, lbs)
    row["binary_auc"] = auc
    row["classification"] = classify_benchmark(
        sig_rate_raw, nonsig_rate_raw,
        row["or_value"], auc if isinstance(auc, float) else float("nan"),
    )
    return row


def failure_profile_row(
    signals: pd.DataFrame,
    outcome: pd.DataFrame,
    benchmark_id: str,
    sample_mask: np.ndarray,
    target: str,
) -> dict[str, Any]:
    sig_col = f"{benchmark_id}_signal"
    elig_col = f"{benchmark_id}_eligible"
    known = outcome[target].to_numpy() != "UNKNOWN"
    out = outcome[target].to_numpy()
    m = sample_mask & signals[elig_col].to_numpy().astype(bool) & known
    sig = signals[sig_col].to_numpy().astype(bool)[m]
    rows = []
    for grp, mask in (("signal", sig), ("non_signal", ~sig)):
        g = pd.DataFrame({"outcome": out[m][mask]})
        n = len(g)
        rows.append({
            "benchmark_id": benchmark_id, "target": target, "group": grp,
            "group_n_known": n,
            "SUCCESS_n": int((g["outcome"] == "SUCCESS").sum()),
            "SUCCESS_rate": round(rate_of(g, "SUCCESS", n), 4) if n else float("nan"),
            "FAILED_BREAKOUT_n": int((g["outcome"] == "FAILED_BREAKOUT").sum()),
            "FAILED_BREAKOUT_rate": (
                round(rate_of(g, "FAILED_BREAKOUT", n), 4) if n else float("nan")),
            "NO_LAUNCH_n": int((g["outcome"] == "NO_LAUNCH").sum()),
            "NO_LAUNCH_rate": round(rate_of(g, "NO_LAUNCH", n), 4) if n else float("nan"),
            "STRUCTURE_FAIL_n": int((g["outcome"] == "STRUCTURE_FAIL").sum()),
            "STRUCTURE_FAIL_rate": (
                round(rate_of(g, "STRUCTURE_FAIL", n), 4) if n else float("nan")),
        })
    return rows


def main() -> None:
    feat, out = input_gate()
    registry_gate()
    canon = load_canonical_gated(set(feat["symbol"].astype(str)))
    print("CANONICAL_ROWS:", len(canon))
    sig = feat[["episode_id", "symbol", "anchor_date", "candidate_date"]].copy()
    sig["anchor_date"] = pd.to_datetime(sig["anchor_date"]).dt.date
    sig["candidate_date"] = pd.to_datetime(sig["candidate_date"]).dt.date
    b4e, b4s = b4_signal(feat["days_since_t0"])
    sig["B4_eligible"] = b4e
    sig["B4_signal"] = b4s
    sig["B4_missing_reason"] = feat["days_since_t0__missing_reason"].fillna("")
    print("SIGNALS_ROWS:", len(sig), "| unique:", sig["episode_id"].nunique())
    # B5/B6/B7 per-episode semantics
    canon["pos"] = canon.groupby("code").cumcount()
    canon["close_prev"] = canon.groupby("code")["close"].shift(1)
    canon["ref_high"] = (
        canon.groupby("code")["high"]
        .transform(lambda s: s.shift(1).rolling(B7_LOOKBACK, min_periods=1).max())
    )
    t0 = canon.rename(columns={
        "trade_date": "anchor_date", "close": "close_t0", "volume": "volume_t0",
        "preclose": "preclose_t0", "close_prev": "close_prev_t0",
        "ref_high": "b7_ref_high", "pos": "pos_t0",
    })[["code", "anchor_date", "close_t0", "volume_t0", "preclose_t0",
        "close_prev_t0", "b7_ref_high", "pos_t0"]]
    dbar = canon.rename(columns={
        "trade_date": "candidate_date", "close": "close_d", "volume": "volume_d",
        "preclose": "preclose_d", "close_prev": "close_prev_d",
    })[["code", "candidate_date", "close_d", "volume_d", "preclose_d",
        "close_prev_d"]]
    sig = sig.merge(t0.rename(columns={"code": "symbol"}), on=["symbol", "anchor_date"],
                    how="left")
    sig = sig.merge(dbar.rename(columns={"code": "symbol"}),
                    on=["symbol", "candidate_date"], how="left")
    # B5
    t0_ca = (sig["preclose_t0"] - sig["close_prev_t0"]).abs() > (
        CA_TOL * sig["close_prev_t0"].abs())
    d_ca = (sig["preclose_d"] - sig["close_prev_d"]).abs() > (
        CA_TOL * sig["close_prev_d"].abs())
    sig["B5_eligible"] = (
        sig["close_t0"].notna() & sig["close_d"].notna()
        & ~t0_ca.fillna(False) & ~d_ca.fillna(False)
    )
    sig["B5_signal"] = sig.apply(
        lambda r: bool(r["B5_eligible"]) and b5_signal(r["close_t0"], r["close_d"]),
        axis=1,
    )
    sig["B5_missing_reason"] = np.select(
        [sig["close_t0"].isna(), sig["close_d"].isna(), t0_ca.fillna(False),
         d_ca.fillna(False)],
        ["MISSING_T0_BAR", "MISSING_D_BAR", "CA_T0", "CA_D"],
        default="",
    )
    # B6
    vol_ok = sig["volume_t0"].notna() & sig["volume_d"].notna() \
        & (sig["volume_t0"] > 0) & (sig["volume_d"] > 0)
    sig["B6_eligible"] = sig["B5_eligible"] & vol_ok
    sig["B6_signal"] = sig.apply(
        lambda r: bool(r["B6_eligible"]) and b6_signal(r["volume_t0"], r["volume_d"]),
        axis=1,
    )
    sig["B6_missing_reason"] = np.select(
        [sig["B5_missing_reason"] != "",
         sig["volume_t0"].isna() | (sig["volume_t0"] <= 0),
         sig["volume_d"].isna() | (sig["volume_d"] <= 0)],
        ["B5_INELIGIBLE", "VOLUME_NONPOSITIVE_T0", "VOLUME_NONPOSITIVE_D"],
        default="",
    )
    # B7
    # B7: no CA filtering per frozen contract (helper does none)
    sig["B7_eligible"] = sig["b7_ref_high"].notna() & sig["close_d"].notna()
    sig["B7_signal"] = sig.apply(
        lambda r: bool(r["B7_eligible"]) and r["close_d"] > r["b7_ref_high"],
        axis=1,
    )
    sig["B7_missing_reason"] = np.select(
        [sig["b7_ref_high"].isna(), sig["close_d"].isna()],
        ["NO_REFERENCE", "MISSING_D_BAR"],
        default="",
    )
    sig["common_eligible"] = (
        sig["B4_eligible"] & sig["B5_eligible"] & sig["B6_eligible"]
        & sig["B7_eligible"]
    )
    sig_cols = [
        "episode_id", "symbol", "anchor_date", "candidate_date",
        "B4_eligible", "B4_signal", "B4_missing_reason",
        "B5_eligible", "B5_signal", "B5_missing_reason",
        "B6_eligible", "B6_signal", "B6_missing_reason",
        "B7_eligible", "B7_signal", "B7_missing_reason",
        "common_eligible",
    ]
    out_sig = sig[sig_cols].copy()
    out_sig["anchor_date"] = out_sig["anchor_date"].astype(str)
    out_sig["candidate_date"] = out_sig["candidate_date"].astype(str)
    out_sig.to_csv(OUT_SIGNALS, index=False)
    print("SIGNALS OUT:", OUT_SIGNALS)
    # results
    rows3, rows5 = [], []
    common_mask = sig["common_eligible"].to_numpy().astype(bool)
    for bid in EXECUTION_SET:
        own_mask = np.ones(len(sig), dtype=bool)
        for target, sink in (("outcome_3d", rows3), ("outcome_5d", rows5)):
            sink.append(benchmark_row(sig, out, bid, own_mask, target))
            sink.append(benchmark_row(sig, out, bid, common_mask, target))
    pd.DataFrame(rows3).to_csv(OUT_RESULTS_3D, index=False)
    pd.DataFrame(rows5).to_csv(OUT_RESULTS_5D, index=False)
    print("\nRESULTS 3D:")
    print(pd.DataFrame(rows3)[
        ["benchmark_id", "sample", "data_eligible_n", "signal_n",
         "signal_success_rate", "nonsignal_success_rate", "or_value",
         "binary_auc", "classification"]
    ].to_string(index=False))
    print("\nRESULTS 5D:")
    print(pd.DataFrame(rows5)[
        ["benchmark_id", "sample", "signal_success_rate",
         "nonsignal_success_rate", "or_value", "binary_auc", "classification"]
    ].to_string(index=False))
    # failure profile 3D (own sample)
    fp = []
    for bid in EXECUTION_SET:
        fp.extend(failure_profile_row(
            sig, out, bid, np.ones(len(sig), dtype=bool), "outcome_3d"))
    pd.DataFrame(fp).to_csv(OUT_FAILURE, index=False)
    print("\nFAILURE PROFILE 3D (signal group):")
    print(pd.DataFrame(fp).to_string(index=False))
    # ---- QA reconciliation (fail closed) ----
    known3 = out["outcome_3d"].to_numpy() != "UNKNOWN"
    for bid in EXECUTION_SET:
        elig = sig[f"{bid}_eligible"].astype(bool).to_numpy()
        sg = sig[f"{bid}_signal"].astype(bool).to_numpy()
        n_known = int((elig & known3).sum())
        sig_n = int((elig & known3 & sg).sum())
        assert n_known == sig_n + (n_known - sig_n)
        assert int((elig & known3 & ~sg).sum()) == n_known - sig_n
        assert int(elig.sum()) == n_known + int((elig & ~known3).sum())
    fp3 = pd.DataFrame(fp)
    for bid in EXECUTION_SET:
        row = fp3[(fp3["benchmark_id"] == bid) & (fp3["group"] == "signal")].iloc[0]
        assert row["group_n_known"] == (
            row["SUCCESS_n"] + row["FAILED_BREAKOUT_n"]
            + row["NO_LAUNCH_n"] + row["STRUCTURE_FAIL_n"]
        )
    r3 = pd.DataFrame(rows3)
    r5 = pd.DataFrame(rows5)
    # 3D/5D signal byte invariance: the on-disk signals artifact is the single
    # source for both targets (signal VALUES, not known-filtered counts).
    sig_disk = pd.read_csv(OUT_SIGNALS)
    for bid in EXECUTION_SET:
        assert (sig_disk[f"{bid}_eligible"].astype(bool)
                == sig[f"{bid}_eligible"].astype(bool)).all()
        assert (sig_disk[f"{bid}_signal"].astype(bool)
                == sig[f"{bid}_signal"].astype(bool)).all()
    assert sig["episode_id"].nunique() == 8682 == len(sig)
    print("QA RECONCILIATION: PASS")


if __name__ == "__main__":
    main()
