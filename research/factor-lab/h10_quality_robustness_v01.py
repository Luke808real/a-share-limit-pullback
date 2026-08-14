"""H10: quality>=80 cohort effect robustness across timing strata (v01).

Frozen baseline (Phase 2D.0/2D.1A): actionable setup_quality>=80 strict E[R]
+0.0257, entry_quality>=80 +0.0769; T+1 10bp entry>=80 +0.2605. H10 asks
whether the effect persists within morphological subgroups. Here morphology
is stratified by days_since_anchor (the strongest available stratification),
plus setup_stage. Pure parquet, no bars, no threshold tuning.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb

EPISODES = Path(
    "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    "/corrected-b2-trigger-outcome/episodes.parquet"
)
EXPECTED_SHA = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
OUT_DIR = Path("research/factor-lab/runs/h10-v01")
GROUPS = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")


def _bucket(days: int) -> str:
    if days <= 2:
        return "1-2"
    if days <= 3:
        return "3"
    if days <= 5:
        return "4-5"
    return "6-10"


def _win_share(rows) -> tuple[int, float | None]:
    n = len(rows)
    if n < 20:
        return n, None
    wins = sum(1 for r in rows if r[2] == "WIN_S1")
    return n, round(wins / n, 4)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(EPISODES.read_bytes()).hexdigest()
    if sha != EXPECTED_SHA:
        raise SystemExit(f"hash mismatch: {sha}")
    con = duckdb.connect()
    rows = con.execute(
        "SELECT days_since_anchor, setup_stage, outcome, setup_quality_score, "
        "entry_quality_score FROM read_parquet(?) WHERE outcome IS NOT NULL",
        [str(EPISODES)],
    ).fetchall()
    resolved = [
        (int(r[0]), r[1], r[2], r[3], r[4])
        for r in rows
        if r[2] in GROUPS
    ]

    def q80(value) -> bool:
        if value is None:
            return False
        try:
            return float(value) >= 80.0
        except (TypeError, ValueError):
            return False

    # overall echo of the frozen baseline
    overall_setup = _win_share([r for r in resolved if q80(r[3])])
    overall_entry = _win_share([r for r in resolved if q80(r[4])])
    overall_all = _win_share(resolved)

    # by timing bucket x setup quality
    by_bucket: dict[str, dict] = {}
    for r in resolved:
        b = _bucket(r[0])
        d = by_bucket.setdefault(b, {"all": [], "setup_ge80": [], "entry_ge80": []})
        d["all"].append(r)
        if q80(r[3]):
            d["setup_ge80"].append(r)
        if q80(r[4]):
            d["entry_ge80"].append(r)

    bucket_stats: dict[str, dict] = {}
    for b in sorted(by_bucket):
        d = by_bucket[b]
        bucket_stats[b] = {
            "all_n": len(d["all"]),
            "all_win": _win_share(d["all"])[1],
            "setup_ge80_n": len(d["setup_ge80"]),
            "setup_ge80_win": _win_share(d["setup_ge80"])[1],
            "entry_ge80_n": len(d["entry_ge80"]),
            "entry_ge80_win": _win_share(d["entry_ge80"])[1],
        }

    payload = {
        "inputs": {"episodes": str(EPISODES), "sha256": sha},
        "overall": {
            "all": overall_all,
            "setup_ge80": overall_setup,
            "entry_ge80": overall_entry,
        },
        "by_timing_bucket": bucket_stats,
    }
    out = OUT_DIR / "h10-v01.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
