"""Snapshot-backed CanonicalDataPort adapter (REF-R3).

Reads one formally usable immutable snapshot through the same memory-bounded
canonical row stream the legacy screen path uses, so values are identical by
construction. Fail closed: unknown snapshots raise; missing rows surface as
None/UNKNOWN instead of silent falses.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from limit_pullback.data.canonical import _canonical_daily_row_stream
from limit_pullback.data.universe import phase2d0_universe_from_snapshot
from limit_pullback.domain.provenance import DataProvenance
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import (
    CanonicalDailyBar,
    SnapshotRecord,
)
from limit_pullback.warehouse.snapshot import require_formally_usable_snapshot

ADAPTER_VERSION = "data.snapshot-adapter-v1"


class SnapshotDataAdapter:
    """CanonicalDataPort over one immutable canonical snapshot."""

    def __init__(
        self,
        layout: WarehouseLayout,
        *,
        snapshot_id: str,
        allow_unusable_snapshot_for_forensics: bool = False,
    ) -> None:
        if not layout.duckdb_path.exists():
            raise ValueError("no dataset snapshot published")
        with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
            snapshot = metadata.snapshot_by_id(snapshot_id)
            if snapshot is None:
                raise ValueError(f"unknown snapshot: {snapshot_id}")
            require_formally_usable_snapshot(
                snapshot,
                allow_unusable_snapshot_for_forensics=(
                    allow_unusable_snapshot_for_forensics
                ),
            )
            self._snapshot: SnapshotRecord = snapshot
        self._layout = layout

    def _rows(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> Iterator[dict[str, Any]]:
        if not symbol.isdigit() or len(symbol) != 6:
            raise ValueError(f"invalid canonical code: {symbol}")
        if start > end:
            raise ValueError("start cannot be after end")
        for row in _canonical_daily_row_stream(
            self._layout,
            self._snapshot,
            codes=(symbol,),
            as_of=end,
        ):
            if row["trade_date"] < start:
                continue
            yield row

    def get_daily(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> tuple[CanonicalDailyBar, ...]:
        bars = []
        for row in self._rows(symbol, start, end):
            bars.append(
                CanonicalDailyBar(
                    code=str(row["code"]),
                    trade_date=row["trade_date"],
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    preclose=Decimal(str(row["preclose"])),
                    volume=Decimal(str(row["volume"])),
                    amount=Decimal(str(row["amount"])),
                    turnover_rate=(
                        Decimal(str(row["turnover_rate"]))
                        if row.get("turnover_rate") is not None
                        else None
                    ),
                    pct_change=(
                        Decimal(str(row["pct_change"]))
                        if row.get("pct_change") is not None
                        else None
                    ),
                    trade_status=bool(row.get("trade_status", True)),
                    is_st=(
                        bool(row["is_st"])
                        if row.get("is_st") is not None
                        else None
                    ),
                    selected_provider=str(row["selected_provider"]),
                    reconciliation_status=str(row["reconciliation_status"]),
                    source_row_hash=str(row["source_row_hash"]),
                    dataset_snapshot_id=str(row["dataset_snapshot_id"]),
                )
            )
        return tuple(bars)

    def get_daily_universe(self, as_of: date) -> tuple[str, ...]:
        universe = phase2d0_universe_from_snapshot(
            self._layout,
            self._snapshot,
            as_of=as_of,
        )
        return tuple(universe.members)

    def get_trading_status(self, symbol: str, day: date) -> str | None:
        rows = self.get_daily(symbol, day, day)
        if not rows:
            return None
        row = rows[0]
        if row.is_st is None:
            return "UNKNOWN"
        if row.is_st is True:
            return "ST"
        if row.trade_status is False:
            return "NO_TRADE"
        return "NORMAL"

    def get_corporate_action(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> tuple[object, ...]:
        raise NotImplementedError(
            "corporate action port is a future interface; no authorized consumer"
        )

    def get_minute(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> tuple[object, ...]:
        raise NotImplementedError(
            "minute bar port is a future interface; no authorized consumer"
        )

    def get_data_provenance(self) -> DataProvenance:
        manifest_hash = None
        if self._snapshot.manifest_path:
            manifest_path = Path(self._snapshot.manifest_path)
            if manifest_path.is_file():
                manifest_hash = hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest()
        return DataProvenance(
            data_provider_system="canonical-snapshot",
            data_snapshot_id=self._snapshot.snapshot_id,
            data_as_of=self._snapshot.as_of,
            source_version=self._snapshot.reconciliation_policy_version,
            adapter_version=ADAPTER_VERSION,
            coverage=f"canonical_file_hashes={len(self._snapshot.canonical_file_hashes)}",
            quality_summary=self._snapshot.status,
            hash=manifest_hash,
        )


__all__ = ["ADAPTER_VERSION", "SnapshotDataAdapter"]
