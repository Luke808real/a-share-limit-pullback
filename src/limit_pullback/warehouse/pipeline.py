"""Historical bootstrap and idempotent daily incremental update."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from limit_pullback.warehouse.auth import redact
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.locking import WarehouseLock
from limit_pullback.resources import (
    PerformanceProfile,
    available_memory_bytes,
    peak_rss_bytes,
)
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import (
    BootstrapResult,
    DailySessionRepairResult,
    QuarantineRecord,
    ReconciliationRecord,
    RepairDateStats,
    SourceFileRecord,
    UpdateResult,
)
from limit_pullback.warehouse.parquet import (
    RAW_SCHEMAS,
    quantize_row,
    read_rows,
    row_hash,
    sha256_file,
    write_rows_atomic,
)
from limit_pullback.warehouse.providers import RealWarehouseProviderSet, WarehouseProviderSet
from limit_pullback.warehouse.reconciliation import (
    CORPORATE_ACTION_PRECLOSE_DIVERGENCE,
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


class _Heartbeat:
    """Explicit liveness heartbeat for the bootstrap supervisor."""

    def __init__(
        self,
        *,
        layout: WarehouseLayout,
        run_id: str,
        clock: Callable[[], datetime],
    ) -> None:
        self.path = layout.root / ".bootstrap_heartbeat.json"
        self.run_id = run_id
        self.clock = clock
        self.phase = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def set_phase(self, phase: str) -> None:
        self.phase = phase

    def stop(self) -> None:
        self._stop.set()
        try:
            self._thread.join(timeout=2)
        except RuntimeError:
            pass

    def _run(self) -> None:
        self._write()
        while not self._stop.wait(30):
            self._write()

    def _write(self) -> None:
        try:
            payload = {
                "pid": os.getpid(),
                "run_id": self.run_id,
                "phase": self.phase,
                "updated_at": self.clock().timestamp(),
            }
            self.path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass


def _rate_limit_sink(
    layout: WarehouseLayout,
    metrics: dict[str, Any] | None = None,
) -> Callable[[float], None]:
    path = layout.root / ".rate_limit_wait.json"

    def sink(next_retry_at: float) -> None:
        if metrics is not None:
            metrics["rate_limit_waits"] = metrics.get("rate_limit_waits", 0) + 1
            metrics["rate_limit_wait_seconds"] = metrics.get(
                "rate_limit_wait_seconds", 0.0
            ) + max(0.0, next_retry_at - _now_utc().timestamp())
        try:
            path.write_text(
                json.dumps({"next_retry_at": next_retry_at}),
                encoding="utf-8",
            )
        except Exception:
            pass

    return sink


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _run_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


_REPAIR_LINEAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _validate_repair_lineage(tag: str) -> None:
    """Repair-lineage input contract: non-empty, bounded (1..64), safe charset.

    Must be called BEFORE any side effect (ensure_dirs / lock / probe /
    calendar / stock_basic / begin_ingest_run) so an invalid tag cannot create
    directories, metadata rows, provider calls, or network opportunities.
    """
    if not isinstance(tag, str) or not _REPAIR_LINEAGE_RE.match(tag):
        raise PipelineError(
            "INVALID_REPAIR_LINEAGE",
            f"repair_lineage must match ^[A-Za-z0-9][A-Za-z0-9._-]{{0,63}}$; "
            f"got {tag!r}",
        )


def _tushare_daily_missing_sessions(
    layout: WarehouseLayout,
    run_id: str,
    trading_dates: Sequence[date],
) -> list[date]:
    """Distinct generator-visible TUSHARE daily sessions present for a run.

    Reads TUSHARE/daily_bars/{run_id}-*.parquet (raw fetch output) and returns
    the requested trading dates with NO row at all. This is the pre-snapshot
    core-coverage gate input: MISSING != [] must fail closed before snapshot
    publication (silent-empty-as-success must never publish a session gap).
    """
    directory = layout.raw_dataset_dir("TUSHARE", "daily_bars")
    files = sorted(directory.glob(f"{run_id}-*.parquet"))
    if not files:
        return list(trading_dates)
    import duckdb

    glob_expr = str(directory / f"{run_id}-*.parquet")
    con = duckdb.connect()
    try:
        present = {
            row[0]
            for row in con.execute(
                f"SELECT DISTINCT trade_date FROM read_parquet('{glob_expr}')"
            ).fetchall()
        }
    finally:
        con.close()
    return [d for d in trading_dates if d not in present]


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
    snapshot_status: str = "CURRENT",
    aux_backfill: bool = False,
    listed_only: bool = False,
    profile: PerformanceProfile | None = None,
    force_finalize: bool = False,
    repair_lineage: str | None = None,
) -> BootstrapResult:
    """Full historical bootstrap with an exclusive write lock.

    ``repair_lineage``: optional explicit tag for a data-repair run. When
    None (normal bootstrap) the run identity is EXACTLY the legacy
    ``_run_id("bootstrap", start, end, codes, policy)`` expression (bit-for-bit
    backward compatible). When set, a separate ``bootstrap-repair`` namespace
    is used so the repair run never collides with nor rewrites an existing
    historical run.
    """

    if repair_lineage is not None:
        _validate_repair_lineage(repair_lineage)
    if repair_lineage is not None and aux_backfill:
        raise PipelineError(
            "REPAIR_LINEAGE_AUX_BACKFILL_UNSUPPORTED",
            "aux_backfill does not support repair_lineage; refusing to "
            "silently ignore the repair flag",
        )

    layout.ensure_dirs()
    with WarehouseLock(layout.root / ".warehouse.lock"):
        if aux_backfill:
            return _aux_backfill_impl(
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
                workers=workers,
                bulk_threshold=bulk_threshold,
                listed_only=listed_only,
                profile=profile,
                force_finalize=force_finalize,
            )
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
            snapshot_status=snapshot_status,
            listed_only=listed_only,
            profile=profile,
            force_finalize=force_finalize,
            repair_lineage=repair_lineage,
        )


def _iter_code_groups(cursor):
    columns = [description[0] for description in cursor.description]
    carry: dict[str, list[dict[str, Any]]] = {}
    carry_order: list[str] = []
    batch = cursor.fetchmany(20000)
    while batch:
        for raw_row in batch:
            row = dict(zip(columns, raw_row))
            code = str(row["code"])
            if code not in carry:
                carry[code] = []
                carry_order.append(code)
            carry[code].append(row)
        for code in carry_order[:-1]:
            yield code, carry.pop(code)
        carry_order = carry_order[-1:]
        batch = cursor.fetchmany(20000)
    for code in carry_order:
        yield code, carry.pop(code)


def _stream_reconcile_market(
    *,
    layout: WarehouseLayout,
    metadata: WarehouseMetadata,
    run_id: str,
    trading_dates: list[date],
    policy: ReconciliationPolicy,
    clock: Callable[[], datetime],
    adjustment_factor_rows: list[dict[str, Any]] = (),
    profile: PerformanceProfile | None = None,
) -> tuple[Any, list[ReconciliationRecord], list[QuarantineRecord], list[ReconciliationRecord]]:
    """Reconcile the full market code-by-code with bounded memory.

    Raw rows are streamed from Parquet through DuckDB cursors and canonical
    rows accumulate in a columnar pyarrow table instead of Python dicts.
    """

    import pyarrow as pa
    import pyarrow.parquet as pq
    import duckdb
    import time

    from limit_pullback.warehouse.parquet import canonical_daily_schema
    from limit_pullback.warehouse.parquet import write_table_atomic

    profile = profile or PerformanceProfile.load()

    globs: dict[str, str] = {}
    codes_by_provider: dict[str, list[str]] = {}
    connection = duckdb.connect()
    for provider in ("TUSHARE", "AKSHARE", "BAOSTOCK"):
        directory = layout.raw_dataset_dir(provider, "daily_bars")
        files = sorted(directory.glob(f"{run_id}-*.parquet"))
        if not files:
            continue
        glob_expr = str(directory / f"{run_id}-*.parquet")
        globs[provider] = glob_expr
        codes_by_provider[provider] = [
            str(row[0])
            for row in connection.execute(
                f"SELECT DISTINCT code FROM read_parquet('{glob_expr}') ORDER BY code"
            ).fetchall()
        ]
    all_codes = sorted(
        set().union(*codes_by_provider.values())
        if codes_by_provider
        else set()
    )
    columns_by_provider: dict[str, list[str]] = {}
    for provider, glob_expr in globs.items():
        cursor = connection.execute(
            f"SELECT * FROM read_parquet('{glob_expr}') WHERE code = ? "
            "ORDER BY trade_date",
            [all_codes[0] if all_codes else ""],
        )
        columns_by_provider[provider] = [
            description[0] for description in cursor.description
        ]

    schema = canonical_daily_schema().remove(
        canonical_daily_schema().get_field_index("dataset_snapshot_id")
    )
    canonical_parts: list[Path] = []
    pending_canonical: list[dict[str, Any]] = []
    part_directory = layout.root / "tmp" / "canonical"
    part_directory.mkdir(parents=True, exist_ok=True)
    daily_records: list[ReconciliationRecord] = []
    quarantines: list[QuarantineRecord] = []
    missing_records: list[ReconciliationRecord] = []

    def flush_canonical() -> None:
        if not pending_canonical:
            return
        part_path = part_directory / f"part-{len(canonical_parts) + 1:05d}.parquet"
        write_table_atomic(
            pa.Table.from_pylist(pending_canonical, schema=schema),
            part_path,
        )
        canonical_parts.append(part_path)
        pending_canonical.clear()

    for code in all_codes:
        available_gb = available_memory_bytes() / (1024**3)
        if available_gb < profile.pause_available_memory_gb:
            flush_canonical()
            time.sleep(2)
        elif available_gb < profile.minimum_available_memory_gb:
            time.sleep(0.5)
        rows_by_provider: dict[str, list[dict[str, Any]]] = {}
        for provider, glob_expr in globs.items():
            if code not in codes_by_provider.get(provider, []):
                continue
            cursor = connection.execute(
                f"SELECT * FROM read_parquet('{glob_expr}') WHERE code = ? "
                "ORDER BY trade_date",
                [code],
            )
            columns = columns_by_provider[provider]
            rows_by_provider[provider] = [
                dict(zip(columns, row)) for row in cursor.fetchall()
            ]
        if not rows_by_provider:
            continue
        canonical, records, quarantined = reconcile_daily_rows(
            rows_by_provider,
            policy=policy,
            clock=clock,
            adjustment_factor_rows=adjustment_factor_rows,
        )
        if canonical:
            pending_canonical.extend(canonical)
            if len(pending_canonical) >= profile.canonical_flush_rows:
                flush_canonical()
        daily_records.extend(records)
        quarantines.extend(quarantined)
        missing_records.extend(
            _missing_records(
                calendar=trading_dates,
                rows_by_provider=rows_by_provider,
                snapshot_id=None,
                clock=clock,
            )
        )
    flush_canonical()
    if canonical_parts:
        tables = [
            pq.read_table(str(path), schema=schema)
            for path in canonical_parts
        ]
        daily_table = pa.concat_tables(tables)
    else:
        daily_table = pa.Table.from_pylist([], schema=canonical_daily_schema())
    connection.close()
    return daily_table, daily_records, quarantines, missing_records


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
    snapshot_status: str = "CURRENT",
    listed_only: bool = False,
    profile: PerformanceProfile | None = None,
    force_finalize: bool = False,
    repair_lineage: str | None = None,
) -> BootstrapResult:
    """Full historical bootstrap with atomic snapshot publication."""

    today_value = today or date.today()
    if start > end:
        raise PipelineError("INVALID_DATE_RANGE", "start must not be after end")
    if end > today_value:
        raise PipelineError("END_DATE_IN_FUTURE", "end must not be in the future")
    provided_codes = tuple(sorted({code.zfill(6) for code in codes}))

    policy = policy or ReconciliationPolicy()
    profile = profile or PerformanceProfile.load()
    metrics: dict[str, Any] = {
        "rate_limit_waits": 0,
        "rate_limit_wait_seconds": 0.0,
        "worker_restarts": 0,
        "peak_rss_mb": 0,
    }
    providers = provider_set or RealWarehouseProviderSet(
        rate_limit_sink=_rate_limit_sink(layout, metrics)
    )
    fetched_at = clock()
    layout.ensure_dirs()
    run_id: str | None = None

    with WarehouseMetadata(layout.duckdb_path, profile=profile) as metadata:
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
                    lambda: providers.fetch_stock_basic(
                        provided_codes, listed_only=listed_only
                    ),
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

                codes_tuple = main_board_universe(stock_basic, start, end)
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
            if all_main_board:
                from limit_pullback.warehouse.fetch import stock_coverage

                coverage = stock_coverage(stock_basic, start, end)
                notes.append(
                    "STOCK_COVERAGE:" + json.dumps(coverage, sort_keys=True)
                )

            if repair_lineage is None:
                # EXACT legacy identity: must stay bit-for-bit unchanged so
                # normal bootstrap keeps resolving historical run_ids.
                run_id = _run_id(
                    "bootstrap", start, end, codes_tuple, policy.policy_version
                )
            else:
                # Explicit repair namespace: never collides with normal runs
                # nor with a different repair tag (deterministic pure hash).
                run_id = _run_id(
                    "bootstrap-repair",
                    start,
                    end,
                    codes_tuple,
                    policy.policy_version,
                    repair_lineage,
                )
            repair_mode = repair_lineage is not None
            use_bulk = len(codes_tuple) >= bulk_threshold
            # Lineage guard: a failure BEFORE this attempt begins its own
            # ingest run (e.g. historical completed-run reuse validation)
            # must never rewrite the historical record to FAILED. Only the
            # current attempt's own run may be marked FAILED.
            run_started_this_attempt = False
            heartbeat = _Heartbeat(layout=layout, run_id=run_id, clock=clock)
            heartbeat.start()
            start_wall = time.monotonic()
            existing = metadata.get_ingest_run(run_id)
            pending = metadata.pending_failures(run_id)
            if (
                existing is not None
                and existing.status == "COMPLETED"
                and not pending
                and not force_finalize
            ):
                # Completed-run reuse gate: a historical COMPLETED bulk run
                # whose TUSHARE daily coverage has a session hole must not be
                # reused and must not hand back its old snapshot.
                if use_bulk and "TUSHARE" in active_providers:
                    missing = _tushare_daily_missing_sessions(
                        layout, run_id, trading_dates
                    )
                    if missing:
                        raise PipelineError(
                            "COMPLETED_RUN_DAILY_COVERAGE_INVALID",
                            "TUSHARE daily session coverage hole in COMPLETED run "
                            f"{run_id}: missing {len(missing)} sessions, e.g. "
                            f"{[d.isoformat() for d in missing[:5]]}",
                        )
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
                kind="bootstrap-repair" if repair_mode else "bootstrap",
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
                        "repair_lineage": repair_lineage,
                        "repair_mode": repair_mode,
                    },
                    sort_keys=True,
                ),
            )
            run_started_this_attempt = True

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
            use_bulk = len(codes_tuple) >= bulk_threshold
            if "TUSHARE" in active_providers and not skip_tushare_aux:
                heartbeat.set_phase("tushare-aux")
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
            heartbeat.set_phase("tushare-daily")
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
                        require_date_presence=True,
                        batch_size=batch_size,
                        return_rows=False,
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
                        return_rows=False,
                    )
            else:
                tushare_daily = []
                notes.append("SKIPPED_DATASET:daily_bars:TUSHARE_INACTIVE")

            if "AKSHARE" in active_providers:
                heartbeat.set_phase("akshare-daily")
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
                    return_rows=False,
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
                heartbeat.set_phase("baostock-daily")
                baostock_daily = fetch_rows(
                    ctx,
                    provider="BAOSTOCK",
                    dataset="daily_bars",
                    items=codes_tuple,
                    per_item_fn=lambda c: providers.fetch_baostock_daily(
                        (c,), start, end
                    ),
                    workers=workers,
                    isolate_process=use_akshare_isolation,
                    start_date=start,
                    end_date=end,
                    worker_codes=codes_tuple,
                    worker_mode="baostock",
                    return_rows=False,
                )
            else:
                baostock_daily = []
                notes.append("SKIPPED_DATASET:baostock_daily:INACTIVE")

            # Pre-snapshot core coverage gate (fail closed): the bulk TUSHARE
            # daily fetch must cover every requested trading session. A
            # silent-empty fetch (no rows for a requested date) must never
            # reach reconciliation / snapshot publication / COMPLETED.
            # Per-code fetch paths are excluded: their per-item failure
            # isolation already records failures, and auxiliary-only runs may
            # legitimately have empty TUSHARE daily.
            if use_bulk and "TUSHARE" in active_providers:
                missing_sessions = _tushare_daily_missing_sessions(
                    layout, run_id, trading_dates
                )
                if missing_sessions:
                    raise PipelineError(
                        "TUSHARE_DAILY_SESSION_COVERAGE_INCOMPLETE",
                        f"missing {len(missing_sessions)} TUSHARE daily sessions, "
                        f"e.g. {[d.isoformat() for d in missing_sessions[:5]]}",
                    )

            daily_table, daily_records, quarantines, missing = _stream_reconcile_market(
                layout=layout,
                metadata=metadata,
                run_id=run_id,
                trading_dates=trading_dates,
                policy=policy,
                clock=clock,
                adjustment_factor_rows=tushare_aux.get("adjustment_factor", []),
                profile=profile,
            )
            canonical_pool, pool_records, pool_quarantines = reconcile_limit_up_pool(
                akshare_pool, clock=clock
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
                daily_rows=[],
                daily_table=daily_table,
                pool_rows=canonical_pool,
                source_file_hashes=source_file_hashes,
                reconciliation_policy_version=policy.policy_version,
                clock=clock,
                status=snapshot_status,
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
            metrics["worker_restarts"] = ctx.worker_restarts
            metrics["rows_written"] = sum(
                row_count for _, _, row_count in source_rows
            )
            metrics["peak_rss_mb"] = peak_rss_bytes() // (1024 * 1024)
            metrics["wall_seconds"] = round(time.monotonic() - start_wall, 3)
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
                canonical_daily_rows=daily_table.num_rows,
                canonical_pool_rows=len(canonical_pool),
                reconciliation_rows=len(all_records),
                quarantine_rows=len([*quarantines, *pool_quarantines]),
                reused=False,
                notes=tuple(notes),
                failure_count=metadata.failure_count(run_id),
                pending_failures=len(metadata.pending_failures(run_id)),
                metrics=dict(metrics),
            )
        except BaseException as exc:
            if run_id is not None and run_started_this_attempt:
                metadata.finish_ingest_run(
                    run_id=run_id,
                    status="FAILED",
                    finished_at=clock(),
                    error=redact(f"{type(exc).__name__}: {exc}"),
                )
            raise


def _read_parent_daily_bars(
    *,
    metadata: WarehouseMetadata,
    layout: WarehouseLayout,
    parent_run_id: str,
    repair_set: set[date],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Read the parent run's AKSHARE/BAOSTOCK daily_bars rows for the repair
    dates (read-only, never copied or modified).

    Returns ``(rows_by_provider, verified_hashes)`` where ``verified_hashes``
    maps relative source paths to the sha256 recorded in ``source_files``.
    A missing or tampered parent file fails closed — parent raw reuse is only
    allowed when the on-disk file matches the recorded digest.
    """

    parent_files = metadata._connection.execute(
        """
        SELECT path, provider, sha256 FROM source_files
        WHERE ingest_run_id = ?
          AND path LIKE '%/daily_bars/%'
        ORDER BY recorded_at ASC
        """,
        [parent_run_id],
    ).fetchall()
    if not parent_files:
        raise PipelineError(
            "REPAIR_PARENT_RAW_UNAVAILABLE",
            f"parent run {parent_run_id} has no recorded daily_bars source files",
        )
    parent_rows: dict[str, list[dict[str, Any]]] = {}
    verified_hashes: dict[str, str] = {}
    for path_value, provider, recorded_sha in parent_files:
        if provider not in ("AKSHARE", "BAOSTOCK"):
            continue
        path = Path(path_value)
        if not path.exists():
            raise PipelineError(
                "REPAIR_PARENT_RAW_MISSING",
                f"parent raw file {path_value} is missing",
            )
        if sha256_file(path) != recorded_sha:
            raise PipelineError(
                "REPAIR_PARENT_RAW_SHA_MISMATCH",
                f"parent raw file {path_value} sha256 mismatch",
            )
        verified_hashes[str(path.relative_to(layout.root))] = recorded_sha
        bucket = parent_rows.setdefault(provider, [])
        for row in read_rows(path):
            if row.get("trade_date") in repair_set:
                bucket.append(dict(row))
    return parent_rows, verified_hashes


