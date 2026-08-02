"""data-validate: bounded-memory integrity, traceability and manifest checks.

The full-market path is deliberately streaming: canonical parquet files are
read row-group by row-group, raw provider rows are never materialized as one
list, validation issues are written to per-worker JSONL artifacts, and the main
process only merges counts/summaries.  Multi-worker mode uses ``spawn`` so a
worker never inherits the parent's Arrow/DuckDB heap.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import multiprocessing as mp
import os
import resource
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import ValidationIssue, ValidationResult
from limit_pullback.warehouse.parquet import row_hash, sha256_file

DAILY_HASH_FIELDS = (
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
)
POOL_HASH_FIELDS = (
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
)
PRICE_TOLERANCE = Decimal("0.01")
PRICE_RELATIVE = Decimal("0.001")

RAW_PROVIDERS = ("TUSHARE", "AKSHARE", "BAOSTOCK")
NON_TUSHARE_PROVIDERS = ("AKSHARE", "BAOSTOCK")
WORKER_SOFT_LIMIT_BYTES = 1_500_000_000
WORKER_HARD_LIMIT_BYTES = 1_800_000_000
ISSUE_IN_MEMORY_LIMIT = 5_000
_CANONICAL_DAILY_COLUMNS = (
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
)


def _issue(check: str, detail: str, severity: str = "error") -> ValidationIssue:
    return ValidationIssue(check=check, severity=severity, detail=detail)


def _schema_has_float(schema: Any) -> bool:
    return any(
        str(field.type) in {"float", "double", "halffloat"}
        for field in schema
    )


def _check_unique(
    rows: list[dict[str, Any]],
    *,
    fields: tuple[str, ...],
    check: str,
    issues: list[ValidationIssue],
) -> None:
    seen: dict[tuple[Any, ...], int] = {}
    for row in rows:
        key = tuple(row.get(field) for field in fields)
        seen[key] = seen.get(key, 0) + 1
    duplicates = sorted((key, count) for key, count in seen.items() if count > 1)
    for key, count in duplicates[:20]:
        issues.append(
            _issue(check, f"{count}x duplicate for {key}")
        )


def _check_daily_row(
    row: dict[str, Any],
    *,
    snapshot_as_of: date,
    today: date,
    issues: list[ValidationIssue],
) -> None:
    code = str(row["code"])
    trade_date = row["trade_date"]
    open_price = row["open"]
    high = row["high"]
    low = row["low"]
    close = row["close"]
    if not (open_price > 0 and high > 0 and low > 0 and close > 0):
        issues.append(_issue("OHLC_POSITIVE", f"{code} {trade_date} has non-positive price"))
    if high < max(open_price, low, close) or low > min(open_price, high, close):
        issues.append(_issue("OHLC_RELATION", f"{code} {trade_date} violates OHLC relation"))
    if row["volume"] < 0 or row["amount"] < 0:
        issues.append(_issue("NON_NEGATIVE", f"{code} {trade_date} has negative volume/amount"))
    if trade_date > snapshot_as_of:
        issues.append(_issue("DATE_RANGE", f"{code} {trade_date} beyond snapshot as_of"))
    if trade_date > today:
        issues.append(_issue("FUTURE_RECORD", f"{code} {trade_date} is in the future"))
    computed = row_hash(DAILY_HASH_FIELDS, row)
    if computed != row["source_row_hash"]:
        issues.append(
            _issue("ROW_HASH", f"{code} {trade_date} raw hash mismatch")
        )


def _previous_close_index(
    raw_rows_by_provider: dict[str, dict[tuple[str, date], dict[str, Any]]],
) -> dict[str, dict[tuple[str, date], Any]]:
    """Index the immediately preceding raw close for each provider/code/date.

    Retained as a small-fixture compatibility helper.  The streaming full-market
    path computes the same predecessor without materializing all raw rows.
    """

    indexed: dict[str, dict[tuple[str, date], Any]] = {}
    for provider, rows_by_key in raw_rows_by_provider.items():
        previous_by_code: dict[str, dict[str, Any]] = {}
        provider_index: dict[tuple[str, date], Any] = {}
        for code, trade_date in sorted(rows_by_key):
            previous = previous_by_code.get(code)
            if previous is not None:
                provider_index[(code, trade_date)] = previous.get("close")
            previous_by_code[code] = rows_by_key[(code, trade_date)]
        indexed[provider] = provider_index
    return indexed


def _read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    from limit_pullback.warehouse.parquet import read_rows

    return read_rows(path)


def _canonical_path(
    layout: WarehouseLayout,
    snapshot,
    dataset: str,
) -> Path | None:
    suffix = f"/{dataset}/{snapshot.snapshot_id}.parquet"
    for relative in snapshot.canonical_file_hashes:
        if relative.endswith(suffix):
            return layout.root / relative
    return None


def _raw_daily_files(
    layout: WarehouseLayout,
    snapshot,
) -> dict[str, list[Path]]:
    files: dict[str, list[Path]] = {provider: [] for provider in RAW_PROVIDERS}
    for relative in snapshot.source_file_hashes:
        if "/daily_bars/" not in relative:
            continue
        parts = Path(relative).parts
        try:
            provider = parts[parts.index("raw") + 1].upper()
        except (ValueError, IndexError):
            continue
        if provider not in files:
            continue
        path = layout.root / relative
        if path.exists():
            files[provider].append(path)
    return files


@dataclass(frozen=True)
class _Partition:
    worker_id: int
    row_groups: tuple[int, ...]
    lo_code: str
    hi_code: str


def _build_partitions(canonical_daily: Path, workers: int) -> list[_Partition]:
    import pyarrow.parquet as pq

    if workers < 1:
        raise ValueError("workers must be >= 1")
    pf = pq.ParquetFile(canonical_daily)
    metadata = pf.metadata
    code_index = pf.schema_arrow.names.index("code")
    groups_info = []
    for index in range(metadata.num_row_groups):
        row_group = metadata.row_group(index)
        stats = row_group.column(code_index).statistics
        lo = str(stats.min) if stats is not None and stats.min is not None else ""
        hi = str(stats.max) if stats is not None and stats.max is not None else ""
        groups_info.append((row_group.num_rows, lo, hi))
    if not groups_info:
        return [
            _Partition(worker_id=index, row_groups=(), lo_code="", hi_code="")
            for index in range(workers)
        ]

    if workers == 1 or len(groups_info) == 1:
        grouped = [list(range(len(groups_info)))]
    elif workers >= len(groups_info):
        grouped = [[index] for index in range(len(groups_info))]
    else:
        total = sum(rows for rows, _, _ in groups_info)
        splits = [0]
        accumulator = 0
        for index, (rows, _, _) in enumerate(groups_info[:-1]):
            accumulator += rows
            if accumulator >= total * len(splits) / workers:
                splits.append(index + 1)
        while len(splits) < workers:
            splits.append(len(groups_info))
        splits = sorted(set(splits))
        grouped = [
            list(range(splits[index], splits[index + 1]))
            for index in range(len(splits) - 1)
        ]

    partitions: list[_Partition] = []
    for worker_id in range(workers):
        group = grouped[worker_id] if worker_id < len(grouped) else []
        if not group:
            partitions.append(
                _Partition(worker_id=worker_id, row_groups=(), lo_code="", hi_code="")
            )
            continue
        lo = groups_info[group[0]][1]
        hi = groups_info[group[-1]][2]
        partitions.append(
            _Partition(
                worker_id=worker_id,
                row_groups=tuple(group),
                lo_code=lo,
                hi_code=hi,
            )
        )
    return partitions


def _write_tushare_partitions(
    tushare_files: Sequence[Path],
    partitions: Sequence[_Partition],
    temp_dir: Path,
    codes: frozenset[str] | None = None,
) -> list[list[Path]]:
    """Pre-partition date-major Tushare raw rows by code range.

    Tushare raw files contain all codes per date batch, so workers must not
    each scan the whole Tushare dataset.  This single pass sorts each original
    file's rows per worker to disk; workers then stream-merge those files with
    bounded memory.
    """

    import pyarrow.parquet as pq

    temp_dir.mkdir(parents=True, exist_ok=True)
    worker_paths: list[list[Path]] = [[] for _ in partitions]
    for file_index, path in enumerate(tushare_files):
        rows_by_worker: dict[int, list[tuple[str, date, str]]] = {}
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(
            columns=("code", "trade_date", "row_hash"),
            batch_size=131072,
            use_threads=False,
        ):
            for row in batch.to_pylist():
                code = str(row["code"])
                if codes is not None and code not in codes:
                    continue
                trade_date = row["trade_date"]
                raw_hash = str(row["row_hash"])
                for index, partition in enumerate(partitions):
                    if not partition.row_groups:
                        continue
                    if partition.lo_code <= code <= partition.hi_code:
                        rows_by_worker.setdefault(index, []).append(
                            (code, trade_date, raw_hash)
                        )
        for index, rows in rows_by_worker.items():
            if not rows:
                continue
            rows.sort(key=lambda item: (item[0], item[1]))
            target = temp_dir / f"tushare-{index}-{file_index:04d}.jsonl"
            with target.open("w", encoding="utf-8") as stream:
                for code, trade_date, raw_hash in rows:
                    stream.write(
                        f"{code}\t{trade_date.isoformat()}\t{raw_hash}\n"
                    )
            worker_paths[index].append(target)
    return worker_paths


def _file_code_range(path: Path):
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    if pf.metadata.num_row_groups == 0:
        return None, None
    code_index = pf.schema_arrow.names.index("code")
    stats = pf.metadata.row_group(0).column(code_index).statistics
    if stats is None or stats.min is None or stats.max is None:
        return None, None
    return str(stats.min), str(stats.max)


def _select_raw_files(
    files: Sequence[Path],
    partition: _Partition,
) -> list[Path]:
    if not partition.row_groups:
        return []
    selected: list[Path] = []
    for path in files:
        lo, hi = _file_code_range(path)
        if lo is None:
            selected.append(path)
            continue
        if lo <= partition.hi_code and hi >= partition.lo_code:
            selected.append(path)
    return selected


def _write_issue_line(stream, issue: ValidationIssue) -> None:
    stream.write(
        json.dumps(
            {
                "check": issue.check,
                "severity": issue.severity,
                "detail": issue.detail,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )


def _iter_raw_sorted(path: Path) -> Iterable[tuple[str, date, Any, str]]:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(
        columns=("code", "trade_date", "close", "row_hash"),
        batch_size=2048,
        use_threads=False,
    ):
        for row in batch.to_pylist():
            yield (
                str(row["code"]),
                row["trade_date"],
                row.get("close"),
                str(row["row_hash"]),
            )


def _iter_raw_sorted_codes(
    path: Path,
    codes: frozenset[str],
) -> Iterable[tuple[str, date, Any, str]]:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(
        columns=("code", "trade_date", "close", "row_hash"),
        batch_size=2048,
        use_threads=False,
    ):
        for row in batch.to_pylist():
            code = str(row["code"])
            if code not in codes:
                continue
            yield (
                code,
                row["trade_date"],
                row.get("close"),
                str(row["row_hash"]),
            )


def _iter_tushare_partition_lines(
    path: Path,
) -> Iterable[tuple[str, date, Any, str]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            code, trade_date_iso, raw_hash = line.split("\t", 2)
            yield (code, date.fromisoformat(trade_date_iso), None, raw_hash)


def _validate_partition(
    *,
    canonical_daily: Path,
    partition: _Partition,
    raw_files_by_provider: Mapping[str, Sequence[Path]],
    tushare_partition_files: Sequence[Path] | None,
    snapshot_as_of: date,
    today: date,
    issue_path: Path,
    use_seen_unique: bool,
    codes: frozenset[str] | None = None,
) -> dict[str, Any]:
    import pyarrow.parquet as pq

    raw_cursors: dict[str, dict[str, Any]] = {}
    if tushare_partition_files:
        tushare_iterator = heapq.merge(
            *[_iter_tushare_partition_lines(path) for path in tushare_partition_files],
            key=lambda item: (item[0], item[1]),
        )
        raw_cursors["TUSHARE"] = {
            "iterator": tushare_iterator,
            "current": next(tushare_iterator, None),
            "last_close_by_code": {},
        }
    for provider in NON_TUSHARE_PROVIDERS:
        files = list(raw_files_by_provider.get(provider, ()))
        if not files:
            continue

        def make_iterator(path: Path):
            if codes is not None:
                return _iter_raw_sorted_codes(path, codes)
            return _iter_raw_sorted(path)

        iterator = heapq.merge(
            *[make_iterator(path) for path in files],
            key=lambda item: (item[0], item[1]),
        )
        raw_cursors[provider] = {
            "iterator": iterator,
            "current": next(iterator, None),
            "last_close_by_code": {},
        }

    def advance_raw(
        cursor: dict[str, Any],
        key: tuple[str, date],
    ) -> tuple[list[str] | None, Any]:
        while cursor["current"] is not None:
            code, trade_date, close, raw_hash = cursor["current"]
            if (code, trade_date) >= key:
                break
            cursor["last_close_by_code"][code] = close
            cursor["current"] = next(cursor["iterator"], None)
        current = cursor["current"]
        if current is None or (current[0], current[1]) != key:
            return None, None
        hashes: list[str] = []
        group_close = None
        while cursor["current"] is not None and (cursor["current"][0], cursor["current"][1]) == key:
            hashes.append(cursor["current"][3])
            group_close = cursor["current"][2]
            cursor["current"] = next(cursor["iterator"], None)
        return hashes, group_close

    issue_count = 0
    seen_counts: dict[tuple[str, date], int] = {}
    previous_key: tuple[str, date] | None = None
    duplicate_run = 0
    active_raw_key: tuple[str, date] | None = None
    active_hashes: list[str] | None = None
    active_prev: Any = None
    active_group_close: Any = None
    with issue_path.open("w", encoding="utf-8") as issue_stream:
        def record(issue: ValidationIssue) -> None:
            nonlocal issue_count
            issue_count += 1
            _write_issue_line(issue_stream, issue)

        local_issues: list[ValidationIssue] = []
        pf = pq.ParquetFile(canonical_daily)
        for batch in pf.iter_batches(
            row_groups=list(partition.row_groups) or None,
            columns=list(_CANONICAL_DAILY_COLUMNS),
            batch_size=4096,
            use_threads=False,
        ):
            for row in batch.to_pylist():
                code = str(row["code"])
                if codes is not None and code not in codes:
                    continue
                trade_date = row["trade_date"]
                key = (code, trade_date)

                if use_seen_unique:
                    seen_counts[key] = seen_counts.get(key, 0) + 1
                else:
                    if previous_key is not None and key == previous_key:
                        duplicate_run += 1
                    else:
                        if duplicate_run > 1:
                            record(_issue("CANONICAL_UNIQUE", f"{duplicate_run}x duplicate for {previous_key}"))
                        duplicate_run = 1
                    previous_key = key

                local_issues.clear()
                _check_daily_row(
                    row,
                    snapshot_as_of=snapshot_as_of,
                    today=today,
                    issues=local_issues,
                )
                provider = str(row["selected_provider"])
                cursor = raw_cursors.get(provider)
                if key != active_raw_key:
                    active_raw_key = key
                    active_hashes, active_group_close = (
                        advance_raw(cursor, key)
                        if cursor is not None
                        else (None, None)
                    )
                    active_prev = (
                        cursor["last_close_by_code"].get(code)
                        if cursor is not None
                        else None
                    )
                traceable = bool(active_hashes) and row["source_row_hash"] in active_hashes
                if not traceable:
                    local_issues.append(
                        _issue(
                            "TRACEABILITY",
                            f"{code} {trade_date} source row not found in {provider} raw",
                        )
                    )
                if row["reconciliation_status"] not in {
                    "CONFIRMED",
                    "PROVISIONAL",
                    "INCOMPLETE",
                }:
                    local_issues.append(
                        _issue(
                            "RECONCILIATION_STATUS",
                            f"{code} {trade_date} invalid status",
                        )
                    )
                if provider in NON_TUSHARE_PROVIDERS:
                    cursor = raw_cursors.get(provider)
                    previous = active_prev
                    if previous is not None:
                        difference = abs(Decimal(row["preclose"]) - Decimal(previous))
                        scale = max(abs(Decimal(row["preclose"])), abs(Decimal(previous)))
                        if difference > max(PRICE_TOLERANCE, PRICE_RELATIVE * scale):
                            local_issues.append(
                                _issue(
                                    "PRECLOSE_CONTINUITY",
                                    f"{code} {trade_date} preclose vs "
                                    f"{provider} prior close mismatch",
                                )
                            )
                    if (
                        cursor is not None
                        and active_group_close is not None
                        and active_raw_key == key
                    ):
                        cursor["last_close_by_code"][code] = active_group_close
                for issue in local_issues:
                    record(issue)

        if use_seen_unique:
            for key, count in sorted(seen_counts.items()):
                if count > 1:
                    record(_issue("CANONICAL_UNIQUE", f"{count}x duplicate for {key}"))
        elif duplicate_run > 1:
            record(_issue("CANONICAL_UNIQUE", f"{duplicate_run}x duplicate for {previous_key}"))

    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if os.uname().sysname != "Darwin":
        peak_rss = peak_rss * 1024
    return {
        "status": "OK",
        "issue_count": issue_count,
        "peak_rss_bytes": int(peak_rss),
    }


def _process_rss_bytes(pid: int) -> int | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        value = result.stdout.strip()
        if not value:
            return None
        return int(value) * 1024
    except Exception:
        return None


def _worker_entry(
    *,
    canonical_daily: str,
    partition: _Partition,
    raw_files_by_provider: dict[str, list[str]],
    tushare_partition_paths: list[str],
    snapshot_as_of: str,
    today: str,
    issue_path: str,
    result_path: str,
    use_seen_unique: bool,
    codes: frozenset[str] | None = None,
) -> None:
    result: dict[str, Any] = {
        "status": "ERROR",
        "error": None,
        "issue_count": 0,
        "peak_rss_bytes": 0,
    }
    try:
        if not partition.row_groups:
            result = {
                "status": "EMPTY",
                "error": None,
                "issue_count": 0,
                "peak_rss_bytes": 0,
            }
        else:
            result = _validate_partition(
                canonical_daily=Path(canonical_daily),
                partition=partition,
                raw_files_by_provider={
                    provider: [Path(path) for path in paths]
                    for provider, paths in raw_files_by_provider.items()
                },
                tushare_partition_files=(
                    [Path(path) for path in tushare_partition_paths]
                    if tushare_partition_paths
                    else None
                ),
                snapshot_as_of=date.fromisoformat(snapshot_as_of),
                today=date.fromisoformat(today),
                issue_path=Path(issue_path),
                use_seen_unique=use_seen_unique,
                codes=codes,
            )
    except Exception as exc:  # pragma: no cover - failure path
        result = {
            "status": "ERROR",
            "error": repr(exc),
            "issue_count": 0,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
    Path(result_path).write_text(json.dumps(result), encoding="utf-8")


def _run_worker_processes(
    *,
    canonical_daily: Path,
    partitions: Sequence[_Partition],
    raw_files_by_partition: Mapping[int, Mapping[str, Sequence[Path]]],
    tushare_partition_files: Sequence[Sequence[Path]],
    snapshot_as_of: date,
    today: date,
    temp_dir: Path,
    use_seen_unique: bool,
    codes: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    context = mp.get_context("spawn")
    processes: list[mp.Process] = []
    result_paths: list[Path] = []
    for partition in partitions:
        result_path = temp_dir / f"worker-{partition.worker_id}.json"
        result_paths.append(result_path)
        if not partition.row_groups:
            result_path.write_text(
                json.dumps(
                    {
                        "status": "EMPTY",
                        "error": None,
                        "issue_count": 0,
                        "peak_rss_bytes": 0,
                    }
                ),
                encoding="utf-8",
            )
            continue
        process = context.Process(
            target=_worker_entry,
            kwargs={
                "canonical_daily": str(canonical_daily),
                "partition": partition,
                "raw_files_by_provider": {
                    provider: [str(path) for path in paths]
                    for provider, paths in raw_files_by_partition[
                        partition.worker_id
                    ].items()
                },
                "tushare_partition_paths": [
                    str(path)
                    for path in tushare_partition_files[partition.worker_id]
                ],
                "snapshot_as_of": snapshot_as_of.isoformat(),
                "today": today.isoformat(),
                "issue_path": str(temp_dir / f"issues-{partition.worker_id}.jsonl"),
                "result_path": str(result_path),
                "use_seen_unique": use_seen_unique,
                "codes": codes,
            },
        )
        process.start()
        processes.append(process)

    peak_rss = 0
    try:
        while any(process.is_alive() for process in processes):
            for process in processes:
                rss = _process_rss_bytes(process.pid)
                if rss is not None:
                    peak_rss = max(peak_rss, rss)
                    if rss > WORKER_HARD_LIMIT_BYTES:
                        for alive in processes:
                            if alive.is_alive():
                                alive.terminate()
                        for alive in processes:
                            alive.join(timeout=10)
                        raise RuntimeError(
                            "WORKER_MEMORY_LIMIT: worker "
                            f"{process.pid} RSS {rss} > {WORKER_HARD_LIMIT_BYTES}"
                        )
            time.sleep(0.5)
        for process in processes:
            process.join(timeout=10)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    results: list[dict[str, Any]] = []
    for partition, result_path in zip(partitions, result_paths):
        if result_path.exists():
            results.append(json.loads(result_path.read_text(encoding="utf-8")))
        else:
            results.append(
                {
                    "status": "ERROR",
                    "error": "missing worker result",
                    "issue_count": 0,
                    "peak_rss_bytes": 0,
                }
            )
    for result in results:
        if result.get("status") == "ERROR":
            raise RuntimeError(
                f"data-validate worker failed: {result.get('error')}"
            )
    return results, peak_rss


def _output_hash(
    snapshot,
    issue_count: int,
    check_counts: Mapping[str, int],
) -> str:
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "canonical_file_hashes": dict(sorted(snapshot.canonical_file_hashes.items())),
        "source_file_hashes": dict(sorted(snapshot.source_file_hashes.items())),
        "issue_count": issue_count,
        "check_counts": dict(sorted(check_counts.items())),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _merge_issue_files(
    paths: Sequence[Path],
    destination: Path,
) -> tuple[int, dict[str, int]]:
    issue_count = 0
    check_counts: dict[str, int] = {}
    with destination.open("w", encoding="utf-8") as output:
        for path in paths:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    output.write(line + "\n")
                    issue_count += 1
                    try:
                        check = json.loads(line)["check"]
                    except Exception:
                        check = "UNKNOWN"
                    check_counts[check] = check_counts.get(check, 0) + 1
    return issue_count, check_counts


def data_validate(
    layout: WarehouseLayout,
    *,
    snapshot_id: str | None = None,
    today: date | None = None,
    workers: int = 1,
    temp_dir: Path | None = None,
    codes: Sequence[str] | None = None,
) -> ValidationResult:
    """Validate a snapshot with bounded memory and optional worker control."""

    today_value = today or date.today()
    code_filter = frozenset(codes) if codes is not None else None
    main_issues: list[ValidationIssue] = []
    if not layout.duckdb_path.exists():
        return ValidationResult(
            valid=False,
            snapshot_id=snapshot_id,
            issues=(_issue("SNAPSHOT", "no snapshot found"),),
            workers=workers,
        )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = (
            metadata.snapshot_by_id(snapshot_id) if snapshot_id else metadata.latest_snapshot()
        )
        if snapshot is None:
            return ValidationResult(
                valid=False,
                snapshot_id=snapshot_id,
                issues=(_issue("SNAPSHOT", "no snapshot found"),),
                workers=workers,
            )

        manifest_path = Path(snapshot.manifest_path or "")
        if not manifest_path.exists():
            main_issues.append(_issue("MANIFEST", f"manifest missing: {manifest_path}"))
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("snapshot_id") != snapshot.snapshot_id:
                    main_issues.append(_issue("MANIFEST", "manifest snapshot_id mismatch"))
                if str(manifest.get("as_of")) != snapshot.as_of.isoformat():
                    main_issues.append(_issue("MANIFEST", "manifest as_of mismatch"))
            except json.JSONDecodeError as exc:
                main_issues.append(_issue("MANIFEST", f"manifest unreadable: {exc}"))

        for relative_path, expected in snapshot.source_file_hashes.items():
            path = layout.root / relative_path
            if not path.exists():
                main_issues.append(_issue("SOURCE_FILE", f"missing raw file: {relative_path}"))
                continue
            if sha256_file(path) != expected:
                main_issues.append(_issue("SOURCE_FILE_HASH", f"hash mismatch: {relative_path}"))

        for relative_path, expected in snapshot.canonical_file_hashes.items():
            path = layout.root / relative_path
            if not path.exists():
                main_issues.append(_issue("CANONICAL_FILE", f"missing canonical file: {relative_path}"))
                continue
            if sha256_file(path) != expected:
                main_issues.append(_issue("CANONICAL_FILE_HASH", f"hash mismatch: {relative_path}"))

        from pyarrow.parquet import read_schema

        for relative_path in snapshot.canonical_file_hashes:
            schema = read_schema(str(layout.root / relative_path))
            if _schema_has_float(schema):
                main_issues.append(_issue("DECIMAL_PRECISION", f"float column in {relative_path}"))

        canonical_daily = _canonical_path(layout, snapshot, "daily_bars")
        canonical_pool = _canonical_path(layout, snapshot, "limit_up_pool")
        if canonical_daily is None or not canonical_daily.exists():
            main_issues.append(_issue("CANONICAL_FILE", "canonical daily parquet missing"))

        pool_issues: list[ValidationIssue] = []
        if canonical_pool is not None and canonical_pool.exists():
            pool_rows = _read_parquet_rows(canonical_pool)
            _check_unique(
                pool_rows,
                fields=("code", "trade_date"),
                check="POOL_UNIQUE",
                issues=pool_issues,
            )
            for row in pool_rows:
                if row["limit_price"] <= 0:
                    pool_issues.append(
                        _issue("POOL_LIMIT_PRICE", f"{row['code']} {row['trade_date']} non-positive")
                    )
                if row["trade_date"] > snapshot.as_of:
                    pool_issues.append(
                        _issue("DATE_RANGE", f"{row['code']} {row['trade_date']} beyond snapshot")
                    )
                computed = row_hash(POOL_HASH_FIELDS, row)
                if computed != row["source_row_hash"]:
                    pool_issues.append(
                        _issue("ROW_HASH", f"{row['code']} {row['trade_date']} pool hash mismatch")
                    )
        main_issues.extend(pool_issues)

        run_dir = (
            temp_dir
            or layout.root
            / "tmp"
            / "validate"
            / f"{snapshot.snapshot_id}-{uuid4().hex[:8]}"
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        partitions = _build_partitions(canonical_daily, workers)
        raw_files = _raw_daily_files(layout, snapshot)
        tushare_paths = _write_tushare_partitions(
            raw_files.get("TUSHARE", ()),
            partitions,
            run_dir,
            codes=code_filter,
        )
        raw_by_partition: dict[int, dict[str, list[Path]]] = {}
        for partition in partitions:
            raw_by_partition[partition.worker_id] = {
                provider: _select_raw_files(raw_files.get(provider, ()), partition)
                for provider in NON_TUSHARE_PROVIDERS
            }

        import pyarrow.parquet as pq

        canonical_total_rows = pq.ParquetFile(canonical_daily).metadata.num_rows
        use_seen_unique = canonical_total_rows <= 200_000
        worker_results, peak_rss = _run_worker_processes(
            canonical_daily=canonical_daily,
            partitions=partitions,
            raw_files_by_partition=raw_by_partition,
            tushare_partition_files=tushare_paths,
            snapshot_as_of=snapshot.as_of,
            today=today_value,
            temp_dir=run_dir,
            use_seen_unique=use_seen_unique,
            codes=code_filter,
        )

        main_issue_path = run_dir / "main-issues.jsonl"
        with main_issue_path.open("w", encoding="utf-8") as stream:
            for issue in main_issues:
                _write_issue_line(stream, issue)

        worker_issue_paths = [
            run_dir / f"issues-{partition.worker_id}.jsonl"
            for partition in partitions
        ]
        merged_path = run_dir / "issues.jsonl"
        issue_count, check_counts = _merge_issue_files(
            [main_issue_path, *worker_issue_paths],
            merged_path,
        )
        for result in worker_results:
            peak_rss = max(peak_rss, int(result.get("peak_rss_bytes") or 0))

        result_issues: tuple[ValidationIssue, ...] = ()
        if issue_count <= ISSUE_IN_MEMORY_LIMIT:
            result_issues = tuple(
                ValidationIssue.model_validate(json.loads(line))
                for line in merged_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )

        notes: list[str] = []
        if peak_rss > WORKER_SOFT_LIMIT_BYTES:
            notes.append("WORKER_SOFT_MEMORY_WARNING")

        return ValidationResult(
            valid=issue_count == 0,
            snapshot_id=snapshot.snapshot_id,
            issues=result_issues,
            issue_artifact_path=str(merged_path),
            issue_count=issue_count,
            check_counts=check_counts,
            output_hash=_output_hash(snapshot, issue_count, check_counts),
            workers=workers,
            peak_rss_bytes=peak_rss,
            notes=tuple(notes),
        )


__all__ = [
    "PRICE_RELATIVE",
    "PRICE_TOLERANCE",
    "WORKER_HARD_LIMIT_BYTES",
    "WORKER_SOFT_LIMIT_BYTES",
    "_previous_close_index",
    "data_validate",
]
