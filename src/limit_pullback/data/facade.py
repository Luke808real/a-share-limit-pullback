"""Transitional data-layer facade over warehouse capabilities (P3).

The screen orchestration modules need five warehouse primitives:
`WarehouseLayout`, `WarehouseMetadata`, `sha256_file`, `write_json_atomic`,
`require_state_snapshot_usable`, `snapshot_status_map`. This module re-exports
the same objects so screen depends on the data layer, not on warehouse
internals. Identity re-exports only — behavior is unchanged.
"""

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import SnapshotRecord
from limit_pullback.warehouse.parquet import sha256_file, write_json_atomic
from limit_pullback.warehouse.asl_adapter import (
    CONTRACT_VERSION as ASL_CONTRACT_VERSION,
    TESTED_COMPAT_REVISION as ASL_TESTED_COMPAT_REVISION,
)
from limit_pullback.warehouse.snapshot import (
    require_formally_usable_snapshot,
    require_state_snapshot_usable,
    snapshot_status_map,
)

__all__ = [
    "WarehouseLayout",
    "WarehouseMetadata",
    "SnapshotRecord",
    "ASL_CONTRACT_VERSION",
    "ASL_TESTED_COMPAT_REVISION",
    "require_formally_usable_snapshot",
    "require_state_snapshot_usable",
    "sha256_file",
    "snapshot_status_map",
    "write_json_atomic",
]