def _read_run_daily_rows(
    metadata: WarehouseMetadata, run_id: str, provider: str
) -> list[dict[str, Any]]:
    """Read one provider's raw daily_bars rows written by a run (read-only)."""

    paths = metadata._connection.execute(
        "SELECT path FROM source_files "
        "WHERE ingest_run_id = ? AND provider = ? AND path LIKE '%/daily_bars/%' "
        "ORDER BY recorded_at ASC",
        [run_id, provider],
    ).fetchall()
    rows: list[dict[str, Any]] = []
    for (path_value,) in paths:
        rows.extend(read_rows(Path(path_value)))
    return rows


def _repair_date_stats(
    *,
    dates: Sequence[date],
    ts_rows: Sequence[Mapping[str, Any]],
    ak_rows: Sequence[Mapping[str, Any]],
    bs_rows: Sequence[Mapping[str, Any]],
    base_daily: Sequence[Mapping[str, Any]],
    repaired_rows: Sequence[Mapping[str, Any]],
    quarantine_by_date: Mapping[date, int],
) -> tuple[RepairDateStats, ...]:
    """Per-date audit numbers proving each repair date individually.

    Every repair date gets TS_N / AK_N / BS_N / CONSENSUS_N /
    TS_COVERAGE_OF_CONSENSUS / BASE_ROW_N / REPAIRED_ROW_N / CONFIRMED_N /
    PROVISIONAL_N / QUARANTINE_N so a 12/12 success claim can be verified
    date by date. TS_N / AK_N / BS_N / CONSENSUS_N count DISTINCT codes (the
    breadth contract's universe), never raw rows, so duplicated provider
    rows can never inflate the breadth numbers.
    """

    stats: list[RepairDateStats] = []
    for d in dates:
        ts_codes_d = {
            str(row["code"]) for row in ts_rows if row.get("trade_date") == d
        }
        ak_codes_d = {
            str(row["code"]) for row in ak_rows if row.get("trade_date") == d
        }
        bs_codes_d = {
            str(row["code"]) for row in bs_rows if row.get("trade_date") == d
        }
        consensus_d = ak_codes_d & bs_codes_d
        repaired_d = [
            row for row in repaired_rows if row.get("trade_date") == d
        ]
        confirmed_d = sum(
            1
            for row in repaired_d
            if row.get("reconciliation_status") == "CONFIRMED"
        )
        stats.append(
            RepairDateStats(
                trade_date=d,
                ts_n=len(ts_codes_d),
                ak_n=len(ak_codes_d),
                bs_n=len(bs_codes_d),
                consensus_n=len(consensus_d),
                ts_coverage_of_consensus=len(consensus_d & ts_codes_d),
                base_row_n=sum(
                    1 for row in base_daily if row.get("trade_date") == d
                ),
                repaired_row_n=len(repaired_d),
                confirmed_n=confirmed_d,
                provisional_n=len(repaired_d) - confirmed_d,
                quarantine_n=int(quarantine_by_date.get(d, 0)),
            )
        )
    return tuple(stats)


