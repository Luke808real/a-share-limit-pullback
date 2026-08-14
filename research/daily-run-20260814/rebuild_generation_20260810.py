"""Rebuild the 2026-08-10 state generation with the B2-monotonic engine.

Context: the 08-10 daily-run promotion succeeded (snapshot SCREEN_READY,
generation ACTIVE) but its sentinel check failed for 605198: the generation
was advanced from 08-07 seed states built by the pre-fix (demotion-allowing)
engine, while a fresh replay with the fixed engine keeps B2_CONFIRMED.

Repair: full rebuild (start=2024-01-01, rebuild=True) of the 08-10 generation
against the already-promoted 08-10 snapshot, using the current fixed engine.
The new generation supersedes the divergent one via the normal promotion
path (no pointer rollback, no hand-edited states). Frozen snapshot and
phase-2d0 manifest remain untouched.

Run: .venv/bin/python research/daily-run-20260814/rebuild_generation_20260810.py
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import pyarrow.parquet as pq

from limit_pullback.ops import (
    _calendar_sessions,
    _layout,
    _sentinel_check,
    _verified_no_trade_from_previous,
    _verify_no_trade_with_baostock,
)
from limit_pullback.runtime import load_runtime_config
from limit_pullback.screen.generation import build_state_generation
from limit_pullback.universe import phase2d0_universe_from_snapshot
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.snapshot import (
    resolve_formal_screen_ready_snapshot,
)

SESSION = date(2026, 8, 10)
STRATEGY_CONFIG = Path("config/strategy.yaml")
BUILD_ROOT = Path("data/tmp/rebuild-gen-20260810")
STAGED_CANDIDATE = next(Path("data/tmp/staging/adr008").glob("adr008-staging-20260810-*/canonical_candidate.parquet"))

STARTED = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - STARTED:7.1f}s] {msg}", flush=True)


def main() -> int:
    layout = _layout()
    runtime = load_runtime_config()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = resolve_formal_screen_ready_snapshot(md)
        prev_snapshot = md.snapshot_by_id("snap-2026-08-07-586cc17164af")
    if snapshot.snapshot_id != "snap-2026-08-10-f811c7f53089":
        raise SystemExit(f"unexpected formal snapshot {snapshot.snapshot_id}")
    if prev_snapshot is None:
        raise SystemExit("prev 08-07 snapshot missing")
    universe = phase2d0_universe_from_snapshot(layout, snapshot)
    calendar = _calendar_sessions(
        layout, snapshot, prev_snapshot.as_of - timedelta(days=30), SESSION
    )
    prior_sessions = tuple(d for d in calendar if d < SESSION)
    prior_verified = _verified_no_trade_from_previous(
        layout, prev_snapshot, prior_sessions, universe.members
    )
    staged_rows = pq.read_table(STAGED_CANDIDATE).to_pylist()
    current_verified = _verify_no_trade_with_baostock(
        layout, SESSION, universe.members, staged_rows
    )
    verified = tuple(sorted(set(prior_verified + current_verified)))
    log(f"calendar={len(calendar)} prior_verified={len(prior_verified)} current_verified={len(current_verified)}")
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    log("starting full rebuild (2024-01-01 .. 2026-08-10) with fixed engine")
    generation = build_state_generation(
        layout,
        snapshot_id=snapshot.snapshot_id,
        universe=universe,
        config_path=STRATEGY_CONFIG,
        as_of=SESSION,
        start=date(2024, 1, 1),
        rebuild=True,
        build_root=BUILD_ROOT,
        dry_run=False,
        verified_no_trade=verified,
        session_calendar=calendar,
        fast_path=False,
        window_calendar_days=runtime.daily_window_calendar_days,
    )
    log(f"new generation: {generation.generation_id} status={generation.status} semantic_root={generation.state_semantic_root_hash}")
    sentinels = _sentinel_check(
        layout, snapshot, generation.generation_root, SESSION, STRATEGY_CONFIG
    )
    print(json.dumps(
        {"generation": generation.generation_id, "status": generation.status,
         "semantic_root": generation.state_semantic_root_hash,
         "sentinels": sentinels},
        ensure_ascii=False, indent=2,
    ))
    return 0 if all(s["match"] for s in sentinels) else 1


if __name__ == "__main__":
    raise SystemExit(main())
