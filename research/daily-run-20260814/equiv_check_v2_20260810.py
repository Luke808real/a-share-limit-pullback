"""Golden equivalence v2: dry-run rebuild of the 08-10 SNAPSHOT (explicit id).

The formal pointer has since advanced to 08-13, so the earlier equiv script
was rebuilding the wrong snapshot. This one pins snap-2026-08-10-f811c7f53089
and uses run_screen directly (no pointer check, no promotion, dry-run only),
then compares state_semantic_root_hash against the 08-10 anchor.

Run twice: first populates the indicator cache, second measures warm-cache time.
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
from limit_pullback.screen.generation import state_semantic_root_hash
from limit_pullback.screen.indicator_cache import indicator_cache_dir
from limit_pullback.screen.runner import run_screen
from limit_pullback.universe import phase2d0_universe_from_snapshot
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import sha256_file

SESSION = date(2026, 8, 10)
SNAPSHOT_ID = "snap-2026-08-10-f811c7f53089"
EXPECTED_SEMANTIC_ROOT = "92ddb9352985b193eff98bb6dd2b9e8230db3ecc544783b0e390b33c58ecf6f0"
STRATEGY_CONFIG = Path("config/strategy.yaml")
BUILD_ROOT = Path("data/tmp/equiv-check-v2-20260810")
STAGED_CANDIDATE = next(Path("data/tmp/staging/adr008").glob("adr008-staging-20260810-*/canonical_candidate.parquet"))

STARTED = time.time()


def main() -> int:
    layout = _layout()
    runtime = load_runtime_config()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = md.snapshot_by_id(SNAPSHOT_ID)
        prev_snapshot = md.snapshot_by_id("snap-2026-08-07-586cc17164af")
    if snapshot is None or snapshot.status != "SCREEN_READY":
        raise SystemExit(f"snapshot unavailable: {snapshot}")
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
    import shutil

    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    states_root = BUILD_ROOT / "states"
    config_hash = sha256_file(STRATEGY_CONFIG)
    cache_dir = indicator_cache_dir(layout, SNAPSHOT_ID, config_hash)
    t0 = time.time()
    import os

    result = run_screen(
        layout=layout,
        as_of=SESSION,
        snapshot_id=SNAPSHOT_ID,
        start=date(2024, 1, 1),
        rebuild=True,
        codes=universe.members,
        config_path=STRATEGY_CONFIG,
        strategy_commit=os.environ.get("BENCH_COMMIT"),
        states_root=states_root,
        compact_output_path=BUILD_ROOT / "screen-output.parquet",
        indicator_cache=cache_dir,
        workers=int(os.environ.get("BENCH_WORKERS", "4")),
    )
    wall = time.time() - t0
    root_hash, state_n = state_semantic_root_hash(states_root)
    print(f"wall={wall:.1f}s semantic_root={root_hash} state_n={state_n}")
    print("cache_dir:", cache_dir)
    print("GOLDEN_MATCH:", root_hash == EXPECTED_SEMANTIC_ROOT)
    return 0 if root_hash == EXPECTED_SEMANTIC_ROOT else 1


if __name__ == "__main__":
    raise SystemExit(main())
