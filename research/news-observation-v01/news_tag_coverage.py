"""News-tag coverage check for the backtest cooperation study (news agent).

Determines whether the ASL announcement/dragon-tiger tables can tag the frozen
corrected episodes. Read-only everywhere.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

EPISODES = Path(
    "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    "/corrected-b2-trigger-outcome/episodes.parquet"
)
ASL = "/Users/luke808/AI/asl-shared/duckdb/ashare-lake.duckdb"
OUT = Path(__file__).resolve().parent.parent / "backtest-cooperation-v01" / "news-tag-coverage.json"


def main() -> int:
    con = duckdb.connect()
    n, lo, hi = con.execute(
        "SELECT count(*), min(anchor_date), max(anchor_date) FROM read_parquet(?)",
        [str(EPISODES)],
    ).fetchone()
    con.close()
    con2 = duckdb.connect(ASL, read_only=True)
    report = {"episodes": {"rows": n, "min_trade_date": str(lo), "max_trade_date": str(hi)}}
    for table, dcol in (("announcement_index", "announce_date"), ("dragon_tiger", "trade_date")):
        cnt, tlo, thi = con2.execute(
            f"SELECT count(*), min({dcol}), max({dcol}) FROM {table}"
        ).fetchone()
        overlap = 0
        if tlo is not None:
            a = max(date.fromisoformat(str(lo)), date.fromisoformat(str(tlo)))
            b = min(date.fromisoformat(str(hi)), date.fromisoformat(str(thi)))
            overlap = max(0, (b - a).days + 1) if a <= b else 0
        report[table] = {
            "rows": cnt,
            "min_date": str(tlo),
            "max_date": str(thi),
            "overlap_days_with_episodes": overlap,
        }
    con2.close()
    report["conclusion"] = (
        "REJECT_FOR_THIS_STUDY"
        if report["announcement_index"]["overlap_days_with_episodes"] == 0
        and report["dragon_tiger"]["overlap_days_with_episodes"] == 0
        else "OBSERVE_ONLY"
    )
    report["note"] = (
        "Frozen episodes end 2026-07-31; ASL news tables start 2026-08-10. "
        "Zero overlap: historical episode tagging is not applicable. News tags "
        "are forward-only going forward (via ops daily-run news-brief)."
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + chr(10))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