def repair_daily_sessions(
    *,
    layout: WarehouseLayout,
    base_snapshot_id: str,
    parent_run_id: str,
    repair_dates: Sequence[date],
    provider_set: WarehouseProviderSet | None = None,
    policy: ReconciliationPolicy | None = None,
    clock: Callable[[], datetime] = _now_utc,
    today: date | None = None,
    repair_lineage: str | None = None,
    batch_size: int = 50,
) -> DailySessionRepairResult:
    """Bounded repair of a small explicit set of daily sessions.

    The pipeline re-fetches ONLY ``repair_dates`` from TUSHARE (bulk,
    date-keyed, ``require_date_presence``), reuses the parent run's
    AKSHARE/BAOSTOCK ``daily_bars`` raw rows for those dates (read-only,
    sha256-verified against ``source_files``), reconciles ONLY the repair
    sessions and publishes a new immutable ``RESEARCH_READY`` snapshot whose
    daily composition is ``base daily - repair dates + repaired rows`` and
    whose pool rows are the base pool rows unchanged.

    Frozen per-date consensus breadth contract. For EVERY repair date d,
    independently (never as a cross-date union):

    * ``TS_CODES[d]`` = new TUSHARE daily rows on d;
    * ``AK_CODES[d]`` = exact parent AKSHARE rows on d;
    * ``BS_CODES[d]`` = exact parent BAOSTOCK rows on d;
    * ``CONSENSUS[d] = AK_CODES[d] & BS_CODES[d]``;
    * hard gates: ``AK_N[d] > 0``, ``BS_N[d] > 0``, ``CONSENSUS_N[d] > 0``
      (``REPAIR_PARENT_PROVIDER_DATE_COVERAGE_INCOMPLETE``) and
      ``CONSENSUS[d] subset TS_CODES[d]``
      (``REPAIR_TUSHARE_CONSENSUS_COVERAGE_INCOMPLETE``).

    Additional fail-closed gates (each raises before any publication):

    * repair dates must be non-empty, not in the future, not beyond
      ``base.as_of`` (``REPAIR_DATE_BEYOND_BASE_AS_OF``), and every requested
      TUSHARE session must have rows (``require_date_presence`` + file-level
      presence check + no PENDING fetch failures);
    * every provider row must fall inside the repair window (bounded scope);
    * every repair date must end up with at least one CONFIRMED row;
    * the composed snapshot must have no duplicate (code, trade_date).

    Snapshot provenance is the union of the base snapshot's source hashes,
    the sha256-verified parent AKSHARE/BAOSTOCK hashes actually read, and the
    new repair-run TUSHARE hashes; the same source path with two different
    hashes fails closed (``REPAIR_SOURCE_SHA_CONFLICT``). The repair snapshot
    ``as_of`` is frozen to ``base.as_of`` — a repair never moves the time
    boundary.

    ``repair_lineage`` is required and must satisfy the shared tag contract.
    The run identity is ``_run_id("daily-session-repair", base_snapshot_id,
    parent_run_id, tuple(repair_dates), policy.policy_version,
    repair_lineage)``; a completed run with no pending failures is ALWAYS
    reused (deterministic, never rewritten in place).
    """

    if repair_lineage is None:
        raise PipelineError(
            "REPAIR_LINEAGE_REQUIRED",
            "repair_daily_sessions requires an explicit repair_lineage tag",
        )
    _validate_repair_lineage(repair_lineage)
    dates = tuple(sorted({d for d in repair_dates}))
    if not dates:
        raise PipelineError("REPAIR_NO_DATES", "at least one repair date is required")
    today_value = today or date.today()
    if dates[-1] > today_value:
        raise PipelineError(
            "END_DATE_IN_FUTURE", "repair dates must not be in the future"
        )
    policy = policy or ReconciliationPolicy()
    metrics: dict[str, Any] = {
        "rate_limit_waits": 0,
        "rate_limit_wait_seconds": 0.0,
        "rows_written": 0,
        "wall_seconds": 0.0,
    }
    providers = provider_set or RealWarehouseProviderSet(
        rate_limit_sink=_rate_limit_sink(layout, metrics)
    )
    fetched_at = clock()
    layout.ensure_dirs()
    run_id: str | None = None
    run_started_this_attempt = False

    with WarehouseLock(layout.root / ".warehouse.lock"):
        with WarehouseMetadata(layout.duckdb_path) as metadata:
            try:
                base = metadata.snapshot_by_id(base_snapshot_id)
                if base is None:
                    raise PipelineError(
                        "REPAIR_BASE_SNAPSHOT_UNKNOWN",
                        f"base snapshot {base_snapshot_id} does not exist",
                    )
                if metadata.get_ingest_run(parent_run_id) is None:
                    raise PipelineError(
                        "REPAIR_PARENT_RUN_UNKNOWN",
                        f"parent run {parent_run_id} does not exist",
                    )
                # as_of freeze: a repair never moves the time boundary and
                # never reaches past the base snapshot frontier (no
                # future-leakage into the composed snapshot).
                if max(dates) > base.as_of:
                    raise PipelineError(
                        "REPAIR_DATE_BEYOND_BASE_AS_OF",
                        f"repair date {max(dates).isoformat()} is beyond base "
                        f"as_of {base.as_of.isoformat()}",
                    )
                notes: list[str] = []
                run_id = _run_id(
                    "daily-session-repair",
                    base_snapshot_id,
                    parent_run_id,
                    dates,
                    policy.policy_version,
                    repair_lineage,
                )
                heartbeat = _Heartbeat(layout=layout, run_id=run_id, clock=clock)
                heartbeat.start()
                start_wall = time.monotonic()
                existing = metadata.get_ingest_run(run_id)
                pending = metadata.pending_failures(run_id)
                if existing is not None and existing.status == "COMPLETED" and not pending:
                    # A completed deterministic repair run is ALWAYS reused;
                    # there is no force_finalize / in-place rewrite path. The
                    # published snapshot is resolved EXACTLY through the
                    # run's own config_json (written at publication time) —
                    # never through source-hash marker search, which would
                    # drift once a descendant snapshot inherits these hashes.
                    run_config = json.loads(existing.config_json or "{}")
                    published_id = run_config.get("published_snapshot_id")
                    if published_id is None:
                        raise PipelineError(
                            "REPAIR_RUN_MISSING_PUBLISHED_SNAPSHOT",
                            f"completed repair run {run_id} has no recorded "
                            "published_snapshot_id",
                        )
                    snapshot = metadata.snapshot_by_id(published_id)
                    if snapshot is None:
                        raise PipelineError(
                            "REPAIR_PUBLISHED_SNAPSHOT_MISSING",
                            f"repair run {run_id} points to unknown snapshot "
                            f"{published_id}",
                        )
                    if snapshot.as_of != base.as_of:
                        raise PipelineError(
                            "REPAIR_PUBLISHED_SNAPSHOT_AS_OF_MISMATCH",
                            f"repair run {run_id} snapshot {published_id} "
                            f"as_of {snapshot.as_of.isoformat()} != base as_of "
                            f"{base.as_of.isoformat()}",
                        )
                    base_daily = read_snapshot_daily(layout, base)
                    repair_set = set(dates)
                    repaired_rows = [
                        row
                        for row in read_snapshot_daily(layout, snapshot)
                        if row.get("trade_date") in repair_set
                    ]
                    confirmed_n = sum(
                        1
                        for row in repaired_rows
                        if row.get("reconciliation_status") == "CONFIRMED"
                    )
                    # Parity with the fresh path: every quarantine record has
                    # exactly one reconciliation record with status
                    # QUARANTINED (provider-internal conflict) or CONFLICTED
                    # (cross-provider conflict), so the reuse counts must
                    # include BOTH statuses.
                    quarantine_n = metadata._connection.execute(
                        "SELECT count(*) FROM reconciliation_results "
                        "WHERE snapshot_id = ? AND status IN "
                        "('QUARANTINED', 'CONFLICTED')",
                        [snapshot.snapshot_id],
                    ).fetchone()[0]
                    quarantine_rows = metadata._connection.execute(
                        "SELECT trade_date FROM reconciliation_results "
                        "WHERE snapshot_id = ? AND status IN "
                        "('QUARANTINED', 'CONFLICTED')",
                        [snapshot.snapshot_id],
                    ).fetchall()
                    quarantine_by_date: dict[date, int] = {}
                    for (q_date,) in quarantine_rows:
                        if q_date is not None:
                            quarantine_by_date[q_date] = (
                                quarantine_by_date.get(q_date, 0) + 1
                            )
                    parent_rows, _ = _read_parent_daily_bars(
                        metadata=metadata,
                        layout=layout,
                        parent_run_id=parent_run_id,
                        repair_set=repair_set,
                    )
                    ts_rows = [
                        row
                        for row in _read_run_daily_rows(metadata, run_id, "TUSHARE")
                        if row.get("trade_date") in repair_set
                    ]
                    per_date_stats = _repair_date_stats(
                        dates=dates,
                        ts_rows=ts_rows,
                        ak_rows=parent_rows.get("AKSHARE", []),
                        bs_rows=parent_rows.get("BAOSTOCK", []),
                        base_daily=base_daily,
                        repaired_rows=repaired_rows,
                        quarantine_by_date=quarantine_by_date,
                    )
                    return DailySessionRepairResult(
                        run_id=run_id,
                        snapshot_id=snapshot.snapshot_id,
                        base_snapshot_id=base_snapshot_id,
                        parent_run_id=parent_run_id,
                        repair_dates=dates,
                        base_row_n=len(base_daily),
                        repaired_row_n=len(repaired_rows),
                        confirmed_n=confirmed_n,
                        provisional_n=len(repaired_rows) - confirmed_n,
                        quarantine_n=int(quarantine_n),
                        per_date_stats=per_date_stats,
                        reused=True,
                        failure_count=metadata.failure_count(run_id),
                        pending_failures=len(pending),
                        metrics=dict(metrics),
                    )
                metadata.begin_ingest_run(
                    run_id=run_id,
                    kind="daily-session-repair",
                    started_at=fetched_at,
                    start_date=dates[0],
                    end_date=dates[-1],
                    codes=(),
                    config_json=json.dumps(
                        {
                            "policy_version": policy.policy_version,
                            "base_snapshot_id": base_snapshot_id,
                            "parent_run_id": parent_run_id,
                            "repair_dates": [d.isoformat() for d in dates],
                            "repair_lineage": repair_lineage,
                        },
                        sort_keys=True,
                    ),
                )
                run_started_this_attempt = True

                from limit_pullback.warehouse.fetch import (
                    FetchContext,
                    fetch_rows,
                    fetch_with_retry,
                )

                provider_versions = providers.provider_versions()
                ctx = FetchContext(
                    layout=layout,
                    metadata=metadata,
                    run_id=run_id,
                    clock=clock,
                    versions=provider_versions,
                    batch_rows=max(20000, batch_size * 400),
                )
                try:
                    stock_basic = fetch_with_retry(
                        lambda: providers.fetch_stock_basic(
                            (), listed_only=False
                        ),
                        retries=6,
                        backoff_seconds=2.0,
                    )
                except CapabilityUnavailable as exc:
                    stock_basic = []
                    notes.append(f"SKIPPED_DATASET:stock_basic:{exc.status}")
                    notes.append(f"STOCK_BASIC_DETAIL:{exc.error_code}:{exc.detail}")

                def _tushare_bulk(
                    dataset: str, wanted: list[date]
                ) -> list[dict[str, Any]]:
                    fetchers = {
                        "adjustment_factor": providers.fetch_tushare_adj_factor_by_trade_date,
                        "daily_basic": providers.fetch_tushare_daily_basic_by_trade_date,
                    }
                    return fetchers[dataset](wanted)

                tushare_aux: dict[str, list[dict[str, Any]]] = {}
                # Corporate-action left boundary: the first repair session's
                # preclose-divergence verdict needs a PREDECESSOR adjustment
                # factor session (the nearest trading day before the first
                # repair date, taken from the base snapshot's own calendar).
                # Without it, a CA change on the first repair date would be
                # misjudged as an OHLC conflict and the row quarantined.
                base_daily = read_snapshot_daily(layout, base)
                first_repair = min(dates)
                predecessor_candidates = sorted(
                    {
                        row["trade_date"]
                        for row in base_daily
                        if row["trade_date"] < first_repair
                    }
                )
                if not predecessor_candidates:
                    raise PipelineError(
                        "REPAIR_ADJ_PREDECESSOR_UNAVAILABLE",
                        f"no base-snapshot trading day before first repair "
                        f"date {first_repair.isoformat()}",
                    )
                adj_predecessor = predecessor_candidates[-1]
                adj_dates = tuple(sorted({adj_predecessor, *dates}))
                for dataset, items in (
                    ("adjustment_factor", adj_dates),
                    ("daily_basic", dates),
                ):
                    heartbeat.set_phase(f"tushare-{dataset}")
                    tushare_aux[dataset] = fetch_rows(
                        ctx,
                        provider="TUSHARE",
                        dataset=dataset,
                        items=items,
                        bulk_fn=lambda wanted, d=dataset: _tushare_bulk(d, wanted),
                        use_bulk=True,
                        item_is_date=True,
                        require_date_presence=(
                            dataset == "adjustment_factor"
                        ),
                        batch_size=batch_size,
                    )

                heartbeat.set_phase("tushare-daily")
                tushare_daily = fetch_rows(
                    ctx,
                    provider="TUSHARE",
                    dataset="daily_bars",
                    items=dates,
                    bulk_fn=lambda wanted: _fill_auxiliary(
                        providers.fetch_tushare_daily_by_trade_date(wanted),
                        daily_basic=tushare_aux.get("daily_basic", []),
                        stock_basic=stock_basic,
                    ),
                    use_bulk=True,
                    item_is_date=True,
                    require_date_presence=True,
                    batch_size=batch_size,
                    return_rows=True,
                )

                # Parent raw extraction: AKSHARE/BAOSTOCK daily_bars for the
                # repair dates ONLY, read-only, sha256-verified against the
                # recorded source_files so tampered/missing parent files can
                # never be silently reused.
                repair_set = set(dates)
                parent_rows, parent_verified_hashes = _read_parent_daily_bars(
                    metadata=metadata,
                    layout=layout,
                    parent_run_id=parent_run_id,
                    repair_set=repair_set,
                )
                akshare_parent = parent_rows.get("AKSHARE", [])
                baostock_parent = parent_rows.get("BAOSTOCK", [])

                # Bounded-scope gate: provider rows must never leak outside
                # the repair window (a bulk fetch answering with extra dates
                # must fail closed, not silently extend the repair).
                for label, rows in (
                    ("TUSHARE", tushare_daily),
                    ("AKSHARE", akshare_parent),
                    ("BAOSTOCK", baostock_parent),
                ):
                    out_of_scope = [
                        row for row in rows if row.get("trade_date") not in repair_set
                    ]
                    if out_of_scope:
                        raise PipelineError(
                            "REPAIR_SCOPE_VIOLATION",
                            f"{label} returned {len(out_of_scope)} rows outside "
                            "the repair dates",
                        )

                # Session presence gates (fail closed before any publication).
                missing = _tushare_daily_missing_sessions(layout, run_id, dates)
                if missing:
                    raise PipelineError(
                        "REPAIR_TUSHARE_SESSION_COVERAGE_INCOMPLETE",
                        f"missing {len(missing)} TUSHARE daily sessions, "
                        f"e.g. {[d.isoformat() for d in missing[:5]]}",
                    )
                pending_now = metadata.pending_failures(run_id)
                if pending_now:
                    raise PipelineError(
                        "REPAIR_FETCH_PENDING_FAILURES",
                        f"{len(pending_now)} pending fetch failures, "
                        f"e.g. {pending_now[:3]}",
                    )

                # Per-date consensus breadth gate (frozen contract, evaluated
                # date by date — NEVER as a cross-date union):
                #   CONSENSUS[d] = AK_CODES[d] & BS_CODES[d]
                #   AK_N[d] > 0, BS_N[d] > 0, CONSENSUS_N[d] > 0
                #   CONSENSUS[d] subset TS_CODES[d]
                for d in dates:
                    ts_codes_d = {
                        str(row["code"])
                        for row in tushare_daily
                        if row.get("trade_date") == d
                    }
                    ak_codes_d = {
                        str(row["code"])
                        for row in akshare_parent
                        if row.get("trade_date") == d
                    }
                    bs_codes_d = {
                        str(row["code"])
                        for row in baostock_parent
                        if row.get("trade_date") == d
                    }
                    if not ak_codes_d:
                        raise PipelineError(
                            "REPAIR_PARENT_PROVIDER_DATE_COVERAGE_INCOMPLETE",
                            f"AKSHARE has no rows on {d.isoformat()}",
                        )
                    if not bs_codes_d:
                        raise PipelineError(
                            "REPAIR_PARENT_PROVIDER_DATE_COVERAGE_INCOMPLETE",
                            f"BAOSTOCK has no rows on {d.isoformat()}",
                        )
                    consensus_d = ak_codes_d & bs_codes_d
                    if not consensus_d:
                        raise PipelineError(
                            "REPAIR_PARENT_PROVIDER_DATE_COVERAGE_INCOMPLETE",
                            f"AKSHARE & BAOSTOCK consensus is empty on "
                            f"{d.isoformat()}",
                        )
                    missing_d = sorted(consensus_d - ts_codes_d)
                    if missing_d:
                        raise PipelineError(
                            "REPAIR_TUSHARE_CONSENSUS_COVERAGE_INCOMPLETE",
                            f"on {d.isoformat()}: {len(missing_d)} consensus "
                            f"codes have no TUSHARE row, e.g. {missing_d[:5]}",
                        )

                rows_by_provider: dict[str, list[dict[str, Any]]] = {}
                if tushare_daily:
                    rows_by_provider["TUSHARE"] = tushare_daily
                if akshare_parent:
                    rows_by_provider["AKSHARE"] = akshare_parent
                if baostock_parent:
                    rows_by_provider["BAOSTOCK"] = baostock_parent
                canonical, records, quarantines = reconcile_daily_rows(
                    rows_by_provider,
                    policy=policy,
                    clock=clock,
                    adjustment_factor_rows=tushare_aux.get("adjustment_factor", []),
                )

                # Every repair date must produce at least one CONFIRMED row;
                # a date whose repaired rows are all single-source or
                # partial-cross-validation is still not repaired.
                confirmed_by_date: dict[date, int] = {}
                for row in canonical:
                    if row.get("reconciliation_status") == "CONFIRMED":
                        d = row["trade_date"]
                        confirmed_by_date[d] = confirmed_by_date.get(d, 0) + 1
                for d in dates:
                    if confirmed_by_date.get(d, 0) <= 0:
                        raise PipelineError(
                            "REPAIR_DATE_NO_CONFIRMED",
                            f"repair date {d.isoformat()} produced no CONFIRMED row",
                        )

                # Composition: base daily minus repair dates plus repaired
                # rows; pool rows carried over unchanged. Final key set must
                # be collision-free (REPAIR_COMPOSED_DUPLICATE_KEY).
                base_kept = [
                    row for row in base_daily if row.get("trade_date") not in repair_set
                ]
                composed = [*base_kept, *canonical]
                composed_keys = [
                    (str(row["code"]), row["trade_date"]) for row in composed
                ]
                if len(composed_keys) != len(set(composed_keys)):
                    raise PipelineError(
                        "REPAIR_COMPOSED_DUPLICATE_KEY",
                        "composed snapshot contains duplicate (code, trade_date)",
                    )
                pool_rows = read_snapshot_pool(layout, base)

                source_rows = metadata._connection.execute(
                    "SELECT path, sha256, row_count FROM source_files "
                    "WHERE ingest_run_id = ?",
                    [run_id],
                ).fetchall()
                new_repair_hashes = {
                    str(Path(path_value).relative_to(layout.root)): sha
                    for path_value, sha, _row_count in source_rows
                }
                # Snapshot provenance is the union of every source actually
                # used: base snapshot sources + verified parent AK/BS hashes +
                # new repair-run TUSHARE hashes. The same source path with two
                # different hashes fails closed.
                source_file_hashes: dict[str, str] = {}
                for label, hashes in (
                    ("base", base.source_file_hashes),
                    ("parent", parent_verified_hashes),
                    ("repair", new_repair_hashes),
                ):
                    for key, sha in hashes.items():
                        previous = source_file_hashes.get(key)
                        if previous is not None and previous != sha:
                            raise PipelineError(
                                "REPAIR_SOURCE_SHA_CONFLICT",
                                f"source path {key} recorded with conflicting "
                                f"sha256 ({previous} vs {sha})",
                            )
                        source_file_hashes[key] = sha
                snapshot = create_snapshot(
                    layout=layout,
                    metadata=metadata,
                    as_of=base.as_of,
                    provider_versions=dict(provider_versions),
                    daily_rows=composed,
                    pool_rows=pool_rows,
                    source_file_hashes=source_file_hashes,
                    reconciliation_policy_version=policy.policy_version,
                    clock=clock,
                    status="RESEARCH_READY",
                )
                # Exact run -> snapshot linkage: record the published
                # snapshot id in the run's own config so reuse resolves the
                # EXACT immutable snapshot and never drifts onto a descendant
                # that inherited these source hashes.
                run_config = json.loads(
                    metadata.get_ingest_run(run_id).config_json or "{}"
                )
                run_config["published_snapshot_id"] = snapshot.snapshot_id
                metadata._connection.execute(
                    "UPDATE ingest_runs SET config_json = ? WHERE run_id = ?",
                    [json.dumps(run_config, sort_keys=True), run_id],
                )
                for record in records:
                    metadata.insert_reconciliation(
                        record.model_copy(
                            update={"snapshot_id": snapshot.snapshot_id}
                        )
                    )
                for record in quarantines:
                    metadata.insert_quarantine(record)
                metadata.finish_ingest_run(
                    run_id=run_id,
                    status="COMPLETED",
                    finished_at=clock(),
                    error=None,
                )
                confirmed_n = sum(
                    1
                    for row in canonical
                    if row.get("reconciliation_status") == "CONFIRMED"
                )
                quarantine_by_date: dict[date, int] = {}
                for record in quarantines:
                    d = record.trade_date
                    if d is not None:
                        quarantine_by_date[d] = quarantine_by_date.get(d, 0) + 1
                per_date_stats = _repair_date_stats(
                    dates=dates,
                    ts_rows=tushare_daily,
                    ak_rows=akshare_parent,
                    bs_rows=baostock_parent,
                    base_daily=base_daily,
                    repaired_rows=canonical,
                    quarantine_by_date=quarantine_by_date,
                )
                metrics["rows_written"] = sum(
                    row_count for _, _, row_count in source_rows
                )
                metrics["wall_seconds"] = round(time.monotonic() - start_wall, 3)
                heartbeat.stop()
                return DailySessionRepairResult(
                    run_id=run_id,
                    snapshot_id=snapshot.snapshot_id,
                    base_snapshot_id=base_snapshot_id,
                    parent_run_id=parent_run_id,
                    repair_dates=dates,
                    base_row_n=len(base_daily),
                    repaired_row_n=len(canonical),
                    confirmed_n=confirmed_n,
                    provisional_n=len(canonical) - confirmed_n,
                    quarantine_n=len(quarantines),
                    per_date_stats=per_date_stats,
                    reused=False,
                    notes=tuple(notes),
                    failure_count=metadata.failure_count(run_id),
                    pending_failures=len(metadata.pending_failures(run_id)),
                    metrics=dict(metrics),
                )
            except BaseException as exc:
                if run_id is not None and run_started_this_attempt:
                    metadata.finish_ingest_run(
                        run_id=run_id,
                        status="FAILED",
                        finished_at=clock(),
                        error=redact(f"{type(exc).__name__}: {exc}"),
                    )
                raise


