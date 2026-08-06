"""PR-C real-data regressions against the safe 7/31 snapshot (integration)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.prc_audit import (
    anchor_regression_0731,
    build_snapshot_derived_pool,
    load_legacy_pool_records,
)
from limit_pullback.universe import phase2d0_universe_from_snapshot
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import sha256_file

pytestmark = pytest.mark.integration

FROZEN_FULL_MARKET_HASH = (
    "9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec"
)
FROZEN_FULL_MARKET_ROWS = 1844543
PRB_STAGING_HASH = (
    "2c4472eeb49484a8425aa2497979d009b77da0d19736f42b2f39c182d930adf3"
)


def _layout() -> WarehouseLayout:
    root = Path(__file__).resolve().parents[2] / "data"
    if not (root / "warehouse.duckdb").exists():
        pytest.skip("real data root not present")
    return WarehouseLayout(root)


def _snapshot(layout: WarehouseLayout, snapshot_id: str):
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(snapshot_id)
    assert snapshot is not None
    return snapshot


def test_phase2d0_universe_0731_exact_3191():
    layout = _layout()
    snapshot = _snapshot(layout, "snap-2026-07-31-b5f84004de8a")
    universe = phase2d0_universe_from_snapshot(layout, snapshot)
    assert universe.member_n == 3191
    assert universe.member_hash == (
        "8d1f99b1b9aac72a9ddfbe898def2f12c59938f83f012fe46017951e24ef1afb"
    )
    # Membership identity is CONFIRMED rows + SH/SZ MAIN board.
    baseline = set(universe.members)
    assert len(baseline) == 3191


def test_bad_d9e_stays_quarantined():
    layout = _layout()
    snapshot = _snapshot(layout, "snap-2026-08-05-d9e93fccc966")
    assert snapshot.status == "QUARANTINED"


def test_prb_staging_hash_unchanged():
    layout = _layout()
    manifest = json.loads(
        (
            layout.root
            / "tmp"
            / "staging"
            / "adr008"
            / "adr008-staging-20260805-tdx-tencent-v1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["staging_canonical_hash"] == PRB_STAGING_HASH


def test_0731_anchor_exact_regression():
    layout = _layout()
    snapshot = _snapshot(layout, "snap-2026-07-31-b5f84004de8a")
    config = load_strategy_config(
        Path(__file__).resolve().parents[2] / "config" / "strategy.yaml"
    )
    legacy = load_legacy_pool_records(layout, snapshot)
    result = anchor_regression_0731(
        layout,
        snapshot,
        config=config,
        legacy_pool=legacy,
    )
    assert result["anchor_regression_diff_n"] == 0
    assert result["old_full_n"] == result["new_full_n"]
    assert result["old_price_only_n"] == result["new_price_only_n"]


def test_0731_full_screen_hash_regression(monkeypatch, tmp_path):
    layout = _layout()
    snapshot = _snapshot(layout, "snap-2026-07-31-b5f84004de8a")
    config = load_strategy_config(
        Path(__file__).resolve().parents[2] / "config" / "strategy.yaml"
    )
    legacy = load_legacy_pool_records(layout, snapshot)
    _, derived_records = build_snapshot_derived_pool(
        layout,
        snapshot,
        config=config,
        legacy_pool=legacy,
        source_id="prc-0731-derived-v1",
    )

    import limit_pullback.screen.runner as runner_mod

    def fake_loader(layout, *, snapshot_id=None, as_of=None, **kwargs):
        return snapshot, derived_records, {
            (record.code, record.trade_date): "CONFIRMED"
            for record in derived_records
        }

    def noop_save_state(*args, **kwargs):
        return None

    monkeypatch.setattr(runner_mod, "load_canonical_metadata", fake_loader)
    monkeypatch.setattr(runner_mod, "save_state", noop_save_state)
    output_path = tmp_path / "screen-prc-0731.json"
    result = runner_mod.run_screen(
        layout=layout,
        as_of=snapshot.as_of,
        start=date(2024, 1, 1),
        rebuild=True,
        codes=None,
        config_path=Path(__file__).resolve().parents[2] / "config" / "strategy.yaml",
        manifest_path_override=output_path,
    )
    assert result.output_hash == FROZEN_FULL_MARKET_HASH
    assert result.rows_count == FROZEN_FULL_MARKET_ROWS
