"""R3A — immutable outcome join + univariate factor screen (research-only).

Joins the frozen feature dataset to the frozen outcome dataset on episode_id
(1:1, exact), and computes a univariate screen for the 24 PRIMARY factors
against SUCCESS vs KNOWN_NON_SUCCESS (3D primary, 5D sensitivity). No ML, no
multivariate model, no score/threshold optimization, no strategy changes.

Impulse_retrace_ratio (#11 DERIVED_ALIAS) is excluded from ranking; only its
identity with t0_gain_retention is QA-checked.
"""

from __future__ import annotations

from datetime import date
import hashlib
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]

FEATURE_CSV = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "second_launch_factors_v01b_reproducible.csv"
)
OUTCOME_CSV = (
    REPO_ROOT / "research" / "second_launch" / "outcome_v01"
    / "second_launch_outcome_v01b_reproducible.csv"
)
FEATURE_MANIFEST = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "manifest_factors_v01b_reproducible.json"
)
OUTCOME_MANIFEST = (
    REPO_ROOT / "research" / "second_launch" / "outcome_v01"
    / "manifest_v01b_reproducible.json"
)

EXPECTED_FEATURE_SHA256 = "a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8"
EXPECTED_OUTCOME_SHA256 = "01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d"
EXPECTED_FEATURE_SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"

PRIMARY_FACTORS = [
    "t0_return", "t0_gap", "t0_range_pct", "t0_close_location",
    "t0_position_20d", "pre_t0_return_5d", "pre_t0_return_20d",
    "t0_volume_ratio_5d", "pullback_depth_close",
    "max_drawdown_from_post_t0_high", "t0_gain_retention",
    "low_vs_t0_mid", "days_above_t0_mid", "pullback_volume_ratio",
    "min_volume_ratio", "volume_slope", "median_range_ratio",
    "range_slope", "quiet_days_n", "days_since_t0",
    "days_to_pullback_low", "pullback_duration",
    "high_vs_pullback_high", "close_vs_pullback_high",
]
DERIVED_ALIAS = "impulse_retrace_ratio"

STRATIFICATION_COLUMNS = [
    "candidate_reconciliation_status",
    "feature_3d_has_provisional",
    "label_5d_has_provisional",
    "data_quality",
    "quality_flags",
]

OUT_CSV = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r3a_univariate_factor_results.csv"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Input gate (fail closed).
# ---------------------------------------------------------------------------

def run_input_gate() -> tuple[pd.DataFrame, pd.DataFrame]:
    if sha256_file(FEATURE_CSV) != EXPECTED_FEATURE_SHA256:
        raise RuntimeError("feature dataset SHA mismatch (fail closed)")
    if sha256_file(OUTCOME_CSV) != EXPECTED_OUTCOME_SHA256:
        raise RuntimeError("outcome dataset SHA mismatch (fail closed)")
    import json

    fm = json.loads(FEATURE_MANIFEST.read_text())
    om = json.loads(OUTCOME_MANIFEST.read_text())
    if fm["DATASET_SHA256"] != EXPECTED_FEATURE_SHA256:
        raise RuntimeError("feature manifest SHA mismatch (fail closed)")
    if om["artifact_sha256"] != EXPECTED_OUTCOME_SHA256:
        raise RuntimeError("outcome manifest SHA mismatch (fail closed)")
    if fm["FEATURE_SNAPSHOT_ID"] != EXPECTED_FEATURE_SNAPSHOT_ID:
        raise RuntimeError("feature snapshot binding mismatch (fail closed)")

    feat = pd.read_csv(FEATURE_CSV, dtype={"symbol": str})
    out = pd.read_csv(OUTCOME_CSV, dtype={"symbol": str})
    if len(feat) != 8682 or len(out) != 8682:
        raise RuntimeError(f"row counts {len(feat)}/{len(out)} != 8682")
    if feat["episode_id"].duplicated().any() or out["episode_id"].duplicated().any():
        raise RuntimeError("duplicate episode_id (fail closed)")
    if set(feat["episode_id"]) != set(out["episode_id"]):
        raise RuntimeError("episode_id sets not 1:1 exact (fail closed)")
    merged = feat.merge(out, on="episode_id", suffixes=("_f", "_o"))
    for col in ["anchor_date", "candidate_date", "symbol"]:
        if not (merged[f"{col}_f"] == merged[f"{col}_o"]).all():
            raise RuntimeError(f"identity column mismatch on {col} (fail closed)")
    if not (out["feature_snapshot_id"] == EXPECTED_FEATURE_SNAPSHOT_ID).all():
        raise RuntimeError("outcome feature_snapshot_id binding mismatch (fail closed)")
    return feat, out


