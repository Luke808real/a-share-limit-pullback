"""Complete the 2026-08-10 daily-run tail after the generation rebuild.

The daily step already promoted the 08-10 snapshot and the rebuild replaced
the divergent generation. This script runs the remaining fail-closed steps
(trade-plan -> news-brief -> watchlist -> reconcile) and writes the final
timing.json for the session.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from limit_pullback.ops import _fmt, _layout, _render_watchlist_md
from limit_pullback.config import load_strategy_config, load_trade_plan_config
from limit_pullback.news_brief import build_news_brief, render_markdown
from limit_pullback.trade_plan import build_trade_plan_output
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import sha256_file

SESSION = date(2026, 8, 10)
SNAPSHOT_ID = "snap-2026-08-10-f811c7f53089"
GENERATION_ID = "stategen-2026-08-10-bf507b268263"
STRATEGY_CONFIG = Path("config/strategy.yaml")
TRADE_PLAN_CONFIG = Path("config/trade_plan.yaml")
ASL_DB = Path("/Users/luke808/AI/asl-shared/duckdb/ashare-lake.duckdb")

STARTED = time.time()
layout = _layout()
run_dir = layout.root / "tmp" / "daily-run-20260810"
run_dir.mkdir(parents=True, exist_ok=True)

steps = [
    {"name": "daily", "wall_seconds": 841.11, "ok": True,
     "detail": "promoted snap-2026-08-10 + old generation; sentinel 605198 mismatch (pre-fix seeds)"},
    {"name": "rebuild-generation", "wall_seconds": None, "ok": True,
     "detail": "full rebuild 2024-01-01..2026-08-10 with fixed engine -> " + GENERATION_ID},
]
completed = ["daily", "rebuild-generation"]


def fail(name: str, exc: Exception) -> int:
    steps.append({"name": name, "wall_seconds": round(time.time() - STARTED, 2), "ok": False, "detail": repr(exc)})
    (run_dir / "timing.json").write_text(json.dumps(
        {"date": SESSION.isoformat(), "steps": steps, "completed": completed, "status": "FAILED"},
        ensure_ascii=False, indent=2) + chr(10))
    print(json.dumps({"error": {"type": "TAIL_FAILED", "step": name, "message": repr(exc)}}, ensure_ascii=False, indent=2))
    return 1


def main() -> int:
    # trade-plan
    t0 = time.time()
    try:
        plan = build_trade_plan_output(
            layout=layout,
            as_of=SESSION,
            snapshot_id=SNAPSHOT_ID,
            config=load_strategy_config(STRATEGY_CONFIG),
            config_hash=sha256_file(STRATEGY_CONFIG),
            trade_plan_config=load_trade_plan_config(TRADE_PLAN_CONFIG),
            execution_config_hash=sha256_file(TRADE_PLAN_CONFIG),
        )
    except Exception as exc:
        return fail("trade-plan", exc)
    (run_dir / "plan.json").write_text(plan.model_dump_json(indent=2) + chr(10))
    steps.append({"name": "trade-plan", "wall_seconds": round(time.time() - t0, 2), "ok": True,
                  "detail": {"actionable": plan.actionable_count, "b1_prep": plan.b1_prep_count,
                             "plans": len(plan.plans)}})
    completed.append("trade-plan")

    # news-brief
    t0 = time.time()
    codes = tuple(sorted({p.code for p in plan.plans}))
    brief = None
    if not codes:
        steps.append({"name": "news-brief", "wall_seconds": round(time.time() - t0, 2), "ok": True,
                      "detail": "no candidates; brief skipped"})
    else:
        try:
            brief = build_news_brief(db_path=ASL_DB, as_of=SESSION, codes=codes, window_days=3)
        except Exception as exc:
            return fail("news-brief", exc)
        (run_dir / "brief.json").write_text(brief.model_dump_json(indent=2) + chr(10))
        (run_dir / "brief.md").write_text(render_markdown(brief))
        steps.append({"name": "news-brief", "wall_seconds": round(time.time() - t0, 2), "ok": True,
                      "detail": {"matched": brief.symbols_matched}})
    completed.append("news-brief")

    # watchlist
    t0 = time.time()
    watch_md = _render_watchlist_md(plan, brief, SESSION)
    (run_dir / "watchlist.md").write_text(watch_md)
    review_dir = Path("research/daily-review")
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / f"{SESSION.isoformat()}-HUMAN-WATCH.md").write_text(watch_md)
    steps.append({"name": "watchlist", "wall_seconds": round(time.time() - t0, 2), "ok": True, "detail": ""})
    completed.append("watchlist")

    # reconcile
    t0 = time.time()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        pointer = md.get_formal_pointer()
        state_pointer = md.get_formal_state_pointer()
    if pointer[0] != SNAPSHOT_ID or state_pointer != GENERATION_ID:
        return fail("reconcile", ValueError(f"pointer mismatch: {pointer} / {state_pointer}"))
    steps.append({"name": "reconcile", "wall_seconds": round(time.time() - t0, 2), "ok": True,
                  "detail": {"snapshot": pointer[0], "state": state_pointer}})
    completed.append("reconcile")

    (run_dir / "timing.json").write_text(json.dumps(
        {"date": SESSION.isoformat(), "steps": steps, "completed": completed, "status": "OK"},
        ensure_ascii=False, indent=2) + chr(10))
    print(json.dumps({"date": SESSION.isoformat(), "status": "OK", "steps": steps}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
