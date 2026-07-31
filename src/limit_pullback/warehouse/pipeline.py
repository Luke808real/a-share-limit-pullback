"""Historical bootstrap and idempotent daily incremental update."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from limit_pullback.warehouse.auth import redact
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.locking import WarehouseLock
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import (
    BootstrapResult,
    QuarantineRecord,
    ReconciliationRecord,
    SourceFileRecord,
    UpdateResult,
)
from limit_pullback.warehouse.parquet import (
    RAW_SCHEMAS,
    quantize_row,
    row_hash,
    sha256_file,
    write_rows_atomic,
)
from limit_pullback.warehouse.providers import RealWarehouseProviderSet, WarehouseProviderSet
from limit_pullback.warehouse.reconciliation import (
    INCOMPLETE,
    ReconciliationPolicy,
    reconcile_daily_rows,
    reconcile_limit_up_pool,
)
from limit_pullback.warehouse.snapshot import (
    create_snapshot,
    read_snapshot_daily,
    read_snapshot_pool,
)
from limit_pullback.warehouse.tushare_provider import CapabilityUnavailable

DATASETS_BY_PROVIDER: dict[str, tuple[tuple[str, str, str], ...]] = {
    "TUSHARE": (
        ("daily_bars", "yuan;lots(shou);thousand_yuan", "yuan;shares;yuan"),
        ("adjustment_factor", "raw_factor", "raw_factor"),
        ("daily_basic", "percent;wan_yuan", "percent;yuan"),
        ("suspension", "code", "code"),
        ("price_limits", "yuan", "yuan"),
    ),
    "AKSHARE": (
        ("daily_bars", "yuan;shares;yuan", "yuan;shares;yuan"),
        ("limit_up_pool", "yuan;percent;yuan", "yuan;percent;yuan"),
    ),
    "BAOSTOCK": (
        ("daily_bars", "yuan;shares;yuan", "yuan;shares;yuan"),
    ),
}

HASH_FIELDS_BY_DATASET: dict[str, tuple[str, ...]] = {
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


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _run_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _dedupe(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        digest = row["row_hash"]
        if digest in seen:
            continue
        seen.add(digest)
        result.append(dict(row))
    return result


def _cleanup_run_files(layout: WarehouseLayout, metadata: WarehouseMetadata, run_id: str) -> None:
    for provider, datasets in DATASETS_BY_PROVIDER.items():
        for dataset, _, _ in datasets:
            directory = layout.raw_dataset_dir(provider, dataset)
            for path in directory.glob(f"{run_id}.parquet"):
                path.unlink(missing_ok=True)
            for path in directory.glob(f".{run_id}.parquet.tmp-*"):
                path.unlink(missing_ok=True)
    metadata.delete_source_files_for_run(run_id)


def _add_metadata(
    provider: str,
    provider_version: str,
    fetched_at: datetime,
    run_id: str,
    source_unit: str,
    normalized_unit: str,
    dataset: str,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    record = dict(row)
    record["provider"] = provider
    record["provider_version"] = provider_version
    record["fetched_at"] = fetched_at
    record["ingest_run_id"] = run_id
    record["source_unit"] = source_unit
    record["normalized_unit"] = normalized_unit
    record["row_hash"] = row_hash(HASH_FIELDS_BY_DATASET[dataset], record)
    return record


def _write_dataset(
    *,
    layout: WarehouseLayout,
    metadata: WarehouseMetadata,
    run_id: str,
    provider: str,
    provider_version: str,
    dataset: str,
    source_unit: str,
    normalized_unit: str,
    rows: Sequence[Mapping[str, Any]],
    fetched_at: datetime,
) -> tuple[SourceFileRecord | None, list[dict[str, Any]]]:
    raw_rows = [
        _add_metadata(
            provider,
            provider_version,
            fetched_at,
            run_id,
            source_unit,
            normalized_unit,
            dataset,
            row,
        )
        for row in rows
    ]
    schema = RAW_SCHEMAS[(provider, dataset)]()
    raw_rows = [quantize_row(row, schema) for row in raw_rows]
    for row in raw_rows:
        row["row_hash"] = row_hash(HASH_FIELDS_BY_DATASET[dataset], row)
    raw_rows = _dedupe(raw_rows)
    directory = layout.raw_dataset_dir(provider, dataset)
    path = directory / f"{run_id}.parquet"
    write_rows_atomic(raw_rows, schema, path)
    digest = sha256_file(path)
    record = SourceFileRecord(
        path=str(path),
        provider=provider,
        ingest_run_id=run_id,
        sha256=digest,
        row_count=len(raw_rows),
        recorded_at=fetched_at,
    )
    metadata.insert_source_file(record)
    return record, raw_rows


def _probe_and_record(
    *,
    provider_set: WarehouseProviderSet,
    layout: WarehouseLayout,
    metadata: WarehouseMetadata,
    clock: Callable[[], datetime],
) -> tuple[list[str], dict[str, str]]:
    from limit_pullback.warehouse.models import ProbeResult

    result: ProbeResult = provider_set.probe()
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
    by_name = {item.capability: item.status for item in result.capabilities}
    for core in ("trade_calendar", "daily_bars"):
        if by_name.get(core) != "AVAILABLE":
            raise PipelineError(
                f"CORE_CAPABILITY_{core}_{by_name.get(core, 'UNKNOWN')}",
                f"core capability {core} is not available",
            )
    notes: list[str] = []
    for capability, status in by_name.items():
        if status != "AVAILABLE" and capability not in ("trade_calendar", "daily_bars"):
            notes.append(f"SKIPPED_DATASET:{capability}:{status}")
    return notes, provider_set.provider_versions(), dict(by_name)


def _trading_dates(calendar: Sequence[date], start: date, end: date) -> list[date]:
    return [day for day in calendar if start <= day <= end]


def _fill_auxiliary(
    daily_rows: Sequence[dict[str, Any]],
    *,
    daily_basic: Sequence[Mapping[str, Any]],
    stock_basic: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    turnover: dict[tuple[str, date], Any] = {}
    for row in daily_basic:
        turnover[(str(row["code"]), row["trade_date"])] = row.get("turnover_rate")
    st: dict[str, Any] = {}
    for row in stock_basic:
        st[str(row["code"])] = row.get("is_st")
    enriched: list[dict[str, Any]] = []
    for row in daily_rows:
        enriched_row = dict(row)
        key = (str(row["code"]), row["trade_date"])
        if enriched_row.get("turnover_rate") is None and key in turnover:
            enriched_row["turnover_rate"] = turnover[key]
        if enriched_row.get("is_st") is None and row["code"] in st:
            enriched_row["is_st"] = st[row["code"]]
        enriched.append(enriched_row)
    return enriched


def _missing_records(
    *,
    calendar: Sequence[date],
    rows_by_provider: Mapping[str, Sequence[Mapping[str, Any]]],
    snapshot_id: str | None,
    clock: Callable[[], datetime],
) -> list[ReconciliationRecord]:
    codes_with_rows = sorted(
        {str(row["code"]) for rows in rows_by_provider.values() for row in rows}
    )
    covered: set[tuple[str, date]] = {
        (str(row["code"]), row["trade_date"])
        for rows in rows_by_provider.values()
        for row in rows
    }
    now = clock()
    records: list[ReconciliationRecord] = []
    for code in codes_with_rows:
        for trade_date in calendar:
            if (code, trade_date) not in covered:
                records.append(
                    ReconciliationRecord(
                        reconciliation_id=f"incomplete-{_run_id(code, trade_date, snapshot_id or '')}",
                        code=code,
                        trade_date=trade_date,
                        providers=(),
                        status=INCOMPLETE,
                        selected_provider=None,
                        notes="MISSING_ALL_PROVIDERS",
                        created_at=now,
                        snapshot_id=snapshot_id,
                    )
                )
    return records


def _historical_daily_rows(
    *,
    layout: WarehouseLayout,
    metadata: WarehouseMetadata,
    exclude_run_id: str,
    window_start: date,
    window_end: date,
) -> dict[tuple[str, str, date], dict[str, Any]]:
    """Latest previously-stored raw daily row per (provider, code, date).

    Used by ``update`` so that a transient provider gap in the revision
    window never silently downgrades previously confirmed rows.
    """

    from limit_pullback.warehouse.parquet import read_rows

    result: dict[tuple[str, str, date], dict[str, Any]] = {}
    rows = metadata._connection.execute(
        """
        SELECT path, provider FROM source_files
        WHERE ingest_run_id <> ?
          AND path LIKE '%/daily_bars/%'
        ORDER BY recorded_at ASC
        """,
        [exclude_run_id],
    ).fetchall()
    for path_value, provider in rows:
        path = Path(path_value)
        if not path.exists():
            continue
        for row in read_rows(path):
            trade_date = row["trade_date"]
            if not (window_start <= trade_date <= window_end):
                continue
            key = (str(provider), str(row["code"]), trade_date)
            result[key] = dict(row)
    return result


def bootstrap(
    *,
    layout: WarehouseLayout,
    start: date,
    end: date,
    codes: Sequence[str],
    provider_set: WarehouseProviderSet | None = None,
    policy: ReconciliationPolicy | None = None,
    clock: Callable[[], datetime] = _now_utc,
    today: date | None = None,
    all_main_board: bool = False,
    batch_size: int = 50,
    active_providers: tuple[str, ...] = ("TUSHARE", "AKSHARE", "BAOSTOCK"),
    bulk_threshold: int = 200,
    workers: int = 1,
    skip_tushare_aux: bool = False,
    isolate_akshare: bool = False,
    akshare_worker_runner=None,
) -> BootstrapResult:
    """Full historical bootstrap with an exclusive write lock."""

    layout.ensure_dirs()
    with WarehouseLock(layout.root / ".warehouse.lock"):
        return _bootstrap_impl(
            layout=layout,
            start=start,
            end=end,
            codes=codes,
            provider_set=provider_set,
            policy=policy,
            clock=clock,
            today=today,
            all_main_board=all_main_board,
            batch_size=batch_size,
            active_providers=active_providers,
            bulk_threshold=bulk_threshold,
            workers=workers,
            skip_tushare_aux=skip_tushare_aux,
            isolate_akshare=isolate_akshare,
            akshare_worker_runner=akshare_worker_runner,
        )


def _bootstrap_impl(
    *,
    layout: WarehouseLayout,
    start: date,
    end: date,
    codes: Sequence[str],
    provider_set: WarehouseProviderSet | None = None,
    policy: ReconciliationPolicy | None = None,
    clock: Callable[[], datetime] = _now_utc,
    today: date | None = None,
    all_main_board: bool = False,
    batch_size: int = 50,
    active_providers: tuple[str, ...] = ("TUSHARE", "AKSHARE", "BAOSTOCK"),
    bulk_threshold: int = 200,
    workers: int = 1,
    skip_tushare_aux: bool = False,
    isolate_akshare: bool = False,
    akshare_worker_runner=None,
) -> BootstrapResult:
    """Full historical bootstrap with atomic snapshot publication."""

    today_value = today or date.today()
    if start > end:
        raise PipelineError("INVALID_DATE_RANGE", "start must not be after end")
    if end > today_value:
        raise PipelineError("END_DATE_IN_FUTURE", "end must not be in the future")
    provided_codes = tuple(sorted({code.zfill(6) for code in codes}))

    policy = policy or ReconciliationPolicy()
    providers = provider_set or RealWarehouseProviderSet()
    fetched_at = clock()
    layout.ensure_dirs()
    run_id: str | None = None

    with WarehouseMetadata(layout.duckdb_path) as metadata:
        try:
            notes, provider_versions, capability_status = _probe_and_record(
                provider_set=providers, layout=layout, metadata=metadata, clock=clock
            )
            calendar = providers.fetch_trade_calendar(start, end)
            trading_dates = _trading_dates(calendar, start, end)
            if not trading_dates:
                raise PipelineError("NO_TRADING_DAYS", "no trading days in range")
            from limit_pullback.warehouse.fetch import fetch_with_retry

            try:
                stock_basic = fetch_with_retry(
                    lambda: providers.fetch_stock_basic(provided_codes),
                    retries=6,
                    backoff_seconds=2.0,
                )
            except CapabilityUnavailable as exc:
                stock_basic = []
                notes.append(f"SKIPPED_DATASET:stock_basic:{exc.status}")
                notes.append(f"STOCK_BASIC_DETAIL:{exc.error_code}:{exc.detail}")
            if all_main_board:
                if not stock_basic:
                    raise PipelineError(
                        "STOCK_BASIC_UNAVAILABLE",
                        (
                            "all-main-board bootstrap requires stock_basic: "
                            f"{notes[-2:] if notes else ''}"
                        ),
                    )
                from limit_pullback.warehouse.fetch import main_board_universe

                codes_tuple = main_board_universe(stock_basic)
                if not codes_tuple:
                    raise PipelineError(
                        "NO_MAIN_BOARD_CODES",
                        "stock_basic returned no legal main-board codes",
                    )
            else:
                codes_tuple = provided_codes or tuple(
                    sorted({str(row["code"]) for row in stock_basic})
                )
            if not codes_tuple:
                raise PipelineError("NO_CODES", "at least one code is required")

            run_id = _run_id(
                "bootstrap", start, end, codes_tuple, policy.policy_version
            )
            existing = metadata.get_ingest_run(run_id)
            pending = metadata.pending_failures(run_id)
            if existing is not None and existing.status == "COMPLETED" and not pending:
                snapshot = metadata.latest_snapshot_for(end)
                return BootstrapResult(
                    run_id=run_id,
                    snapshot_id=snapshot.snapshot_id if snapshot else None,
                    start_date=start,
                    end_date=end,
                    codes=codes_tuple,
                    reused=True,
                    failure_count=metadata.failure_count(run_id),
                    pending_failures=len(pending),
                )
            metadata.begin_ingest_run(
                run_id=run_id,
                kind="bootstrap",
                started_at=fetched_at,
                start_date=start,
                end_date=end,
                codes=codes_tuple,
                config_json=json.dumps(
                    {
                        "policy_version": policy.policy_version,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "all_main_board": all_main_board,
                        "active_providers": list(active_providers),
                    },
                    sort_keys=True,
                ),
            )

            from limit_pullback.warehouse.fetch import FetchContext, fetch_rows

            ctx = FetchContext(
                layout=layout,
                metadata=metadata,
                run_id=run_id,
                clock=clock,
                versions=provider_versions,
                batch_rows=max(20000, batch_size * 400),
            )
            ctx.worker_runner = akshare_worker_runner
            use_akshare_isolation = (
                isolate_akshare or akshare_worker_runner is not None
            )
            use_bulk = len(codes_tuple) >= bulk_threshold

            def _tushare_bulk(dataset: str, dates: list[date]) -> list[dict[str, Any]]:
                fetchers = {
                    "adjustment_factor": providers.fetch_tushare_adj_factor_by_trade_date,
                    "daily_basic": providers.fetch_tushare_daily_basic_by_trade_date,
                    "suspension": providers.fetch_tushare_suspension_by_trade_date,
                    "price_limits": providers.fetch_tushare_price_limits_by_trade_date,
                }
                return fetchers[dataset](dates)

            def _tushare_per_code(
                dataset: str, code: str
            ) -> list[dict[str, Any]]:
                fetchers = {
                    "adjustment_factor": providers.fetch_tushare_adj_factor,
                    "daily_basic": providers.fetch_tushare_daily_basic,
                    "suspension": providers.fetch_tushare_suspension,
                    "price_limits": providers.fetch_tushare_price_limits,
                }
                return fetchers[dataset]((code,), start, end)

            tushare_aux: dict[str, list[dict[str, Any]]] = {}
            if "TUSHARE" in active_providers and not skip_tushare_aux:
                for dataset in (
                    "adjustment_factor",
                    "daily_basic",
                    "suspension",
                    "price_limits",
                ):
                    if capability_status.get(dataset) != "AVAILABLE":
                        notes.append(
                            f"SKIPPED_DATASET:{dataset}:"
                            f"{capability_status.get(dataset, 'INACTIVE')}"
                        )
                        continue
                    if use_bulk:
                        tushare_aux[dataset] = fetch_rows(
                            ctx,
                            provider="TUSHARE",
                            dataset=dataset,
                            items=trading_dates,
                            bulk_fn=lambda dates, d=dataset: _tushare_bulk(d, dates),
                            use_bulk=True,
                            item_is_date=True,
                            batch_size=batch_size,
                        )
                    else:
                        tushare_aux[dataset] = fetch_rows(
                            ctx,
                            provider="TUSHARE",
                            dataset=dataset,
                            items=codes_tuple,
                            per_item_fn=lambda c, d=dataset: _tushare_per_code(d, c),
                            workers=workers,
                        )
            elif skip_tushare_aux:
                for dataset in (
                    "adjustment_factor",
                    "daily_basic",
                    "suspension",
                    "price_limits",
                ):
                    notes.append(f"SKIPPED_DATASET:{dataset}:AUX_SKIPPED_BY_FLAG")

            daily_basic_rows = tushare_aux.get("daily_basic", [])
            if (
                "TUSHARE" in active_providers
                and capability_status.get("daily_bars") == "AVAILABLE"
            ):
                if use_bulk:
                    tushare_daily = fetch_rows(
                        ctx,
                        provider="TUSHARE",
                        dataset="daily_bars",
                        items=trading_dates,
                        bulk_fn=lambda dates: _fill_auxiliary(
                            providers.fetch_tushare_daily_by_trade_date(dates),
                            daily_basic=daily_basic_rows,
                            stock_basic=stock_basic,
                        ),
                        use_bulk=True,
                        item_is_date=True,
                        batch_size=batch_size,
                    )
                else:
                    tushare_daily = fetch_rows(
                        ctx,
                        provider="TUSHARE",
                        dataset="daily_bars",
                        items=codes_tuple,
                        per_item_fn=lambda c: _fill_auxiliary(
                            providers.fetch_tushare_daily((c,), start, end),
                            daily_basic=daily_basic_rows,
                            stock_basic=stock_basic,
                        ),
                        workers=workers,
                    )
            else:
                tushare_daily = []
                notes.append("SKIPPED_DATASET:daily_bars:TUSHARE_INACTIVE")

            if "AKSHARE" in active_providers:
                akshare_daily = fetch_rows(
                    ctx,
                    provider="AKSHARE",
                    dataset="daily_bars",
                    items=codes_tuple,
                    per_item_fn=lambda c: _fill_auxiliary(
                        providers.fetch_akshare_daily((c,), start, end),
                        daily_basic=[],
                        stock_basic=stock_basic,
                    ),
                    workers=workers,
                    isolate_process=use_akshare_isolation,
                    start_date=start,
                    end_date=end,
                    worker_codes=codes_tuple,
                )
                akshare_pool = fetch_rows(
                    ctx,
                    provider="AKSHARE",
                    dataset="limit_up_pool",
                    items=trading_dates,
                    per_item_fn=lambda d: providers.fetch_akshare_limit_up_pool(
                        [d], codes_tuple
                    ),
                    item_is_date=True,
                    workers=workers,
                    isolate_process=use_akshare_isolation,
                    start_date=start,
                    end_date=end,
                    worker_codes=codes_tuple,
                )
            else:
                akshare_daily = []
                akshare_pool = []
                notes.append("SKIPPED_DATASET:akshare_daily:INACTIVE")

            if "BAOSTOCK" in active_providers:
                baostock_daily = fetch_rows(
                    ctx,
                    provider="BAOSTOCK",
                    dataset="daily_bars",
                    items=codes_tuple,
                    per_item_fn=lambda c: providers.fetch_baostock_daily(
                        (c,), start, end
                    ),
                    workers=workers,
                )
            else:
                baostock_daily = []
                notes.append("SKIPPED_DATASET:baostock_daily:INACTIVE")

            rows_by_provider = {
                "TUSHARE": tushare_daily,
                "AKSHARE": akshare_daily,
                "BAOSTOCK": baostock_daily,
            }
            canonical_daily, daily_records, quarantines = reconcile_daily_rows(
                rows_by_provider,
                policy=policy,
                clock=clock,
                adjustment_factor_rows=tushare_aux.get("adjustment_factor", []),
            )
            canonical_pool, pool_records, pool_quarantines = reconcile_limit_up_pool(
                akshare_pool, clock=clock
            )
            missing = _missing_records(
                calendar=trading_dates,
                rows_by_provider=rows_by_provider,
                snapshot_id=None,
                clock=clock,
            )
            all_records = [*daily_records, *pool_records, *missing]
            source_rows = metadata._connection.execute(
                "SELECT path, sha256, row_count FROM source_files WHERE ingest_run_id = ?",
                [run_id],
            ).fetchall()
            source_file_hashes = {
                str(Path(path_value).relative_to(layout.root)): sha
                for path_value, sha, _row_count in source_rows
            }
            snapshot = create_snapshot(
                layout=layout,
                metadata=metadata,
                as_of=end,
                provider_versions=dict(provider_versions),
                daily_rows=canonical_daily,
                pool_rows=canonical_pool,
                source_file_hashes=source_file_hashes,
                reconciliation_policy_version=policy.policy_version,
                clock=clock,
            )
            for record in all_records:
                metadata.insert_reconciliation(
                    record.model_copy(update={"snapshot_id": snapshot.snapshot_id})
                )
            for record in [*quarantines, *pool_quarantines]:
                metadata.insert_quarantine(record)
            metadata.finish_ingest_run(
                run_id=run_id,
                status="COMPLETED",
                finished_at=clock(),
                error=None,
            )
            return BootstrapResult(
                run_id=run_id,
                snapshot_id=snapshot.snapshot_id,
                start_date=start,
                end_date=end,
                codes=codes_tuple,
                raw_files=tuple(
                    SourceFileRecord(
                        path=str(path_value),
                        provider=str(path_value).split("/")[-3].upper()
                        if "/raw/" in str(path_value)
                        else "UNKNOWN",
                        ingest_run_id=run_id,
                        sha256=sha,
                        row_count=row_count,
                        recorded_at=fetched_at,
                    )
                    for path_value, sha, row_count in source_rows
                ),
                canonical_daily_rows=len(canonical_daily),
                canonical_pool_rows=len(canonical_pool),
                reconciliation_rows=len(all_records),
                quarantine_rows=len([*quarantines, *pool_quarantines]),
                reused=False,
                notes=tuple(notes),
                failure_count=metadata.failure_count(run_id),
                pending_failures=len(metadata.pending_failures(run_id)),
            )
        except BaseException as exc:
            if run_id is not None:
                metadata.finish_ingest_run(
                    run_id=run_id,
                    status="FAILED",
                    finished_at=clock(),
                    error=redact(f"{type(exc).__name__}: {exc}"),
                )
            raise


def update(
    *,
    layout: WarehouseLayout,
    as_of: date,
    codes: Sequence[str] | None = None,
    provider_set: WarehouseProviderSet | None = None,
    policy: ReconciliationPolicy | None = None,
    revision_calendar_days: int = 7,
    clock: Callable[[], datetime] = _now_utc,
    today: date | None = None,
) -> UpdateResult:
    """Incremental idempotent update with an exclusive write lock."""

    layout.ensure_dirs()
    with WarehouseLock(layout.root / ".warehouse.lock"):
        return _update_impl(
            layout=layout,
            as_of=as_of,
            codes=codes,
            provider_set=provider_set,
            policy=policy,
            revision_calendar_days=revision_calendar_days,
            clock=clock,
            today=today,
        )


def _update_impl(
    *,
    layout: WarehouseLayout,
    as_of: date,
    codes: Sequence[str] | None = None,
    provider_set: WarehouseProviderSet | None = None,
    policy: ReconciliationPolicy | None = None,
    revision_calendar_days: int = 7,
    clock: Callable[[], datetime] = _now_utc,
    today: date | None = None,
) -> UpdateResult:
    """Incremental idempotent update to a new as-of date."""

    today_value = today or date.today()
    if as_of > today_value:
        raise PipelineError("AS_OF_IN_FUTURE", "as_of must not be in the future")
    requested_codes = tuple(sorted({code.zfill(6) for code in (codes or ())}))
    policy = policy or ReconciliationPolicy()
    providers = provider_set or RealWarehouseProviderSet()
    fetched_at = clock()
    layout.ensure_dirs()

    with WarehouseMetadata(layout.duckdb_path) as metadata:
        previous = metadata.latest_snapshot()
        if previous is None:
            raise PipelineError("NO_BASELINE_SNAPSHOT", "bootstrap must run before update")
        if as_of < previous.as_of:
            raise PipelineError(
                "AS_OF_BEFORE_LATEST_SNAPSHOT",
                "update cannot rewrite a date before the latest snapshot",
            )
        previous_daily = read_snapshot_daily(layout, previous)
        previous_pool = read_snapshot_pool(layout, previous)
        known_codes = sorted({str(row["code"]) for row in previous_daily})
        codes_tuple = tuple(sorted(set(known_codes) | set(requested_codes)))
        run_id = _run_id(
            "update", previous.as_of, as_of, codes_tuple, policy.policy_version
        )
        if as_of == previous.as_of:
            return UpdateResult(
                run_id=run_id,
                snapshot_id=previous.snapshot_id,
                as_of=as_of,
                previous_snapshot_id=previous.snapshot_id,
                codes=codes_tuple,
                reused=True,
            )
        existing = metadata.get_ingest_run(run_id)
        if existing is not None and existing.status == "COMPLETED":
            snapshot = metadata.latest_snapshot_for(as_of)
            return UpdateResult(
                run_id=run_id,
                snapshot_id=snapshot.snapshot_id if snapshot else None,
                as_of=as_of,
                previous_snapshot_id=previous.snapshot_id,
                codes=codes_tuple,
                reused=True,
            )
        metadata.begin_ingest_run(
            run_id=run_id,
            kind="update",
            started_at=fetched_at,
            start_date=previous.as_of,
            end_date=as_of,
            codes=codes_tuple,
            config_json=json.dumps(
                {
                    "policy_version": policy.policy_version,
                    "previous_as_of": previous.as_of.isoformat(),
                    "as_of": as_of.isoformat(),
                },
                sort_keys=True,
            ),
        )
        _cleanup_run_files(layout, metadata, run_id)
        try:
            notes, provider_versions, _ = _probe_and_record(
                provider_set=providers, layout=layout, metadata=metadata, clock=clock
            )
            fetch_start = max(
                previous.as_of - timedelta(days=revision_calendar_days),
                date(2000, 1, 1),
            )
            calendar = providers.fetch_trade_calendar(fetch_start, as_of)
            new_trade_dates = _trading_dates(
                calendar, previous.as_of + timedelta(days=1), as_of
            )
            if not new_trade_dates:
                metadata.finish_ingest_run(
                    run_id=run_id,
                    status="COMPLETED",
                    finished_at=clock(),
                    error=None,
                )
                return UpdateResult(
                    run_id=run_id,
                    snapshot_id=previous.snapshot_id,
                    as_of=as_of,
                    previous_snapshot_id=previous.snapshot_id,
                    codes=codes_tuple,
                    reused=True,
                )
            try:
                stock_basic = providers.fetch_stock_basic(codes_tuple)
            except CapabilityUnavailable as exc:
                stock_basic = []
                notes.append(f"SKIPPED_DATASET:stock_basic:{exc.status}")

            tushare_daily = providers.fetch_tushare_daily(codes_tuple, fetch_start, as_of)
            tushare_daily_basic: list[dict[str, Any]] = []
            tushare_adj_factor: list[dict[str, Any]] = []
            for capability, fetch in (
                ("adjustment_factor", providers.fetch_tushare_adj_factor),
                ("daily_basic", providers.fetch_tushare_daily_basic),
                ("suspension", providers.fetch_tushare_suspension),
                ("price_limits", providers.fetch_tushare_price_limits),
            ):
                try:
                    rows = fetch(codes_tuple, fetch_start, as_of)
                    if capability == "daily_basic":
                        tushare_daily_basic = rows
                    if capability == "adjustment_factor":
                        tushare_adj_factor = rows
                    _write_dataset(
                        layout=layout,
                        metadata=metadata,
                        run_id=run_id,
                        provider="TUSHARE",
                        provider_version=provider_versions.get("TUSHARE", "unknown"),
                        dataset=capability,
                        source_unit=DATASETS_BY_PROVIDER["TUSHARE"][
                            [item[0] for item in DATASETS_BY_PROVIDER["TUSHARE"]].index(capability)
                        ][1],
                        normalized_unit=DATASETS_BY_PROVIDER["TUSHARE"][
                            [item[0] for item in DATASETS_BY_PROVIDER["TUSHARE"]].index(capability)
                        ][2],
                        rows=rows,
                        fetched_at=fetched_at,
                    )
                except CapabilityUnavailable as exc:
                    notes.append(f"SKIPPED_DATASET:{capability}:{exc.status}")

            try:
                akshare_daily = providers.fetch_akshare_daily(codes_tuple, fetch_start, as_of)
            except Exception as exc:
                akshare_daily = []
                notes.append(f"SKIPPED_DATASET:akshare_daily:{type(exc).__name__}")
            try:
                pool_rows = providers.fetch_akshare_limit_up_pool(new_trade_dates, codes_tuple)
            except Exception as exc:
                pool_rows = []
                notes.append(f"SKIPPED_DATASET:limit_up_pool:{type(exc).__name__}")
            try:
                baostock_daily = providers.fetch_baostock_daily(codes_tuple, fetch_start, as_of)
            except Exception as exc:
                baostock_daily = []
                notes.append(f"SKIPPED_DATASET:baostock_daily:{type(exc).__name__}")

            tushare_daily = _fill_auxiliary(
                tushare_daily,
                daily_basic=tushare_daily_basic,
                stock_basic=stock_basic,
            )
            akshare_daily = _fill_auxiliary(
                akshare_daily, daily_basic=[], stock_basic=stock_basic
            )

            source_files: list[SourceFileRecord] = []
            versions = {
                "TUSHARE": provider_versions.get("TUSHARE", "unknown"),
                "AKSHARE": provider_versions.get("AKSHARE", "unknown"),
                "BAOSTOCK": provider_versions.get("BAOSTOCK", "unknown"),
            }
            raw_daily_by_provider: dict[str, list[dict[str, Any]]] = {}
            raw_pool_rows: list[dict[str, Any]] = []
            for provider, dataset, rows in (
                ("TUSHARE", "daily_bars", tushare_daily),
                ("AKSHARE", "daily_bars", akshare_daily),
                ("AKSHARE", "limit_up_pool", pool_rows),
                ("BAOSTOCK", "daily_bars", baostock_daily),
            ):
                if not rows:
                    continue
                dataset_defs = DATASETS_BY_PROVIDER[provider]
                _, source_unit, normalized_unit = dataset_defs[
                    [item[0] for item in dataset_defs].index(dataset)
                ]
                record, raw_rows = _write_dataset(
                    layout=layout,
                    metadata=metadata,
                    run_id=run_id,
                    provider=provider,
                    provider_version=versions[provider],
                    dataset=dataset,
                    source_unit=source_unit,
                    normalized_unit=normalized_unit,
                    rows=rows,
                    fetched_at=fetched_at,
                )
                if record is not None:
                    source_files.append(record)
                if dataset == "daily_bars":
                    raw_daily_by_provider[provider] = raw_rows
                if dataset == "limit_up_pool":
                    raw_pool_rows = raw_rows

            window_start = fetch_start
            fallback_rows: dict[str, list[dict[str, Any]]] = {
                "TUSHARE": raw_daily_by_provider.get("TUSHARE", []),
                "AKSHARE": raw_daily_by_provider.get("AKSHARE", []),
                "BAOSTOCK": raw_daily_by_provider.get("BAOSTOCK", []),
            }
            for row in previous_daily:
                key = (str(row["code"]), row["trade_date"])
                if not (window_start <= key[1] <= as_of):
                    continue
                provider = str(row["selected_provider"])
                if not any(
                    str(candidate["code"]) == key[0]
                    and candidate["trade_date"] == key[1]
                    for candidate in fallback_rows.get(provider, [])
                ):
                    fallback_row = dict(row)
                    fallback_row["row_hash"] = fallback_row["source_row_hash"]
                    fallback_rows.setdefault(provider, []).append(fallback_row)

            historical_rows = _historical_daily_rows(
                layout=layout,
                metadata=metadata,
                exclude_run_id=run_id,
                window_start=window_start,
                window_end=as_of,
            )
            current_keys = {
                (provider, str(row["code"]), row["trade_date"])
                for provider, rows in raw_daily_by_provider.items()
                for row in rows
            }
            for (provider, code, trade_date), row in historical_rows.items():
                if (provider, code, trade_date) in current_keys:
                    continue
                if window_start <= trade_date <= as_of:
                    fallback_rows.setdefault(provider, []).append(dict(row))

            canonical_daily, daily_records, quarantines = reconcile_daily_rows(
                fallback_rows,
                policy=policy,
                clock=clock,
                adjustment_factor_rows=tushare_adj_factor,
            )
            canonical_pool, pool_records, pool_quarantines = reconcile_limit_up_pool(
                raw_pool_rows, clock=clock
            )
            missing = _missing_records(
                calendar=new_trade_dates,
                rows_by_provider=fallback_rows,
                snapshot_id=None,
                clock=clock,
            )
            all_records = [*daily_records, *pool_records, *missing]

            replacement_keys = {
                (str(row["code"]), row["trade_date"]) for row in canonical_daily
            }
            final_daily = [
                dict(row)
                for row in previous_daily
                if (str(row["code"]), row["trade_date"]) not in replacement_keys
            ]
            final_daily.extend(canonical_daily)
            final_daily.sort(key=lambda row: (row["code"], row["trade_date"]))
            final_pool = [dict(row) for row in previous_pool]
            final_pool.extend(canonical_pool)
            final_pool.sort(key=lambda row: (row["code"], row["trade_date"]))

            source_file_hashes = {
                **previous.source_file_hashes,
                **{
                    str(Path(record.path).relative_to(layout.root)): record.sha256
                    for record in source_files
                },
            }
            snapshot = create_snapshot(
                layout=layout,
                metadata=metadata,
                as_of=as_of,
                provider_versions=versions,
                daily_rows=final_daily,
                pool_rows=final_pool,
                source_file_hashes=source_file_hashes,
                reconciliation_policy_version=policy.policy_version,
                clock=clock,
            )
            for record in all_records:
                metadata.insert_reconciliation(
                    record.model_copy(update={"snapshot_id": snapshot.snapshot_id})
                )
            for record in [*quarantines, *pool_quarantines]:
                metadata.insert_quarantine(record)
            metadata.finish_ingest_run(
                run_id=run_id,
                status="COMPLETED",
                finished_at=clock(),
                error=None,
            )
            return UpdateResult(
                run_id=run_id,
                snapshot_id=snapshot.snapshot_id,
                as_of=as_of,
                previous_snapshot_id=previous.snapshot_id,
                codes=codes_tuple,
                new_trade_dates=tuple(new_trade_dates),
                raw_files=tuple(source_files),
                canonical_daily_rows=len(final_daily),
                canonical_pool_rows=len(final_pool),
                reconciliation_rows=len(all_records),
                quarantine_rows=len([*quarantines, *pool_quarantines]),
                reused=False,
                notes=tuple(notes),
            )
        except BaseException as exc:
            metadata.finish_ingest_run(
                run_id=run_id,
                status="FAILED",
                finished_at=clock(),
                error=redact(f"{type(exc).__name__}: {exc}"),
            )
            raise
