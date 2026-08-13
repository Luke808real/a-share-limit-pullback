"""Task helper: build + promote the 2026-08-13 state generation (ASL path)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from limit_pullback.screen.generation import build_state_generation
from limit_pullback.universe import phase2d0_universe_from_snapshot
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata


def main() -> None:
    layout = WarehouseLayout(Path("data"))
    snapshot_id = "snap-2026-08-13-308ffef3d9bf"
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snap = md.snapshot_by_id(snapshot_id)
    universe = phase2d0_universe_from_snapshot(
        layout, snap, as_of=date(2026, 8, 13)
    )
    con = duckdb.connect()
    sessions = tuple(
        row[0]
        for row in con.execute(
            "SELECT DISTINCT trade_date FROM read_parquet(?) "
            "WHERE reconciliation_status='CONFIRMED' "
            "AND trade_date BETWEEN DATE '2024-01-02' AND DATE '2026-08-13' "
            "ORDER BY trade_date",
            [str(layout.root / "canonical/daily_bars" / f"{snapshot_id}.parquet")],
        ).fetchall()
    )
    print(f"universe={universe.member_n} sessions={len(sessions)}", flush=True)
    result = build_state_generation(
        layout,
        snapshot_id=snapshot_id,
        universe=universe,
        config_path=Path("config/strategy.yaml"),
        as_of=date(2026, 8, 13),
        start=date(2024, 1, 2),
        rebuild=True,
        build_root=Path("data/tmp/stategen-0813-build-v2"),
        seed_states_root=None,
        session_calendar=sessions,
    )
    print(f"RESULT={result.status} id={result.generation_id}", flush=True)
    print(f"pointer_after={result.pointer_after}", flush=True)
    print(f"state_n={result.state_n} setup_counts={result.setup_counts}", flush=True)


if __name__ == "__main__":
    main()
