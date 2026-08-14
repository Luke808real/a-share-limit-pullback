"""Assemble the backtest cooperation study inputs-verified + provenance JSON.

Read-only. Hash-computes every artifact the study cites.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

STUDY = Path(__file__).resolve().parent.parent / "backtest-cooperation-v01"
BASE = Path(
    "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
)
EPISODES = BASE / "corrected-b2-trigger-outcome" / "episodes.parquet"
FROZEN_DIR = BASE / "corrected-b2-trigger-outcome" / "execution-reality"
RECHECK_DIR = STUDY / "runs" / "execution-reality-recheck"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    frozen_summary = json.loads((FROZEN_DIR / "summary.json").read_text())
    recheck_summary = json.loads((RECHECK_DIR / "summary.json").read_text())

    def strip(d):
        out = dict(d)
        perf = dict(out.get("performance") or {})
        perf.pop("analysis_seconds", None)
        out["performance"] = perf
        return out

    semantic_equal = json.dumps(strip(frozen_summary), sort_keys=True) == json.dumps(
        strip(recheck_summary), sort_keys=True
    )

    cohorts = {
        k: {
            "10bp_E_R": v.get("10bp_E_R"),
            "20bp_E_R": v.get("20bp_E_R"),
            "strict_E_R": v.get("strict_E_R"),
            "conservative_E_R": v.get("conservative_E_R"),
            "resolved": v.get("resolved") or v.get("filled"),
        }
        for k, v in frozen_summary.get("cohorts", {}).items()
    }

    verified = {
        "study": "backtest-cooperation-v01",
        "episodes": {
            "path": str(EPISODES),
            "sha256": sha(EPISODES),
            "expected_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
            "match": sha(EPISODES)
            == "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
            "rows": frozen_summary.get("episode_count"),
        },
        "snapshot_id": frozen_summary.get("snapshot_id"),
        "expected_snapshot_id": "snap-2026-07-31-b5f84004de8a",
        "frozen_outputs": {
            "dir": str(FROZEN_DIR),
            "summary_sha256": sha(FROZEN_DIR / "summary.json"),
            "episodes_parquet_sha256": sha(FROZEN_DIR / "execution_episodes.parquet"),
            "analysis_seconds": frozen_summary.get("performance", {}).get(
                "analysis_seconds"
            ),
        },
        "recheck_outputs": {
            "dir": str(RECHECK_DIR),
            "summary_sha256": sha(RECHECK_DIR / "summary.json"),
            "episodes_parquet_sha256": sha(RECHECK_DIR / "execution_episodes.parquet"),
            "analysis_seconds": recheck_summary.get("performance", {}).get(
                "analysis_seconds"
            ),
            "derived_rows": recheck_summary.get("performance", {}).get("derived_rows"),
            "evaluate_strategy_calls": recheck_summary.get("evaluate_strategy_calls"),
        },
        "semantic_equal_after_stripping_analysis_seconds": semantic_equal,
        "cohorts": cohorts,
    }
    (STUDY / "inputs-verified.json").write_text(
        json.dumps(verified, ensure_ascii=False, indent=2) + chr(10)
    )
    print(json.dumps(verified, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
