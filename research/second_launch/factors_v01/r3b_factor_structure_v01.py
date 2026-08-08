"""R3B — factor structure diagnostics (F3 redundancy / dose-response, F5 time
shape, F6 failure boundary, F3 x F6 descriptive crosstab).

Exploratory research only: no ML, no score/threshold optimization, no backtest,
no strategy changes. Reuses the R3A.1 input gate and statistics helpers.
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


OUT_MAIN = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r3b_factor_structure_results.csv"
)
OUT_CORR = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r3b_f3_correlation_matrix.csv"
)
OUT_CROSSTAB = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r3b_f3_f6_crosstab.csv"
)

F3_FACTORS = [
    "pullback_volume_ratio",
    "min_volume_ratio",
    "median_range_ratio",
    "quiet_days_n",
    "volume_slope",
]
F3_PROMISING = F3_FACTORS[:4]


def wilson_ci(success: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = success / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


def bucket_rows(
    df: pd.DataFrame,
    factor: str,
    bucket_labels: pd.Series,
    order: list[str],
) -> list[dict[str, Any]]:
    rows = []
    for label in order:
        g = df[bucket_labels == label]
        n = len(g)
        if n == 0:
            continue
        succ = int((g["outcome_3d"] == "SUCCESS").sum())
        fb = int((g["outcome_3d"] == "FAILED_BREAKOUT").sum())
        nl = int((g["outcome_3d"] == "NO_LAUNCH").sum())
        sf = int((g["outcome_3d"] == "STRUCTURE_FAIL").sum())
        lo, hi = wilson_ci(succ, n)
        rows.append(
            {
                "factor": factor,
                "bucket": str(label),
                "n": n,
                "success_n": succ,
                "success_rate": round(succ / n, 4),
                "fb_rate": round(fb / n, 4),
                "nl_rate": round(nl / n, 4),
                "sf_rate": round(sf / n, 4),
                "ci_low": round(lo, 4),
                "ci_high": round(hi, 4),
            }
        )
    return rows


def shape_label(rates: list[tuple[str, float, int]]) -> str:
    """Heuristic OBSERVATION label on the SUCCESS-rate sequence.

    Rule (pre-registered, qualitative):
    - fewer than 3 buckets with n>=30 -> DATA_LIMITED
    - non-increasing across ordered buckets -> MONOTONIC_DECREASING
    - single interior peak above both neighbours -> INVERTED_U
    - first bucket rate > last bucket rate by >1pp -> STALE_DECAY
    - otherwise NO_PATTERN
    """
    valid = [(b, r, n) for b, r, n in rates if n >= 30]
    if len(valid) < 3:
        return "DATA_LIMITED"
    seq = [r for _, r, _ in valid]
    if all(seq[i] >= seq[i + 1] - 1e-9 for i in range(len(seq) - 1)):
        return "MONOTONIC_DECREASING"
    if all(seq[i] <= seq[i + 1] + 1e-9 for i in range(len(seq) - 1)):
        return "MONOTONIC_INCREASING"
    if 1 <= int(np.argmax(seq)) <= len(seq) - 2:
        peak = int(np.argmax(seq))
        if seq[peak] > seq[peak - 1] and seq[peak] > seq[peak + 1]:
            return "INVERTED_U"
    if valid[0][1] - valid[-1][1] > 0.01:
        return "STALE_DECAY"
    return "NO_PATTERN"


def main() -> None:
    feat, out = r3a.run_input_gate()
    df = feat.merge(out, on="episode_id", suffixes=("_f", "_o"))
    df = df.drop(columns=[c for c in df.columns if c.endswith("_o")])
    df = df.rename(columns={c: c[:-2] for c in df.columns if c.endswith("_f")})
    print("JOIN_ROWS:", len(df))
    rows: list[dict[str, Any]] = []

    # ---- F3 redundancy: Spearman correlation on pairwise-complete sample ----
    corr_rows = []
    for i, a in enumerate(F3_FACTORS):
        for b in F3_FACTORS[i + 1:]:
            m = df[[a, b]].notna().all(axis=1)
            n = int(m.sum())
            if n < 30:
                corr_rows.append({"factor_a": a, "factor_b": b, "pairwise_n": n,
                                  "corr_all": float("nan"), "corr_success": float("nan"),
                                  "corr_nonsuccess": float("nan")})
                continue
            va = pd.to_numeric(df.loc[m, a]).to_numpy()
            vb = pd.to_numeric(df.loc[m, b]).to_numpy()
            known = df["outcome_3d"].to_numpy()[m] != "UNKNOWN"
            corr_all = r3a._spearman(va, vb)
            corr_succ = r3a._spearman(
                va[known & (df["outcome_3d"].to_numpy()[m] == "SUCCESS")],
                vb[known & (df["outcome_3d"].to_numpy()[m] == "SUCCESS")],
            ) if known.sum() > 10 else float("nan")
            corr_ns = r3a._spearman(
                va[known & (df["outcome_3d"].to_numpy()[m] != "SUCCESS")],
                vb[known & (df["outcome_3d"].to_numpy()[m] != "SUCCESS")],
            ) if known.sum() > 10 else float("nan")
            corr_rows.append({"factor_a": a, "factor_b": b, "pairwise_n": n,
                              "corr_all": round(corr_all, 4),
                              "corr_success": round(corr_succ, 4),
                              "corr_nonsuccess": round(corr_ns, 4)})
            rows.append({"section": "F3_REDUNDANCY", "factor": f"{a}~{b}",
                         "bucket": "pairwise", "n": n,
                         "success_rate": float("nan"),
                         "extra": f"corr_all={corr_all:.3f} succ={corr_succ:.3f} ns={corr_ns:.3f}"})
    corr_df = pd.DataFrame(corr_rows)
    corr_df.to_csv(OUT_CORR, index=False)
    print("F3_REDUNDANCY:")
    print(corr_df.to_string(index=False))

    # ---- representative F3 selection (pre-registered rule) ----
    r3a_results = pd.read_csv(
        REPO_ROOT / "research" / "second_launch" / "factors_v01"
        / "r3a_univariate_factor_results.csv"
    )
    meta = r3a_results.set_index("factor")
    eligible = [f for f in F3_PROMISING
                if meta.loc[f, "stability"] == "STABLE"
                and meta.loc[f, "coverage_3d"] >= 0.90]
    if eligible:
        corr_mat = corr_df[corr_df["factor_a"].isin(F3_PROMISING) &
                           corr_df["factor_b"].isin(F3_PROMISING)]
        medians = {}
        for f in eligible:
            vals = []
            for _, r in corr_mat.iterrows():
                if r["factor_a"] == f:
                    vals.append(abs(r["corr_all"]))
                elif r["factor_b"] == f:
                    vals.append(abs(r["corr_all"]))
            medians[f] = float(np.median(vals)) if vals else float("nan")
        rep_f3 = min(eligible, key=lambda f: medians[f])
    else:
        rep_f3 = "quiet_days_n"
    print("REPRESENTATIVE_F3:", rep_f3, "(rule: STABLE + coverage>=0.90 + lowest median |corr|)")

    # ---- F3 dose response ----
    for f in F3_PROMISING:
        vals = pd.to_numeric(df[f], errors="coerce")
        known = df["outcome_3d"] != "UNKNOWN"
        if f == "quiet_days_n":
            g = vals[known].astype("Int64")
            labels = pd.Series(
                ["2+" if (pd.notna(v) and v >= 2) else (str(int(v)) if pd.notna(v) else "NA")
                 for v in vals[known]],
                index=df.index[known],
            )
            order = ["0", "1", "2+"]
        else:
            q = pd.qcut(vals[known], 5, duplicates="drop")
            labels = q.astype(str)
            cats = list(q.cat.categories.astype(str))
            order = cats
        for r in bucket_rows(df[known], f, labels, order):
            r["section"] = "F3_DOSE_RESPONSE"
            r["extra"] = ""
            rows.append(r)
        rates = [(r["bucket"], r["success_rate"], r["n"])
                 for r in rows if r.get("section") == "F3_DOSE_RESPONSE"
                 and r["factor"] == f]
        print(f"F3_DOSE {f}: shape={shape_label(rates)}")

    # ---- F5 time shape ----
    for f in ["days_since_t0", "days_to_pullback_low", "pullback_duration"]:
        vals = pd.to_numeric(df[f], errors="coerce")
        known = df["outcome_3d"] != "UNKNOWN"
        g = vals[known]
        vc = g.value_counts().sort_index()
        # natural integer buckets; merge tiny tails (n<30) into tail buckets
        labels = pd.Series(index=df.index[known], dtype=object)
        tail_values: list[str] = []
        for v in vc.index:
            v = int(v)
            if vc[v] < 30:
                tail_values.append(str(v))
        for idx in df.index[known]:
            raw = g[idx]
            if pd.isna(raw):
                labels[idx] = "NA"
                continue
            v = int(raw)
            labels[idx] = f"tail({'+'.join(tail_values)})" if str(v) in tail_values else str(v)
        order = [str(int(v)) for v in vc.index if str(int(v)) not in tail_values]
        if tail_values:
            order.append(f"tail({'+'.join(tail_values)})")
        for r in bucket_rows(df[known], f, labels, order):
            r["section"] = "F5_TIME_SHAPE"
            r["extra"] = ""
            rows.append(r)
        rates = [(r["bucket"], r["success_rate"], r["n"])
                 for r in rows if r.get("section") == "F5_TIME_SHAPE"
                 and r["factor"] == f]
        print(f"F5_SHAPE {f}: shape={shape_label(rates)}")

    # ---- F6 failure boundary: class rates by quantile ----
    for f in ["high_vs_pullback_high", "close_vs_pullback_high"]:
        vals = pd.to_numeric(df[f], errors="coerce")
        known = df["outcome_3d"] != "UNKNOWN"
        q = pd.qcut(vals[known], 5, duplicates="drop")
        labels = q.astype(str)
        order = list(q.cat.categories.astype(str))
        for r in bucket_rows(df[known], f, labels, order):
            r["section"] = "F6_FAILURE_BOUNDARY"
            r["extra"] = ""
            rows.append(r)

    # ---- F3 x F6 descriptive crosstab ----
    ct_rows = []
    vals3 = pd.to_numeric(df[rep_f3], errors="coerce")
    vals6 = pd.to_numeric(df["close_vs_pullback_high"], errors="coerce")
    known = (df["outcome_3d"] != "UNKNOWN") & vals3.notna() & vals6.notna()
    if rep_f3 == "quiet_days_n":
        g3 = vals3[known].astype(int)
        labels3 = pd.Series(
            ["LOW" if v == 0 else ("MID" if v == 1 else "HIGH") for v in g3],
            index=df.index[known],
        )
    else:
        labels3 = pd.Series(
            pd.qcut(vals3[known], 3, duplicates="drop").astype(str),
            index=df.index[known],
        )
    med6 = float(np.median(vals6[known]))
    labels6 = pd.Series(
        ["LOW" if v < med6 else "HIGH" for v in vals6[known]],
        index=df.index[known],
    )
    for l3 in sorted(set(labels3)):
        for l6 in ["LOW", "HIGH"]:
            m = labels3 == l3
            m2 = labels6 == l6
            g = df[known][m & m2]
            n = len(g)
            if n == 0:
                continue
            succ = int((g["outcome_3d"] == "SUCCESS").sum())
            fb = int((g["outcome_3d"] == "FAILED_BREAKOUT").sum())
            nl = int((g["outcome_3d"] == "NO_LAUNCH").sum())
            sf = int((g["outcome_3d"] == "STRUCTURE_FAIL").sum())
            lo, hi = wilson_ci(succ, n)
            ct_rows.append({"f3": l3, "f6": l6, "n": n,
                            "success_rate": round(succ / n, 4),
                            "fb_rate": round(fb / n, 4),
                            "nl_rate": round(nl / n, 4),
                            "sf_rate": round(sf / n, 4),
                            "ci_low": round(lo, 4), "ci_high": round(hi, 4)})
    ct = pd.DataFrame(ct_rows)
    ct.to_csv(OUT_CROSSTAB, index=False)
    print("F3xF6 CROSSTAB (rep_f3=", rep_f3, "):")
    print(ct.to_string(index=False))

    # ---- temporal check: quiet_days groups + close_vs_ph median split per quarter ----
    df["cand_q"] = pd.to_datetime(df["candidate_date"]).dt.to_period("Q")
    tq = []
    for q, g in df.groupby("cand_q"):
        if len(g) < 30:
            continue
        qv = pd.to_numeric(g["quiet_days_n"], errors="coerce")
        hi_q = (qv >= 1).sum()
        lo_q = (qv == 0).sum()
        if hi_q >= 10 and lo_q >= 10:
            r_hi = (g.loc[qv >= 1, "outcome_3d"] == "SUCCESS").mean()
            r_lo = (g.loc[qv == 0, "outcome_3d"] == "SUCCESS").mean()
        else:
            r_hi = r_lo = float("nan")
        cv = pd.to_numeric(g["close_vs_pullback_high"], errors="coerce")
        med = float(np.nanmedian(cv))
        hi_c = cv >= med
        lo_c = cv < med
        if hi_c.sum() >= 10 and lo_c.sum() >= 10:
            r_chi = (g.loc[hi_c, "outcome_3d"] == "SUCCESS").mean()
            r_clo = (g.loc[lo_c, "outcome_3d"] == "SUCCESS").mean()
        else:
            r_chi = r_clo = float("nan")
        tq.append({"quarter": str(q), "n": len(g),
                   "quiet_hi_rate": round(r_hi, 4), "quiet_lo_rate": round(r_lo, 4),
                   "close_hi_rate": round(r_chi, 4), "close_lo_rate": round(r_clo, 4)})
    tq_df = pd.DataFrame(tq)
    print("TEMPORAL (quarterly):")
    print(tq_df.to_string(index=False))
    for _, r in tq_df.iterrows():
        rows.append({
            "section": "TEMPORAL_QUARTERLY", "factor": "quiet_days_n>=1",
            "bucket": str(r["quarter"]), "n": int(r["n"]),
            "success_rate": r["quiet_hi_rate"],
            "extra": f"close_hi={r['close_hi_rate']} close_lo={r['close_lo_rate']}",
        })

    out_df = pd.DataFrame(rows)
    out_df.to_csv(OUT_MAIN, index=False)
    print("OUT:", OUT_MAIN, "rows:", len(out_df))


if __name__ == "__main__":
    main()
