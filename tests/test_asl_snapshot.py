"""Phase 1C-1 tests: authoritative ASL -> canonical candidate snapshot.

Covers the Phase 1C-1 risk set: adapter->canonical mapping contract, writer
round-trip through the EXISTING create_snapshot, formal SCREEN_READY guard,
empty pool round-trip, fail-closed on missing/malformed ASL, and a regression
guard proving the build path never calls legacy/network providers.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from limit_pullback.warehouse.asl_adapter import AslAdapterError
from limit_pullback.warehouse.asl_snapshot import (
    ASL_RECONCILIATION_POLICY_VERSION,
    asl_rows_to_canonical_rows,
    build_asl_candidate_snapshot,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import canonical_daily_schema
from limit_pullback.warehouse.snapshot import (
    read_snapshot_daily,
    read_snapshot_daily_table,
    read_snapshot_pool,
)
from limit_pullback.warehouse.validate import (
    DAILY_HASH_FIELDS,
    data_validate,
    is_asl_authoritative,
)
from limit_pullback.warehouse.parquet import row_hash

AS_OF = date(2026, 6, 15)
START = date(2026, 6, 11)
CODES = ["000001", "000010", "000524", "605198"]

_WEEKEND = (date(2026, 6, 13), date(2026, 6, 14))
_TRADING_DAYS = [date(2026, 6, 11), date(2026, 6, 12), date(2026, 6, 15)]


def _write(path: Path, rows: list[dict]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _build_lake(
    root: Path,
    *,
    drop_datasets: tuple[str, ...] = (),
) -> None:
    """Minimal synthetic ASL lake (mirrors the Phase-1A fixture shape)."""

    if "instruments" not in drop_datasets:
        _write(
            root / "curated" / "instruments" / "part-merged.parquet",
            [
                {"symbol": "000001.SZ", "list_date": None, "delist_date": None},
                {"symbol": "000010.SZ", "list_date": None, "delist_date": None},
                {"symbol": "000524.SZ", "list_date": None, "delist_date": None},
                {"symbol": "300750.SZ", "list_date": None, "delist_date": None},
                {"symbol": "605198.SH", "list_date": None, "delist_date": None},
                # AS_OF scope edge instruments (AS_OF = 2026-06-15):
                {"symbol": "600000.SH", "list_date": date(1995, 1, 1), "delist_date": date(2026, 6, 1)},   # delisted before AS_OF
                {"symbol": "600001.SH", "list_date": date(2026, 6, 20), "delist_date": None},               # listed after AS_OF
                {"symbol": "600002.SH", "list_date": date(2000, 1, 1), "delist_date": None},                # no AS_OF bar
                {"symbol": "600003.SH", "list_date": date(2000, 1, 1), "delist_date": None},                # zero-volume AS_OF bar
            ],
        )
    if "trading_calendar" not in drop_datasets:
        _write(
            root
            / "curated"
            / "trading_calendar"
            / "trade_date=2026"
            / "part-merged.parquet",
            [
                {"trade_date": day, "is_trading": day in _TRADING_DAYS}
                for day in [
                    date(2026, 6, 11),
                    date(2026, 6, 12),
                    *_WEEKEND,
                    date(2026, 6, 15),
                    date(2026, 6, 16),
                    date(2026, 6, 17),
                ]
            ],
        )
    if "daily_bars" not in drop_datasets:
        bars = {
            "000001.SZ": [
                {"trade_date": date(2026, 6, 11), "open": 11.30, "high": 11.40, "low": 11.20, "close": 11.30, "volume": 100000, "amount": 1129999.5},
                {"trade_date": date(2026, 6, 12), "open": 11.00, "high": 11.25, "low": 10.88, "close": 11.24, "volume": 200000, "amount": 2222222.25},
                {"trade_date": date(2026, 6, 15), "open": 11.21, "high": 11.21, "low": 10.98, "close": 11.06, "volume": 150000, "amount": 1650000.0},
            ],
            "000010.SZ": [
                {"trade_date": date(2026, 6, 11), "open": 2.00, "high": 2.01, "low": 1.99, "close": 2.00, "volume": 50000, "amount": 100000.0},
                {"trade_date": date(2026, 6, 12), "open": 2.00, "high": 2.06, "low": 2.00, "close": 2.05, "volume": 60000, "amount": 122000.0},
                {"trade_date": date(2026, 6, 15), "open": 2.05, "high": 2.10, "low": 2.04, "close": 2.10, "volume": 70000, "amount": 145000.0},
            ],
            "000524.SZ": [
                {"trade_date": date(2026, 6, 11), "open": 9.00, "high": 9.10, "low": 8.95, "close": 9.00, "volume": 80000, "amount": 720000.0},
                {"trade_date": date(2026, 6, 12), "open": 9.00, "high": 9.05, "low": 8.95, "close": 9.00, "volume": 0, "amount": 0.0},
                {"trade_date": date(2026, 6, 15), "open": 9.10, "high": 9.25, "low": 9.05, "close": 9.20, "volume": 90000, "amount": 825000.0},
            ],
            "605198.SH": [
                {"trade_date": date(2026, 6, 11), "open": 49.9, "high": 50.1, "low": 49.8, "close": 50.0, "volume": 20000, "amount": 1000000.0},
                {"trade_date": date(2026, 6, 12), "open": 50.0, "high": 50.5, "low": 49.8, "close": 50.2, "volume": 30000, "amount": 1500000.0},
                {"trade_date": date(2026, 6, 15), "open": 50.2, "high": 50.6, "low": 50.0, "close": 50.4, "volume": 35000, "amount": 1760000.0},
            ],
            "300750.SZ": [
                {"trade_date": date(2026, 6, 11), "open": 200.0, "high": 205.0, "low": 199.0, "close": 204.0, "volume": 1000000, "amount": 2.03e8},
                {"trade_date": date(2026, 6, 12), "open": 203.0, "high": 206.0, "low": 201.0, "close": 205.0, "volume": 1100000, "amount": 2.25e8},
                {"trade_date": date(2026, 6, 15), "open": 205.0, "high": 207.0, "low": 203.0, "close": 204.5, "volume": 900000, "amount": 1.84e8},
            ],
            "600002.SH": [
                {"trade_date": date(2026, 6, 11), "open": 5.0, "high": 5.1, "low": 4.9, "close": 5.0, "volume": 10000, "amount": 50000.0},
                {"trade_date": date(2026, 6, 12), "open": 5.0, "high": 5.0, "low": 4.8, "close": 4.9, "volume": 10000, "amount": 49000.0},
            ],
            "600003.SH": [
                {"trade_date": date(2026, 6, 11), "open": 6.0, "high": 6.1, "low": 5.9, "close": 6.0, "volume": 10000, "amount": 60000.0},
                {"trade_date": date(2026, 6, 12), "open": 6.0, "high": 6.2, "low": 5.9, "close": 6.1, "volume": 10000, "amount": 61000.0},
                {"trade_date": date(2026, 6, 15), "open": 6.1, "high": 6.1, "low": 6.0, "close": 6.0, "volume": 0, "amount": 0.0},
            ],
        }
        by_date: dict[date, list[dict]] = {}
        for symbol, rows in bars.items():
            for row in rows:
                by_date.setdefault(row["trade_date"], []).append(
                    {
                        "symbol": symbol,
                        "trade_date": row["trade_date"],
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": row["volume"],
                        "amount": row["amount"],
                        "source": "tdx_protocol",
                        "data_version": "v2",
                        "fetched_at": "2026-08-07T00:00:00Z",
                    }
                )
        for trade_date, rows in sorted(by_date.items()):
            _write(
                root
                / "curated"
                / "daily_bars"
                / f"trade_date={trade_date.isoformat()}"
                / "part-merged.parquet",
                rows,
            )
    if "trading_status" not in drop_datasets:
        _write(
            root / "curated" / "trading_status" / "trade_date=2026-06" / "part-merged.parquet",
            [
                {"symbol": "000010.SZ", "trade_date": date(2026, 6, 12), "is_trading": True, "status": "st", "source": "baostock", "data_version": "v1", "fetched_at": "2026-08-07T00:00:00Z"},
                {"symbol": "000010.SZ", "trade_date": date(2026, 6, 15), "is_trading": True, "status": "*st", "source": "baostock", "data_version": "v1", "fetched_at": "2026-08-07T00:00:00Z"},
                {"symbol": "000524.SZ", "trade_date": date(2026, 6, 12), "is_trading": False, "status": "suspended", "source": "derived_bar_gap", "data_version": "v1", "fetched_at": "2026-08-07T00:00:00Z"},
            ],
        )


def _layout(tmp_path: Path) -> WarehouseLayout:
    layout = WarehouseLayout(tmp_path / "data")
    layout.ensure_dirs()
    return layout


def _build(tmp_path: Path, lake: Path, codes=CODES) -> tuple[WarehouseLayout, object]:
    layout = _layout(tmp_path)
    snapshot = build_asl_candidate_snapshot(
        layout=layout,
        asl_root=lake,
        as_of=AS_OF,
        codes=codes,
        start=START,
    )
    return layout, snapshot


def test_adapter_rows_map_to_canonical_daily_schema(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    layout = _layout(tmp_path)
    from limit_pullback.warehouse.asl_adapter import load_asl_daily_slice

    slice_ = load_asl_daily_slice(lake, as_of=AS_OF, start=START, codes=CODES)
    rows = asl_rows_to_canonical_rows(slice_.rows)
    assert rows
    schema_names = set(canonical_daily_schema().names)
    for row in rows:
        assert set(row) <= schema_names | {"dataset_snapshot_id"}
        assert row["code"] in CODES
        assert isinstance(row["trade_date"], date)
        assert row["preclose"] is not None
        # source_row_hash is the existing deterministic canonical row hash.
        assert row["source_row_hash"] == row_hash(DAILY_HASH_FIELDS, row)


def test_turnover_rate_none_and_provider_asl(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    from limit_pullback.warehouse.asl_adapter import load_asl_daily_slice

    slice_ = load_asl_daily_slice(lake, as_of=AS_OF, start=START, codes=CODES)
    rows = asl_rows_to_canonical_rows(slice_.rows)
    assert rows
    assert all(row["turnover_rate"] is None for row in rows)
    assert all(row["selected_provider"] == "ASL" for row in rows)
    # CONFIRMED here means "accepted canonical fact from authoritative ASL".
    assert all(row["reconciliation_status"] == "CONFIRMED" for row in rows)


def test_snapshot_written_and_readable_by_existing_reader(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(snapshot.snapshot_id)
        rows = read_snapshot_daily(layout, stored)
        table = read_snapshot_daily_table(layout, stored)
    # 6/11 is MISSING_PRECLOSE (no predecessor partition in the synthetic
    # lake), so the canonical snapshot holds 4 codes x 2 days = 8 VALID rows.
    assert len(rows) == 8
    assert table is not None and table.num_rows == 8
    assert {row["selected_provider"] for row in rows} == {"ASL"}
    # Existing canonical reader (forensic path) accepts the candidate.
    from limit_pullback.screen.canonical import load_canonical_market

    market = load_canonical_market(
        layout,
        snapshot_id=snapshot.snapshot_id,
        codes=CODES,
        as_of=AS_OF,
        allow_unusable_snapshot_for_forensics=True,
    )
    assert market is not None
    assert len(market.bars_by_code.get("000001", ())) == 2


def test_snapshot_files_manifest_and_hashes(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    daily_rel = next(
        key for key in snapshot.canonical_file_hashes
        if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
    )
    pool_rel = next(
        key for key in snapshot.canonical_file_hashes
        if key.endswith("/limit_up_pool/" + snapshot.snapshot_id + ".parquet")
    )
    assert (layout.root / daily_rel).exists()
    assert (layout.root / pool_rel).exists()
    assert len(snapshot.canonical_file_hashes) == 2
    manifest = json.loads(Path(snapshot.manifest_path).read_text())
    assert manifest["snapshot_id"] == snapshot.snapshot_id
    assert manifest["as_of"] == AS_OF.isoformat()
    assert manifest["status"] == "CURRENT"
    assert manifest["canonical_file_hashes"] == snapshot.canonical_file_hashes
    assert manifest["provider_versions"]["ASL"] == "ba5681a"


def test_candidate_snapshot_formal_reader_fails_closed(tmp_path):
    """A CURRENT candidate is NOT formally consumable: the existing
    SCREEN_READY guard blocks it, and only the explicit forensic path reads
    it (never weakened)."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    from limit_pullback.screen.canonical import load_canonical_market
    from limit_pullback.warehouse.snapshot import SnapshotUsabilityError

    with pytest.raises(SnapshotUsabilityError) as excinfo:
        load_canonical_market(layout, snapshot_id=snapshot.snapshot_id, as_of=AS_OF)
    assert excinfo.value.code == "SNAPSHOT_NOT_SCREEN_READY"
    assert snapshot.status == "CURRENT"
    # Forensic/test path still works without weakening the formal guard.
    market = load_canonical_market(
        layout,
        snapshot_id=snapshot.snapshot_id,
        as_of=AS_OF,
        allow_unusable_snapshot_for_forensics=True,
    )
    assert market is not None


