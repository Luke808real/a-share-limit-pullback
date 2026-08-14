"""Write the study provenance manifest (input/script/output + hashes)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

STUDY = Path(__file__).resolve().parent
NEWS = STUDY.parent / "news-observation-v01"
BASE = Path(
    "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    manifest = {
        "study": "backtest-cooperation-v01",
        "date": "2026-08-14",
        "inputs": {
            "episodes.parquet": {
                "path": str(BASE / "corrected-b2-trigger-outcome" / "episodes.parquet"),
                "sha256": sha(BASE / "corrected-b2-trigger-outcome" / "episodes.parquet"),
            },
            "frozen_execution_reality": {
                "summary.json": sha(
                    BASE / "corrected-b2-trigger-outcome" / "execution-reality" / "summary.json"
                ),
                "execution_episodes.parquet": sha(
                    BASE / "corrected-b2-trigger-outcome" / "execution-reality" / "execution_episodes.parquet"
                ),
            },
        },
        "scripts": {
            "assemble_inputs_verified.py": sha(STUDY / "assemble_inputs_verified.py"),
            "news_tag_coverage.py": sha(NEWS / "news_tag_coverage.py"),
            "asl_news_ingest_driver.py": sha(NEWS / "asl_news_ingest_driver.py"),
        },
        "outputs": {
            "inputs-verified.json": sha(STUDY / "inputs-verified.json"),
            "news-tag-coverage.json": sha(STUDY / "news-tag-coverage.json"),
            "protocol.md": sha(STUDY / "protocol.md"),
            "conclusions.md": sha(STUDY / "conclusions.md"),
            "recheck_summary.json": sha(
                STUDY / "runs" / "execution-reality-recheck" / "summary.json"
            ),
            "recheck_execution_episodes.parquet": sha(
                STUDY / "runs" / "execution-reality-recheck" / "execution_episodes.parquet"
            ),
        },
        "conclusions": {
            "H1_input_provenance": "SUPPORTED",
            "H2_determinism_resources": "SUPPORTED",
            "H3_news_tags_historical": "REJECT_FOR_THIS_STUDY",
            "H3_news_tags_forward": "OBSERVE_ONLY",
            "H4_frozen_conclusions_intact": "SUPPORTED",
        },
        "promoted": "NONE — SUPPORTED != PROMOTED; no strategy change",
    }
    (STUDY / "provenance.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + chr(10)
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
