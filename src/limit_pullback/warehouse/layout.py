"""Warehouse directory layout and data-root resolution."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATA_ROOT = Path("data")
ENV_DATA_ROOT = "LIMIT_PULLBACK_DATA_ROOT"


def resolve_data_root(cli_root: str | Path | None = None) -> Path:
    if cli_root is not None:
        return Path(cli_root).expanduser().resolve()
    env_root = os.environ.get(ENV_DATA_ROOT)
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path.cwd() / DEFAULT_DATA_ROOT


class WarehouseLayout:
    """All paths used by the warehouse, relative to one data root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.raw_tushare_dir = self.root / "raw" / "tushare"
        self.raw_akshare_dir = self.root / "raw" / "akshare"
        self.raw_baostock_dir = self.root / "raw" / "baostock"
        self.canonical_dir = self.root / "canonical"
        self.canonical_daily_dir = self.canonical_dir / "daily_bars"
        self.canonical_pool_dir = self.canonical_dir / "limit_up_pool"
        self.quarantine_dir = self.root / "quarantine"
        self.manifests_dir = self.root / "manifests"
        self.duckdb_path = self.root / "warehouse.duckdb"

    def raw_dataset_dir(self, provider: str, dataset: str) -> Path:
        if provider.upper() == "TUSHARE":
            base = self.raw_tushare_dir
        elif provider.upper() == "AKSHARE":
            base = self.raw_akshare_dir
        elif provider.upper() == "BAOSTOCK":
            base = self.raw_baostock_dir
        else:
            base = self.root / "raw" / provider.lower()
        return base / dataset

    def ensure_dirs(self) -> None:
        for path in (
            self.raw_tushare_dir / "daily_bars",
            self.raw_tushare_dir / "adjustment_factor",
            self.raw_tushare_dir / "daily_basic",
            self.raw_tushare_dir / "suspension",
            self.raw_tushare_dir / "price_limits",
            self.raw_akshare_dir / "daily_bars",
            self.raw_akshare_dir / "limit_up_pool",
            self.raw_baostock_dir / "daily_bars",
            self.canonical_daily_dir,
            self.canonical_pool_dir,
            self.quarantine_dir,
            self.manifests_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
