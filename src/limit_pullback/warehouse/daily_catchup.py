"""Daily provider delta fast path: per-code cache, resume, typed failures.

Operational layer only.  It reuses the formal TDX/Tencent adapters and never
changes reconciliation, coverage, or canonical truth semantics.
"""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from limit_pullback.providers.tdx_daily import fetch_tdx_daily
from limit_pullback.providers.tencent_daily import fetch_tencent_daily
from limit_pullback.runtime import RuntimeConfig
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.staging import load_seed_previous_closes


@dataclass(frozen=True)
class ProviderDeltaResult:
    session: date
    raw_tdx_path: Path
    raw_tencent_path: Path
    provider_total_codes: int
    provider_cached_codes: int
    provider_requested_codes: int
    provider_retry_codes: int
    provider_wall_time: float
    tdx_row_n: int
    tencent_row_n: int
    tdx_failure_n: int
    tencent_failure_n: int
    summary_path: Path


def _sha256_file(path: Path) -> str:
    if not path.exists():
        # No rows fetched -> no parquet written; the empty input hashes as
        # the empty stream so the summary stays deterministic.
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    if rows:
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, path, compression="zstd")


def _code_has_session(path: Path, session: date) -> bool:
    if not path.exists():
        return False
    try:
        table = pq.read_table(path, columns=["trade_date"])
        return any(
            str(value) == session.isoformat()
            for value in table.column("trade_date").to_pylist()
        )
    except Exception:
        return False


def _read_code_cache(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return pq.read_table(path).to_pylist()


def _write_code_cache(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_rows(rows, path)


def fetch_daily_delta(
    layout: WarehouseLayout,
    *,
    base_snapshot_id: str,
    session: date,
    runtime: RuntimeConfig,
    run_id: str,
    cache_root: Path,
) -> ProviderDeltaResult:
    """Fetch one session's TDX primary + Tencent confirm rows with resume."""

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        base = md.snapshot_by_id(base_snapshot_id)
    if base is None:
        raise ValueError(f"unknown base snapshot: {base_snapshot_id}")
    closes = load_seed_previous_closes(layout, base)
    codes = sorted(closes)
    tdx_cache = cache_root / "raw_tdx"
    tx_cache = cache_root / "raw_tencent"
    tdx_cache.mkdir(parents=True, exist_ok=True)
    tx_cache.mkdir(parents=True, exist_ok=True)

    # TDX: resume via per-code cache; fetch only codes missing this session.
    tdx_cached = [
        code for code in codes if _code_has_session(tdx_cache / f"{code}.parquet", session)
    ]
    tdx_missing = [code for code in codes if code not in set(tdx_cached)]
    # Tencent: remove stale caches that lack this session, then fetch missing.
    tx_cached = [
        code for code in codes if _code_has_session(tx_cache / f"{code}.parquet", session)
    ]
    tx_missing = [code for code in codes if code not in set(tx_cached)]
    started = time.time()
    tdx_failures: list[Any] = []
    tx_failures: list[Any] = []
    tdx_wall: list[float] = [0.0]
    tx_wall: list[float] = [0.0]
    chunk_size = 400

    def _fetch_tdx() -> None:
        t0 = time.time()
        for start in range(0, len(tdx_missing), chunk_size):
            chunk = tdx_missing[start : start + chunk_size]
            rows, failures = fetch_tdx_daily(
                chunk,
                sessions=[session],
                run_id=run_id,
                normalize=False,
            )
            tdx_failures.extend(failures)
            by_code: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                by_code.setdefault(str(row["code"]), []).append(row)
            for code, code_rows in by_code.items():
                path = tdx_cache / f"{code}.parquet"
                existing = _read_code_cache(path)
                existing.extend(code_rows)
                _write_code_cache(path, existing)
        tdx_wall[0] = time.time() - t0

    def _fetch_tencent() -> None:
        t0 = time.time()
        for code in tx_missing:
            path = tx_cache / f"{code}.parquet"
            if path.exists():
                path.unlink()
        _rows, failures = fetch_tencent_daily(
            tx_missing,
            sessions=[session],
            cache_dir=tx_cache,
            workers=runtime.tencent_workers,
            retries=2,
            run_id=run_id,
            normalize=False,
        )
        tx_failures.extend(failures)
        tx_wall[0] = time.time() - t0

    # TDX (TCP) and Tencent (HTTP) are independent fetches for the same
    # session: overlap them so the wall time is the slower provider, not the
    # sum. Failures from either thread still fail the run via f.result().
    with ThreadPoolExecutor(max_workers=2) as pool:
        tdx_future = pool.submit(_fetch_tdx)
        tx_future = pool.submit(_fetch_tencent)
        tdx_future.result()
        tx_future.result()

    tdx_rows: list[dict[str, Any]] = []
    for code in codes:
        tdx_rows.extend(_read_code_cache(tdx_cache / f"{code}.parquet"))
    tdx_rows = [
        row for row in tdx_rows if row.get("trade_date") == session
    ]
    tdx_rows.sort(key=lambda row: (row["code"], row["trade_date"]))

    tx_rows = []
    for code in codes:
        tx_rows.extend(_read_code_cache(tx_cache / f"{code}.parquet"))
    tx_rows = [
        row for row in tx_rows if row.get("trade_date") == session
    ]
    tx_rows.sort(key=lambda row: (row["code"], row["trade_date"]))
    wall = time.time() - started

    raw_tdx_path = cache_root / "raw_tdx_full.parquet"
    raw_tencent_path = cache_root / "raw_tencent_full.parquet"
    _write_rows(tdx_rows, raw_tdx_path)
    _write_rows(tx_rows, raw_tencent_path)
    summary = {
        "run_id": run_id,
        "session": session.isoformat(),
        "provider_total_codes": len(codes),
        "provider_cached_codes": len(tdx_cached),
        "provider_requested_codes": len(tdx_missing),
        "provider_retry_codes": len(tdx_failures) + len(tx_failures),
        "provider_wall_time": round(wall, 3),
        "tdx_wall_seconds": round(tdx_wall[0], 3),
        "tencent_wall_seconds": round(tx_wall[0], 3),
        "tdx_row_n": len(tdx_rows),
        "tencent_row_n": len(tx_rows),
        "tdx_failure_n": len(tdx_failures),
        "tencent_failure_n": len(tx_failures),
        "tdx_full_sha256": _sha256_file(raw_tdx_path),
        "tencent_full_sha256": _sha256_file(raw_tencent_path),
    }
    summary_path = cache_root / "fetch-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return ProviderDeltaResult(
        session=session,
        raw_tdx_path=raw_tdx_path,
        raw_tencent_path=raw_tencent_path,
        provider_total_codes=len(codes),
        provider_cached_codes=len(tdx_cached),
        provider_requested_codes=len(tdx_missing),
        provider_retry_codes=len(tdx_failures) + len(tx_failures),
        provider_wall_time=wall,
        tdx_row_n=len(tdx_rows),
        tencent_row_n=len(tx_rows),
        tdx_failure_n=len(tdx_failures),
        tencent_failure_n=len(tx_failures),
        summary_path=summary_path,
    )
