"""Offline canonical-snapshot readers for the market-wide screen.

The screen never contacts a provider: daily bars are read from the published
canonical snapshot (CONFIRMED rows only) and anchor records from the published
limit-up pool dataset.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from limit_pullback.models.enums import DataQuality
from limit_pullback.models.market import (
    DailyBar,
    DailyBarsRequest,
    DailyBarsResult,
    LimitUpPoolRequest,
    LimitUpPoolResult,
    LimitUpRecord,
)
from limit_pullback.providers.base import DailyBarProvider, LimitUpPoolProvider
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import SnapshotRecord
from limit_pullback.warehouse.snapshot import read_snapshot_daily, read_snapshot_pool

FIXED_FETCHED_AT = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)


def _as_time(value: str | None) -> time | None:
    if value is None:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


class CanonicalDailyBarProvider(DailyBarProvider):
    """Serves CONFIRMED canonical daily bars as a replay-compatible source."""

    provider_name = "CANONICAL"
    provider_version = "phase-2c2b"

    def __init__(
        self,
        bars_by_code: dict[str, tuple[DailyBar, ...]],
        fetched_at: datetime = FIXED_FETCHED_AT,
    ) -> None:
        self._bars_by_code = bars_by_code
        self._fetched_at = fetched_at

    def fetch_daily_bars(self, request: DailyBarsRequest) -> DailyBarsResult:
        bars = tuple(
            bar
            for code in request.codes
            for bar in self._bars_by_code.get(code, ())
            if request.start_date <= bar.trade_date <= request.end_date
        )
        return DailyBarsResult(
            bars=bars,
            quality=DataQuality.OK,
            fetched_at=self._fetched_at,
        )


class CanonicalLimitUpPoolProvider(LimitUpPoolProvider):
    """Serves the published canonical limit-up pool as anchor records."""

    provider_name = "CANONICAL_POOL"
    provider_version = "phase-2c2b"

    def __init__(
        self,
        records_by_date: dict[date, tuple[LimitUpRecord, ...]],
        status_by_key: dict[tuple[str, date], str] | None = None,
        pool_mode: str = "formal",
        fetched_at: datetime = FIXED_FETCHED_AT,
    ) -> None:
        self._records_by_date = records_by_date
        self._status_by_key = status_by_key or {}
        self._pool_mode = pool_mode
        self._fetched_at = fetched_at

    def fetch_limit_up_pool(
        self, request: LimitUpPoolRequest
    ) -> LimitUpPoolResult:
        records = tuple(
            record
            for record in self._records_by_date.get(request.trade_date, ())
            if not request.codes or record.code in request.codes
        )
        flags: list[str] = []
        quality = DataQuality.OK
        if records:
            from limit_pullback.screen.engine import pool_quality

            statuses = {
                self._status_by_key.get((record.code, record.trade_date))
                for record in records
            }
            worst_status = (
                "PROVISIONAL" if "PROVISIONAL" in statuses else
                "CONFIRMED" if statuses == {"CONFIRMED"} else None
            )
            quality, flag = pool_quality(worst_status, pool_mode=self._pool_mode)
            if flag is not None:
                flags.append(flag)
        return LimitUpPoolResult(
            trade_date=request.trade_date,
            records=records,
            quality=quality,
            quality_flags=tuple(sorted(flags)),
            fetched_at=self._fetched_at,
        )


class CanonicalMarketData:
    """Canonical snapshot view for the screen."""

    def __init__(
        self,
        *,
        snapshot: SnapshotRecord,
        bars_by_code: dict[str, tuple[DailyBar, ...]],
        pool_records: tuple[LimitUpRecord, ...],
        pool_status: dict[tuple[str, date], str],
    ) -> None:
        self.snapshot = snapshot
        self.bars_by_code = bars_by_code
        self.pool_records = pool_records
        self.pool_status = pool_status

    @property
    def universe(self) -> tuple[str, ...]:
        return tuple(sorted(self.bars_by_code))

    def daily_provider(self) -> CanonicalDailyBarProvider:
        return CanonicalDailyBarProvider(self.bars_by_code)

    def pool_provider(
        self, *, pool_mode: str = "formal"
    ) -> CanonicalLimitUpPoolProvider:
        by_date: dict[date, tuple[LimitUpRecord, ...]] = {}
        for record in self.pool_records:
            by_date.setdefault(record.trade_date, []).append(record)
        return CanonicalLimitUpPoolProvider(
            {key: tuple(value) for key, value in by_date.items()},
            status_by_key=self.pool_status,
            pool_mode=pool_mode,
        )


def load_canonical_market(
    layout: WarehouseLayout,
    *,
    snapshot_id: str | None = None,
    as_of: date | None = None,
) -> CanonicalMarketData:
    """Load one immutable canonical snapshot; no network access."""

    if not layout.duckdb_path.exists():
        raise ValueError("no dataset snapshot published")
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        if snapshot_id is not None:
            snapshot = metadata.snapshot_by_id(snapshot_id)
            if snapshot is None:
                raise ValueError(f"unknown snapshot: {snapshot_id}")
        elif as_of is not None:
            snapshot = metadata.resolve_snapshot(as_of)
            if snapshot is None:
                raise ValueError(
                    f"no snapshot available for as_of {as_of}; "
                    "pass an explicit --snapshot-id for later-published data"
                )
        else:
            snapshot = metadata.latest_snapshot()
            if snapshot is None:
                raise ValueError("no dataset snapshot published")
        daily_rows = read_snapshot_daily(layout, snapshot)
        pool_rows = read_snapshot_pool(layout, snapshot)

    fetched_at = FIXED_FETCHED_AT
    bars_by_code: dict[str, list[DailyBar]] = {}
    for row in daily_rows:
        if str(row.get("reconciliation_status")) != "CONFIRMED":
            continue
        code = str(row["code"])
        bars_by_code.setdefault(code, []).append(
            DailyBar(
                trade_date=row["trade_date"],
                code=code,
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                preclose=Decimal(row["preclose"]),
                volume=Decimal(row["volume"]),
                amount=Decimal(row["amount"]),
                turnover_rate=(
                    Decimal(row["turnover_rate"])
                    if row.get("turnover_rate") is not None
                    else None
                ),
                pct_change=(
                    Decimal(row["pct_change"])
                    if row.get("pct_change") is not None
                    else None
                ),
                trade_status=bool(row.get("trade_status", True)),
                is_st=(
                    bool(row["is_st"]) if row.get("is_st") is not None else None
                ),
                source="CANONICAL_SCREEN",
                fetched_at=fetched_at,
            )
        )
    pool_records = tuple(
        LimitUpRecord(
            trade_date=row["trade_date"],
            code=str(row["code"]),
            name=str(row["name"]),
            limit_price=Decimal(row["limit_price"]),
            first_seal_time=_as_time(row.get("first_seal_time")),
            last_seal_time=_as_time(row.get("last_seal_time")),
            open_count=row.get("open_count"),
            consecutive_count=row.get("consecutive_count"),
            turnover_rate=(
                Decimal(row["turnover_rate"])
                if row.get("turnover_rate") is not None
                else None
            ),
            float_market_cap=(
                Decimal(row["float_market_cap"])
                if row.get("float_market_cap") is not None
                else None
            ),
            total_market_cap=(
                Decimal(row["total_market_cap"])
                if row.get("total_market_cap") is not None
                else None
            ),
            industry=row.get("industry"),
            source="CANONICAL_POOL",
            fetched_at=fetched_at,
        )
        for row in pool_rows
    )
    pool_status = {
        (str(row["code"]), row["trade_date"]): str(
            row.get("reconciliation_status", "PROVISIONAL")
        )
        for row in pool_rows
    }
    return CanonicalMarketData(
        snapshot=snapshot,
        bars_by_code={
            code: tuple(sorted(bars, key=lambda bar: bar.trade_date))
            for code, bars in bars_by_code.items()
        },
        pool_records=pool_records,
        pool_status=pool_status,
    )
