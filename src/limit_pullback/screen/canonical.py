"""Offline canonical-snapshot readers for the market-wide screen.

The screen never contacts a provider: daily bars are read from the published
canonical snapshot (CONFIRMED rows only) and anchor records from the published
limit-up pool dataset.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Sequence

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
    codes: Sequence[str] | None = None,
    stats: dict[str, Any] | None = None,
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
        pool_rows = read_snapshot_pool(layout, snapshot)

    fetched_at = FIXED_FETCHED_AT
    requested_codes = tuple(sorted(set(codes))) if codes else None
    bars_by_code = _load_daily_bars_stream(
        layout,
        snapshot,
        codes=requested_codes,
        as_of=as_of,
        fetched_at=fetched_at,
        stats=stats,
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


def load_canonical_metadata(
    layout: WarehouseLayout,
    *,
    snapshot_id: str | None = None,
    as_of: date | None = None,
):
    """Resolve snapshot and small pool metadata without materializing daily bars."""

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
        pool_rows = read_snapshot_pool(layout, snapshot)
    fetched_at = FIXED_FETCHED_AT
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
    return snapshot, pool_records, pool_status


def _daily_bar_from_row(
    row: dict[str, Any],
    *,
    fetched_at: datetime,
) -> DailyBar:
    return DailyBar(
        trade_date=row["trade_date"],
        code=str(row["code"]),
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


def iter_canonical_code_bars(
    layout: WarehouseLayout,
    snapshot: SnapshotRecord,
    *,
    codes: Sequence[str] | None = None,
    as_of: date | None = None,
    fetched_at: datetime = FIXED_FETCHED_AT,
) -> Iterator[tuple[str, tuple[DailyBar, ...]]]:
    """Single sequential Parquet pass yielding one code's bars at a time."""

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    daily_rel = next(
        (
            key
            for key in snapshot.canonical_file_hashes
            if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
        ),
        None,
    )
    if daily_rel is None:
        return
    path = layout.root / daily_rel
    pf = pq.ParquetFile(path)
    columns = [
        "code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "turnover_rate",
        "pct_change",
        "trade_status",
        "is_st",
        "reconciliation_status",
    ]
    requested = tuple(sorted(set(codes))) if codes else None
    value_set = pa.array(requested) if requested else None
    current_code: str | None = None
    current_bars: list[DailyBar] = []

    def flush() -> Iterator[tuple[str, tuple[DailyBar, ...]]]:
        nonlocal current_code, current_bars
        if current_code is not None and current_bars:
            yield current_code, tuple(current_bars)
        current_code = None
        current_bars = []

    for batch in pf.iter_batches(
        columns=columns,
        batch_size=4096,
        use_threads=False,
    ):
        if value_set is not None:
            batch = batch.filter(pc.is_in(batch["code"], value_set=value_set))
        batch = batch.filter(
            pc.equal(batch["reconciliation_status"], pa.scalar("CONFIRMED"))
        )
        if as_of is not None:
            batch = batch.filter(pc.less_equal(batch["trade_date"], pa.scalar(as_of)))
        for row in batch.to_pylist():
            code = str(row["code"])
            if current_code is not None and code != current_code:
                yield from flush()
            current_code = code
            current_bars.append(_daily_bar_from_row(row, fetched_at=fetched_at))
    yield from flush()


def _load_daily_bars_stream(
    layout: WarehouseLayout,
    snapshot: SnapshotRecord,
    *,
    codes: tuple[str, ...] | None,
    as_of: date | None,
    fetched_at: datetime,
    stats: dict[str, Any] | None,
) -> dict[str, tuple[DailyBar, ...]]:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    daily_rel = next(
        (
            key
            for key in snapshot.canonical_file_hashes
            if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
        ),
        None,
    )
    if daily_rel is None:
        return {}
    path = layout.root / daily_rel
    pf = pq.ParquetFile(path)
    code_index = pf.schema_arrow.names.index("code")
    columns = [
        "code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "turnover_rate",
        "pct_change",
        "trade_status",
        "is_st",
        "reconciliation_status",
    ]
    row_groups = list(range(pf.metadata.num_row_groups))
    if codes is not None:
        selected: list[int] = []
        for index in row_groups:
            row_group = pf.metadata.row_group(index)
            column_stats = row_group.column(code_index).statistics
            if column_stats is None or column_stats.min is None or column_stats.max is None:
                selected.append(index)
                continue
            lo = str(column_stats.min)
            hi = str(column_stats.max)
            if any(lo <= code <= hi for code in codes):
                selected.append(index)
        row_groups = selected
    value_set = pa.array(sorted(codes)) if codes is not None else None
    bars_by_code: dict[str, list[DailyBar]] = {}
    rows_read = 0
    rows_materialized = 0
    for group in row_groups:
        for batch in pf.iter_batches(
            row_groups=[group],
            columns=columns,
            batch_size=4096,
            use_threads=False,
        ):
            rows_read += batch.num_rows
            if value_set is not None:
                batch = batch.filter(pc.is_in(batch["code"], value_set=value_set))
            batch = batch.filter(
                pc.equal(batch["reconciliation_status"], pa.scalar("CONFIRMED"))
            )
            if as_of is not None:
                batch = batch.filter(pc.less_equal(batch["trade_date"], pa.scalar(as_of)))
            for row in batch.to_pylist():
                rows_materialized += 1
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
                            bool(row["is_st"])
                            if row.get("is_st") is not None
                            else None
                        ),
                        source="CANONICAL_SCREEN",
                        fetched_at=fetched_at,
                    )
                )
    if stats is not None:
        stats["rows_read"] = rows_read
        stats["rows_materialized"] = rows_materialized
    return {
        code: tuple(sorted(bars, key=lambda bar: bar.trade_date))
        for code, bars in bars_by_code.items()
    }