# ---------------------------------------------------------------------------
# Statistics helpers.
# ---------------------------------------------------------------------------

def _rankdata(values: np.ndarray) -> np.ndarray:
    """Average ranks (ties get mean rank), scipy-free."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        ranks[order[i:j + 1]] = avg
        i = j + 1
    return ranks


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    rx = _rankdata(x)
    ry = _rankdata(y)
    if np.std(rx) == 0 or np.std(ry) == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def binary_auc(values: np.ndarray, labels: np.ndarray) -> float:
    """ROC-AUC via Mann-Whitney U (no direction flipping)."""
    pos = values[labels == 1]
    neg = values[labels == 0]
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = _rankdata(np.concatenate([pos, neg]))
    u = ranks[:n_pos].sum() - n_pos * (n_pos + 1) / 2.0
    return float(u / (n_pos * n_neg))


def auc_pvalue(values: np.ndarray, labels: np.ndarray) -> float:
    """Two-sided asymptotic Mann-Whitney U p-value WITH tie correction.

    Var(U) = n1*n0/12 * (N + 1 - sum(t^3 - t) / (N*(N-1)))
    using pooled tie-group sizes t. Average ranks (ties) are unchanged.
    All-equal values: variance = 0; if U equals the null expectation the
    p-value is exactly 1.0; otherwise FAIL CLOSED (no epsilon hack).
    AUC direction is never flipped.
    """
    pos = values[labels == 1]
    neg = values[labels == 0]
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0 or n_pos + n_neg < 8:
        return float("nan")
    pooled = np.concatenate([pos, neg])
    ranks = _rankdata(pooled)
    u = ranks[:n_pos].sum() - n_pos * (n_pos + 1) / 2.0
    n = n_pos + n_neg
    _, counts = np.unique(pooled, return_counts=True)
    tie_adjustment = float(np.sum(counts ** 3 - counts))
    var_u = n_pos * n_neg / 12.0 * (n + 1 - tie_adjustment / (n * (n - 1)))
    mu = n_pos * n_neg / 2.0
    if var_u <= 0:
        if abs(u - mu) <= 1e-12:
            return 1.0
        raise RuntimeError(
            "MWU variance <= 0 with U != null expectation (fail closed)"
        )
    z = (u - mu) / np.sqrt(var_u)
    return float(2.0 * (1.0 - _norm_cdf(abs(z))))


def spearman_binary(values: np.ndarray, labels: np.ndarray) -> float:
    return _spearman(values, labels)


def quintile_rates(values: np.ndarray, labels: np.ndarray) -> dict[str, Any]:
    """Deterministic quintile bins (duplicates dropped -> reduced bins recorded)."""
    s = pd.Series(values)
    bins = pd.qcut(s, 5, duplicates="drop")
    n_bins = bins.cat.categories.size if hasattr(bins.cat, "categories") else 1
    rates: list[float] = []
    counts: list[int] = []
    for label in range(n_bins):
        mask = (bins.cat.codes == label).to_numpy()
        counts.append(int(mask.sum()))
        rates.append(float(labels[mask].mean()) if mask.sum() else float("nan"))
    return {
        "bins_n": int(n_bins),
        "rate_bottom": rates[0] if rates else float("nan"),
        "rate_top": rates[-1] if rates else float("nan"),
        "bin_counts": counts,
    }


def odds_ratio_ci(values: np.ndarray, labels: np.ndarray) -> dict[str, Any]:
    """Top vs bottom quintile OR with Woolf 95% CI (0.5 correction on zero cells)."""
    s = pd.Series(values)
    bins = pd.qcut(s, 5, duplicates="drop")
    n_bins = bins.cat.categories.size if hasattr(bins.cat, "categories") else 1
    if n_bins < 2:
        return {"or": float("nan"), "ci_low": float("nan"), "ci_high": float("nan")}
    codes = bins.cat.codes.to_numpy()
    bottom = codes == 0
    top = codes == n_bins - 1
    a = float(labels[top].sum())
    b = float((~labels[top].astype(bool)).sum())
    c = float(labels[bottom].sum())
    d = float((~labels[bottom].astype(bool)).sum())
    if min(a, b, c, d) == 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
        corrected = True
    else:
        corrected = False
    if b == 0 or d == 0:
        return {"or": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
                "haldane_corrected": corrected}
    log_or = np.log((a / b) / (c / d))
    se = np.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return {
        "or": float(np.exp(log_or)),
        "ci_low": float(np.exp(log_or - 1.96 * se)),
        "ci_high": float(np.exp(log_or + 1.96 * se)),
        "haldane_corrected": corrected,
    }


def bh_fdr(pvalues: dict[str, float]) -> dict[str, float]:
    names = [k for k, v in pvalues.items() if not np.isnan(v)]
    ps = np.array([pvalues[k] for k in names], dtype=float)
    order = np.argsort(ps)
    # BH-FDR: q_i = min_{j>=i} p_(j) * m / j  (reverse cumulative min).
    adj_sorted = ps[order] * len(ps) / np.arange(1, len(ps) + 1)
    adj_sorted = np.minimum.accumulate(adj_sorted[::-1])[::-1]
    adj = np.empty_like(ps)
    adj[order] = adj_sorted
    adj = np.minimum(adj, 1.0)
    out = {k: float(v) for k, v in zip(names, adj)}
    for k, v in pvalues.items():
        if np.isnan(v):
            out[k] = float("nan")
    return out


def classify(results: dict[str, dict[str, Any]], factor: str) -> str:
    r = results[factor]
    coverage = r["coverage_3d"]
    n = r["n_known_3d"]
    auc = r["auc_3d"]
    q = r["q_bh_3d"]
    stability = r["stability"]
    if coverage < 0.5 or n < 200:
        return "DATA_LIMITED"
    if stability in ("UNSTABLE",):
        return "UNSTABLE"
    effect = abs(auc - 0.5)
    if effect >= 0.05 and (q < 0.10 or np.isnan(q)):
        return "PROMISING"
    if effect >= 0.02:
        return "WEAK" if stability != "MIXED" else "UNSTABLE"
    return "NO_SIGNAL"


# ---------------------------------------------------------------------------
# Main screen.
# ---------------------------------------------------------------------------

def main() -> None:
    feat, out = run_input_gate()
    df = feat.merge(out, on="episode_id", suffixes=("_f", "_o"))
    df = df.drop(columns=[c for c in df.columns if c.endswith("_o")])
    df = df.rename(columns={c: c[:-2] for c in df.columns if c.endswith("_f")})
    print("JOIN_ROWS:", len(df))

    for target in ["outcome_3d", "outcome_5d"]:
        print(f"LABEL_COUNTS_{target.upper()}:",
              df[target].value_counts(dropna=False).to_dict())

    # Identity QA for the derived alias (not a predictor).
    both = df[df["impulse_retrace_ratio"].notna() & df["t0_gain_retention"].notna()]
    err = (both["impulse_retrace_ratio"] + both["t0_gain_retention"] - 1).abs()
    print("ALIAS_QA: comparable", len(both), "max_err", float(err.max()),
          "mismatch", int((err > 1e-9).sum()))

    rows: list[dict[str, Any]] = []
    pvalues_3d: dict[str, float] = {}
    for factor in PRIMARY_FACTORS:
        values = pd.to_numeric(df[factor], errors="coerce").to_numpy()
        missing = int(pd.isna(df[factor]).sum())
        res: dict[str, Any] = {"factor": factor, "missing_n": missing}
        for target, suffix in [("outcome_3d", "3d"), ("outcome_5d", "5d")]:
            labels_raw = df[target].to_numpy()
            known = labels_raw != "UNKNOWN"
            mask = (~np.isnan(values)) & known
            labels = (labels_raw[mask] == "SUCCESS").astype(int)
            vals = values[mask]
            n = int(mask.sum())
            n_known = int(known.sum())
            res[f"n_known_{suffix}"] = n_known
            res[f"n_{suffix}"] = n
            res[f"coverage_{suffix}"] = round(n / max(1, n_known), 4)
            if n == 0:
                res[f"auc_{suffix}"] = float("nan")
                res[f"p_{suffix}"] = float("nan")
                res[f"spearman_{suffix}"] = float("nan")
                res[f"succ_median_{suffix}"] = float("nan")
                res[f"nonsucc_median_{suffix}"] = float("nan")
                continue
            pos = vals[labels == 1]
            neg = vals[labels == 0]
            res[f"succ_median_{suffix}"] = float(np.median(pos)) if len(pos) else float("nan")
            res[f"succ_p25_{suffix}"] = float(np.percentile(pos, 25)) if len(pos) else float("nan")
            res[f"succ_p75_{suffix}"] = float(np.percentile(pos, 75)) if len(pos) else float("nan")
            res[f"nonsucc_median_{suffix}"] = float(np.median(neg)) if len(neg) else float("nan")
            res[f"nonsucc_p25_{suffix}"] = float(np.percentile(neg, 25)) if len(neg) else float("nan")
            res[f"nonsucc_p75_{suffix}"] = float(np.percentile(neg, 75)) if len(neg) else float("nan")
            res[f"auc_{suffix}"] = binary_auc(vals, labels)
            res[f"p_{suffix}"] = auc_pvalue(vals, labels)
            res[f"spearman_{suffix}"] = spearman_binary(vals, labels)
            res[f"succ_n_{suffix}"] = int(labels.sum())
        # Pairwise failure-class comparisons (3D target): SUCCESS vs each class.
        values = pd.to_numeric(df[factor], errors="coerce").to_numpy()
        for cls in ["FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"]:
            in_bin = df["outcome_3d"].isin(["SUCCESS", cls]).to_numpy()
            m = (~np.isnan(values)) & in_bin
            lbs = (df["outcome_3d"].to_numpy()[m] == "SUCCESS").astype(int)
            if (lbs == 1).sum() >= 20 and (lbs == 0).sum() >= 20:
                res[f"auc_3d_vs_{cls}"] = binary_auc(values[m], lbs)
            else:
                res[f"auc_3d_vs_{cls}"] = float("nan")
        if res.get("n_3d", 0) > 0:
            res["q_3d"] = float("nan")  # filled after BH
            pvalues_3d[factor] = res["p_3d"]
            q = quintile_rates(
                values[(~np.isnan(values)) & (df["outcome_3d"].to_numpy() != "UNKNOWN")],
                (df.loc[(~np.isnan(values)) & (df["outcome_3d"].to_numpy() != "UNKNOWN"),
                        "outcome_3d"] == "SUCCESS").astype(int).to_numpy(),
            )
            res.update(q)
            orc = odds_ratio_ci(
                values[(~np.isnan(values)) & (df["outcome_3d"].to_numpy() != "UNKNOWN")],
                (df.loc[(~np.isnan(values)) & (df["outcome_3d"].to_numpy() != "UNKNOWN"),
                        "outcome_3d"] == "SUCCESS").astype(int).to_numpy(),
            )
            res.update(orc)
            res["effect_direction"] = (
                "POSITIVE" if res["auc_3d"] >= 0.5 else "NEGATIVE"
            )
            d3 = res["auc_3d"] - 0.5
            d5 = res["auc_5d"] - 0.5
            res["direction_consistent_3d_5d"] = bool(
                np.sign(d3) == np.sign(d5)
                if not (np.isnan(d3) or np.isnan(d5)) else np.isnan(d3) and np.isnan(d5)
            )
        rows.append(res)

    qvals = bh_fdr(pvalues_3d)
    for r in rows:
        r["q_bh_3d"] = qvals.get(r["factor"], float("nan"))

    # Temporal stability: calendar-quarter buckets on candidate_date.
    df["cand_q"] = pd.to_datetime(df["candidate_date"]).dt.to_period("Q")
    for r in rows:
        factor = r["factor"]
        values = pd.to_numeric(df[factor], errors="coerce")
        labels = (df["outcome_3d"].to_numpy() == "SUCCESS").astype(int)
        known = df["outcome_3d"].to_numpy() != "UNKNOWN"
        bucket_rows = []
        for q, g in df.groupby("cand_q"):
            m = (~values.isna()) & known & (df["cand_q"] == q)
            vals = values[m].to_numpy()
            lbs = labels[m]
            if len(vals) < 30 or (lbs == 1).sum() < 10 or (lbs == 0).sum() < 10:
                continue
            auc = binary_auc(vals, lbs)
            bucket_rows.append({"q": str(q), "n": int(len(vals)),
                                "succ_n": int(lbs.sum()), "auc": auc,
                                "direction": "POSITIVE" if auc >= 0.5 else "NEGATIVE"})
        r["buckets"] = bucket_rows
        r["buckets_n"] = len(bucket_rows)
        r["bucket_pos_n"] = sum(1 for b in bucket_rows if b["direction"] == "POSITIVE")
        r["bucket_auc_min"] = min((b["auc"] for b in bucket_rows), default=float("nan"))
        r["bucket_auc_max"] = max((b["auc"] for b in bucket_rows), default=float("nan"))
        dirs = [b["direction"] for b in bucket_rows]
        if len(bucket_rows) < 3:
            r["stability"] = "DATA_LIMITED"
        else:
            pos_n = sum(1 for d in dirs if d == "POSITIVE")
            if pos_n == len(dirs) or pos_n == 0:
                r["stability"] = "STABLE"
            elif min(pos_n, len(dirs) - pos_n) <= len(dirs) / 3:
                r["stability"] = "MIXED"
            else:
                r["stability"] = "UNSTABLE"
        r["classification"] = classify({rr["factor"]: rr for rr in rows}, factor)

    results = pd.DataFrame(rows)
    # provenance sensitivity strata (AUC under quality strata)
    strata_rows = []
    for factor in PRIMARY_FACTORS:
        values = pd.to_numeric(df[factor], errors="coerce")
        labels_raw = df["outcome_3d"].to_numpy()
        known = labels_raw != "UNKNOWN"
        for stratum, mask in [
            ("full", np.ones(len(df), dtype=bool)),
            ("feature_3d_clean", df["feature_3d_has_provisional"].astype(bool).to_numpy() == False),  # noqa: E712
            ("label_5d_clean", df["label_5d_has_provisional"].astype(bool).to_numpy() == False),  # noqa: E712
        ]:
            m = (~values.isna()) & known & mask
            vals = values[m].to_numpy()
            lbs = (labels_raw[m] == "SUCCESS").astype(int)
            if (lbs == 1).sum() < 20 or (lbs == 0).sum() < 20:
                strata_rows.append({"factor": factor, "stratum": stratum,
                                    "n": int(m.sum()), "auc": float("nan")})
                continue
            strata_rows.append({"factor": factor, "stratum": stratum,
                                "n": int(m.sum()), "auc": binary_auc(vals, lbs)})
    strata = pd.DataFrame(strata_rows)

    results.to_csv(OUT_CSV, index=False)
    print("OUT:", OUT_CSV)
    summary = results[
        ["factor", "n_3d", "coverage_3d", "auc_3d", "p_3d", "q_bh_3d",
         "spearman_3d", "auc_5d", "direction_consistent_3d_5d",
         "or", "ci_low", "ci_high", "bins_n", "rate_bottom", "rate_top",
         "stability", "classification"]
    ]
    print(summary.to_string(index=False))
    print("STRATA_AUC_DELTA (full vs feature_3d_clean):")
    wide = strata.pivot(index="factor", columns="stratum", values="auc")
    wide["delta_feature"] = (wide["feature_3d_clean"] - wide["full"]).abs()
    wide["delta_label"] = (wide["label_5d_clean"] - wide["full"]).abs()
    print(wide[["full", "feature_3d_clean", "delta_feature", "delta_label"]]
          .round(4).to_string())


if __name__ == "__main__":
    main()
