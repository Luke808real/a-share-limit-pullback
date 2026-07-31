"""Resumable, failure-isolated market fetch for historical bootstrap.

A single interface or single stock failure is recorded in the failure ledger
and never discards already-confirmed batch files. Re-running the same
bootstrap run_id only retries missing/failed items and appends new batches.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any

from limit_pullback.warehouse.auth import redact
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import SourceFileRecord
from limit_pullback.warehouse.parquet import (
    RAW_SCHEMAS,
    row_hash,
    read_rows,
    sha256_file,
    write_rows_atomic,
)

SOURCE_UNITS: dict[tuple[str, str], tuple[str, str]] = {
    ("TUSHARE", "daily_bars"): ("yuan;lots(shou);thousand_yuan", "yuan;shares;yuan"),
    ("TUSHARE", "adjustment_factor"): ("raw_factor", "raw_factor"),
    ("TUSHARE", "daily_basic"): ("percent;wan_yuan", "percent;yuan"),
    ("TUSHARE", "suspension"): ("code", "code"),
    ("TUSHARE", "price_limits"): ("yuan", "yuan"),
    ("AKSHARE", "daily_bars"): ("yuan;shares;yuan", "yuan;shares;yuan"),
    ("AKSHARE", "limit_up_pool"): ("yuan;percent;yuan", "yuan;percent;yuan"),
    ("BAOSTOCK", "daily_bars"): ("yuan;shares;yuan", "yuan;shares;yuan"),
}

HASH_FIELDS: dict[str, tuple[str, ...]] = {
    "daily_bars": (
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
    ),
    "adjustment_factor": ("code", "trade_date", "adj_factor"),
    "daily_basic": (
        "code",
        "trade_date",
        "turnover_rate",
        "volume_ratio",
        "pe",
        "pb",
        "total_mv",
        "circ_mv",
    ),
    "suspension": ("code", "trade_date", "suspend_type", "suspend_timing"),
    "price_limits": ("code", "trade_date", "up_limit", "down_limit"),
    "limit_up_pool": (
        "code",
        "trade_date",
        "name",
        "limit_price",
        "first_seal_time",
        "last_seal_time",
        "open_count",
        "consecutive_count",
        "turnover_rate",
        "float_market_cap",
        "total_market_cap",
        "industry",
    ),
}


def fetch_with_retry(
    function: Callable[[], list[dict[str, Any]]],
    *,
    retries: int = 2,
    backoff_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    attempts = 0
    while True:
        try:
            return function()
        except Exception:
            if attempts >= retries:
                raise
            attempts += 1
            time.sleep(backoff_seconds * (2 ** (attempts - 1)))


def main_board_universe(stock_basic_rows: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    """All legal SH/SZ main-board codes from Tushare stock_basic."""

    codes: set[str] = set()
    for row in stock_basic_rows:
        code = str(row.get("code") or "").zfill(6)
        if code.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
            codes.add(code)
    return tuple(sorted(codes))


def _failure_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


class FetchContext:
    """Progress ledger + batch file writer for one bootstrap run."""

    def __init__(
        self,
        *,
        layout: WarehouseLayout,
        metadata: WarehouseMetadata,
        run_id: str,
        clock: Callable[[], datetime],
        versions: dict[str, str],
        batch_rows: int = 20000,
        retries: int = 2,
        backoff_seconds: float = 1.0,
    ) -> None:
        self.layout = layout
        self.metadata = metadata
        self.run_id = run_id
        self.clock = clock
        self.versions = versions
        self.batch_rows = batch_rows
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.failures: list[dict[str, Any]] = []

    def completed(self, provider: str, dataset: str) -> set[str]:
        return self.metadata.completed_progress_codes(
            run_id=self.run_id, provider=provider, dataset=dataset
        )

    def _mark(self, provider: str, dataset: str, code: str, rows: int) -> None:
        self.metadata.upsert_progress(
            run_id=self.run_id,
            provider=provider,
            dataset=dataset,
            code=code,
            status="COMPLETED",
            rows=rows,
            updated_at=self.clock(),
        )
        self.metadata._connection.execute(
            """
            UPDATE ingest_failures
            SET status = 'RESOLVED', updated_at = ?
            WHERE run_id = ? AND provider = ? AND dataset = ? AND code = ?
            """,
            [self.clock(), self.run_id, provider, dataset, code],
        )

    def _fail(
        self,
        provider: str,
        dataset: str,
        code: str | None,
        trade_date: date | None,
        error: str,
    ) -> None:
        failure_id = _failure_id(
            self.run_id, provider, dataset, code or "", trade_date or ""
        )
        self.metadata.record_failure(
            failure_id=failure_id,
            run_id=self.run_id,
            provider=provider,
            dataset=dataset,
            code=code,
            trade_date=trade_date,
            error=error,
            retry_count=1,
            status="PENDING",
            created_at=self.clock(),
        )
        self.failures.append(
            {
                "provider": provider,
                "dataset": dataset,
                "code": code,
                "trade_date": trade_date.isoformat() if trade_date else None,
                "error": error,
            }
        )

    def _write_batch(
        self,
        provider: str,
        dataset: str,
        rows: Sequence[dict[str, Any]],
        fetched_at: datetime,
    ) -> SourceFileRecord | None:
        directory = self.layout.raw_dataset_dir(provider, dataset)
        sequence = len(list(directory.glob(f"{self.run_id}-*.parquet"))) + 1
        path = directory / f"{self.run_id}-{sequence:04d}.parquet"
        schema = RAW_SCHEMAS[(provider, dataset)]()
        from limit_pullback.warehouse.parquet import quantize_row

        prepared = []
        seen: set[str] = set()
        for row in rows:
            source_unit, normalized_unit = SOURCE_UNITS[(provider, dataset)]
            record = dict(row)
            record["provider"] = provider
            record["provider_version"] = self.versions.get(provider, "unknown")
            record["fetched_at"] = fetched_at
            record["ingest_run_id"] = self.run_id
            record["source_unit"] = source_unit
            record["normalized_unit"] = normalized_unit
            quantized = quantize_row(record, schema)
            quantized["row_hash"] = row_hash(HASH_FIELDS[dataset], quantized)
            digest = quantized.get("row_hash")
            if digest is not None:
                if digest in seen:
                    continue
                seen.add(digest)
            prepared.append(quantized)
        write_rows_atomic(prepared, schema, path)
        record = SourceFileRecord(
            path=str(path),
            provider=provider,
            ingest_run_id=self.run_id,
            sha256=sha256_file(path),
            row_count=len(prepared),
            recorded_at=fetched_at,
        )
        self.metadata.insert_source_file(record)
        return record

    def read_all(self, provider: str, dataset: str) -> list[dict[str, Any]]:
        directory = self.layout.raw_dataset_dir(provider, dataset)
        paths = sorted(directory.glob(f"{self.run_id}-*.parquet"))
        rows: list[dict[str, Any]] = []
        for path in paths:
            rows.extend(read_rows(path))
        return rows


def fetch_rows(
    ctx: FetchContext,
    *,
    provider: str,
    dataset: str,
    items: Sequence[str] | Sequence[date],
    per_item_fn: Callable[[Any], list[dict[str, Any]]] | None = None,
    bulk_fn: Callable[[list[Any]], list[dict[str, Any]]] | None = None,
    use_bulk: bool = False,
    item_is_date: bool = False,
    batch_size: int = 20,
) -> list[dict[str, Any]]:
    """Fetch dataset rows with per-item failure isolation and resume.

    Items are codes (per-code fetch) or trade dates (bulk fetch). Completed
    items from a previous attempt are skipped; failed items are recorded and
    retried on the next run of the same run_id.
    """

    def key(item: Any) -> str:
        if item_is_date:
            return f"DATE:{item.isoformat()}"
        return str(item).zfill(6)

    completed = ctx.completed(provider, dataset)
    pending_rows: list[dict[str, Any]] = []
    pending_keys: list[str] = []
    fetched_at = ctx.clock()

    def flush() -> None:
        if not pending_rows:
            pending_keys.clear()
            return
        ctx._write_batch(provider, dataset, pending_rows, fetched_at)
        for pending_key in pending_keys:
            ctx._mark(provider, dataset, pending_key, 0)
        pending_rows.clear()
        pending_keys.clear()

    if use_bulk and bulk_fn is not None:
        date_items = [item for item in items]
        for offset in range(0, len(date_items), batch_size):
            batch = date_items[offset : offset + batch_size]
            todo = [item for item in batch if key(item) not in completed]
            if not todo:
                continue
            try:
                rows = fetch_with_retry(
                    lambda todo=todo: bulk_fn(todo),
                    retries=ctx.retries,
                    backoff_seconds=ctx.backoff_seconds,
                )
                pending_rows.extend(rows)
                pending_keys.extend(key(item) for item in todo)
            except Exception as exc:
                for item in todo:
                    ctx._fail(
                        provider,
                        dataset,
                        None,
                        item,
                        redact(f"{type(exc).__name__}: {exc}"),
                    )
            flush()
        return ctx.read_all(provider, dataset)

    for item in items:
        item_key = key(item)
        if item_key in completed:
            continue
        try:
            rows = fetch_with_retry(
                lambda item=item: per_item_fn(item),
                retries=ctx.retries,
                backoff_seconds=ctx.backoff_seconds,
            )
            pending_rows.extend(rows)
            pending_keys.append(item_key)
        except Exception as exc:
            ctx._fail(
                provider,
                dataset,
                None if item_is_date else str(item).zfill(6),
                item if item_is_date else None,
                redact(f"{type(exc).__name__}: {exc}"),
            )
        if len(pending_rows) >= ctx.batch_rows:
            flush()
    flush()
    return ctx.read_all(provider, dataset)
