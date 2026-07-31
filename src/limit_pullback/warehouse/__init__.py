"""Phase 2C.2A: reconciled local market-data warehouse.

The warehouse stores provider raw rows in Parquet, publishes canonical rows
through explicit reconciliation snapshots, and keeps metadata (runs, files,
snapshots, reconciliations, quarantines) in DuckDB.
"""

from __future__ import annotations

from limit_pullback.warehouse.auth import TushareTokenError, tushare_token
from limit_pullback.warehouse.layout import (
    DEFAULT_DATA_ROOT,
    ENV_DATA_ROOT,
    WarehouseLayout,
    resolve_data_root,
)

__all__ = [
    "DEFAULT_DATA_ROOT",
    "ENV_DATA_ROOT",
    "TushareTokenError",
    "WarehouseLayout",
    "resolve_data_root",
    "tushare_token",
]
