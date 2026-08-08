"""VFLASH_ASL_VALIDATOR_RESOURCE_FIX_V01 — bounded ASL authoritative
validation.

Proves the streaming ASL data_validate() path preserves every frozen ASL
check while never materializing the full canonical daily dataset and never
touching the legacy raw-provider readers.

Reuses the synthetic Phase-1C-1 lake fixture from test_asl_snapshot.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import row_hash, sha256_file
from limit_pullback.warehouse.snapshot import create_snapshot
from limit_pullback.warehouse.validate import (
    DAILY_HASH_FIELDS,
    data_validate,
    is_asl_authoritative,
)

from tests.test_asl_snapshot import (
    AS_OF,
    CODES,
    START,
    _build,
    _build_lake,
    _tamper_daily_file,
)

# Fixed reference day so FUTURE_RECORD never fires spuriously regardless of
# the wall-clock date the suite runs on.
_TODAY = date(2026, 6, 20)

_DAILY_CONTENT_CHECKS = {
    "CANONICAL_UNIQUE",
    "PRECLOSE_CONTINUITY",
    "ROW_HASH",
    "OHLC_POSITIVE",
    "OHLC_RELATION",
    "NON_NEGATIVE",
    "DATE_RANGE",
    "FUTURE_RECORD",
    "ASL_PROVIDER",
    "ASL_TURNOVER",
    "RECONCILIATION_STATUS",
}


def _issue_codes(
    layout: WarehouseLayout, snapshot_id: str, today: date = _TODAY
) -> tuple[set[str], bool]:
    result = data_validate(layout, snapshot_id=snapshot_id, today=today)
    return {issue.check for issue in result.issues}, result.valid


def _build_without_contract_provenance(tmp_path, lake):
    """ASL-declared snapshot whose provider_versions omits the frozen
    ASL_CONTRACT_VERSION key (ASL_PROVENANCE fail-closed gate)."""

    from limit_pullback.warehouse.asl_adapter import load_asl_daily_slice
    from limit_pullback.warehouse.asl_snapshot import (
        ASL_RECONCILIATION_POLICY_VERSION,
        asl_rows_to_canonical_rows,
    )

    layout = WarehouseLayout(tmp_path / "data")
    layout.ensure_dirs()
    slice_ = load_asl_daily_slice(lake, as_of=AS_OF, start=START, codes=CODES)
    rows = asl_rows_to_canonical_rows(slice_.rows)
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        snapshot = create_snapshot(
            layout=layout,
            metadata=metadata,
            as_of=AS_OF,
            provider_versions={"ASL": "ba5681a"},
            daily_rows=rows,
            pool_rows=[],
            source_file_hashes={},
            reconciliation_policy_version=ASL_RECONCILIATION_POLICY_VERSION,
            status="CURRENT",
        )
    return layout, snapshot


def _rewrite_daily_rows(layout, snapshot, rows) -> None:
    """Rewrite the canonical daily parquet with recomputed row hashes."""

    import pyarrow as pa
    import pyarrow.parquet as pq

    daily_rel = next(
        key
        for key in snapshot.canonical_file_hashes
        if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
    )
    path = layout.root / daily_rel
    for row in rows:
        row["source_row_hash"] = row_hash(DAILY_HASH_FIELDS, row)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_asl_streaming_clean_snapshot(tmp_path):
    """A. clean ASL snapshot: valid=True, issues=[]."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    result = data_validate(layout, snapshot_id=snapshot.snapshot_id, today=_TODAY)
    assert result.valid is True
    assert result.issues == ()
    assert is_asl_authoritative(snapshot) is True


def test_asl_streaming_provider_mismatch(tmp_path):
    """B. provider mismatch -> ASL_PROVIDER."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    _tamper_daily_file(
        layout, snapshot, lambda row: row.update(selected_provider="TUSHARE")
    )
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is False
    assert "ASL_PROVIDER" in codes


def test_asl_streaming_turnover_non_null(tmp_path):
    """C. non-null turnover -> ASL_TURNOVER."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    _tamper_daily_file(
        layout, snapshot, lambda row: row.update(turnover_rate="1.23")
    )
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is False
    assert "ASL_TURNOVER" in codes


