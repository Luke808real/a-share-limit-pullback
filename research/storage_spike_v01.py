"""LOCAL ANALYTICS STORAGE SPIKE v0.1 (read-only, research-only)."""

from __future__ import annotations

import json
import os
import re
import resource
import sys
import time
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from limit_pullback.screen.canonical import load_canonical_market
from limit_pullback.warehouse.layout import WarehouseLayout


ROOT = Path("/Users/luke808/AI/V flash")
SNAP = "snap-2026-07-31-b5f84004de8a"
CANONICAL = ROOT / "data/canonical/daily_bars" / f"{SNAP}.parquet"
TMP = ROOT / "data/tmp/storage-spike"
HARD_LIMIT = 1_800_000_000
SOFT_LIMIT = 1_500_000_000
COLUMNS = [
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


def rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if os.uname().sysname == "Darwin" else value * 1024


def sample_codes(size: int) -> list[str]:
    state_dir = ROOT / "data/screen/states"
    all_codes = sorted(
        path.stem for path in state_dir.glob("[0-9][0-9][0-9][0-9][0-9][0-9].json")
    )
    if size >= len(all_codes):
        return all_codes
    step = (len(all_codes) - 1) / (size - 1)
    return sorted({all_codes[round(index * step)] for index in range(size)})


def codes_sql(codes: list[str]) -> str:
    return ",".join("'" + code + "'" for code in codes)


def bench_current_pyarrow(codes: list[str]) -> dict:
    if len(codes) >= 3191:
        return {"completed": False, "reason": "SKIPPED_PYARROW_FULL_MATERIALIZATION_MEMORY_GUARD"}
    layout = WarehouseLayout(ROOT / "data")
    stats: dict = {}
    started = time.perf_counter()
    market = load_canonical_market(
        layout,
        snapshot_id=SNAP,
        codes=codes,
        stats=stats,
    )
    elapsed = time.perf_counter() - started
    return {
        "completed": True,
        "codes": len(codes),
        "seconds": round(elapsed, 3),
        "peak_rss_bytes": rss_bytes(),
        "rows_scanned": stats.get("rows_read"),
        "rows_returned": stats.get("rows_materialized"),
        "rows_returned_actual": sum(len(bars) for bars in market.bars_by_code.values()),
    }


def new_duckdb() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='4GB'")
    con.execute("SET preserve_insertion_order=false")
    TMP.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{TMP / 'duckdb-tmp'}'")
    return con


def explain_rows_scanned(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    result = con.execute(f"EXPLAIN ANALYZE {sql}").fetchall()
    text = "\n".join(str(row) for row in result)
    match = re.search(r"rows scanned:\s*(\d+)", text)
    return int(match.group(1)) if match else -1


def bench_duckdb_parquet(con: duckdb.DuckDBPyConnection, codes: list[str]) -> dict:
    cols = ", ".join(COLUMNS)
    where = (
        "WHERE reconciliation_status='CONFIRMED' AND trade_date <= DATE '2026-07-31' "
        f"AND code IN ({codes_sql(codes)})"
    )
    sql = f"SELECT {cols} FROM read_parquet('{CANONICAL}') {where}"
    started = time.perf_counter()
    reader = con.execute(sql).fetch_record_batch()
    returned = 0
    for batch in reader:
        returned += batch.num_rows
    elapsed = time.perf_counter() - started
    scanned = explain_rows_scanned(con, sql)
    return {
        "codes": len(codes),
        "seconds": round(elapsed, 3),
        "peak_rss_bytes": rss_bytes(),
        "rows_scanned": scanned,
        "rows_returned": returned,
    }


def build_code_major(con: duckdb.DuckDBPyConnection) -> Path:
    out = TMP / "daily_by_code"
    out.mkdir(parents=True, exist_ok=True)
    cols = ", ".join(COLUMNS)
    for index in range(32):
        lo = f"{index * 1_000_000 // 32:06d}"
        hi = f"{(index + 1) * 1_000_000 // 32:06d}"
        target = out / f"bucket_{index:02d}.parquet"
        con.execute(
            f"COPY (SELECT {cols} FROM read_parquet('{CANONICAL}') "
            f"WHERE reconciliation_status='CONFIRMED' AND code >= '{lo}' AND code < '{hi}' "
            f"ORDER BY code, trade_date) TO '{target}' "
            f"(FORMAT PARQUET, ROW_GROUP_SIZE 65536)"
        )
    return out


def build_date_major(con: duckdb.DuckDBPyConnection) -> Path:
    out = TMP / "daily_by_date"
    out.mkdir(parents=True, exist_ok=True)
    target = out / "all.parquet"
    cols = ", ".join(COLUMNS)
    con.execute(
        f"COPY (SELECT {cols} FROM read_parquet('{CANONICAL}') "
        f"WHERE reconciliation_status='CONFIRMED' ORDER BY trade_date, code) "
        f"TO '{target}' (FORMAT PARQUET, ROW_GROUP_SIZE 65536)"
    )
    return target


def bench_duckdb_projection(
    con: duckdb.DuckDBPyConnection,
    *,
    path: str,
    codes: list[str] | None,
    latest_day: bool = False,
) -> dict:
    cols = ", ".join(COLUMNS)
    where = "WHERE reconciliation_status='CONFIRMED'"
    params = []
    if codes is not None:
        where += f" AND code IN ({codes_sql(codes)})"
    if latest_day:
        where += " AND trade_date = DATE '2026-07-31'"
    sql = f"SELECT {cols} FROM read_parquet('{path}') {where}"
    started = time.perf_counter()
    reader = con.execute(sql).fetch_record_batch()
    returned = 0
    for batch in reader:
        returned += batch.num_rows
    elapsed = time.perf_counter() - started
    scanned = explain_rows_scanned(con, sql)
    return {
        "latest_day": latest_day,
        "codes": len(codes) if codes is not None else None,
        "seconds": round(elapsed, 3),
        "peak_rss_bytes": rss_bytes(),
        "rows_scanned": scanned,
        "rows_returned": returned,
    }


def main() -> None:
    sizes = [int(v) for v in sys.argv[1:]] or [20, 200, 3191]
    results: dict = {"benchmarks": {}}
    TMP.mkdir(parents=True, exist_ok=True)
    results["benchmarks"]["current_pyarrow"] = {
        str(size): bench_current_pyarrow(sample_codes(size)) for size in sizes
    }
    if rss_bytes() > HARD_LIMIT:
        results["stop_reason"] = "RSS_BUDGET_ABORTED"
        _write(results)
        return
    con = new_duckdb()
    results["benchmarks"]["duckdb_current_parquet"] = {
        str(size): bench_duckdb_parquet(con, sample_codes(size)) for size in sizes
    }
    results["benchmarks"]["duckdb_current_parquet"]["latest_day"] = bench_duckdb_projection(
        con,
        path=str(CANONICAL),
        codes=None,
        latest_day=True,
    )
    if rss_bytes() > HARD_LIMIT:
        results["stop_reason"] = "RSS_BUDGET_ABORTED"
        _write(results)
        return
    code_major = build_code_major(con)
    results["benchmarks"]["duckdb_code_major"] = {
        str(size): bench_duckdb_projection(
            con,
            path=str(code_major),
            codes=sample_codes(size),
        )
        for size in sizes
    }
    date_major = build_date_major(con)
    results["benchmarks"]["duckdb_date_major"] = {
        "latest_day": bench_duckdb_projection(
            con,
            path=str(date_major),
            codes=None,
            latest_day=True,
        ),
        "20_code": bench_duckdb_projection(
            con,
            path=str(date_major),
            codes=sample_codes(20),
        ),
    }
    results["duckdb_native"] = {"completed": False, "reason": "OPTIONAL_NOT_RUN_MEMORY_GUARD"}
    results["chdb"] = "CHDB_NOT_AVAILABLE"
    results["final_peak_rss_bytes"] = rss_bytes()
    _write(results)


def _write(results: dict) -> None:
    out = TMP / "benchmark.json"
    out.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
