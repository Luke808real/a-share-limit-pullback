"""R4 — factor stability across TIME / REGIME / BOARD / T0 TYPE.

Pre-registered contract:
    research/reports/SECOND_LAUNCH_FACTOR_R4_STABILITY_CONTRACT_V01.md
Reuses the R3A.1 input gate, AUC and rank helpers. Research-only; no ML,
no factor/score/threshold optimization, no strategy changes.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402


OUT_GLOBAL = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r4_stability_global_3d.csv"
)
OUT_STRATA = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r4_stability_strata_3d.csv"
)
OUT_VERDICTS = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r4_stability_verdicts_3d.csv"
)
OUT_SENS = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r4_stability_sensitivity_5d.csv"
)

CANONICAL_SNAPSHOT = (
    REPO_ROOT / "data" / "canonical" / "daily_bars"
    / "snap-2026-07-31-b5f84004de8a.parquet"
)

PRIMARY_FACTORS = [
    "pullback_volume_ratio",
    "min_volume_ratio",
    "median_range_ratio",
    "quiet_days_n",
    "high_vs_pullback_high",
    "close_vs_pullback_high",
]
CONTROL_FACTORS = [
    "t0_return",
    "t0_gap",
    "t0_close_location",
    "t0_position_20d",
    "t0_gain_retention",
    "low_vs_t0_mid",
    "max_drawdown_from_post_t0_high",
    "days_since_t0",
    "days_to_pullback_low",
    "pullback_duration",
]
ALL_FACTORS = PRIMARY_FACTORS + CONTROL_FACTORS

# ---- pre-registered contract constants ----
STRATUM_MIN_N = 60
STRATUM_MIN_SUCC = 10
STRATUM_MIN_NONSUCC = 10
CONSISTENCY_THRESHOLD = 0.80
MATERIAL_EFFECT = 0.03
NO_SIGNAL_EFFECT = 0.01
REGIME_LOOKBACK = 20
REGIME_MIN_PRIOR = 15
REGIME_MIN_STOCKS = 4000

DIMENSION_FAMILY = {
    "year": "TIME",
    "quarter": "TIME",
    "regime": "REGIME",
    "board": "BOARD",
    "t0_position": "T0TYPE",
    "t0_gap_up": "T0TYPE",
}
FAMILY_PRIORITY = ["TIME", "BOARD", "T0TYPE", "REGIME"]

BOARD_ORDER = ["SH_MAIN", "SZ_MAIN", "SZ_CHINEXT", "SH_STAR", "BSE"]
REGIME_ORDER = ["RISK_ON", "RISK_OFF", "NEUTRAL"]
POSITION_ORDER = ["LOW", "MID", "HIGH"]
GAP_ORDER = ["GAP_UP", "NO_GAP_UP"]


def board_of(symbol: str) -> str:
    """Deterministic symbol-prefix board mapping (contract 3.3)."""
    s = str(symbol)
    if len(s) != 6 or not s.isdigit():
        return "UNMAPPED"
    if s.startswith(("600", "601", "603", "605")):
        return "SH_MAIN"
    if s.startswith(("688", "689")):
        return "SH_STAR"
    if s.startswith(("000", "001", "002", "003")):
        return "SZ_MAIN"
    if s.startswith(("300", "301", "302")):
        return "SZ_CHINEXT"
    if s.startswith("920"):
        return "BSE"
    return "UNMAPPED"


def t0_position_bucket(value: float) -> str | None:
    """Absolute 1/3-2/3 boundaries on the native [0,1] scale (contract 3.4)."""
    if value is None or not np.isfinite(value):
        return None
    if value < 1.0 / 3.0:
        return "LOW"
    if value < 2.0 / 3.0:
        return "MID"
    return "HIGH"


def t0_gap_bucket(value: float) -> str | None:
    """t0_gap > 0 -> GAP_UP else NO_GAP_UP (contract 3.4)."""
    if value is None or not np.isfinite(value):
        return None
    return "GAP_UP" if value > 0.0 else "NO_GAP_UP"


def direction_of(auc: float) -> str:
    if not np.isfinite(auc):
        return "UNKNOWN"
    return "POSITIVE" if auc >= 0.5 else "NEGATIVE"


def build_breadth_series(canonical_parquet: Path) -> pd.DataFrame:
    """Market breadth per session from the canonical snapshot (contract 3.2).

    breadth(s) = share of stocks with pct_change > 0 on session s;
    sessions with fewer than REGIME_MIN_STOCKS rows are dropped (fail closed).
    """
    df = pd.read_parquet(
        canonical_parquet, columns=["trade_date", "pct_change"]
    )
    pc = pd.to_numeric(df["pct_change"], errors="coerce")
    day = pd.to_datetime(df["trade_date"]).dt.date
    g = pd.DataFrame({"day": day, "up": pc.fillna(-1.0) > 0.0})
    agg = g.groupby("day").agg(n=("up", "size"), up=("up", "sum"))
    agg = agg[agg["n"] >= REGIME_MIN_STOCKS].copy()
    agg["breadth"] = agg["up"] / agg["n"]
    return agg


def regime_labels(
    breadth: pd.Series, lookback: int = REGIME_LOOKBACK,
    min_prior: int = REGIME_MIN_PRIOR,
) -> tuple[dict[Any, str], pd.DataFrame]:
    """Regime per session vs median breadth of prior valid sessions.

    Returns (labels, audit_frame) where audit_frame carries breadth and the
    trailing median for every session (NaN median -> DATA_LIMITED).
    """
    med = breadth.shift(1).rolling(lookback, min_periods=min_prior).median()
    labels: dict[Any, str] = {}
    for d in breadth.index:
        m = med.loc[d]
        if not np.isfinite(m):
            labels[d] = "DATA_LIMITED"
        elif breadth.loc[d] > m:
            labels[d] = "RISK_ON"
        elif breadth.loc[d] < m:
            labels[d] = "RISK_OFF"
        else:
            labels[d] = "NEUTRAL"
    audit = pd.DataFrame(
        {"breadth": breadth, "trailing_median": med}
    )
    return labels, audit


def stratum_stats(
    df: pd.DataFrame,
    factor: str,
    known: np.ndarray,
    labels: np.ndarray,
    mask: np.ndarray,
) -> dict[str, Any]:
    values = pd.to_numeric(df[factor], errors="coerce").to_numpy()
    m = (~np.isnan(values)) & known & mask
    n = int(m.sum())
    succ = int(labels[m].sum())
    nonsucc = n - succ
    base: dict[str, Any] = {
        "n": n,
        "success_n": succ,
        "nonsuccess_n": nonsucc,
        "auc": float("nan"),
        "direction": "UNKNOWN",
        "effect": float("nan"),
        "reportable": False,
        "note": "",
    }
    if n == 0:
        base["note"] = "NO_ROWS"
        return base
    if n < STRATUM_MIN_N:
        base["note"] = f"GATE n<{STRATUM_MIN_N}"
        return base
    if succ < STRATUM_MIN_SUCC:
        base["note"] = f"GATE success_n<{STRATUM_MIN_SUCC}"
        return base
    if nonsucc < STRATUM_MIN_NONSUCC:
        base["note"] = f"GATE nonsuccess_n<{STRATUM_MIN_NONSUCC}"
        return base
    auc = r3a.binary_auc(values[m], labels[m])
    base.update(
        {
            "auc": auc,
            "direction": direction_of(auc),
            "effect": abs(auc - 0.5),
            "reportable": True,
        }
    )
    return base


def dimension_strata(
    df: pd.DataFrame,
    factor: str,
    known: np.ndarray,
    labels: np.ndarray,
    dimension: str,
) -> list[dict[str, Any]]:
    """Ordered per-stratum stats for one dimension."""
    rows: list[dict[str, Any]] = []
    if dimension == "year":
        for y in sorted(df["year"].unique()):
            rows.append(
                dict(
                    dimension=dimension,
                    stratum=str(y),
                    **stratum_stats(df, factor, known, labels,
                                    (df["year"] == y).to_numpy()),
                )
            )
    elif dimension == "quarter":
        for q in sorted(df["quarter"].unique()):
            rows.append(
                dict(
                    dimension=dimension,
                    stratum=str(q),
                    **stratum_stats(df, factor, known, labels,
                                    (df["quarter"] == q).to_numpy()),
                )
            )
    elif dimension == "board":
        for b in BOARD_ORDER:
            rows.append(
                dict(
                    dimension=dimension,
                    stratum=b,
                    **stratum_stats(df, factor, known, labels,
                                    (df["board"] == b).to_numpy()),
                )
            )
    elif dimension == "regime":
        for r in REGIME_ORDER:
            rows.append(
                dict(
                    dimension=dimension,
                    stratum=r,
                    **stratum_stats(df, factor, known, labels,
                                    (df["regime"] == r).to_numpy()),
                )
            )
    elif dimension == "t0_position":
        for p in POSITION_ORDER:
            rows.append(
                dict(
                    dimension=dimension,
                    stratum=p,
                    **stratum_stats(df, factor, known, labels,
                                    (df["t0_position"] == p).to_numpy()),
                )
            )
    elif dimension == "t0_gap_up":
        for g in GAP_ORDER:
            rows.append(
                dict(
                    dimension=dimension,
                    stratum=g,
                    **stratum_stats(df, factor, known, labels,
                                    (df["t0_gap_up"] == g).to_numpy()),
                )
            )
    else:
        raise ValueError(f"unknown dimension: {dimension}")
    return rows


def dimension_verdict(
    global_dir: str, strata: list[dict[str, Any]]
) -> tuple[str, float, int, int]:
    """Pre-registered verdict rules (contract 5)."""
    reportable = [s for s in strata if s["reportable"]]
    if len(reportable) < 3:
        return "DATA_LIMITED", float("nan"), 0, 0
    same = sum(1 for s in reportable if s["direction"] == global_dir)
    consistency = same / len(reportable)
    opposite_n = len(reportable) - same
    reversals = [
        s for s in reportable
        if s["direction"] != global_dir and s["effect"] >= MATERIAL_EFFECT
    ]
    if consistency >= CONSISTENCY_THRESHOLD and not reversals:
        return "STABLE", consistency, len(reversals), opposite_n
    if (opposite_n >= 2 and len(reversals) >= 1) or consistency <= 0.50:
        return "UNSTABLE", consistency, len(reversals), opposite_n
    return "MIXED", consistency, len(reversals), opposite_n


def binary_dimension_verdict(
    global_dir: str, strata: list[dict[str, Any]]
) -> tuple[str, float, int, int]:
    """Pre-registered BINARY_DIMENSION_CLAUSE (contract 5 amendment).

    Two-state dimensions (regime, t0_gap_up): verdict only when both states
    are reportable AND both show a directional effect >= MATERIAL_EFFECT.
    """
    reportable = [s for s in strata if s["reportable"]]
    if len(reportable) < 2:
        return "DATA_LIMITED", float("nan"), 0, 0
    directional = [s for s in reportable if s["effect"] >= MATERIAL_EFFECT]
    if len(directional) < 2:
        return "DATA_LIMITED", float("nan"), 0, 0
    same = sum(1 for s in directional if s["direction"] == global_dir)
    consistency = same / len(directional)
    if consistency >= CONSISTENCY_THRESHOLD:
        return "STABLE", consistency, 0, len(directional) - same
    return "UNSTABLE", consistency, 1, len(directional) - same


def overall_verdict(verdicts: dict[str, str]) -> str:
    """Pre-registered overall rule (contract 5)."""
    unstable = [d for d, v in verdicts.items() if v == "UNSTABLE"]
    if unstable:
        return "UNSTABLE"
    mixed = [d for d, v in verdicts.items() if v == "MIXED"]
    if mixed:
        fams = sorted(
            {DIMENSION_FAMILY[d] for d in mixed},
            key=lambda f: FAMILY_PRIORITY.index(f),
        )
        return f"{fams[0]}_DEPENDENT"
    limited = [d for d, v in verdicts.items() if v == "DATA_LIMITED"]
    if limited:
        return "DATA_LIMITED"
    return "STABLE"


def analysis_for_target(
    df: pd.DataFrame, factor: str, target: str
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    """Global stats + per-dimension strata + verdicts for one target."""
    known = (df[target].to_numpy() != "UNKNOWN")
    labels = (df[target].to_numpy() == "SUCCESS").astype(int)
    values = pd.to_numeric(df[factor], errors="coerce").to_numpy()
    m = (~np.isnan(values)) & known
    n = int(m.sum())
    succ = int(labels[m].sum())
    if n == 0 or succ == 0 or succ == n:
        auc = float("nan")
    else:
        auc = r3a.binary_auc(values[m], labels[m])
    global_stats = {
        "factor": factor,
        "target": target,
        "n_known": int(known.sum()),
        "n": n,
        "success_n": succ,
        "auc": auc,
        "direction": direction_of(auc),
        "effect": abs(auc - 0.5) if np.isfinite(auc) else float("nan"),
        "global_signal": (
            "YES" if np.isfinite(auc) and abs(auc - 0.5) >= NO_SIGNAL_EFFECT
            else "NO"
        ),
    }
    strata: list[dict[str, Any]] = []
    verdicts: dict[str, str] = {}
    for dim in DIMENSION_FAMILY:
        dim_rows = dimension_strata(df, factor, known, labels, dim)
        strata.extend(dim_rows)
        if dim in ("regime", "t0_gap_up"):
            verdict, consistency, reversals, opposite = binary_dimension_verdict(
                global_stats["direction"], dim_rows
            )
        else:
            verdict, consistency, reversals, opposite = dimension_verdict(
                global_stats["direction"], dim_rows
            )
        verdicts[dim] = verdict
        for r in dim_rows:
            r["verdict"] = verdict
            r["consistency"] = consistency
            r["material_reversal_n"] = reversals
            r["opposite_n"] = opposite
    return global_stats, strata, verdicts


def main() -> None:
    feat, out = r3a.run_input_gate()
    df = feat.merge(out, on="episode_id", suffixes=("_f", "_o"))
    df = df.drop(columns=[c for c in df.columns if c.endswith("_o")])
    df = df.rename(columns={c: c[:-2] for c in df.columns if c.endswith("_f")})
    print("JOIN_ROWS:", len(df))

    cand = pd.to_datetime(df["candidate_date"]).dt.date
    df["year"] = pd.to_datetime(df["candidate_date"]).dt.year
    df["quarter"] = pd.to_datetime(df["candidate_date"]).dt.to_period("Q").astype(str)
    df["board"] = df["symbol"].map(board_of)
    df["t0_position"] = (
        pd.to_numeric(df["t0_position_20d"], errors="coerce")
        .map(t0_position_bucket)
    )
    df["t0_gap_up"] = (
        pd.to_numeric(df["t0_gap"], errors="coerce").map(t0_gap_bucket)
    )

    # ---- regime (PIT-safe breadth proxy; same canonical snapshot family) ----
    breadth = build_breadth_series(CANONICAL_SNAPSHOT)
    reg_labels, reg_audit = regime_labels(breadth["breadth"])
    reg_by_day = cand.map(reg_labels)
    df["regime"] = reg_by_day.fillna("DATA_LIMITED")
    regime_excluded = int((df["regime"] == "DATA_LIMITED").sum())
    print("REGIME_AUDIT: sessions", len(breadth),
          "| episodes regime DATA_LIMITED:", regime_excluded)

    unmapped = int((df["board"] == "UNMAPPED").sum())
    pos_na = int(df["t0_position"].isna().sum())
    gap_na = int(df["t0_gap_up"].isna().sum())
    print("BOARD_UNMAPPED:", unmapped,
          "| T0_POSITION missing:", pos_na,
          "| T0_GAP missing:", gap_na)

    role = {f: "PRIMARY" if f in PRIMARY_FACTORS else "CONTROL"
            for f in ALL_FACTORS}
    global_rows: list[dict[str, Any]] = []
    strata_rows: list[dict[str, Any]] = []
    verdict_rows: list[dict[str, Any]] = []
    sens_rows: list[dict[str, Any]] = []

    for factor in ALL_FACTORS:
        g3, s3, v3 = analysis_for_target(df, factor, "outcome_3d")
        for r in s3:
            r["factor"] = factor
            r["role"] = role[factor]
        global_rows.append({"role": role[factor], **g3})
        strata_rows.extend(s3)
        for dim in DIMENSION_FAMILY:
            verdict_rows.append(
                {
                    "factor": factor,
                    "role": role[factor],
                    "dimension": dim,
                    "family": DIMENSION_FAMILY[dim],
                    "verdict": v3[dim],
                    "consistency": next(
                        r["consistency"] for r in s3
                        if r["dimension"] == dim
                    ),
                    "material_reversal_n": next(
                        r["material_reversal_n"] for r in s3
                        if r["dimension"] == dim
                    ),
                    "reportable_n": sum(
                        1 for r in s3
                        if r["dimension"] == dim and r["reportable"]
                    ),
                }
            )
        overall = overall_verdict(v3)
        if g3["global_signal"] == "NO":
            overall = "NO_GLOBAL_SIGNAL"
        verdict_rows.append(
            {
                "factor": factor,
                "role": role[factor],
                "dimension": "OVERALL",
                "family": "",
                "verdict": overall,
                "consistency": float("nan"),
                "material_reversal_n": 0,
                "reportable_n": 0,
            }
        )
        if factor in PRIMARY_FACTORS:
            g5, s5, v5 = analysis_for_target(df, factor, "outcome_5d")
            o5 = overall_verdict(v5)
            if g5["global_signal"] == "NO":
                o5 = "NO_GLOBAL_SIGNAL"
            sens_rows.append(
                {
                    "factor": factor,
                    "verdict_3d": overall,
                    "verdict_5d": o5,
                    "auc_3d": g3["auc"],
                    "auc_5d": g5["auc"],
                    "n_5d": g5["n"],
                    "success_n_5d": g5["success_n"],
                    "sens_diff": "DIFF" if o5 != overall else "SAME",
                }
            )

    pd.DataFrame(global_rows).to_csv(OUT_GLOBAL, index=False)
    pd.DataFrame(strata_rows).to_csv(OUT_STRATA, index=False)
    pd.DataFrame(verdict_rows).to_csv(OUT_VERDICTS, index=False)
    pd.DataFrame(sens_rows).to_csv(OUT_SENS, index=False)

    print("\nGLOBAL (3D):")
    print(pd.DataFrame(global_rows).round(4).to_string(index=False))
    print("\nVERDICTS (3D):")
    vd = pd.DataFrame(verdict_rows)
    print(
        vd.pivot_table(
            index=["factor", "role"], columns="dimension",
            values="verdict", aggfunc="first",
        ).to_string()
    )
    print("\nSENSITIVITY (5D, PRIMARY 6):")
    print(pd.DataFrame(sens_rows).round(4).to_string(index=False))
    print("\nOUT:", OUT_GLOBAL)
    print("OUT:", OUT_STRATA)
    print("OUT:", OUT_VERDICTS)
    print("OUT:", OUT_SENS)


if __name__ == "__main__":
    main()