def _reprocess_preclose_divergences(
    *,
    layout: WarehouseLayout,
    metadata: WarehouseMetadata,
    policy: ReconciliationPolicy,
    clock: Callable[[], datetime],
    adj_run_id: str,
) -> tuple[list[dict[str, Any]], list[ReconciliationRecord]]:
    """Re-evaluate PRECLOSE_DIVERGENCE_UNCONFIRMED records with adj data."""

    quarantines = metadata._connection.execute(
        """
        SELECT code, trade_date FROM quarantine_records
        WHERE reason = 'PRECLOSE_DIVERGENCE_UNCONFIRMED'
        """
    ).fetchall()
    if not quarantines:
        return [], []

    def query_rows(glob_expr: str, where: str, params: list[Any]) -> list[dict[str, Any]]:
        cursor = metadata._connection.execute(
            f"SELECT * FROM read_parquet('{glob_expr}') WHERE {where}",
            params,
        )
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    adj_glob = str(
        layout.raw_dataset_dir("TUSHARE", "adjustment_factor")
        / f"{adj_run_id}-*.parquet"
    )
    if not any(
        layout.raw_dataset_dir("TUSHARE", "adjustment_factor").glob(
            f"{adj_run_id}-*.parquet"
        )
    ):
        return [], []
    daily_globs = {
        provider: str(layout.raw_dataset_dir(provider, "daily_bars") / "*.parquet")
        for provider in ("TUSHARE", "AKSHARE", "BAOSTOCK")
    }
    daily_files_exist = {
        provider: any(
            layout.raw_dataset_dir(provider, "daily_bars").glob("*.parquet")
        )
        for provider in ("TUSHARE", "AKSHARE", "BAOSTOCK")
    }
    raw_cache: dict[tuple[str, str], dict[date, dict[str, Any]]] = {}
    for provider in ("TUSHARE", "AKSHARE", "BAOSTOCK"):
        raw_cache[(provider, "")] = {}

    released: list[dict[str, Any]] = []
    records: list[ReconciliationRecord] = []
    for code, trade_date in quarantines:
        code = str(code)
        adjustment_factor_rows = query_rows(
            adj_glob,
            "code = ?",
            [code],
        )
        adjustment_factor_rows.sort(key=lambda row: row["trade_date"])
        if not adjustment_factor_rows:
            continue
        rows_by_provider: dict[str, list[dict[str, Any]]] = {}
        for provider in ("TUSHARE", "AKSHARE", "BAOSTOCK"):
            if not daily_files_exist[provider]:
                continue
            cache_key = (provider, code)
            if cache_key not in raw_cache:
                raw_cache[cache_key] = {
                    row["trade_date"]: row
                    for row in query_rows(
                        daily_globs[provider],
                        "code = ?",
                        [code],
                    )
                }
            row = raw_cache[cache_key].get(trade_date)
            if row is not None:
                rows_by_provider[provider] = [dict(row)]
        if "TUSHARE" not in rows_by_provider:
            continue
        canonical, reconciled, _ = reconcile_daily_rows(
            rows_by_provider,
            policy=policy,
            clock=clock,
            adjustment_factor_rows=adjustment_factor_rows,
        )
        if canonical and any(
            CORPORATE_ACTION_PRECLOSE_DIVERGENCE in (record.notes or "")
            for record in reconciled
        ):
            released.extend(canonical)
            records.extend(reconciled)
            metadata._connection.execute(
                """
                UPDATE quarantine_records SET reason = 'RESOLVED_CORPORATE_ACTION'
                WHERE code = ? AND trade_date = ?
                  AND reason = 'PRECLOSE_DIVERGENCE_UNCONFIRMED'
                """,
                [code, trade_date],
            )
    return released, records


