"""PR-E real integration: 7/31 golden, full 8/5, incremental parity, promote."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.screen.generation import (
    build_state_generation,
    compact_output_roundtrip_hash,
    normalize_output_payload,
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


def _build(layout, *, as_of, start, rebuild, build_root, dry_run, seed=None,
           verified=(), calendar=()):
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
        verified_no_trade=verified,
        session_calendar=calendar,
    )


VERIFIED_NO_TRADE = (
    ("600530", date(2026, 8, 3)),
    ("603221", date(2026, 8, 3)),
    ("603221", date(2026, 8, 4)),
    ("603221", date(2026, 8, 5)),
    ("000838", date(2026, 8, 3)),
    ("000838", date(2026, 8, 4)),
    ("000838", date(2026, 8, 5)),
    ("002214", date(2026, 8, 4)),
)
SESSIONS_0803_05 = (
    date(2026, 8, 3),
    date(2026, 8, 4),
    date(2026, 8, 5),
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

    # 1) 7/31 frozen checkpoint (dry).
    checkpoint_root = layout.root / "tmp" / "pr-e" / "checkpoint-0731"
    cp_manifest = json.loads(
        (checkpoint_root / "manifest.json").read_text(encoding="utf-8")
    )
    assert cp_manifest["output_hash"] == FROZEN_0731_HASH
    cp_states = list((checkpoint_root / "states").glob("[0-9]*.json"))
    assert len(cp_states) == 3191

    # 2) Full 8/5 rebuild -> real ACTIVE promotion.
    if pointer_before is not None:
        with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
            existing = metadata.state_generation_by_id(pointer_before)
        assert existing["status"] == "ACTIVE"
        assert existing["snapshot_id"] == FORMAL_SNAPSHOT_ID
        full_root = (
            layout.root / "screen" / "generations" / pointer_before
        )
        generation_manifest = json.loads(
            (full_root / "generation.json").read_text(encoding="utf-8")
        )
        verification_report = json.loads(
            (full_root / "verification.json").read_text(encoding="utf-8")
        )
        full = SimpleNamespace(
            generation_id=generation_manifest["generation_id"],
            status="ACTIVE",
            state_n=verification_report["state_n"],
            last_processed_20260805_n=verification_report[
                "last_processed_20260805_n"
            ],
            generation_root=full_root,
            state_semantic_root_hash=verification_report[
                "state_semantic_root_hash"
            ],
            compact_output_hash=verification_report["compact_output_hash"],
            idempotent=True,
        )
    else:
        full_root = layout.root / "tmp" / "pr-e" / "full-0805"
        full = _build(
            layout,
            as_of=date(2026, 8, 5),
            start=date(2024, 1, 1),
            rebuild=True,
            build_root=full_root,
            dry_run=False,
            verified=VERIFIED_NO_TRADE,
            calendar=SESSIONS_0803_05,
        )
        full_root = full.generation_root
    assert full.status == "ACTIVE"
    assert full.state_n == 3191
    assert full.last_processed_20260805_n == 3189  # QA metric, not a gate

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
        verified=VERIFIED_NO_TRADE,
        calendar=SESSIONS_0803_05,
    )
    assert incremental.state_semantic_root_hash == full.state_semantic_root_hash
    assert incremental.state_n == full.state_n
    full_table = pq.read_table(full_root / "screen-output.parquet")
    full_payloads = {
        normalize_output_payload(payload)
        for day, payload in zip(
            full_table["trade_date"].to_pylist(),
            full_table["payload"].to_pylist(),
            strict=True,
        )
        if day > date(2026, 7, 31)
    }
    inc_payloads = set(
        normalize_output_payload(payload)
        for payload in pq.read_table(inc_root / "screen-output.parquet")[
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
        verified=VERIFIED_NO_TRADE,
        calendar=SESSIONS_0803_05,
    )
    assert repeat.state_semantic_root_hash == full.state_semantic_root_hash

    full_generation_manifest = json.loads(
        (full_root / "generation.json").read_text(encoding="utf-8")
    )
    assert (
        full_generation_manifest["state_coverage_through_as_of_n"] == 3191
    )
    assert full_generation_manifest["state_uncovered_n"] == 0
    assert full_generation_manifest["verified_no_trade_covered_n"] == 2
    verification_report = json.loads(
        (full_root / "verification.json").read_text(encoding="utf-8")
    )
    assert verification_report["last_processed_20260805_n"] == 3189
    assert (
        verification_report[
            "latest_confirmed_bar_after_state_last_processed_n"
        ]
        == 0
    )
    coverage = pq.read_table(
        full_root / "state-coverage.parquet"
    ).to_pylist()
    for code in ("000838", "603221"):
        row = next(row for row in coverage if row["code"] == code)
        assert row["state_last_processed_date"] == date(2026, 7, 31)
        assert row["coverage_through"] == date(2026, 8, 5)
        assert row["coverage_status"] == "STATE_COVERED_THROUGH_AS_OF"
        assert row["verified_no_trade_session_n"] == 3

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
