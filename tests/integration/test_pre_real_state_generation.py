"""PR-E real integration: 7/31 golden, full 8/5, incremental parity, promote."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.screen.generation import (
    build_state_generation,
    compact_output_roundtrip_hash,
    state_semantic_root_hash,
)
from limit_pullback.trade_plan import StrategySemanticReviewPendingError
from limit_pullback.universe import phase2d0_universe_from_snapshot
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import sha256_file

pytestmark = pytest.mark.integration

FROZEN_0731_HASH = (
    "9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec"
)
FORMAL_SNAPSHOT_ID = "snap-2026-08-05-49a843e6d7aa"
BAD_DAILY = (
    "ce9b489292b79d5a482bfc7f2aa027326587cf1687cea13e532ed1a30b405b16"
)


def _layout() -> WarehouseLayout:
    root = Path(__file__).resolve().parents[2] / "data"
    if not (root / "warehouse.duckdb").exists():
        pytest.skip("real data root not present")
    return WarehouseLayout(root)


def _legacy_state_root_hash(layout) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        (layout.root / "screen" / "states").glob("[0-9]*.json"),
        key=lambda p: p.stem,
    ):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _build(layout, *, as_of, start, rebuild, build_root, dry_run, seed=None):
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(FORMAL_SNAPSHOT_ID)
    assert snapshot is not None and snapshot.status == "SCREEN_READY"
    universe = phase2d0_universe_from_snapshot(layout, snapshot)
    assert universe.member_n == 3191
    return build_state_generation(
        layout,
        snapshot_id=FORMAL_SNAPSHOT_ID,
        universe=universe,
        config_path=Path(__file__).resolve().parents[2]
        / "config"
        / "strategy.yaml",
        as_of=as_of,
        start=start,
        rebuild=rebuild,
        build_root=build_root,
        dry_run=dry_run,
        seed_states_root=seed,
    )


def test_pre_real_state_generation_promotion():
    layout = _layout()
    config = load_strategy_config(
        Path(__file__).resolve().parents[2] / "config" / "strategy.yaml"
    )
    legacy_before = _legacy_state_root_hash(layout)
    legacy_count = len(
        list((layout.root / "screen" / "states").glob("[0-9]*.json"))
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        bad = metadata.snapshot_by_id("snap-2026-08-05-d9e93fccc966")
        pointer_before = metadata.get_formal_state_pointer()
    assert bad.status == "QUARANTINED"
    assert pointer_before is None

    # 1) 7/31 frozen checkpoint (dry).
    checkpoint_root = layout.root / "tmp" / "pr-e" / "checkpoint-0731"
    checkpoint = _build(
        layout,
        as_of=date(2026, 7, 31),
        start=date(2024, 1, 1),
        rebuild=True,
        build_root=checkpoint_root,
        dry_run=True,
    )
    cp_manifest = json.loads(
        (checkpoint_root / "manifest.json").read_text(encoding="utf-8")
    )
    assert cp_manifest["output_hash"] == FROZEN_0731_HASH
    assert checkpoint.state_n == 3191

    # 2) Full 8/5 rebuild -> real ACTIVE promotion.
    full_root = layout.root / "tmp" / "pr-e" / "full-0805"
    full = _build(
        layout,
        as_of=date(2026, 8, 5),
        start=date(2024, 1, 1),
        rebuild=True,
        build_root=full_root,
        dry_run=False,
    )
    assert full.status == "ACTIVE"
    assert full.state_n == 3191
    assert full.last_processed_20260805_n == 3191

    # 3) Incremental 8/5 from the 7/31 checkpoint (dry).
    inc_root = layout.root / "tmp" / "pr-e" / "inc-0805"
    incremental = _build(
        layout,
        as_of=date(2026, 8, 5),
        start=None,
        rebuild=False,
        build_root=inc_root,
        dry_run=True,
        seed=checkpoint_root / "states",
    )
    assert incremental.state_semantic_root_hash == full.state_semantic_root_hash
    assert incremental.state_n == full.state_n
    full_table = pq.read_table(full_root / "screen-output.parquet")
    full_payloads = {
        payload
        for day, payload in zip(
            full_table["trade_date"].to_pylist(),
            full_table["payload"].to_pylist(),
            strict=True,
        )
        if day > date(2026, 7, 31)
    }
    inc_payloads = set(
        pq.read_table(inc_root / "screen-output.parquet")[
            "payload"
        ].to_pylist()
    )
    assert full_payloads == inc_payloads

    # 4) Repeat full rebuild determinism (dry).
    repeat_root = layout.root / "tmp" / "pr-e" / "repeat-0805"
    repeat = _build(
        layout,
        as_of=date(2026, 8, 5),
        start=date(2024, 1, 1),
        rebuild=True,
        build_root=repeat_root,
        dry_run=True,
    )
    assert repeat.state_semantic_root_hash == full.state_semantic_root_hash

    # 5) Final invariants.
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        pointer = metadata.get_formal_state_pointer()
        generation = metadata.state_generation_by_id(pointer)
    assert pointer == full.generation_id
    assert generation["status"] == "ACTIVE"
    assert generation["snapshot_id"] == FORMAL_SNAPSHOT_ID
    state_root = (
        layout.root / "screen" / "generations" / full.generation_id / "states"
    )
    codes = sorted(path.stem for path in state_root.glob("[0-9]*.json"))
    assert len(codes) == 3191
    assert not any(code.startswith(("300", "301", "688", "689")) for code in codes)
    assert _legacy_state_root_hash(layout) == legacy_before
    assert len(
        list((layout.root / "screen" / "states").glob("[0-9]*.json"))
    ) == legacy_count
    assert bad.status == "QUARANTINED"
    assert sha256_file(
        layout.canonical_dir
        / "daily_bars"
        / "snap-2026-08-05-d9e93fccc966.parquet"
    ) == BAD_DAILY

    # 6) Compact artifact + manifest.
    manifest = json.loads(
        (full_root / "manifest.json").read_text(encoding="utf-8")
    )
    assert "rows" not in manifest
    roundtrip, row_n = compact_output_roundtrip_hash(
        full_root / "screen-output.parquet"
    )
    assert roundtrip == manifest["output_hash"]
    assert row_n == manifest["compact_output_row_n"]

    # 7) TradePlan blocked by semantic review; snapshot hash check.
    from limit_pullback.trade_plan import build_trade_plan_output

    with pytest.raises(StrategySemanticReviewPendingError):
        build_trade_plan_output(
            layout=layout,
            as_of=date(2026, 8, 5),
            snapshot_id=FORMAL_SNAPSHOT_ID,
            config=config,
            config_hash="x" * 64,
        )
