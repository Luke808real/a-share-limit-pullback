"""data-status: freshness and reconciliation state summary."""

from __future__ import annotations

from datetime import date
from typing import Any

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import DataStatusOutput
from limit_pullback.warehouse.snapshot import read_snapshot_daily


def data_status(layout: WarehouseLayout) -> DataStatusOutput:
    if not layout.duckdb_path.exists():
        return DataStatusOutput()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.latest_snapshot()
        by_provider = metadata.raw_max_date_by_provider(str(layout.root))
        counts = metadata.count_by_status()
        quarantined = metadata.quarantine_count()

        latest_canonical_date: date | None = None
        if snapshot is not None:
            rows = read_snapshot_daily(layout, snapshot)
            if rows:
                latest_canonical_date = max(row["trade_date"] for row in rows)
            if latest_canonical_date is None:
                latest_canonical_date = snapshot.as_of

        lagging: list[str] = []
        if snapshot is not None:
            for provider, max_date in by_provider.items():
                if max_date is None or max_date < snapshot.as_of:
                    lagging.append(provider)

        return DataStatusOutput(
            latest_requested_date=snapshot.as_of if snapshot else None,
            latest_available_date_by_provider=dict(by_provider),
            latest_canonical_date=latest_canonical_date,
            reconciliation_status=dict(counts),
            lagging_providers=tuple(sorted(set(lagging))),
            conflicted_rows=int(counts.get("CONFLICTED", 0)),
            quarantined_rows=quarantined,
            dataset_snapshot_id=snapshot.snapshot_id if snapshot else None,
        )