def test_asl_streaming_row_hash_tamper(tmp_path):
    """D. source_row_hash tamper (hash NOT recomputed) -> ROW_HASH."""

    import pyarrow as pa
    import pyarrow.parquet as pq

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    daily_rel = next(
        key
        for key in snapshot.canonical_file_hashes
        if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
    )
    path = layout.root / daily_rel
    rows = pq.ParquetFile(path).read().to_pylist()
    for row in rows:
        row["close"] = Decimal(row["close"]) + Decimal("0.01")
    # NOTE: hashes NOT recomputed on purpose.
    pq.write_table(pa.Table.from_pylist(rows), path)
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is False
    assert "ROW_HASH" in codes


def test_asl_streaming_preclose_tamper(tmp_path):
    """E. second-row preclose tamper with recomputed row hash ->
    PRECLOSE_CONTINUITY and NOT ROW_HASH."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)

    def mutate(row):
        if row["code"] == "000001" and row["trade_date"] == date(2026, 6, 15):
            row["preclose"] = Decimal(row["preclose"]) + Decimal("1.00")

    _tamper_daily_file(layout, snapshot, mutate)
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is False
    assert "PRECLOSE_CONTINUITY" in codes
    assert "ROW_HASH" not in codes


def test_asl_streaming_duplicate_pk(tmp_path):
    """F. duplicate canonical (code, trade_date) -> CANONICAL_UNIQUE."""

    import pyarrow.parquet as pq

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    daily_rel = next(
        key
        for key in snapshot.canonical_file_hashes
        if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
    )
    path = layout.root / daily_rel
    rows = pq.ParquetFile(path).read().to_pylist()
    rows.append(dict(rows[0]))  # duplicate 000001 / 2026-06-11
    _rewrite_daily_rows(layout, snapshot, rows)
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is False
    assert "CANONICAL_UNIQUE" in codes


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda row: row.update(close=Decimal("0")), "OHLC_POSITIVE"),
        (lambda row: row.update(high=Decimal("0.01")), "OHLC_RELATION"),
        (lambda row: row.update(volume=Decimal("-1")), "NON_NEGATIVE"),
        (lambda row: row.update(trade_date=date(2026, 6, 16)), "DATE_RANGE"),
    ],
)
def test_asl_streaming_generic_checks_active(tmp_path, mutate, expected):
    """G. OHLC / date / non-negative generic checks remain active."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    _tamper_daily_file(layout, snapshot, mutate)
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is False
    assert expected in codes


