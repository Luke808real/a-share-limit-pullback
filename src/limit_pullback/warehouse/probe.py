"""Provider capability probing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import ProbeResult
from limit_pullback.warehouse.tushare_provider import TushareProProvider


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def probe_tushare(
    *,
    layout: WarehouseLayout | None = None,
    provider: TushareProProvider | None = None,
    clock: Callable[[], datetime] = _now_utc,
) -> ProbeResult:
    """Probe Tushare capabilities and optionally persist results to DuckDB."""

    probe_provider = provider or TushareProProvider(clock=clock)
    result = probe_provider.probe_all()
    if layout is not None:
        layout.ensure_dirs()
        with WarehouseMetadata(layout.duckdb_path) as metadata:
            checked_at = clock()
            for capability in result.capabilities:
                metadata.record_capability(
                    provider="TUSHARE",
                    capability=capability.capability,
                    status=capability.status,
                    checked_at=checked_at,
                    provider_version=result.provider_version,
                    error_code=capability.error_code,
                    detail=capability.detail,
                )
    return result
