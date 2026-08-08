"""2026-08-06 daily catch-up + state evolution real invariants."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata

pytestmark = pytest.mark.integration

SNAPSHOT_ID = "snap-2026-08-06-e798f88ff67b"
GENERATION_ID = "stategen-2026-08-06-a846075a5ac7"
BASE_SNAPSHOT_ID = "snap-2026-08-05-49a843e6d7aa"
BAD_SNAPSHOT_ID = "snap-2026-08-05-d9e93fccc966"
UNIVERSE_HASH = (
    "8d1f99b1b9aac72a9ddfbe898def2f12c59938f83f012fe46017951e24ef1afb"
)


def _layout() -> WarehouseLayout:
    root = Path(__file__).resolve().parents[2] / "data"
    if not (root / "warehouse.duckdb").exists():
        pytest.skip("real data root not present")
    return WarehouseLayout(root)


def test_daily_20260806_snapshot_and_state_generation_invariants():
    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        pointer = metadata.get_formal_pointer()
        state_pointer = metadata.get_formal_state_pointer()
        snapshot = metadata.snapshot_by_id(SNAPSHOT_ID)
        base = metadata.snapshot_by_id(BASE_SNAPSHOT_ID)
        bad = metadata.snapshot_by_id(BAD_SNAPSHOT_ID)
        generation = metadata.state_generation_by_id(GENERATION_ID)
    assert pointer == (SNAPSHOT_ID, "cc3a163e42022a8b5fd1158539fccbcaff4f8e3ab9278ae5f6c7d51847742e4d")
    assert state_pointer == GENERATION_ID
    assert snapshot is not None and snapshot.status == "SCREEN_READY"
    assert snapshot.as_of == date(2026, 8, 6)
    assert base is not None and base.status == "SCREEN_READY"
    assert bad is not None and bad.status == "QUARANTINED"
    assert generation["status"] == "ACTIVE"
    assert generation["snapshot_id"] == SNAPSHOT_ID
    assert generation["universe_hash"] == UNIVERSE_HASH
    generation_root = layout.root / "screen" / "generations" / GENERATION_ID
    verification = json.loads(
        (generation_root / "verification.json").read_text(encoding="utf-8")
    )
    assert verification["state_n"] == 3191
    assert verification["state_coverage_through_as_of_n"] == 3191
    assert verification["state_uncovered_n"] == 0
    assert verification["passed"] is True
