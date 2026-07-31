"""Parquet I/O: fixed schemas, Decimal-safe writes, atomic publish, hashing."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

PRICE = pa.decimal128(18, 4)
AMOUNT = pa.decimal128(38, 8)
RATE = pa.decimal128(28, 10)
INT = pa.int32()

META_FIELDS = (
    pa.field("provider", pa.string(), nullable=False),
    pa.field("provider_version", pa.string(), nullable=False),
    pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=False),
    pa.field("source_unit", pa.string(), nullable=False),
    pa.field("normalized_unit", pa.string(), nullable=False),
    pa.field("row_hash", pa.string(), nullable=False),
)


def raw_daily_schema() -> pa.Schema:
    return pa.schema(
        [
            *META_FIELDS,
            pa.field("code", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("open", PRICE, nullable=False),
            pa.field("high", PRICE, nullable=False),
            pa.field("low", PRICE, nullable=False),
            pa.field("close", PRICE, nullable=False),
            pa.field("preclose", PRICE, nullable=True),
            pa.field("volume", AMOUNT, nullable=False),
            pa.field("amount", AMOUNT, nullable=False),
            pa.field("turnover_rate", RATE, nullable=True),
            pa.field("pct_change", RATE, nullable=True),
            pa.field("trade_status", pa.bool_(), nullable=False),
            pa.field("is_st", pa.bool_(), nullable=True),
        ]
    )


def raw_adjustment_factor_schema() -> pa.Schema:
    return pa.schema(
        [
            *META_FIELDS,
            pa.field("code", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("adj_factor", RATE, nullable=False),
        ]
    )


def raw_daily_basic_schema() -> pa.Schema:
    return pa.schema(
        [
            *META_FIELDS,
            pa.field("code", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("turnover_rate", RATE, nullable=True),
            pa.field("volume_ratio", RATE, nullable=True),
            pa.field("pe", RATE, nullable=True),
            pa.field("pb", RATE, nullable=True),
            pa.field("total_mv", AMOUNT, nullable=True),
            pa.field("circ_mv", AMOUNT, nullable=True),
        ]
    )


def raw_suspension_schema() -> pa.Schema:
    return pa.schema(
        [
            *META_FIELDS,
            pa.field("code", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("suspend_type", pa.string(), nullable=True),
            pa.field("suspend_timing", pa.string(), nullable=True),
        ]
    )


def raw_price_limits_schema() -> pa.Schema:
    return pa.schema(
        [
            *META_FIELDS,
            pa.field("code", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("up_limit", PRICE, nullable=False),
            pa.field("down_limit", PRICE, nullable=False),
        ]
    )


def raw_limit_up_pool_schema() -> pa.Schema:
    return pa.schema(
        [
            *META_FIELDS,
            pa.field("code", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("name", pa.string(), nullable=False),
            pa.field("limit_price", PRICE, nullable=False),
            pa.field("first_seal_time", pa.string(), nullable=True),
            pa.field("last_seal_time", pa.string(), nullable=True),
            pa.field("open_count", INT, nullable=True),
            pa.field("consecutive_count", INT, nullable=True),
            pa.field("turnover_rate", RATE, nullable=True),
            pa.field("float_market_cap", AMOUNT, nullable=True),
            pa.field("total_market_cap", AMOUNT, nullable=True),
            pa.field("industry", pa.string(), nullable=True),
        ]
    )


def canonical_daily_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("code", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("open", PRICE, nullable=False),
            pa.field("high", PRICE, nullable=False),
            pa.field("low", PRICE, nullable=False),
            pa.field("close", PRICE, nullable=False),
            pa.field("preclose", PRICE, nullable=False),
            pa.field("volume", AMOUNT, nullable=False),
            pa.field("amount", AMOUNT, nullable=False),
            pa.field("turnover_rate", RATE, nullable=True),
            pa.field("pct_change", RATE, nullable=True),
            pa.field("trade_status", pa.bool_(), nullable=False),
            pa.field("is_st", pa.bool_(), nullable=True),
            pa.field("selected_provider", pa.string(), nullable=False),
            pa.field("reconciliation_status", pa.string(), nullable=False),
            pa.field("source_row_hash", pa.string(), nullable=False),
            pa.field("dataset_snapshot_id", pa.string(), nullable=False),
        ]
    )


def canonical_limit_up_pool_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("code", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("name", pa.string(), nullable=False),
            pa.field("limit_price", PRICE, nullable=False),
            pa.field("first_seal_time", pa.string(), nullable=True),
            pa.field("last_seal_time", pa.string(), nullable=True),
            pa.field("open_count", INT, nullable=True),
            pa.field("consecutive_count", INT, nullable=True),
            pa.field("turnover_rate", RATE, nullable=True),
            pa.field("float_market_cap", AMOUNT, nullable=True),
            pa.field("total_market_cap", AMOUNT, nullable=True),
            pa.field("industry", pa.string(), nullable=True),
            pa.field("selected_provider", pa.string(), nullable=False),
            pa.field("reconciliation_status", pa.string(), nullable=False),
            pa.field("source_row_hash", pa.string(), nullable=False),
            pa.field("dataset_snapshot_id", pa.string(), nullable=False),
        ]
    )


RAW_SCHEMAS = {
    ("TUSHARE", "daily_bars"): raw_daily_schema,
    ("TUSHARE", "adjustment_factor"): raw_adjustment_factor_schema,
    ("TUSHARE", "daily_basic"): raw_daily_basic_schema,
    ("TUSHARE", "suspension"): raw_suspension_schema,
    ("TUSHARE", "price_limits"): raw_price_limits_schema,
    ("AKSHARE", "daily_bars"): raw_daily_schema,
    ("AKSHARE", "limit_up_pool"): raw_limit_up_pool_schema,
    ("BAOSTOCK", "daily_bars"): raw_daily_schema,
}

RAW_DAILY_HASH_FIELDS = (
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
CANONICAL_DAILY_HASH_FIELDS = (
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
)


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return str(value)


def row_hash(fields: Sequence[str], row: Mapping[str, Any]) -> str:
    payload = "|".join(_format_value(row.get(field)) for field in fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_rows_atomic(
    rows: Sequence[Mapping[str, Any]],
    schema: pa.Schema,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    quantized_rows = [quantize_row(dict(row), schema) for row in rows]
    try:
        table = pa.Table.from_pylist(quantized_rows, schema=schema)
    except pa.ArrowInvalid as exc:
        raise pa.ArrowInvalid(
            f"parquet conversion failed for {path}: {exc}"
        ) from exc
    temporary = path.with_name(f".{path.name}.tmp-{uuid4().hex}")
    try:
        pq.write_table(table, temporary, compression="zstd")
        _fsync_file(temporary)
        os.replace(temporary, path)
        _fsync_file(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def quantize_row(row: Mapping[str, Any], schema: pa.Schema) -> dict[str, Any]:
    """Quantize Decimal values to the schema scale.

    Third-party providers deliver float artifacts (e.g. 10.120000000000001);
    quantization keeps values in Decimal form while removing non-significant
    provider noise before hashing and storage.
    """

    output = dict(row)
    for field in schema:
        if not isinstance(field.type, pa.Decimal128Type):
            continue
        value = output.get(field.name)
        if isinstance(value, Decimal):
            quantum = Decimal(1).scaleb(-field.type.scale)
            output[field.name] = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return output


def read_rows(path: str | Path) -> list[dict[str, Any]]:
    table = pq.read_table(str(path))
    return [dict(row) for row in table.to_pylist()]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid4().hex}")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        _fsync_file(temporary)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