def _aux_backfill_impl(
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
    workers: int = 1,
    bulk_threshold: int = 200,
    listed_only: bool = False,
    profile: PerformanceProfile | None = None,
    force_finalize: bool = False,
) -> BootstrapResult:
    """Backfill Tushare auxiliary datasets under a dedicated run_id.

    Publishes a RESEARCH_READY snapshot on top of the previous SCREEN_READY
    snapshot, and re-releases ex-date rows whose preclose divergence is now
    confirmed as a corporate action by adjustment_factor.
    """

    today_value = today or date.today()
    if start > end:
        raise PipelineError("INVALID_DATE_RANGE", "start must not be after end")
    if end > today_value:
        raise PipelineError("END_DATE_IN_FUTURE", "end must not be in the future")
    provided_codes = tuple(sorted({code.zfill(6) for code in codes}))
    policy = policy or ReconciliationPolicy()
    profile = profile or PerformanceProfile.load()
    metrics: dict[str, Any] = {
        "rate_limit_waits": 0,
        "rate_limit_wait_seconds": 0.0,
        "worker_restarts": 0,
        "peak_rss_mb": 0,
    }
    providers = provider_set or RealWarehouseProviderSet(
        rate_limit_sink=_rate_limit_sink(layout, metrics)
    )
    fetched_at = clock()
    layout.ensure_dirs()
    run_id: str | None = None

    with WarehouseMetadata(layout.duckdb_path, profile=profile) as metadata:
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
                    lambda: providers.fetch_stock_basic(
                        provided_codes, listed_only=listed_only
                    ),
                    retries=6,
                    backoff_seconds=2.0,
                )
            except CapabilityUnavailable as exc:
                stock_basic = []
                notes.append(f"SKIPPED_DATASET:stock_basic:{exc.status}")
            if all_main_board:
                if not stock_basic:
                    raise PipelineError(
                        "STOCK_BASIC_UNAVAILABLE",
                        "aux backfill requires stock_basic",
                    )
                from limit_pullback.warehouse.fetch import main_board_universe

                codes_tuple = main_board_universe(stock_basic, start, end)
            else:
                codes_tuple = provided_codes or tuple(
                    sorted({str(row["code"]) for row in stock_basic})
                )
            if not codes_tuple:
                raise PipelineError("NO_CODES", "at least one code is required")

            run_id = _run_id(
                "aux-backfill", start, end, codes_tuple, policy.policy_version
            )
            heartbeat = _Heartbeat(layout=layout, run_id=run_id, clock=clock)
            heartbeat.start()
            existing = metadata.get_ingest_run(run_id)
            if (
                existing is not None
                and existing.status == "COMPLETED"
                and not metadata.pending_failures(run_id)
            ):
                return BootstrapResult(
                    run_id=run_id,
                    snapshot_id=None,
                    start_date=start,
                    end_date=end,
                    codes=codes_tuple,
                    reused=True,
                    notes=tuple(["AUX_BACKFILL_COMPLETED"]),
                )
            metadata.begin_ingest_run(
                run_id=run_id,
                kind="aux-backfill",
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

            aux_rows: dict[str, list[dict[str, Any]]] = {}
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
                heartbeat.set_phase(f"aux-{dataset}")
                if use_bulk:
                    aux_rows[dataset] = fetch_rows(
                        ctx,
                        provider="TUSHARE",
                        dataset=dataset,
                        items=trading_dates,
                        bulk_fn=lambda dates, d=dataset: _tushare_bulk(d, dates),
                        use_bulk=True,
                        item_is_date=True,
                        batch_size=batch_size,
                        return_rows=False,
                    )
                else:
                    aux_rows[dataset] = fetch_rows(
                        ctx,
                        provider="TUSHARE",
                        dataset=dataset,
                        items=codes_tuple,
                        per_item_fn=lambda c, d=dataset: _tushare_per_code(d, c),
                        workers=workers,
                        return_rows=False,
                    )

            previous = metadata.latest_snapshot()
            if previous is None:
                raise PipelineError(
                    "NO_BASELINE_SNAPSHOT",
                    "aux backfill requires a published core snapshot",
                )
            import pyarrow as pa

            from limit_pullback.warehouse.parquet import canonical_daily_schema
            from limit_pullback.warehouse.snapshot import read_snapshot_daily_table

            previous_daily_table = read_snapshot_daily_table(layout, previous)
            previous_pool = read_snapshot_pool(layout, previous)
            released, released_records = _reprocess_preclose_divergences(
                layout=layout,
                metadata=metadata,
                policy=policy,
                clock=clock,
                adj_run_id=run_id,
            )
            released_table = (
                pa.Table.from_pylist(
                    released,
                    schema=canonical_daily_schema().remove(
                        canonical_daily_schema().get_field_index(
                            "dataset_snapshot_id"
                        )
                    ),
                )
                if released
                else None
            )
            tables = [
                table
                for table in (previous_daily_table, released_table)
                if table is not None
            ]
            tables = [
                table.drop("dataset_snapshot_id")
                if "dataset_snapshot_id" in table.column_names
                else table
                for table in tables
            ]
            if tables:
                daily_table = pa.concat_tables(tables)
            else:
                daily_table = pa.Table.from_pylist(
                    [],
                    schema=canonical_daily_schema(),
                )
            source_rows = metadata._connection.execute(
                "SELECT path, sha256 FROM source_files WHERE ingest_run_id = ?",
                [run_id],
            ).fetchall()
            source_file_hashes = {
                **previous.source_file_hashes,
                **{
                    str(Path(path_value).relative_to(layout.root)): sha
                    for path_value, sha in source_rows
                },
            }
            snapshot = create_snapshot(
                layout=layout,
                metadata=metadata,
                as_of=end,
                provider_versions=dict(provider_versions),
                daily_rows=[],
                daily_table=daily_table,
                pool_rows=previous_pool,
                source_file_hashes=source_file_hashes,
                reconciliation_policy_version=policy.policy_version,
                clock=clock,
                status="RESEARCH_READY",
            )
            for record in released_records:
                metadata.insert_reconciliation(
                    record.model_copy(update={"snapshot_id": snapshot.snapshot_id})
                )
            notes.append(
                f"RELEASED_CORPORATE_ACTION_ROWS:{len(released)}"
            )
            metadata.finish_ingest_run(
                run_id=run_id,
                status="COMPLETED",
                finished_at=clock(),
                error=None,
            )
            metrics["worker_restarts"] = ctx.worker_restarts
            metrics["peak_rss_mb"] = peak_rss_bytes() // (1024 * 1024)
            return BootstrapResult(
                run_id=run_id,
                snapshot_id=snapshot.snapshot_id,
                start_date=start,
                end_date=end,
                codes=codes_tuple,
                canonical_daily_rows=daily_table.num_rows,
                reconciliation_rows=len(released_records),
                reused=False,
                notes=tuple(notes),
                failure_count=metadata.failure_count(run_id),
                pending_failures=len(metadata.pending_failures(run_id)),
                metrics=dict(metrics),
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
