"""PR-D real integration: dry + real atomic promotion of corrected snapshot."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.derived_limit_event import (
    build_derived_limit_events,
    derived_event_content_hash,
)
from limit_pullback.universe import phase2d0_universe_from_snapshot
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import sha256_file
from limit_pullback.warehouse.promotion import promote_snapshot

pytestmark = pytest.mark.integration

PRB_STAGING_HASH = (
    "2c4472eeb49484a8425aa2497979d009b77da0d19736f42b2f39c182d930adf3"
)
DERIVED_EVENT_HASH = (
    "2b721d660070f9cf664c2925129bcb8270ccbfbec224b2e8bdb6a40f9f4d9acf"
)
UNIVERSE_HASH = (
    "8d1f99b1b9aac72a9ddfbe898def2f12c59938f83f012fe46017951e24ef1afb"
)
BAD_DAILY = (
    "ce9b489292b79d5a482bfc7f2aa027326587cf1687cea13e532ed1a30b405b16"
)


def _layout() -> WarehouseLayout:
    root = Path(__file__).resolve().parents[2] / "data"
    if not (root / "warehouse.duckdb").exists():
        pytest.skip("real data root not present")
    return WarehouseLayout(root)


def _snapshot(layout, snapshot_id):
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(snapshot_id)
    assert snapshot is not None
    return snapshot


def _inputs(layout, config):
    base = _snapshot(layout, "snap-2026-07-31-b5f84004de8a")
    universe = phase2d0_universe_from_snapshot(layout, base)
    assert universe.member_n == 3191
    assert universe.member_hash == UNIVERSE_HASH
    staged = pq.read_table(
        layout.root
        / "tmp"
        / "staging"
        / "adr008"
        / "adr008-staging-20260805-tdx-tencent-v1"
        / "canonical_candidate.parquet"
    ).to_pylist()
    staging_manifest_path = (
        layout.root
        / "tmp"
        / "staging"
        / "adr008"
        / "adr008-staging-20260805-tdx-tencent-v1"
        / "manifest.json"
    )
    declared_hash = json.loads(
        staging_manifest_path.read_text(encoding="utf-8")
    )["staging_canonical_hash"]
    assert declared_hash == PRB_STAGING_HASH
    events = build_derived_limit_events(
        [
            {
                "code": row["code"],
                "trade_date": row["trade_date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "preclose": row["preclose"],
                "source_daily_hash": row.get("selected_source_hash") or "",
            }
            for row in staged
            if row.get("close") is not None
            and row.get("preclose") is not None
            and row["code"] in set(universe.members)
        ],
        source_id="adr008-staging-20260805-tdx-tencent-v1",
        config=config,
        universe_members=set(universe.members),
    )
    assert derived_event_content_hash(events) == DERIVED_EVENT_HASH
    return {
        "base_snapshot_id": base.snapshot_id,
        "staged_rows": staged,
        "prb_staging_hash": PRB_STAGING_HASH,
        "prb_staging_manifest_path": staging_manifest_path,
        "universe": universe,
        "derived_events": events,
        "derived_event_hash": DERIVED_EVENT_HASH,
        "config": config,
        "raw_tdx_path": (
            layout.root
            / "tmp"
            / "canonical-catchup-2026-08"
            / "raw_tdx_full.parquet"
        ),
        "raw_tencent_path": (
            layout.root
            / "tmp"
            / "canonical-catchup-2026-08"
            / "raw_tencent_full.parquet"
        ),
        "verified_no_trade": (
            ("600530", date(2026, 8, 3)),
            ("603221", date(2026, 8, 3)),
            ("603221", date(2026, 8, 4)),
            ("000838", date(2026, 8, 3)),
            ("000838", date(2026, 8, 4)),
            ("002214", date(2026, 8, 4)),
        ),
    }


def test_prd_real_dry_and_promotion():
    layout = _layout()
    config = load_strategy_config(
        Path(__file__).resolve().parents[2] / "config" / "strategy.yaml"
    )
    kwargs = _inputs(layout, config)
    states_before = len(
        list((layout.root / "screen" / "states").glob("[0-9]*.json"))
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        bad = metadata.snapshot_by_id("snap-2026-08-05-d9e93fccc966")
        pointer_before = metadata.get_formal_pointer()
    assert bad.status == "QUARANTINED"

    dry = promote_snapshot(layout, **kwargs, dry_run=True)
    if not dry.idempotent:
        assert dry.status == "STAGED"
        assert dry.published_20260803_n == 3188
        assert dry.published_20260804_n == 5194
        assert dry.published_20260805_n == 5196
        assert dry.legacy_pool_published_n == 901
        assert dry.derived_20260803_published_n == 75
        assert dry.derived_20260804_published_n == 125
        assert dry.derived_20260805_published_n == 97
        with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
            assert metadata.snapshot_by_id(dry.snapshot_id) is None
            assert metadata.get_formal_pointer() == pointer_before

    result = promote_snapshot(layout, **kwargs)
    assert result.status == "SCREEN_READY"
    assert result.snapshot_id == dry.snapshot_id
    assert result.formal_pointer_after == result.snapshot_id
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        pointer = metadata.get_formal_pointer()
        promoted = metadata.snapshot_by_id(result.snapshot_id)
        validation_row = metadata._connection.execute(
            """
            SELECT report_hash FROM snapshot_validation_records
            WHERE snapshot_id = ?
            """,
            [result.snapshot_id],
        ).fetchone()
    assert pointer[0] == result.snapshot_id
    assert pointer[1] is not None
    assert validation_row is not None
    assert validation_row[0] == pointer[1]
    assert promoted.status == "SCREEN_READY"
    assert promoted.manifest_path is not None

    # Idempotent repromotion.
    again = promote_snapshot(layout, **kwargs)
    assert again.idempotent is True
    assert again.snapshot_id == result.snapshot_id

    # Invariants.
    assert bad.status == "QUARANTINED"
    assert sha256_file(
        layout.canonical_dir
        / "daily_bars"
        / "snap-2026-08-05-d9e93fccc966.parquet"
    ) == BAD_DAILY
    states_after = len(
        list((layout.root / "screen" / "states").glob("[0-9]*.json"))
    )
    assert states_after == states_before
    manifest = json.loads(
        (layout.manifests_dir / f"{result.snapshot_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert "/Users/" not in json.dumps(manifest)
    assert manifest["parent_snapshot"] == "snap-2026-07-31-b5f84004de8a"
    assert manifest["daily_source_staging_hash"] == PRB_STAGING_HASH
    assert manifest["derived_event_hash"] == DERIVED_EVENT_HASH
    assert manifest["universe_hash"] == UNIVERSE_HASH
