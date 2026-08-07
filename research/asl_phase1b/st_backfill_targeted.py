"""Official ASL historical ST backfill for the Phase-1B targeted cohort.

Narrowest OFFICIAL mechanism for the decision-relevant ST codes.  Reuses the
exact functions the official ``asl backfill trading_status`` step uses,
restricted to the target symbols:

* fetch  : ``ashare_lake.adapters.baostock.st_history.fetch_st_history``
           (per-symbol baostock isST days, official safe pacing from config:
           batch 20 / rest 120 s — the documented non-blacklisting rate)
* write  : ``ashare_lake.steps.http_common.write_fetched(source="baostock")``
           -> official staging write with provenance
* compact: ``JobEngine.run_step("compact", ...)`` -> official curated merge
           (dedupe by PK keeping latest fetched_at)
* marker : ``ashare_lake.steps.reference._mark_st_backfilled`` (official
           resume-state bookkeeping)
* manifest: official ``Manifest`` run/batch lifecycle methods

No manual Parquet editing.  No new provider implementation.  Core ASL data
(daily_bars / trading_calendar / instruments / corporate_actions) untouched.

The ASL CLI itself does not support symbol-scoped trading_status backfill
(``--symbols`` is restricted to minute_bars/minute_bars_5m/trade_ticks and the
step's backfill branch sweeps the full all_a bar universe minus the resume
marker), so this is the narrowest official supported path.

Run with the ASL environment (revision ba5681a):

    /private/tmp/asl_inspect/asl/.venv/bin/python \
        research/asl_phase1b/st_backfill_targeted.py \
        --config /tmp/asl_phase1b_lake/status-safe.toml \
        --summary research/asl_phase1b/shadow_summary.json
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date
from pathlib import Path

from ashare_lake.config.loader import load_config
from ashare_lake.orchestrator.engine import JobEngine
from ashare_lake.adapters.baostock.st_history import fetch_st_history
from ashare_lake.steps.http_common import write_fetched
from ashare_lake.steps.reference import _mark_st_backfilled

WINDOW_START = date(2024, 1, 16)
AS_OF = date(2026, 8, 6)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--start", default=WINDOW_START.isoformat())
    parser.add_argument("--end", default=AS_OF.isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    codes = summary["st_coverage"]["decision_relevant_st_unknown_codes"]
    symbols = sorted(
        code + (".SH" if code.startswith("6") else ".SZ") for code in codes
    )
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    print(f"TARGET_ST_CODE_N={len(codes)}  symbols={len(symbols)}  window={start}..{end}")
    if args.dry_run:
        print("dry-run: no fetch")
        return 0

    df, failed = fetch_st_history(symbols, start, end, config=cfg)
    print(f"fetched rows={df.height}  failed_symbols={len(failed)} {failed[:10]}")
    if failed:
        print("FAILED_SYMBOLS:", json.dumps(failed))
    if df.is_empty() and not failed:
        print("no ST rows for cohort (legitimate empty: never ST in window)")
        return 0

    engine = JobEngine(cfg)
    trade_date = date.today()
    run_id = engine.manifest.start_run(
        "backfill", {"trade_date": trade_date.isoformat(), "backfill": True}
    )
    batch_id = uuid.uuid4().hex
    engine.manifest.start_batch(
        run_id,
        batch_id,
        task_id="trading_status",
        dataset="trading_status",
        symbols=symbols,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
    )
    try:
        written = write_fetched(
            cfg, run_id, "trading_status", df, source="baostock", batch_id=batch_id
        )
        engine.manifest.finish_batch(
            run_id, batch_id, "success",
            rows_read=int(written.get("rows_read", 0)),
            rows_written=int(written.get("rows_written", 0)),
        )
    except Exception:
        engine.manifest.finish_batch(
            run_id, batch_id, "failed", error_message="targeted st backfill write failed"
        )
        raise
    compact = engine.run_step("compact", trade_date, run_id)
    engine.manifest.finish_run(
        run_id, "success",
        rows_read=int(written.get("rows_read", 0)),
        rows_written=int(written.get("rows_written", 0)),
    )
    swept = [s for s in symbols if s not in set(failed)]
    _mark_st_backfilled(cfg, swept)

    out = {
        "run_id": run_id,
        "target_symbols": symbols,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "rows_fetched": df.height,
        "rows_written": written,
        "compact": compact,
        "failed_symbols": failed,
        "marked_completed": len(swept),
    }
    print(json.dumps(out, indent=2, default=str))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
