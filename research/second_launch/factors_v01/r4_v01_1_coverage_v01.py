"""R4 V01.1 — stability coverage extension: availability audit + degenerate
dimension strata (BOARD / T0_TYPE).

Pre-registered contract:
    research/reports/SECOND_LAUNCH_FACTOR_R4_V01_1_COVERAGE_CONTRACT.md
Reuses the R4 V01 input gate, AUC, stratum gates and verdict rules.
Research-only; no R5/R6/R7, no strategy/production/forward/TradePlan changes.
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
import r4_stability_v01 as r4v01  # noqa: E402


OUT_AUDIT = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r4_v01_1_coverage_audit.csv"
)
OUT_BOARD = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r4_v01_1_board_strata.csv"
)
OUT_RESULTS = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r4_v01_1_stability_results.csv"
)

LIMIT_POOL_SNAPSHOT = (
    REPO_ROOT / "data" / "canonical" / "limit_up_pool"
    / "snap-2026-07-31-b5f84004de8a.parquet"
)
# Pinned from data/manifests/snap-2026-07-31-b5f84004de8a.json
# canonical_file_hashes["canonical/limit_up_pool/snap-2026-07-31-b5f84004de8a.parquet"].
EXPECTED_LIMIT_POOL_SHA256 = (
    "45faa1a23583b04acfd6c4faf5ef42311c2575c93a4c702cf5846d0213f31517"
)


def load_canonical_bars_gated(
    path: Path,
    columns: list[str],
    expected_sha: str = r4v01.EXPECTED_FEATURE_SNAPSHOT_SHA256,
    expected_id: str = r4v01.FEATURE_SNAPSHOT_ID,
) -> pd.DataFrame:
    """Immutable gate (SHA + snapshot binding) then read selected columns."""
    if r4v01.sha256_file(path) != expected_sha:
        raise RuntimeError("canonical snapshot SHA mismatch (fail closed)")
    df = pd.read_parquet(
        path, columns=columns + ["dataset_snapshot_id"]
    )
    ids = set(df["dataset_snapshot_id"].astype(str).unique())
    if ids != {expected_id}:
        raise RuntimeError(
            f"snapshot binding mismatch: {sorted(ids)} (fail closed)"
        )
    return df


def t0_type_of(open_: float, high: float, low: float, close: float) -> str:
    """Contract 2.4 geometry on the T0 bar (4-dp rounding for float noise).

    PIT-safe by construction: only the T0 bar is used; no future bars.
    """
    o = round(float(open_), 4)
    h = round(float(high), 4)
    l = round(float(low), 4)
    if h == l:
        return "ONE_PRICE"
    if o == h and l < h:
        return "T_SHAPE"
    return "NORMAL_LIMIT"


def board_composition(symbols: pd.Series) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in symbols.astype(str):
        b = r4v01.board_of(s)
        counts[b] = counts.get(b, 0) + 1
    return counts


def position_decomposition(
    feat: pd.DataFrame,
) -> dict[str, Any]:
    pos = pd.to_numeric(feat["t0_position_20d"], errors="coerce")
    miss = feat["t0_position_20d__missing_reason"]
    nonmissing = pos.notna()
    low_mask = nonmissing & (pos < 1.0 / 3.0)
    return {
        "total_n": int(len(feat)),
        "nonmissing_n": int(nonmissing.sum()),
        "missing_n": int((~nonmissing).sum()),
        "missing_CA_UNKNOWN": int((miss == "CORPORATE_ACTION_UNKNOWN").sum()),
        "missing_CA_EVENT": int((miss == "CORPORATE_ACTION_EVENT").sum()),
        "low_n": int(low_mask.sum()),
        "low_share_of_nonmissing": round(
            low_mask.sum() / max(1, int(nonmissing.sum())), 4
        ),
        "pos_median": float(pos.median()),
        "pos_p75": float(pos.quantile(0.75)),
        "low_anchor_min": str(pd.to_datetime(
            feat.loc[low_mask, "anchor_date"]).min().date()),
        "low_anchor_max": str(pd.to_datetime(
            feat.loc[low_mask, "anchor_date"]).max().date()),
    }


def pool_coverage(
    anchors: pd.DataFrame,
) -> dict[str, Any]:
    if r4v01.sha256_file(LIMIT_POOL_SNAPSHOT) != EXPECTED_LIMIT_POOL_SHA256:
        raise RuntimeError("limit_up_pool snapshot SHA mismatch (fail closed)")
    pool = pd.read_parquet(LIMIT_POOL_SNAPSHOT, columns=["trade_date", "code"])
    d = pd.to_datetime(pool["trade_date"]).dt.date
    pool_dates = set(d.unique())
    anchors_dates = set(pd.to_datetime(anchors["anchor_date"]).dt.date.unique())
    overlap = len(anchors_dates & pool_dates)
    return {
        "pool_rows": int(len(pool)),
        "pool_min_date": str(min(pool_dates)),
        "pool_max_date": str(max(pool_dates)),
        "pool_days": len(pool_dates),
        "pool_prefixes": (
            pool["code"].astype(str).str[:3].value_counts().to_dict()
        ),
        "cohort_anchor_days_inside_pool_window": overlap,
        "pool_sha256": EXPECTED_LIMIT_POOL_SHA256,
    }


# STRICT-REGIME availability is PRE-FLIGHT EVIDENCE only (frozen once on
# 2026-08-08 before any V01.1 calculation; see contract section 2.2):
#   search roots: data/canonical, data/raw/akshare, data/raw/baostock,
#     data/raw/tushare, data/outcome-study, data/manifests, research/, src/
#   identifiers: filenames *index* / *000001* / *000300*; code-pattern scan
#     ('.' separators, sh./sz. prefixes) over raw daily-bar parquet code
#     columns; text terms 上证指数 / index close / hs300 over research/ and src/
#   RESULT: no eligible PIT-safe market-index artifact found
# => STRICT_REGIME = UNAVAILABLE. This is NOT a runtime dependency: reruns
#    must not change results when repository files change.

# NOTE: legacy raw provider artifacts (tushare/akshare/baostock) may exist in
# the repository, but are EXCLUDED from the R4 V01.1 executable/statistical
# lineage. The only non-frozen-cohort artifact read by this script is the
# hash-pinned canonical limit_up_pool (manifest SHA 45faa1a2...).


def build_t0_types(
    feat: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """Deterministic T0-type classification from the frozen canonical bars."""
    bars = load_canonical_bars_gated(
        r4v01.CANONICAL_SNAPSHOT, ["code", "trade_date", "open", "high", "low", "close"]
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
    for c in ["open", "high", "low", "close"]:
        bars[c] = pd.to_numeric(bars[c], errors="coerce")
    episodes = pd.DataFrame({
        "code": feat["symbol"].astype(str),
        "trade_date": pd.to_datetime(feat["anchor_date"]).dt.date,
        "episode_id": feat["episode_id"],
        "t0_ca": feat["t0_return__missing_reason"].notna(),
    })
    out = classify_episode_t0_types(episodes, bars)
    return out, int((out["t0_type"] == "CA_EXCLUDED").sum())


def classify_episode_t0_types(
    episodes: pd.DataFrame, bars: pd.DataFrame
) -> pd.DataFrame:
    """Classify T0-bar geometry per episode (contract 2.4).

    PIT-safe by construction: the join key is (code, anchor_date) only, so a
    later bar of the same code can never enter the classification.
    """
    merged = episodes.merge(
        bars[["code", "trade_date", "open", "high", "low", "close"]],
        on=["code", "trade_date"],
        how="left",
    )
    rows = []
    for _, r in merged.iterrows():
        if bool(r["t0_ca"]):
            t = "CA_EXCLUDED"
        elif (
            pd.isna(r["open"]) or pd.isna(r["high"])
            or pd.isna(r["low"]) or pd.isna(r["close"])
        ):
            t = "MISSING_T0_BAR"
        else:
            t = t0_type_of(r["open"], r["high"], r["low"], r["close"])
        rows.append({"episode_id": r["episode_id"], "t0_type": t})
    return pd.DataFrame(rows)


def primary_strata(df: pd.DataFrame, factor: str, strata_col: str,
                   stratum_names: list[str]) -> list[dict[str, Any]]:
    known = df["outcome_3d"].to_numpy() != "UNKNOWN"
    labels = (df["outcome_3d"].to_numpy() == "SUCCESS").astype(int)
    rows = []
    for name in stratum_names:
        st = r4v01.stratum_stats(
            df, factor, known, labels,
            (df[strata_col] == name).to_numpy(),
        )
        rows.append({"stratum": name, **st})
    return rows


def build_audit_rows(
    feat: pd.DataFrame,
    boards: dict[str, int],
    low: dict[str, Any],
    pool: dict[str, Any],
    t0_dist: dict[str, Any],
    n_ca: int,
) -> pd.DataFrame:
    """Availability audit table (frozen evidence, no runtime repo scans)."""
    anchor = pd.to_datetime(feat["anchor_date"]).dt.date
    sh = boards.get("SH_MAIN", 0)
    sz = boards.get("SZ_MAIN", 0)
    other = sum(v for k, v in boards.items() if k not in ("SH_MAIN", "SZ_MAIN"))
    rows = [
        {
            "target": "BOARD",
            "status": "DATA_LIMITED",
            "artifact": "frozen feature cohort",
            "artifact_sha256": r3a.EXPECTED_FEATURE_SHA256,
            "date_coverage": f"{anchor.min()}..{anchor.max()}",
            "episode_coverage": (
                f"SH_MAIN {sh} / SZ_MAIN {sz} / other {other}"
            ),
            "pit_status": "n/a (cohort property)",
            "missing_reason": (
                "frozen cohort 100% 10% limit main-board; extension requires "
                "frozen cohort change (forbidden); hash-pinned canonical "
                "limit_up_pool (SHA 45faa1a2...) kept as separate coverage "
                "supporting evidence only"
            ),
        },
        {
            "target": "STRICT_REGIME",
            "status": "UNAVAILABLE",
            "artifact": "none found (pre-flight evidence, not runtime scan)",
            "artifact_sha256": "",
            "date_coverage": "",
            "episode_coverage": "",
            "pit_status": "formula pre-registered (000001.SH close vs MA60, PIT)",
            "missing_reason": (
                "pre-flight bounded inspection (roots: data/canonical, "
                "data/raw/akshare|baostock|tushare, data/outcome-study, "
                "data/manifests, research/, src/; identifiers: *index*, "
                "*000001*, *000300*, sh./sz. code patterns, 上证指数/index "
                "close/hs300 terms): no eligible PIT-safe index artifact; "
                "temp fetch forbidden"
            ),
        },
        {
            "target": "LOW_POSITION",
            "status": "DATA_LIMITED",
            "artifact": "frozen feature CSV t0_position_20d",
            "artifact_sha256": r3a.EXPECTED_FEATURE_SHA256,
            "date_coverage": (
                f"{low['low_anchor_min']}..{low['low_anchor_max']}"
            ),
            "episode_coverage": (
                f"LOW {low['low_n']} / nonmissing {low['nonmissing_n']} "
                f"({low['low_share_of_nonmissing']}); missing "
                f"{low['missing_n']} = CA_UNKNOWN {low['missing_CA_UNKNOWN']} "
                f"+ CA_EVENT {low['missing_CA_EVENT']}"
            ),
            "pit_status": "PIT-safe (frozen feature)",
            "missing_reason": "natural rarity + CA missing; no extra frozen cohort",
        },
        {
            "target": "T0_TYPE_GEOMETRY",
            "status": "DATA_LIMITED",
            "artifact": "frozen canonical daily_bars b5f84004de8a (T0 bars)",
            "artifact_sha256": r4v01.EXPECTED_FEATURE_SNAPSHOT_SHA256,
            "date_coverage": f"{anchor.min()}..{anchor.max()} (anchor dates)",
            "episode_coverage": f"{t0_dist} (CA_EXCLUDED {n_ca})",
            "pit_status": "PIT-safe (T0 bar only, PRICE_ONLY geometry)",
            "missing_reason": (
                "degenerate cohort: 0 ONE_PRICE / 0 T_SHAPE; "
                "NORMAL_LIMIT only"
            ),
        },
        {
            "target": "FIRST_BOARD_MULTI_BOARD",
            "status": "UNAVAILABLE",
            "artifact": "canonical limit_up_pool b5f84004de8a",
            "artifact_sha256": EXPECTED_LIMIT_POOL_SHA256,
            "date_coverage": (
                f"{pool['pool_min_date']}..{pool['pool_max_date']} "
                f"({pool['pool_days']} days)"
            ),
            "episode_coverage": (
                f"cohort anchor days inside pool window: "
                f"{pool['cohort_anchor_days_inside_pool_window']}"
            ),
            "pit_status": "PIT-safe only inside pool window",
            "missing_reason": (
                "frozen rule forbids price-inferred consecutive count; "
                "pool consecutive_count covers 15 days only"
            ),
        },
    ]
    return pd.DataFrame(rows)


def main() -> None:
    feat, out = r3a.run_input_gate()
    df = feat.merge(out, on="episode_id", suffixes=("_f", "_o"))
    df = df.drop(columns=[c for c in df.columns if c.endswith("_o")])
    df = df.rename(columns={c: c[:-2] for c in df.columns if c.endswith("_f")})
    print("JOIN_ROWS:", len(df))

    # ---- coverage audit ----
    boards = board_composition(feat["symbol"])
    low = position_decomposition(feat)
    pool = pool_coverage(feat)
    t0types, n_ca = build_t0_types(feat)
    feat2 = feat.merge(t0types, on="episode_id", validate="1:1")
    t0_dist = feat2["t0_type"].value_counts().to_dict()

    audit_df = build_audit_rows(feat, boards, low, pool, t0_dist, n_ca)
    audit_df.to_csv(OUT_AUDIT, index=False)
    print("AUDIT:")
    print(audit_df[
        ["target", "status", "episode_coverage"]
    ].to_string(index=False))

    # ---- degenerate dimension strata (PRIMARY 6, 3D) ----
    df2 = df.merge(t0types, on="episode_id", validate="1:1")
    df2["board"] = df2["symbol"].map(r4v01.board_of)
    primary = r4v01.PRIMARY_FACTORS
    known = df2["outcome_3d"].to_numpy() != "UNKNOWN"
    labels = (df2["outcome_3d"].to_numpy() == "SUCCESS").astype(int)
    board_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    for factor in primary:
        g3 = r4v01.stratum_stats(
            df2, factor, known, labels, np.ones(len(df2), dtype=bool)
        )
        global_dir = g3["direction"]
        # board (2 reportable at most -> DATA_LIMITED per >=3 rule)
        bstrata = primary_strata(
            df2, factor, "board", ["SH_MAIN", "SZ_MAIN"]
        )
        bverdict, bcons, brev, bopp = r4v01.dimension_verdict(
            global_dir, bstrata
        )
        for s in bstrata:
            board_rows.append({
                "factor": factor, "stratum": s["stratum"],
                "n": s["n"], "success_n": s["success_n"],
                "auc": s["auc"], "direction": s["direction"],
                "effect": s["effect"], "reportable": s["reportable"],
                "note": s["note"], "verdict": bverdict,
            })
        # t0_type (single category -> DATA_LIMITED)
        tstrata = primary_strata(
            df2, factor, "t0_type", ["NORMAL_LIMIT"]
        )
        tverdict, _, _, _ = r4v01.dimension_verdict(global_dir, tstrata)
        for s in tstrata:
            result_rows.append({
                "factor": factor, "dimension": "t0_type",
                "stratum": s["stratum"], "n": s["n"],
                "success_n": s["success_n"], "auc": s["auc"],
                "direction": s["direction"], "reportable": s["reportable"],
                "note": s["note"], "verdict": tverdict,
            })
        result_rows.append({
            "factor": factor, "dimension": "overall",
            "stratum": "", "n": g3["n"], "success_n": g3["success_n"],
            "auc": g3["auc"], "direction": global_dir,
            "reportable": True, "note": "no READY dims in V01.1",
            "verdict": "DATA_LIMITED",
        })

    pd.DataFrame(board_rows).to_csv(OUT_BOARD, index=False)
    pd.DataFrame(result_rows).to_csv(OUT_RESULTS, index=False)
    print("\nBOARD STRATA (descriptive; verdict DATA_LIMITED by >=3 rule):")
    print(pd.DataFrame(board_rows).round(4).to_string(index=False))
    print("\nT0_TYPE STRATA:")
    print(pd.DataFrame(result_rows).round(4).to_string(index=False))
    print("\nOUT:", OUT_AUDIT)
    print("OUT:", OUT_BOARD)
    print("OUT:", OUT_RESULTS)


if __name__ == "__main__":
    main()
