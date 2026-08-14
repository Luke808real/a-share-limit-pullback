"""Golden equivalence + timing: dry-run full rebuild of 2026-08-10.

The current code (B2-monotonic engine + rolling-window indicators) must
reproduce the 08-10 generation semantic root bit for bit. Also measures
the optimized full-rebuild wall time. Dry-run only: nothing promoted.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path

import pyarrow.parquet as pq

from limit_pullback.ops import (
    _calendar_sessions,
    _layout,
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
EXPECTED_SEMANTIC_ROOT = "92ddb9352985b193eff98bb6dd2b9e8230db3ecc544783b0e390b33c58ecf6f0"
STRATEGY_CONFIG = Path("config/strategy.yaml")
BUILD_ROOT = Path("data/tmp/equiv-check-20260810")
STAGED_CANDIDATE = next(Path("data/tmp/staging/adr008").glob("adr008-staging-20260810-*/canonical_candidate.parquet"))

STARTED = time.time()


def main() -> int:
    layout = _layout()
    runtime = load_runtime_config()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = resolve_formal_screen_ready_snapshot(md)
        prev_snapshot = md.snapshot_by_id("snap-2026-08-07-586cc17164af")
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
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    generation = build_state_generation(
        layout,
        snapshot_id=snapshot.snapshot_id,
        universe=universe,
        config_path=STRATEGY_CONFIG,
        as_of=SESSION,
        start=date(2024, 1, 1),
        rebuild=True,
        build_root=BUILD_ROOT,
        dry_run=True,
        verified_no_trade=verified,
        session_calendar=calendar,
        fast_path=False,
        window_calendar_days=runtime.daily_window_calendar_days,
    )
    wall = time.time() - t0
    match = generation.state_semantic_root_hash == EXPECTED_SEMANTIC_ROOT
    print(f"wall={wall:.1f}s semantic_root={generation.state_semantic_root_hash}")
    print("GOLDEN_MATCH:", match, "| state_n:", generation.state_n)
    return 0 if match else 1


if __name__ == "__main__":
    raise SystemExit(main())
