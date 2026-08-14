"""H10 v01 (audit-fix): quality>=80 vs <80 comparator on score-DEFINED
samples only, with missing scores reported separately; robustness strata
by timing bucket and setup_stage.

AUDIT FIX (ChatGPT research-QC): the v01 draft compared ge80 against the
full resolved population (including score-missing rows) and called that a
factor effect. This version partitions score-defined rows into mutually
exclusive ge80 / lt80 strata, reports missing_n apart, keeps the overall
win share only as background, and adds a minimal by_setup_stage stratum.
Pure parquet, no bars, no threshold tuning, no promotion.
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
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
OUT_DIR = Path("research/factor-lab/runs/h10-v01")
GROUPS = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")
WIN = "WIN_S1"
MIN_N = 20


def parse_score(value) -> float | None:
    """Parse a score cell; None means missing (NULL or unparseable)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _win_share(n: int, wins: int, min_n: int = MIN_N) -> float | None:
    if n < min_n:
        return None
    return round(wins / n, 4)


def score_strata(rows, min_n: int = MIN_N) -> dict:
    """Partition (outcome, parsed_score_or_None) rows.

    ge80 / lt80 are mutually exclusive strata over score-DEFINED rows only;
    missing scores are counted separately and never enter either stratum.
    Win shares (and the delta) are None when a stratum has fewer than min_n
    rows, so small cells are not interpreted.
    """
    rows = list(rows)
    missing_n = sum(1 for _, s in rows if s is None)
    ge80 = [(o, s) for o, s in rows if s is not None and s >= 80.0]
    lt80 = [(o, s) for o, s in rows if s is not None and s < 80.0]
    ge80_n = len(ge80)
    lt80_n = len(lt80)
    ge80_win = _win_share(ge80_n, sum(1 for o, _ in ge80 if o == WIN), min_n)
    lt80_win = _win_share(lt80_n, sum(1 for o, _ in lt80 if o == WIN), min_n)
    delta = None
    if ge80_win is not None and lt80_win is not None:
        delta = round(ge80_win - lt80_win, 4)
    return {
        "defined_n": ge80_n + lt80_n,
        "missing_n": missing_n,
        "ge80_n": ge80_n,
        "ge80_win": ge80_win,
        "lt80_n": lt80_n,
        "lt80_win": lt80_win,
        "delta_ge80_vs_lt80": delta,
    }


def stage_strata(rows, min_n: int = MIN_N) -> dict:
    """Minimal by_setup_stage robustness strata.

    rows: (setup_stage, outcome, parsed_setup_score_or_None).
    Per stage: all_n / all_win (background), score-defined n, setup ge80 vs
    lt80 win shares and delta. Cells with fewer than min_n rows are None.
    """
    by_stage: dict[str, list] = {}
    for stage, outcome, score in rows:
        by_stage.setdefault(stage, []).append((outcome, score))
    out: dict[str, dict] = {}
    for stage in sorted(by_stage):
        bucket = by_stage[stage]
        all_n = len(bucket)
        all_win = _win_share(all_n, sum(1 for o, _ in bucket if o == WIN), min_n)
        strata = score_strata(bucket, min_n)
        out[stage] = {
            "all_n": all_n,
            "all_win": all_win,
            "setup_defined_n": strata["defined_n"],
            "setup_ge80_n": strata["ge80_n"],
            "setup_ge80_win": strata["ge80_win"],
            "setup_lt80_n": strata["lt80_n"],
            "setup_lt80_win": strata["lt80_win"],
            "setup_delta": strata["delta_ge80_vs_lt80"],
        }
    return out


def _bucket(days: int) -> str:
    if days <= 2:
        return "1-2"
    if days <= 3:
        return "3"
    if days <= 5:
        return "4-5"
    return "6-10"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(EPISODES.read_bytes()).hexdigest()
    if sha != EXPECTED_SHA:
        raise SystemExit(f"episodes hash mismatch: {sha}")
    con = duckdb.connect()
    rows = con.execute(
        "SELECT days_since_anchor, setup_stage, outcome, setup_quality_score, "
        "entry_quality_score FROM read_parquet(?) WHERE outcome IS NOT NULL",
        [str(EPISODES)],
    ).fetchall()
    resolved = [
        (int(r[0]), r[1], r[2], parse_score(r[3]), parse_score(r[4]))
        for r in rows
        if r[2] in GROUPS
    ]

    overall_n = len(resolved)
    overall_win = _win_share(overall_n, sum(1 for r in resolved if r[2] == WIN))
    setup_quality = score_strata([(r[2], r[3]) for r in resolved])
    entry_quality = score_strata([(r[2], r[4]) for r in resolved])

    by_bucket: dict[str, dict] = {}
    for r in resolved:
        b = _bucket(r[0])
        by_bucket.setdefault(b, {"all": [], "setup": [], "entry": []})
        by_bucket[b]["all"].append(r)
        by_bucket[b]["setup"].append((r[2], r[3]))
        by_bucket[b]["entry"].append((r[2], r[4]))
    bucket_stats: dict[str, dict] = {}
    for b in sorted(by_bucket):
        d = by_bucket[b]
        setup = score_strata(d["setup"])
        entry = score_strata(d["entry"])
        bucket_stats[b] = {
            "all_n": len(d["all"]),
            "all_win": _win_share(len(d["all"]), sum(1 for r in d["all"] if r[2] == WIN)),
            "setup_defined_n": setup["defined_n"],
            "setup_ge80_n": setup["ge80_n"],
            "setup_ge80_win": setup["ge80_win"],
            "setup_lt80_n": setup["lt80_n"],
            "setup_lt80_win": setup["lt80_win"],
            "setup_delta": setup["delta_ge80_vs_lt80"],
            "entry_defined_n": entry["defined_n"],
            "entry_ge80_n": entry["ge80_n"],
            "entry_ge80_win": entry["ge80_win"],
            "entry_lt80_n": entry["lt80_n"],
            "entry_lt80_win": entry["lt80_win"],
            "entry_delta": entry["delta_ge80_vs_lt80"],
        }

    stages = stage_strata([(r[1], r[2], r[3]) for r in resolved])

    payload = {
        "inputs": {
            "episodes": str(EPISODES),
            "episodes_sha256": sha,
            "snapshot_id": SNAPSHOT_ID,
        },
        "overall_background": {"resolved_n": overall_n, "win_share": overall_win},
        "setup_quality": setup_quality,
        "entry_quality": entry_quality,
        "by_timing_bucket": bucket_stats,
        "by_setup_stage": stages,
    }
    out = OUT_DIR / "h10-v01.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