def test_empty_limit_up_pool_round_trip(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(snapshot.snapshot_id)
        pool = read_snapshot_pool(layout, stored)
    assert pool == []
    # The typed empty pool file exists with the canonical pool schema.
    from limit_pullback.warehouse.parquet import canonical_limit_up_pool_schema

    pool_rel = next(
        key for key in snapshot.canonical_file_hashes
        if key.endswith("/limit_up_pool/" + snapshot.snapshot_id + ".parquet")
    )
    import pyarrow.parquet as pq

    table = pq.read_table(layout.root / pool_rel)
    assert set(table.column_names) <= set(canonical_limit_up_pool_schema().names)


@pytest.mark.parametrize("drop", ["instruments", "trading_calendar", "daily_bars", "trading_status"])
def test_missing_required_asl_dataset_fails_closed(tmp_path, drop):
    lake = tmp_path / "lake"
    _build_lake(lake, drop_datasets=(drop,))
    layout = _layout(tmp_path)
    with pytest.raises(AslAdapterError):
        build_asl_candidate_snapshot(
            layout=layout,
            asl_root=lake,
            as_of=AS_OF,
            codes=CODES,
            start=START,
        )


def test_malformed_asl_value_fails_closed(tmp_path):
    lake = tmp_path / "lake"
    _build_lake(lake)
    # Corrupt one bar close into a non-numeric value (string column), so the
    # adapter's UNPARSABLE_VALUE fail-closed path fires.
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = (
        lake / "curated" / "daily_bars" / "trade_date=2026-06-11" / "part-merged.parquet"
    )
    # Single-file read: pq.read_table() would treat the hive-partitioned
    # parent directory as a dataset and merge a string partition column.
    table = pq.ParquetFile(path).read()
    close_str = pa.array(
        [
            "not-a-number" if row["symbol"] == "000001.SZ" else str(row["close"])
            for row in table.to_pylist()
        ],
        type=pa.string(),
    )
    corrupted = table.set_column(
        table.schema.get_field_index("close"),
        pa.field("close", pa.string()),
        close_str,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(corrupted, path)
    layout = _layout(tmp_path)
    with pytest.raises(AslAdapterError):
        build_asl_candidate_snapshot(
            layout=layout,
            asl_root=lake,
            as_of=AS_OF,
            codes=CODES,
            start=START,
        )


def test_build_path_never_calls_legacy_providers(tmp_path, monkeypatch):
    """Regression guard: the ASL snapshot build must not enter any
    legacy/network provider path (pipeline bootstrap/update or provider
    fetch)."""

    lake = tmp_path / "lake"
    _build_lake(lake)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("legacy provider path must not be called")

    monkeypatch.setattr(
        "limit_pullback.warehouse.pipeline.bootstrap", _forbidden
    )
    monkeypatch.setattr("limit_pullback.warehouse.pipeline.update", _forbidden)
    monkeypatch.setattr(
        "limit_pullback.warehouse.fetch.fetch_rows", _forbidden
    )
    monkeypatch.setattr(
        "limit_pullback.warehouse.fetch.fetch_with_retry", _forbidden
    )
    layout, snapshot = _build(tmp_path, lake)
    assert snapshot.status == "CURRENT"
    assert snapshot.reconciliation_policy_version == (
        ASL_RECONCILIATION_POLICY_VERSION
    )


def _resolved_scope(lake: Path) -> set[str]:
    from limit_pullback.warehouse.asl_snapshot import resolve_asl_asof_scope

    return set(resolve_asl_asof_scope(lake, AS_OF))


def test_codes_none_resolves_asof_scope(tmp_path):
    """codes=None now means AS_OF pre-ST market scope (evaluation date first):
    active main-board codes with a valid positive-volume AS_OF bar only."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    scope = _resolved_scope(lake)
    # Active main-board + positive-volume AS_OF bar -> included (A).
    assert scope == {"000001", "000010", "000524", "605198"}
    layout = _layout(tmp_path)
    snapshot = build_asl_candidate_snapshot(
        layout=layout, asl_root=lake, as_of=AS_OF, codes=None, start=START,
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(snapshot.snapshot_id)
        rows = read_snapshot_daily(layout, stored)
    assert {row["code"] for row in rows} == scope
    assert len(rows) == 8  # 4 codes x 2 VALID days (6/11 was MISSING_PRECLOSE)


def test_asof_scope_excludes_by_listing_and_bar_rules(tmp_path):
    """B-F: delisted / not-yet-listed / no-AS_OF-bar / zero-volume / ChiNext
    instruments are all OUTSIDE the AS_OF scope (no hardcoded exclusions)."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    scope = _resolved_scope(lake)
    assert "600000" not in scope  # B: delisted before AS_OF
    assert "600001" not in scope  # C: listed after AS_OF
    assert "600002" not in scope  # D: no AS_OF bar
    assert "600003" not in scope  # E: zero-volume AS_OF bar
    assert "300750" not in scope  # F: ChiNext / non-main-board


def test_asof_scope_keeps_st_history_intact(tmp_path):
    """H: ST history/status does NOT remove a stock from the AS_OF snapshot
    scope at this stage — ST remains a later eligibility/readiness layer and
    historical ST rows stay in the snapshot."""

    lake = tmp_path / "lake"
    _build_lake(lake)  # 000010 has trusted baostock st/*st rows
    scope = _resolved_scope(lake)
    assert "000010" in scope
    layout = _layout(tmp_path)
    snapshot = build_asl_candidate_snapshot(
        layout=layout, asl_root=lake, as_of=AS_OF, codes=None, start=START,
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(snapshot.snapshot_id)
        rows = read_snapshot_daily(layout, stored)
    st_rows = [row for row in rows if row["code"] == "000010" and row["is_st"] is True]
    assert len(st_rows) == 2  # 6/12 st + 6/15 *st rows remain in the snapshot


def test_explicit_codes_still_work(tmp_path):
    """Explicit codes keep the exact prior semantics (subset, no universe
    derivation)."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout = _layout(tmp_path)
    snapshot = build_asl_candidate_snapshot(
        layout=layout, asl_root=lake, as_of=AS_OF, codes=["000001"], start=START,
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(snapshot.snapshot_id)
        rows = read_snapshot_daily(layout, stored)
    assert {row["code"] for row in rows} == {"000001"}
    assert len(rows) == 2


def test_cli_without_codes_builds_nonempty_snapshot(tmp_path, capsys):
    """The CLI path without --codes must NOT produce a zero-row snapshot:
    omitted --codes stays None and derives the ASL main-board universe."""

    import json as _json

    lake = tmp_path / "lake"
    _build_lake(lake)
    data_root = tmp_path / "data"
    from limit_pullback.cli import main

    rc = main(
        [
            "asl-snapshot",
            "--as-of", AS_OF.isoformat(),
            "--asl-root", str(lake),
            "--start", START.isoformat(),
            "--data-root", str(data_root),
        ]
    )
    assert rc == 0
    payload = _json.loads(capsys.readouterr().out)
    assert payload["snapshot_id"]
    layout = WarehouseLayout(data_root)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(payload["snapshot_id"])
        rows = read_snapshot_daily(layout, stored)
    assert len(rows) > 0
    assert {row["code"] for row in rows} == {
        "000001", "000010", "000524", "605198",
    }


def _tamper_daily_file(
    layout: WarehouseLayout, snapshot, mutate
) -> None:
    """Rewrite the canonical daily parquet with *mutate* applied per row and
    source_row_hash recomputed (the manifest/file hashes go stale on purpose;
    the tests assert the ASL contract check fires)."""

    import pyarrow as pa
    import pyarrow.parquet as pq

    daily_rel = next(
        key
        for key in snapshot.canonical_file_hashes
        if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
    )
    path = layout.root / daily_rel
    rows = pq.ParquetFile(path).read().to_pylist()
    for row in rows:
        mutate(row)
    for row in rows:
        row["source_row_hash"] = row_hash(DAILY_HASH_FIELDS, row)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _issue_codes(layout: WarehouseLayout, snapshot_id: str) -> set[str]:
    result = data_validate(layout, snapshot_id=snapshot_id)
    return {issue.check for issue in result.issues}, result.valid


def test_asl_candidate_validates_clean(tmp_path):
    """A. Synthetic ASL candidate snapshot passes data_validate (canonical
    integrity valid; no legacy traceability required)."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is True
    assert "TRACEABILITY" not in codes
    assert is_asl_authoritative(snapshot) is True


def test_asl_provider_mismatch_fails_closed(tmp_path):
    """B. A canonical row not labelled ASL fails closed (ASL_PROVIDER)."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    _tamper_daily_file(layout, snapshot, lambda row: row.update(selected_provider="TUSHARE"))
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is False
    assert "ASL_PROVIDER" in codes


def test_asl_turnover_non_null_fails_closed(tmp_path):
    """C. turnover_rate unexpectedly non-null fails closed (ASL_TURNOVER)."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    _tamper_daily_file(layout, snapshot, lambda row: row.update(turnover_rate="1.23"))
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is False
    assert "ASL_TURNOVER" in codes


def test_asl_preclose_continuity_detected(tmp_path):
    """D. Tampered second-row preclose is detected as PRECLOSE_CONTINUITY
    (source_row_hash recomputed, so this proves continuity, not ROW_HASH)."""

    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    # 6/11 is MISSING_PRECLOSE, so 6/12 is the first canonical row (its
    # predecessor lies outside the window and is not invented).  Tamper the
    # SECOND canonical row (6/15), whose predecessor is the canonical 6/12.
    tampered = {"code": "000001", "date": date(2026, 6, 15)}

    def mutate(row):
        if row["code"] == tampered["code"] and row["trade_date"] == tampered["date"]:
            row["preclose"] = Decimal(row["preclose"]) + Decimal("1.00")

    _tamper_daily_file(layout, snapshot, mutate)
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is False
    assert "PRECLOSE_CONTINUITY" in codes
    assert "ROW_HASH" not in codes


def test_asl_validation_never_reads_legacy_raw(tmp_path, monkeypatch):
    """F. ASL validation never calls the legacy raw-provider reader."""

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("legacy raw-provider read must not happen")

    monkeypatch.setattr(
        "limit_pullback.warehouse.validate._read_parquet_rows", _forbidden
    )
    lake = tmp_path / "lake"
    _build_lake(lake)
    layout, snapshot = _build(tmp_path, lake)
    codes, valid = _issue_codes(layout, snapshot.snapshot_id)
    assert valid is True


def test_cli_asl_snapshot_help_available():
    from limit_pullback.cli import build_parser

    parser = build_parser()
    subcommands = {
        action.dest: action
        for action in parser._actions
        if isinstance(action, type(parser._subparsers._group_actions[0]))
    }
    # argparse exposes subparsers choices via the subparsers action.
    subparsers_action = next(
        action
        for action in parser._actions
        if action.dest == "command"
    )
    assert "asl-snapshot" in subparsers_action.choices
