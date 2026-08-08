"""Offline canonical-snapshot readers for the market-wide screen.

The screen never contacts a provider: daily bars are read from the published
canonical snapshot (CONFIRMED rows only) and anchor records from the published
limit-up pool dataset.
"""

from __future__ import annotations

import os
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
from limit_pullback.warehouse.snapshot import (
    read_snapshot_daily,
    read_snapshot_pool,
    require_formally_usable_snapshot,
    resolve_formal_screen_ready_snapshot,
)

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
    allow_unusable_snapshot_for_forensics: bool = False,
) -> CanonicalMarketData:
    """Load one immutable canonical snapshot; no network access."""

    if not layout.duckdb_path.exists():
        raise ValueError("no dataset snapshot published")
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        if snapshot_id is not None:
            snapshot = metadata.snapshot_by_id(snapshot_id)
            if snapshot is None:
                raise ValueError(f"unknown snapshot: {snapshot_id}")
        else:
            snapshot = resolve_formal_screen_ready_snapshot(metadata)
        require_formally_usable_snapshot(
            snapshot,
            allow_unusable_snapshot_for_forensics=(
                allow_unusable_snapshot_for_forensics
            ),
        )
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
    allow_unusable_snapshot_for_forensics: bool = False,
):
    """Resolve snapshot and small pool metadata without materializing daily bars."""

    if not layout.duckdb_path.exists():
        raise ValueError("no dataset snapshot published")
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        if snapshot_id is not None:
            snapshot = metadata.snapshot_by_id(snapshot_id)
            if snapshot is None:
                raise ValueError(f"unknown snapshot: {snapshot_id}")
        else:
            snapshot = resolve_formal_screen_ready_snapshot(metadata)
        require_formally_usable_snapshot(
            snapshot,
            allow_unusable_snapshot_for_forensics=(
                allow_unusable_snapshot_for_forensics
            ),
        )
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
    """Yield each code's complete CONFIRMED bar history exactly once.

    The canonical parquet may store one code in multiple physically separated
    blocks (history block + appended rows).  This reader never assumes code
    contiguity: rows are merged through a memory-bounded ordered scan, sorted
    by ``(code, trade_date)``, identical duplicates are deduplicated, and
    conflicting duplicates fail closed.
    """

    current_code: str | None = None
    current_bars: list[DailyBar] = []

    def flush() -> Iterator[tuple[str, tuple[DailyBar, ...]]]:
        nonlocal current_code, current_bars
        if current_code is not None and current_bars:
            yield current_code, tuple(current_bars)
        current_code = None
        current_bars = []

    for row in _canonical_daily_row_stream(
        layout,
        snapshot,
        codes=codes,
        as_of=as_of,
    ):
        code = str(row["code"])
        if current_code is not None and code != current_code:
            yield from flush()
        current_code = code
        current_bars.append(_daily_bar_from_row(row, fetched_at=fetched_at))
    yield from flush()


def _canonical_daily_row_stream(
    layout: WarehouseLayout,
    snapshot: SnapshotRecord,
    *,
    codes: Sequence[str] | None = None,
    as_of: date | None = None,
) -> Iterator[dict[str, Any]]:
    """Memory-bounded, globally ordered CONFIRMED daily row stream.

    Uses DuckDB's external sort (bounded by 2GB) so the reader does not rely
    on physical row contiguity.  Identical ``(code, trade_date)`` duplicates
    are deduplicated; conflicting duplicates fail closed.
    """

    import duckdb
    import re

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
    columns = (
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
        "selected_provider",
        "reconciliation_status",
        "source_row_hash",
        "dataset_snapshot_id",
    )
    sql = (
        f"SELECT {', '.join(columns)} FROM read_parquet(?) "
        "WHERE reconciliation_status = 'CONFIRMED'"
    )
    params: list[Any] = [str(layout.root / daily_rel)]
    if codes is not None:
        normalized = tuple(str(code).zfill(6) for code in codes)
        for code in normalized:
            if not re.fullmatch(r"\d{6}", code):
                raise ValueError(f"invalid canonical code: {code}")
        sql += f" AND code IN ({','.join('?' for _ in normalized)})"
        params.extend(normalized)
    if as_of is not None:
        sql += " AND trade_date <= CAST(? AS DATE)"
        params.append(as_of.isoformat())
    sql += " ORDER BY code, trade_date"

    con = duckdb.connect()
    con.execute(
        "SET threads='"
        + os.environ.get("LIMIT_PULLBACK_CANONICAL_READER_THREADS", "4")
        + "'"
    )
    con.execute("SET enable_progress_bar=false")
    con.execute(
        "SET memory_limit='"
        + os.environ.get(
            "LIMIT_PULLBACK_CANONICAL_READER_MEMORY_LIMIT",
            "2GB",
        )
        + "'"
    )
    cursor = con.execute(sql, params)
    field_names = [description[0] for description in cursor.description]
    seen_key: tuple[str, date] | None = None
    seen_row: dict[str, Any] | None = None
    while True:
        batch = cursor.fetchmany(20000)
        if not batch:
            break
        for raw in batch:
            row = dict(zip(field_names, raw, strict=True))
            key = (str(row["code"]), row["trade_date"])
            if key == seen_key:
                if seen_row is not None and _canonical_row_content(row) != (
                    _canonical_row_content(seen_row)
                ):
                    raise ValueError(
                        "DUPLICATE_CANONICAL_ROW_CONFLICT:"
                        f"{key[0]}:{key[1].isoformat()}"
                    )
                continue
            seen_key = key
            seen_row = row
            yield row


def _canonical_row_content(row: Mapping[str, Any]) -> tuple[Any, ...]:
    keys = (
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
        "selected_provider",
        "reconciliation_status",
        "source_row_hash",
        "dataset_snapshot_id",
    )
    return tuple(row.get(key) for key in keys)


def canonical_universe_codes(
    layout: WarehouseLayout,
    snapshot: SnapshotRecord,
) -> tuple[str, ...]:
    """Sorted CONFIRMED universe codes from canonical daily Parquet."""

    import duckdb

    daily_rel = next(
        (
            key
            for key in snapshot.canonical_file_hashes
            if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
        ),
        None,
    )
    if daily_rel is None:
        return ()
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='2GB'")
    rows = con.execute(
        f"SELECT DISTINCT code FROM read_parquet('{layout.root / daily_rel}') "
        "WHERE reconciliation_status='CONFIRMED' ORDER BY code"
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _load_daily_bars_stream(
    layout: WarehouseLayout,
    snapshot: SnapshotRecord,
    *,
    codes: tuple[str, ...] | None,
    as_of: date | None,
    fetched_at: datetime,
    stats: dict[str, Any] | None,
) -> dict[str, tuple[DailyBar, ...]]:
    """Load complete per-code bars using the contiguity-safe ordered stream."""

    bars_by_code: dict[str, list[DailyBar]] = {}
    rows_read = 0
    rows_materialized = 0
    for row in _canonical_daily_row_stream(
        layout,
        snapshot,
        codes=codes,
        as_of=as_of,
    ):
        rows_read += 1
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
        rows_materialized += 1
    if stats is not None:
        stats["rows_read"] = rows_read
        stats["rows_materialized"] = rows_materialized
    return {
        code: tuple(sorted(bars, key=lambda bar: bar.trade_date))
        for code, bars in bars_by_code.items()
    }