def test_asl_streaming_missing_contract_provenance(tmp_path):
    """H. missing ASL contract provenance -> ASL_PROVENANCE."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build_without_contract_provenance(tmp_path, lake)
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is False
    assert "ASL_PROVENANCE" in codes


def test_asl_streaming_never_calls_read_snapshot_daily(tmp_path, monkeypatch):
    """I. ASL validation must NOT call read_snapshot_daily() (full row list).
    """

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("read_snapshot_daily must not be called for ASL")

    monkeypatch.setattr(
        "limit_pullback.warehouse.validate.read_snapshot_daily", _forbidden
    )
    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    result = data_validate(layout, snapshot_id=snapshot.snapshot_id, today=_TODAY)
    assert result.valid is True
    assert result.issues == ()


def test_asl_streaming_never_reads_legacy_raw(tmp_path, monkeypatch):
    """J. ASL validation must NOT read legacy raw provider rows."""

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("legacy raw-provider read must not happen")

    monkeypatch.setattr(
        "limit_pullback.warehouse.validate._read_parquet_rows", _forbidden
    )
    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    result = data_validate(layout, snapshot_id=snapshot.snapshot_id, today=_TODAY)
    assert result.valid is True
    assert result.issues == ()


def test_asl_streaming_matches_legacy_helpers(tmp_path):
    """Streaming ASL daily-content issues equal the legacy full-row helper
    issues (check names AND details) on a tampered fixture."""

    from limit_pullback.warehouse.snapshot import read_snapshot_daily
    from limit_pullback.warehouse.validate import (
        _canonical_previous_close_index,
        _check_daily_row,
        _check_unique,
        _issue,
        preclose_continuity_issues,
    )

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)

    def mutate(row):
        if row["code"] == "000001" and row["trade_date"] == date(2026, 6, 15):
            row["preclose"] = Decimal(row["preclose"]) + Decimal("1.00")

    _tamper_daily_file(layout, snapshot, mutate)

    legacy_issues = []
    daily_rows = read_snapshot_daily(layout, snapshot)
    _check_unique(
        daily_rows,
        fields=("code", "trade_date"),
        check="CANONICAL_UNIQUE",
        issues=legacy_issues,
    )
    for row in daily_rows:
        _check_daily_row(
            row,
            snapshot_as_of=snapshot.as_of,
            today=_TODAY,
            issues=legacy_issues,
        )
        if str(row["selected_provider"]) != "ASL":
            legacy_issues.append(
                _issue(
                    "ASL_PROVIDER",
                    f"{row['code']} {row['trade_date']} "
                    f"selected_provider={row['selected_provider']!r} != ASL",
                )
            )
        if row.get("turnover_rate") is not None:
            legacy_issues.append(
                _issue(
                    "ASL_TURNOVER",
                    f"{row['code']} {row['trade_date']} "
                    "turnover_rate must remain None",
                )
            )
        if row["reconciliation_status"] not in {
            "CONFIRMED",
            "PROVISIONAL",
            "INCOMPLETE",
        }:
            legacy_issues.append(
                _issue(
                    "RECONCILIATION_STATUS",
                    f"{row['code']} {row['trade_date']} invalid status",
                )
            )
    legacy_issues.extend(
        preclose_continuity_issues(
            daily_rows,
            previous_close_index=_canonical_previous_close_index(daily_rows),
            provider_label="ASL canonical",
        )
    )

    new_result = data_validate(
        layout, snapshot_id=snapshot.snapshot_id, today=_TODAY
    )
    new_daily = [
        (issue.check, issue.detail)
        for issue in new_result.issues
        if issue.check in _DAILY_CONTENT_CHECKS
    ]
    legacy_daily = [
        (issue.check, issue.detail)
        for issue in legacy_issues
        if issue.check in _DAILY_CONTENT_CHECKS
    ]
    assert new_daily == legacy_daily
    assert new_daily == [
        (
            "PRECLOSE_CONTINUITY",
            "000001 2026-06-15 preclose vs ASL canonical prior close mismatch",
        )
    ]


def test_asl_multi_row_group_validates_identically(tmp_path):
    """L. multi-row-group canonical parquet validates identically (issue
    contract unchanged when physical row grouping differs)."""

    import pyarrow as pa
    import pyarrow.parquet as pq

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    daily_rel = next(
        key
        for key in snapshot.canonical_file_hashes
        if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
    )
    path = layout.root / daily_rel
    rows = pq.ParquetFile(path).read().to_pylist()

    def _rewrite_grouped(group_size):
        for row in rows:
            row["source_row_hash"] = row_hash(DAILY_HASH_FIELDS, row)
        pq.write_table(
            pa.Table.from_pylist(rows), path, row_group_size=group_size
        )
        new_hashes = {
            key: (sha256_file(path) if key == daily_rel else value)
            for key, value in snapshot.canonical_file_hashes.items()
        }
        with WarehouseMetadata(layout.duckdb_path) as metadata:
            metadata.insert_snapshot(
                snapshot.model_copy(update={"canonical_file_hashes": new_hashes})
            )

    _rewrite_grouped(3)
    result_grouped = data_validate(
        layout, snapshot_id=snapshot.snapshot_id, today=_TODAY
    )
    assert result_grouped.valid is True
    assert result_grouped.issues == ()

    _rewrite_grouped(None)
    result_ungrouped = data_validate(
        layout, snapshot_id=snapshot.snapshot_id, today=_TODAY
    )
    assert result_ungrouped.valid is True
    assert result_ungrouped.issues == ()
    assert (
        result_grouped.issues
        == result_ungrouped.issues
        == ()
    )
