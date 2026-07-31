"""data-validate: integrity, traceability and manifest verification."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import ValidationIssue, ValidationResult
from limit_pullback.warehouse.parquet import row_hash, sha256_file
from limit_pullback.warehouse.snapshot import read_snapshot_daily, read_snapshot_pool

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


def data_validate(
    layout: WarehouseLayout,
    *,
    snapshot_id: str | None = None,
    today: date | None = None,
) -> ValidationResult:
    today_value = today or date.today()
    issues: list[ValidationIssue] = []
    if not layout.duckdb_path.exists():
        return ValidationResult(
            valid=False,
            snapshot_id=snapshot_id,
            issues=(_issue("SNAPSHOT", "no snapshot found"),),
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
            )

        manifest_path = Path(snapshot.manifest_path or "")
        if not manifest_path.exists():
            issues.append(_issue("MANIFEST", f"manifest missing: {manifest_path}"))
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("snapshot_id") != snapshot.snapshot_id:
                    issues.append(_issue("MANIFEST", "manifest snapshot_id mismatch"))
                if str(manifest.get("as_of")) != snapshot.as_of.isoformat():
                    issues.append(_issue("MANIFEST", "manifest as_of mismatch"))
            except json.JSONDecodeError as exc:
                issues.append(_issue("MANIFEST", f"manifest unreadable: {exc}"))

        for relative_path, expected in snapshot.source_file_hashes.items():
            path = layout.root / relative_path
            if not path.exists():
                issues.append(_issue("SOURCE_FILE", f"missing raw file: {relative_path}"))
                continue
            if sha256_file(path) != expected:
                issues.append(_issue("SOURCE_FILE_HASH", f"hash mismatch: {relative_path}"))

        for relative_path, expected in snapshot.canonical_file_hashes.items():
            path = layout.root / relative_path
            if not path.exists():
                issues.append(_issue("CANONICAL_FILE", f"missing canonical file: {relative_path}"))
                continue
            if sha256_file(path) != expected:
                issues.append(_issue("CANONICAL_FILE_HASH", f"hash mismatch: {relative_path}"))

        daily_rows = read_snapshot_daily(layout, snapshot)
        pool_rows = read_snapshot_pool(layout, snapshot)

        raw_hashes_by_provider: dict[str, set[str]] = {
            provider: set()
            for provider in ("TUSHARE", "AKSHARE", "BAOSTOCK")
        }
        for relative_path in snapshot.source_file_hashes:
            path = layout.root / relative_path
            if not path.exists():
                continue
            if "/daily_bars/" not in relative_path:
                continue
            provider = relative_path.split("/raw/")[1].split("/")[0].upper()
            if provider not in raw_hashes_by_provider:
                continue
            for row in _read_parquet_rows(path):
                raw_hashes_by_provider[provider].add(str(row["row_hash"]))

        _check_unique(
            daily_rows,
            fields=("code", "trade_date"),
            check="CANONICAL_UNIQUE",
            issues=issues,
        )
        _check_unique(
            pool_rows,
            fields=("code", "trade_date"),
            check="POOL_UNIQUE",
            issues=issues,
        )

        for row in daily_rows:
            _check_daily_row(
                row,
                snapshot_as_of=snapshot.as_of,
                today=today_value,
                issues=issues,
            )
            provider = str(row["selected_provider"])
            if row["source_row_hash"] not in raw_hashes_by_provider.get(provider, set()):
                issues.append(
                    _issue(
                        "TRACEABILITY",
                        f"{row['code']} {row['trade_date']} source row not found in {provider} raw",
                    )
                )
            if row["reconciliation_status"] not in {
                "CONFIRMED",
                "PROVISIONAL",
                "INCOMPLETE",
            }:
                issues.append(
                    _issue(
                        "RECONCILIATION_STATUS",
                        f"{row['code']} {row['trade_date']} invalid status",
                    )
                )

        by_date: dict[str, list[dict[str, Any]]] = {}
        for row in daily_rows:
            by_date.setdefault(str(row["code"]), []).append(row)
        for code, rows in by_date.items():
            rows.sort(key=lambda item: item["trade_date"])
            previous: dict[str, Any] | None = None
            for row in rows:
                if previous is not None:
                    difference = abs(Decimal(row["preclose"]) - Decimal(previous["close"]))
                    scale = max(abs(Decimal(row["preclose"])), abs(Decimal(previous["close"])))
                    if difference > max(PRICE_TOLERANCE, PRICE_RELATIVE * scale):
                        issues.append(
                            _issue(
                                "PRECLOSE_CONTINUITY",
                                f"{code} {row['trade_date']} preclose vs prior close mismatch",
                            )
                        )
                previous = row

        for row in pool_rows:
            if row["limit_price"] <= 0:
                issues.append(
                    _issue("POOL_LIMIT_PRICE", f"{row['code']} {row['trade_date']} non-positive")
                )
            if row["trade_date"] > snapshot.as_of:
                issues.append(
                    _issue("DATE_RANGE", f"{row['code']} {row['trade_date']} beyond snapshot")
                )
            computed = row_hash(POOL_HASH_FIELDS, row)
            if computed != row["source_row_hash"]:
                issues.append(
                    _issue("ROW_HASH", f"{row['code']} {row['trade_date']} pool hash mismatch")
                )

        from pyarrow.parquet import read_schema

        for relative_path in snapshot.canonical_file_hashes:
            schema = read_schema(str(layout.root / relative_path))
            if _schema_has_float(schema):
                issues.append(_issue("DECIMAL_PRECISION", f"float column in {relative_path}"))

    return ValidationResult(
        valid=not issues,
        snapshot_id=snapshot.snapshot_id,
        issues=tuple(issues),
    )


def _read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    from limit_pullback.warehouse.parquet import read_rows

    return read_rows(path)
