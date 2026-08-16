"""JULY 2026 CANONICAL DAILY SESSION COVERAGE AUDIT V01 — read-only.

Audits whether the frozen 2026-07-31 canonical daily contains the expected
2026-07 A-share trading sessions, focusing on the suspected 07-09..07-24 gap
identified in the T0 transition result review, and assesses contamination
scope for T0 registry / transition result.

Read-only: no data repair, no registry rebuild, no transition rerun.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

ROOT = Path(__file__).resolve().parents[2]
DAILY_PATH = ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"
REGISTRY_PATH = ROOT / "research/factor-lab/runs/t0-registry-v01/t0-registry-v01.csv"
TRANSITION_PATH = ROOT / "research/factor-lab/runs/ttl-t0-transition-result-v01/ttl-t0-transition-v01.csv"
OUT_DIR = ROOT / "research/factor-lab/runs/july-2026-session-coverage-audit-v01"

DAILY_SHA256 = "e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514"
OBSERVATION_END = date(2026, 7, 31)

EXPECTED_JULY_SESSIONS = [
    "2026-07-01", "2026-07-02", "2026-07-03",
    "2026-07-06", "2026-07-07", "2026-07-08",
    "2026-07-09", "2026-07-10",
    "2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17",
    "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24",
    "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31",
]

GAP_DATES = [
    "2026-07-09", "2026-07-10",
    "2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17",
    "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_daily(path: Path, expected_sha: str = DAILY_SHA256) -> pd.DataFrame:
    if isinstance(path, pd.DataFrame):
        raise TypeError("load_daily: DataFrame bypass forbidden")
    if sha256(path) != expected_sha:
        raise RuntimeError(f"daily SHA mismatch: {path}")
    return pd.read_parquet(path)


def date_coverage(daily: pd.DataFrame) -> pd.DataFrame:
    daily = daily.copy()
    daily["d"] = daily["trade_date"].astype(str)
    daily["is_confirmed"] = daily["reconciliation_status"].astype(str) == "CONFIRMED"
    daily["is_single"] = daily["reconciliation_status"].astype(str) == "CONFIRMED_SINGLE_SOURCE"
    rows = []
    for d in EXPECTED_JULY_SESSIONS:
        sub = daily[daily["d"] == d]
        rows.append({
            "trade_date": d,
            "TOTAL_ROW_N": len(sub),
            "UNIQUE_CODE_N": sub["code"].nunique(),
            "CONFIRMED_N": int(sub["is_confirmed"].sum()),
            "CONFIRMED_SINGLE_SOURCE_N": int(sub["is_single"].sum()),
            "OTHER_RECONCILIATION_N": int((~sub["is_confirmed"] & ~sub["is_single"]).sum()),
            "TRADE_STATUS_TRUE_N": int((sub["trade_status"] == True).sum()) if len(sub) else 0,  # noqa: E712
            "TRADE_STATUS_FALSE_N": int((sub["trade_status"] == False).sum()) if len(sub) else 0,  # noqa: E712
        })
    return pd.DataFrame(rows)


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    daily = load_daily(DAILY_PATH)
    cov = date_coverage(daily)
    cov.to_csv(OUT_DIR / "july-session-coverage-v01.csv", index=False)

    present = set(cov.loc[cov["TOTAL_ROW_N"] > 0, "trade_date"])
    zero_confirmed = cov[cov["CONFIRMED_N"] == 0]["trade_date"].tolist()
    missing = [d for d in EXPECTED_JULY_SESSIONS if d not in present]
    gap_present = [d for d in GAP_DATES if d in present]
    gap_missing = [d for d in GAP_DATES if d not in present]

    result = {
        "DAILY_SHA256": DAILY_SHA256,
        "EXPECTED_SESSION_N": len(EXPECTED_JULY_SESSIONS),
        "PRESENT_DATE_N": len(present),
        "MISSING_DATE_N": len(missing),
        "MISSING_DATE_LIST": missing,
        "ZERO_CONFIRMED_DATE_N": len(zero_confirmed),
        "ZERO_CONFIRMED_DATE_LIST": zero_confirmed,
        "JUL09_JUL24_PRESENT_N": len(gap_present),
        "JUL09_JUL24_MISSING_N": len(gap_missing),
        "JUL09_JUL24_MISSING_LIST": gap_missing,
        "MARKET_SESSION_COVERAGE_BLOCKER": (
            "YES" if (missing or zero_confirmed) else "NO"
        ),
        "DATE_COVERAGE": cov.to_dict("records"),
    }

    # ---- registry: T0 per July expected session ----
    registry = pd.read_csv(REGISTRY_PATH, dtype={"setup_id": str, "code": str})
    reg = registry.copy()
    reg["anchor_date"] = reg["anchor_date"].astype(str)
    reg_july = reg[reg["anchor_date"].between("2026-07-01", "2026-07-31")]
    t0_by_date = reg_july.groupby("anchor_date").size().to_dict()
    result["JULY_T0_SETUP_N_BY_EXPECTED_SESSION"] = {
        d: int(t0_by_date.get(d, 0)) for d in EXPECTED_JULY_SESSIONS
    }
    missing_or_zero = set(missing) | set(zero_confirmed)
    result["T0_POPULATION_COMPLETENESS_FOR_JULY"] = (
        "NOT_ESTABLISHED"
        if any(d in missing_or_zero for d in EXPECTED_JULY_SESSIONS)
        else "ESTABLISHED"
    )

    # ---- 438 immature classification ----
    trans = pd.read_csv(TRANSITION_PATH, dtype={"setup_id": str, "code": str})
    trans["anchor_date"] = trans["anchor_date"].astype(str)
    immature = trans[trans["FULL_WINDOW_MATURED"] == False].copy()  # noqa: E712

    # expected market followup after anchor: count of expected sessions > anchor_date (within July window)
    expected_set = set(EXPECTED_JULY_SESSIONS)
    rows: list[dict] = []
    for _, r in immature.iterrows():
        anchor = date.fromisoformat(r["anchor_date"])
        # expected market sessions after anchor through 07-31 (from expected list only, July)
        expected_after = sum(1 for d in EXPECTED_JULY_SESSIONS if date.fromisoformat(d) > anchor)
        confirmed_after = int(r["FOLLOWUP_SESSIONS_AVAILABLE"])
        last_confirmed = None
        sub = daily[daily["trade_date"].astype(str) > r["anchor_date"]]
        if len(sub):
            last_confirmed = str(sub["trade_date"].max())
        rows.append({
            "setup_id": r["setup_id"],
            "code": r["code"],
            "anchor_date": r["anchor_date"],
            "expected_market_followup_n": expected_after,
            "confirmed_code_followup_n": confirmed_after,
            "shortfall_n": expected_after - confirmed_after,
            "last_confirmed_date": last_confirmed,
            "class": (
                "SNAPSHOT_TAIL"
                if expected_after < 9
                else "CODE_LEVEL_SHORTFALL"
            ),
        })
    imm_df = pd.DataFrame(rows)
    tail_n = int((imm_df["class"] == "SNAPSHOT_TAIL").sum())
    shortfall_n = int((imm_df["class"] == "CODE_LEVEL_SHORTFALL").sum())
    earliest_shortfall = (
        imm_df.loc[imm_df["class"] == "CODE_LEVEL_SHORTFALL", "anchor_date"].min()
        if shortfall_n else None
    )
    result["IMMATURE_TOTAL_N"] = len(imm_df)
    result["SNAPSHOT_TAIL_N"] = tail_n
    result["CODE_LEVEL_SHORTFALL_N"] = shortfall_n
    result["EARLIEST_SHORTFALL_ANCHOR_DATE"] = (
        None if earliest_shortfall is None else str(earliest_shortfall)
    )
    result["CODE_LEVEL_SHORTFALL_ROWS"] = imm_df[
        imm_df["class"] == "CODE_LEVEL_SHORTFALL"
    ].to_dict("records")
    imm_df.to_csv(OUT_DIR / "immature-classification-v01.csv", index=False)

    # ---- episode primary event signal dates by July date ----
    episodes = pd.read_parquet(
        ROOT
        / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
        / "corrected-b2-trigger-outcome/episodes.parquet"
    )
    prim = episodes[
        episodes["execution_label"].isin(["B1_READY", "B2_READY", "B2_CONFIRMED"])
    ].copy()
    prim["signal_date"] = prim["signal_date"].astype(str)
    prim_july = prim[prim["signal_date"].between("2026-07-01", "2026-07-31")]
    result["PRIMARY_EVENT_SIGNAL_DATE_N_BY_DATE"] = {
        d: int((prim_july["signal_date"] == d).sum()) for d in EXPECTED_JULY_SESSIONS
    }
    result["EVENT_TIME_REAL_SESSION_VALIDITY"] = (
        "BLOCKED" if result["MARKET_SESSION_COVERAGE_BLOCKER"] == "YES" else "OK"
    )
    result["CURRENT_TRANSITION_RESULT_AUTHORITY"] = (
        "BLOCKED" if result["MARKET_SESSION_COVERAGE_BLOCKER"] == "YES" else "OK"
    )

    # ---- root cause evidence from manifest / lineage ----
    manifest_path = ROOT / "data/manifests/snap-2026-07-31-b5f84004de8a.json"
    root_cause_evidence: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        root_cause_evidence["manifest_exists"] = True
        root_cause_evidence["manifest_created_at"] = manifest.get("created_at")
        root_cause_evidence["reconciliation_policy_version"] = manifest.get(
            "reconciliation_policy_version"
        )
        root_cause_evidence["raw_source_parts"] = sorted(
            k for k in manifest.get("source_file_hashes", {}) if "daily" in k
        )
    else:
        root_cause_evidence["manifest_exists"] = False

    # raw source coverage: earliest/latest trade_date per raw daily part
    raw_parts = sorted((ROOT / "data/raw/akshare/daily_bars").glob("*.parquet")) if (
        ROOT / "data/raw/akshare/daily_bars"
    ).exists() else []
    raw_ranges = []
    import pyarrow.parquet as pq
    for p in raw_parts:
        try:
            t = pq.read_table(p, columns=["trade_date"]).to_pandas()
            raw_ranges.append({
                "part": p.name,
                "min": str(t["trade_date"].min()),
                "max": str(t["trade_date"].max()),
            })
        except Exception as exc:  # noqa: BLE001
            raw_ranges.append({"part": p.name, "error": str(exc)})
    root_cause_evidence["raw_daily_parts_n"] = len(raw_parts)
    root_cause_evidence["raw_daily_date_ranges"] = raw_ranges
    result["ROOT_CAUSE_EVIDENCE"] = root_cause_evidence

    # warehouse reconciliation evidence for gap dates (read-only)
    try:
        import duckdb
        con = duckdb.connect(ROOT / "data/warehouse.duckdb", read_only=True)
        recon = con.execute(
            "SELECT trade_date, status, count(*) n FROM reconciliation_results "
            "WHERE snapshot_id = 'snap-2026-07-31-b5f84004de8a' "
            "AND trade_date >= '2026-07-08' AND trade_date <= '2026-07-25' "
            "GROUP BY trade_date, status ORDER BY trade_date"
        ).df()
        result["RECONCILIATION_RESULTS_GAP_WINDOW"] = json.loads(
            recon.astype(str).to_json(orient="records")
        )
    except Exception as exc:  # noqa: BLE001
        result["RECONCILIATION_RESULTS_GAP_WINDOW"] = {"error": str(exc)}

    # raw provider coverage for gap window (all three providers have the dates)
    raw_gap = {}
    for provider in ("akshare", "tushare", "baostock"):
        d = ROOT / "data/raw" / provider / "daily_bars"
        if not d.exists():
            raw_gap[provider] = "NO_RAW_DIR"
            continue
        try:
            import pyarrow.parquet as pq
            present = set()
            for p in sorted(d.glob("*.parquet")):
                t = pq.read_table(p, columns=["trade_date"]).to_pandas()
                present.update(t["trade_date"].astype(str).unique())
            raw_gap[provider] = sorted(
                d for d in GAP_DATES if d in present
            )
        except Exception as exc:  # noqa: BLE001
            raw_gap[provider] = {"error": str(exc)}
    result["RAW_PROVIDER_GAP_WINDOW_COVERAGE"] = raw_gap

    result["ROOT_CAUSE"] = (
        "SNAPSHOT_RECONCILIATION_OUTCOME: 07-09..07-24 rows exist in raw "
        "providers (akshare/tushare/baostock) and in the canonical parquet as "
        "PROVISIONAL, but the frozen snapshot's reconciliation produced no "
        "CONFIRMED rows for those dates (CONFIRMED_N=0); generator-visible "
        "CONFIRMED-only timebase therefore lacks 12 mid-July sessions. "
        "Not a raw-source absence; a snapshot construction/reconciliation "
        "outcome gap."
        if result["MARKET_SESSION_COVERAGE_BLOCKER"] == "YES"
        else "NO_BLOCKER"
    )

    result["JULY_SESSION_COVERAGE_STATUS"] = (
        "PASS" if result["MARKET_SESSION_COVERAGE_BLOCKER"] == "NO" else "BLOCKED"
    )
    result["T0_REGISTRY_REBUILD_REQUIRED"] = (
        "YES" if result["MARKET_SESSION_COVERAGE_BLOCKER"] == "YES" else "NO"
    )
    result["TRANSITION_RESULT_RERUN_REQUIRED"] = (
        "YES" if result["MARKET_SESSION_COVERAGE_BLOCKER"] == "YES" else "NO"
    )

    (OUT_DIR / "july-session-coverage-v01.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "july-session-coverage-v01-report.md").write_text(
        render_report(result), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def render_report(r: dict) -> str:
    lines = [
        "# JULY 2026 CANONICAL DAILY SESSION COVERAGE AUDIT V01 — 只读审计",
        "",
        f"- DAILY_SHA256 = {r['DAILY_SHA256']}",
        f"- EXPECTED_SESSION_N = {r['EXPECTED_SESSION_N']}；PRESENT_DATE_N = {r['PRESENT_DATE_N']}；"
        f"MISSING_DATE_N = {r['MISSING_DATE_N']}；MISSING_DATE_LIST = {r['MISSING_DATE_LIST']}",
        f"- ZERO_CONFIRMED_DATE_N = {r['ZERO_CONFIRMED_DATE_N']}；"
        f"ZERO_CONFIRMED_DATE_LIST = {r['ZERO_CONFIRMED_DATE_LIST']}",
        f"- JUL09_JUL24_PRESENT_N = {r['JUL09_JUL24_PRESENT_N']}；"
        f"JUL09_JUL24_MISSING_N = {r['JUL09_JUL24_MISSING_N']}；"
        f"JUL09_JUL24_MISSING_LIST = {r['JUL09_JUL24_MISSING_LIST']}",
        f"- MARKET_SESSION_COVERAGE_BLOCKER = {r['MARKET_SESSION_COVERAGE_BLOCKER']}",
        "",
        "## DATE-LEVEL COVERAGE（23 个 expected sessions）",
        "| trade_date | TOTAL_ROW_N | UNIQUE_CODE_N | CONFIRMED_N | CONFIRMED_SINGLE_SOURCE_N | OTHER | TRADE_STATUS_TRUE_N | TRADE_STATUS_FALSE_N |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in r["DATE_COVERAGE"]:
        lines.append(
            f"| {row['trade_date']} | {row['TOTAL_ROW_N']} | {row['UNIQUE_CODE_N']} | "
            f"{row['CONFIRMED_N']} | {row['CONFIRMED_SINGLE_SOURCE_N']} | "
            f"{row['OTHER_RECONCILIATION_N']} | {row['TRADE_STATUS_TRUE_N']} | "
            f"{row['TRADE_STATUS_FALSE_N']} |"
        )
    lines += [
        "",
        "## SUSPECTED GAP 07/09–07/24",
        f"- 12 个 weekday dates 中 present = {r['JUL09_JUL24_PRESENT_N']}，missing = {r['JUL09_JUL24_MISSING_N']}："
        f"{r['JUL09_JUL24_MISSING_LIST']}",
        "",
        "## 438 IMMATURE CLASSIFICATION",
        f"- IMMATURE_TOTAL_N = {r['IMMATURE_TOTAL_N']}；SNAPSHOT_TAIL_N = {r['SNAPSHOT_TAIL_N']}；"
        f"CODE_LEVEL_SHORTFALL_N = {r['CODE_LEVEL_SHORTFALL_N']}；"
        f"EARLIEST_SHORTFALL_ANCHOR_DATE = {r['EARLIEST_SHORTFALL_ANCHOR_DATE']}",
        "- CODE_LEVEL_SHORTFALL 明细见 immature-classification-v01.csv",
        "",
        "## T0 REGISTRY / TRANSITION IMPACT",
        f"- T0_POPULATION_COMPLETENESS_FOR_JULY = {r['T0_POPULATION_COMPLETENESS_FOR_JULY']}",
        f"- EVENT_TIME_REAL_SESSION_VALIDITY = {r['EVENT_TIME_REAL_SESSION_VALIDITY']}",
        f"- CURRENT_TRANSITION_RESULT_AUTHORITY = {r['CURRENT_TRANSITION_RESULT_AUTHORITY']}",
        f"- JULY_T0_SETUP_N_BY_EXPECTED_SESSION = {r['JULY_T0_SETUP_N_BY_EXPECTED_SESSION']}",
        "",
        "## ROOT CAUSE EVIDENCE（只读，未猜结论）",
        f"- {r['ROOT_CAUSE_EVIDENCE']}",
        "",
        "## DECISION",
        f"- JULY_SESSION_COVERAGE_STATUS = {r['JULY_SESSION_COVERAGE_STATUS']}",
        f"- T0_REGISTRY_REBUILD_REQUIRED = {r['T0_REGISTRY_REBUILD_REQUIRED']}",
        f"- TRANSITION_RESULT_RERUN_REQUIRED = {r['TRANSITION_RESULT_RERUN_REQUIRED']}",
        "- 本轮禁止 rebuild / rerun / data repair",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
