"""ASL news-layer ingestion driver (news-analysis agent, Phase 3).

Runs the ASL lake's own registered steps for the news observation layer,
targeting only the datasets the V flash news brief needs, for the three
sessions 2026-08-11 .. 2026-08-13:

- news_headlines   (eastmoney, snapshot semantics -> one run per date)
- flash_news_wire  (eastmoney, snapshot semantics -> one run per date)
- announcement_index (cninfo, daily semantics -> single run covers lookback)
- dragon_tiger     (eastmoney, daily semantics -> single run covers lookback)

Everything goes through JobEngine + StagingWriter + compact, exactly like
the asl run daily schedule groups. Nothing is fetched or written by hand,
and the lake manifest records every run.

Run with the ASL project's own venv:
    /Users/luke808/AI/ashare-lake-architecture-convergence-v01/.venv/bin/python \\
        research/news-observation-v01/asl_news_ingest_driver.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, "/Users/luke808/AI/ashare-lake-architecture-convergence-v01/src")

import ashare_lake.steps  # noqa: F401 — register steps
from ashare_lake.config import load_config
from ashare_lake.orchestrator.engine import JobEngine

CONFIG_PATH = "/Users/luke808/AI/asl-shared-config.toml"
SESSIONS = (date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13))
SNAPSHOT_DATASETS = ("news_headlines", "flash_news_wire")
DAILY_DATASETS = ("announcement_index", "dragon_tiger")
OUT_DIR = Path(__file__).resolve().parent / "runs"
OK_STATUSES = {"success", "warning", "skipped_non_trading_day"}

STARTED = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - STARTED:7.1f}s] {msg}", flush=True)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config(CONFIG_PATH)
    engine = JobEngine(cfg)
    summary: dict = {"config": CONFIG_PATH, "runs": [], "failed": []}

    plan: list[tuple[str, list[str], date]] = []
    for d in SESSIONS:
        for ds in SNAPSHOT_DATASETS:
            plan.append((f"daily:news:{ds}", [ds, "compact"], d))
    for ds in DAILY_DATASETS:
        plan.append((f"daily:news:{ds}", [ds, "compact"], SESSIONS[-1]))

    for job_name, steps, d in plan:
        log(f"run {job_name} steps={steps} trade_date={d.isoformat()}")
        try:
            result = engine.run_job(job_name, trade_date=d, steps=steps)
        except Exception as exc:
            summary["failed"].append(
                {"job": job_name, "trade_date": d.isoformat(), "error": repr(exc)}
            )
            log(f"FAILED {job_name}: {exc!r}")
            continue
        summary["runs"].append(
            {
                "job": job_name,
                "steps": steps,
                "trade_date": d.isoformat(),
                "run_id": result.get("run_id"),
                "status": result.get("status"),
                "rows_read": result.get("rows_read"),
                "rows_written": result.get("rows_written"),
            }
        )
        log(
            f"{job_name}: status={result.get('status')} "
            f"rows_read={result.get('rows_read')} rows_written={result.get('rows_written')}"
        )
        if result.get("status") not in OK_STATUSES:
            summary["failed"].append(
                {
                    "job": job_name,
                    "trade_date": d.isoformat(),
                    "status": result.get("status"),
                }
            )

    out_path = OUT_DIR / "ingest-20260813-summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    log(f"summary -> {out_path}")
    if summary["failed"]:
        print("INGESTION_HAD_FAILURES", flush=True)
        return 1
    print("INGESTION_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
