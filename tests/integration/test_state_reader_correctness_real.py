"""STATE_READER_CORRECTNESS real regression on the formal snapshot."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from limit_pullback.screen.canonical import (
    iter_canonical_code_bars,
    load_canonical_market,
)
from limit_pullback.screen.runner import _bars_prefix_hash, run_screen
from limit_pullback.universe import phase2d0_universe_from_snapshot
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata

pytestmark = pytest.mark.integration

FORMAL_SNAPSHOT_ID = "snap-2026-08-05-49a843e6d7aa"
CORRECT_603980_PREFIX_HASH = (
    "5d7c43a1944f82995135b472d718b012c4abd402cf7db196d3e946419ddbef81"
)


def _layout() -> WarehouseLayout:
    root = Path(__file__).resolve().parents[2] / "data"
    if not (root / "warehouse.duckdb").exists():
        pytest.skip("real data root not present")
    return WarehouseLayout(root)


def test_real_603980_reader_and_runner_consistency(tmp_path):
    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(FORMAL_SNAPSHOT_ID)
    universe = phase2d0_universe_from_snapshot(layout, snapshot)
    assert universe.member_n == 3191

    # Reader: every code yielded exactly once; 603980 carries full history.
    groups = {}
    for code, bars in iter_canonical_code_bars(
        layout,
        snapshot,
        codes=universe.members,
        as_of=date(2026, 8, 5),
    ):
        groups[code] = groups.get(code, 0) + 1
        if code == "603980":
            iter_hash = _bars_prefix_hash(bars, date(2026, 8, 5))
            assert len(bars) == 589
            assert iter_hash == CORRECT_603980_PREFIX_HASH
    assert len(groups) == 3191
    assert all(count == 1 for count in groups.values())

    # Grouped (dict) reader agrees with the streaming reader.
    market = load_canonical_market(
        layout,
        snapshot_id=FORMAL_SNAPSHOT_ID,
        codes=["603980"],
    )
    grouped_hash = _bars_prefix_hash(
        market.bars_by_code["603980"],
        date(2026, 8, 5),
    )
    assert grouped_hash == CORRECT_603980_PREFIX_HASH

    # Runner single-code state: no longer truncated NORMAL.
    states_root = tmp_path / "states-603980"
    compact_path = tmp_path / "603980-out.parquet"
    manifest_path = tmp_path / "603980-manifest.json"
    result = run_screen(
        layout=layout,
        as_of=date(2026, 8, 5),
        snapshot_id=FORMAL_SNAPSHOT_ID,
        start=date(2024, 1, 1),
        rebuild=True,
        codes=["603980"],
        config_path=Path(__file__).resolve().parents[2]
        / "config"
        / "strategy.yaml",
        strategy_commit="reader-fix-review",
        states_root=states_root,
        compact_output_path=compact_path,
        manifest_path_override=manifest_path,
    )
    assert result.rows_count == 589
    state = json.loads(
        (states_root / "603980.json").read_text(encoding="utf-8")
    )
    signal = json.loads(state["signal_json"])
    assert signal["setup_stage"] != "NORMAL"
    assert signal.get("anchor") is not None
    assert state["bars_prefix_hash"] == CORRECT_603980_PREFIX_HASH
