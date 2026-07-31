from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.locking import WarehouseLock
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.pipeline import (
    PipelineError,
    bootstrap,
    update,
)
from limit_pullback.warehouse.parquet import sha256_file
from limit_pullback.warehouse.snapshot import read_snapshot_daily
from tests.warehouse_fakes import FakeProviderSet, daily_row


def _layout(tmp_path) -> WarehouseLayout:
    return WarehouseLayout(tmp_path / "data")


def _dates(*days):
    return [date(2026, 7, day) for day in days]


def _tushare_rows(calendar, *, code="603318", baostock_missing_last=False):
    rows = [daily_row(code, day.isoformat()) for day in calendar]
    if baostock_missing_last:
        rows = rows[:-1]
    return rows


def test_bootstrap_publishes_snapshot_and_is_idempotent(tmp_path):
    layout = _layout(tmp_path)
    calendar = _dates(27, 28, 29, 30)
    tushare = _tushare_rows(calendar)
    akshare = _tushare_rows(calendar)
    baostock = _tushare_rows(calendar, baostock_missing_last=True)
    fake = FakeProviderSet(
        calendar=calendar,
        tushare_daily=tushare,
        akshare_daily=akshare,
        baostock_daily=baostock,
        daily_basic=[
            {
                "code": "603318",
                "trade_date": day,
                "turnover_rate": Decimal("2.50"),
                "volume_ratio": None,
                "pe": None,
                "pb": None,
                "total_mv": None,
                "circ_mv": None,
            }
            for day in calendar
        ],
        stock_basic=[
            {"code": "603318", "name": "某公司", "industry": "xx", "market": "主板", "list_date": None, "is_st": False}
        ],
    )
    result = bootstrap(
        layout=layout,
        start=calendar[0],
        end=calendar[-1],
        codes=["603318"],
        provider_set=fake,
        today=calendar[-1],
    )
    assert result.snapshot_id is not None
    assert result.canonical_daily_rows == 4
    assert result.quarantine_rows == 0
    assert len(result.raw_files) == 4  # tushare daily+basic, akshare, baostock

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.latest_snapshot()
        assert snapshot is not None
        assert snapshot.as_of == calendar[-1]
        counts = metadata.count_by_status()
        assert counts.get("CONFIRMED") == 4
        assert counts.get("INCOMPLETE", 0) == 0
        rows = read_snapshot_daily(layout, snapshot)
        assert all(row["reconciliation_status"] == "CONFIRMED" for row in rows)
        assert all(row["selected_provider"] == "TUSHARE" for row in rows)

    raw_count_before = len(list((layout.root / "raw").rglob("*.parquet")))
    again = bootstrap(
        layout=layout,
        start=calendar[0],
        end=calendar[-1],
        codes=["603318"],
        provider_set=fake,
        today=calendar[-1],
    )
    assert again.reused is True
    assert again.snapshot_id == result.snapshot_id
    raw_count_after = len(list((layout.root / "raw").rglob("*.parquet")))
    assert raw_count_after == raw_count_before


def test_baostock_lagging_is_recorded_but_confirmed(tmp_path):
    layout = _layout(tmp_path)
    calendar = _dates(29, 30)
    fake = FakeProviderSet(
        calendar=calendar,
        tushare_daily=[
            daily_row("603318", "2026-07-29"),
            daily_row("603318", "2026-07-30", preclose="10.20", close="10.30"),
        ],
        akshare_daily=[
            daily_row("603318", "2026-07-29"),
            daily_row("603318", "2026-07-30", preclose="10.20", close="10.30"),
        ],
        baostock_daily=_tushare_rows(calendar, baostock_missing_last=True),
    )
    bootstrap(
        layout=layout,
        start=calendar[0],
        end=calendar[-1],
        codes=["603318"],
        provider_set=fake,
        today=calendar[-1],
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        rows = metadata._connection.execute(
            """
            SELECT notes FROM reconciliation_results
            WHERE status = 'CONFIRMED' AND notes LIKE '%BAOSTOCK_LAGGING%'
            """
        ).fetchall()
        assert len(rows) == 1


def test_same_source_duplicates_are_deduplicated(tmp_path):
    layout = _layout(tmp_path)
    calendar = _dates(30)
    duplicated = _tushare_rows(calendar) * 2
    fake = FakeProviderSet(
        calendar=calendar,
        tushare_daily=duplicated,
        akshare_daily=_tushare_rows(calendar),
    )
    result = bootstrap(
        layout=layout,
        start=calendar[0],
        end=calendar[-1],
        codes=["603318"],
        provider_set=fake,
        today=calendar[-1],
    )
    assert result.canonical_daily_rows == 1
    daily_files = list(layout.raw_tushare_dir.glob("daily_bars/*.parquet"))
    from limit_pullback.warehouse.parquet import read_rows

    assert len(read_rows(daily_files[0])) == 1


def test_same_source_conflict_goes_to_quarantine(tmp_path):
    layout = _layout(tmp_path)
    day = date(2026, 7, 30)
    first = daily_row("603318", day.isoformat(), close="10.20")
    second = daily_row("603318", day.isoformat(), close="11.00")
    fake = FakeProviderSet(
        calendar=[day],
        tushare_daily=[first, second],
        akshare_daily=[first],
    )
    result = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=["603318"],
        provider_set=fake,
        today=day,
    )
    assert result.canonical_daily_rows == 1
    assert result.quarantine_rows >= 1
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        assert metadata.quarantine_count() >= 1
        from limit_pullback.warehouse.snapshot import read_snapshot_daily

        snapshot = metadata.latest_snapshot()
        rows = read_snapshot_daily(layout, snapshot)
        assert rows[0]["reconciliation_status"] == "PROVISIONAL"
        assert rows[0]["selected_provider"] == "AKSHARE"


def test_cross_source_conflict_is_not_published(tmp_path):
    layout = _layout(tmp_path)
    day = date(2026, 7, 30)
    tushare = daily_row("603318", day.isoformat(), close="10.20")
    akshare = daily_row("603318", day.isoformat(), close="9.00")
    fake = FakeProviderSet(
        calendar=[day],
        tushare_daily=[tushare],
        akshare_daily=[akshare],
        baostock_daily=[tushare],
    )
    result = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=["603318"],
        provider_set=fake,
        today=day,
    )
    assert result.canonical_daily_rows == 0
    assert result.quarantine_rows == 1
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        counts = metadata.count_by_status()
        assert counts.get("CONFLICTED") == 1
        assert metadata.quarantine_count() == 1


def test_update_is_idempotent_and_point_in_time_is_stable(tmp_path):
    layout = _layout(tmp_path)
    calendar = _dates(29, 30)
    fake = FakeProviderSet(
        calendar=calendar,
        tushare_daily=[
            daily_row("603318", "2026-07-29"),
            daily_row("603318", "2026-07-30", preclose="10.20", close="10.30"),
        ],
        akshare_daily=[
            daily_row("603318", "2026-07-29"),
            daily_row("603318", "2026-07-30", preclose="10.20", close="10.30"),
        ],
    )
    first = bootstrap(
        layout=layout,
        start=calendar[0],
        end=calendar[-1],
        codes=["603318"],
        provider_set=fake,
        today=calendar[-1],
    )
    snapshot_30 = first.snapshot_id
    daily_file_30 = layout.canonical_daily_dir / f"{snapshot_30}.parquet"
    hash_30 = sha256_file(daily_file_30)

    day_31 = date(2026, 7, 31)
    fake.calendar.append(day_31)
    fake.tushare_daily.append(daily_row("603318", day_31.isoformat()))
    fake.akshare_daily.append(daily_row("603318", day_31.isoformat()))

    updated = update(
        layout=layout,
        as_of=day_31,
        provider_set=fake,
        today=day_31,
    )
    assert updated.snapshot_id != snapshot_30
    assert updated.new_trade_dates == (day_31,)
    assert updated.canonical_daily_rows == 3

    again = update(
        layout=layout,
        as_of=day_31,
        provider_set=fake,
        today=day_31,
    )
    assert again.reused is True
    assert again.snapshot_id == updated.snapshot_id

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot_30_resolved = metadata.resolve_snapshot(date(2026, 7, 30))
        assert snapshot_30_resolved.snapshot_id == snapshot_30
        rows = read_snapshot_daily(layout, snapshot_30_resolved)
        assert all(row["trade_date"] <= date(2026, 7, 30) for row in rows)
        assert len(rows) == 2
        assert sha256_file(daily_file_30) == hash_30


def test_update_requires_baseline_snapshot(tmp_path):
    layout = _layout(tmp_path)
    with pytest.raises(PipelineError) as exc_info:
        update(layout=layout, as_of=date(2026, 7, 30), today=date(2026, 7, 30))
    assert exc_info.value.code == "NO_BASELINE_SNAPSHOT"


def test_update_rejects_future_as_of(tmp_path):
    layout = _layout(tmp_path)
    calendar = _dates(29, 30)
    fake = FakeProviderSet(
        calendar=calendar,
        tushare_daily=_tushare_rows(calendar),
        akshare_daily=_tushare_rows(calendar),
    )
    bootstrap(
        layout=layout,
        start=calendar[0],
        end=calendar[-1],
        codes=["603318"],
        provider_set=fake,
        today=calendar[-1],
    )
    with pytest.raises(PipelineError) as exc_info:
        update(
            layout=layout,
            as_of=date(2026, 8, 1),
            provider_set=fake,
            today=date(2026, 7, 31),
        )
    assert exc_info.value.code == "AS_OF_IN_FUTURE"


def test_update_marks_incomplete_dates_and_keeps_confirmed_history(tmp_path):
    layout = _layout(tmp_path)
    calendar = _dates(29, 30)
    fake = FakeProviderSet(
        calendar=calendar,
        tushare_daily=_tushare_rows(calendar),
        akshare_daily=_tushare_rows(calendar),
    )
    bootstrap(
        layout=layout,
        start=calendar[0],
        end=calendar[-1],
        codes=["603318"],
        provider_set=fake,
        today=calendar[-1],
    )
    day_31 = date(2026, 7, 31)
    fake.calendar.append(day_31)
    result = update(
        layout=layout,
        as_of=day_31,
        provider_set=fake,
        today=day_31,
    )
    assert result.canonical_daily_rows == 2  # previous history kept
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        counts = metadata.count_by_status()
        assert counts.get("INCOMPLETE", 0) >= 1


def test_update_provider_revision_replaces_row_in_new_snapshot(tmp_path):
    layout = _layout(tmp_path)
    calendar = _dates(29, 30)
    fake = FakeProviderSet(
        calendar=calendar,
        tushare_daily=_tushare_rows(calendar),
        akshare_daily=_tushare_rows(calendar),
    )
    first = bootstrap(
        layout=layout,
        start=calendar[0],
        end=calendar[-1],
        codes=["603318"],
        provider_set=fake,
        today=calendar[-1],
    )
    day_31 = date(2026, 7, 31)
    revised_30 = daily_row("603318", "2026-07-30", close="10.33")
    fake.calendar.append(day_31)
    fake.tushare_daily = [
        daily_row("603318", "2026-07-29"),
        revised_30,
        daily_row("603318", day_31.isoformat()),
    ]
    fake.akshare_daily = [
        daily_row("603318", "2026-07-29"),
        revised_30,
        daily_row("603318", day_31.isoformat()),
    ]
    updated = update(
        layout=layout,
        as_of=day_31,
        provider_set=fake,
        today=day_31,
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        new_snapshot = metadata.snapshot_by_id(updated.snapshot_id)
        rows = read_snapshot_daily(layout, new_snapshot)
        row_30 = next(row for row in rows if row["trade_date"] == date(2026, 7, 30))
        assert row_30["close"] == Decimal("10.33")
        old_snapshot = metadata.snapshot_by_id(first.snapshot_id)
        old_rows = read_snapshot_daily(layout, old_snapshot)
        old_30 = next(row for row in old_rows if row["trade_date"] == date(2026, 7, 30))
        assert old_30["close"] == Decimal("10.20")


def test_bootstrap_rejects_future_end(tmp_path):
    layout = _layout(tmp_path)
    with pytest.raises(PipelineError) as exc_info:
        bootstrap(
            layout=layout,
            start=date(2026, 7, 29),
            end=date(2026, 8, 1),
            codes=["603318"],
            today=date(2026, 7, 31),
        )
    assert exc_info.value.code == "END_DATE_IN_FUTURE"


def test_core_capability_permission_stops_bootstrap(tmp_path):
    layout = _layout(tmp_path)
    from tests.warehouse_fakes import probe_result_with

    fake = FakeProviderSet(
        calendar=_dates(29, 30),
        probe_result=probe_result_with({"daily_bars": "UNAVAILABLE_PERMISSION"}),
    )
    with pytest.raises(PipelineError) as exc_info:
        bootstrap(
            layout=layout,
            start=date(2026, 7, 29),
            end=date(2026, 7, 30),
            codes=["603318"],
            provider_set=fake,
            today=date(2026, 7, 30),
        )
    assert exc_info.value.code == "CORE_CAPABILITY_daily_bars_UNAVAILABLE_PERMISSION"


def test_warehouse_lock_is_exclusive(tmp_path):
    lock_path = tmp_path / "data" / ".warehouse.lock"
    first = WarehouseLock(lock_path)
    second = WarehouseLock(lock_path)
    with first:
        with pytest.raises(BlockingIOError):
            second.acquire(nonblocking=True)
    second.acquire(nonblocking=True)
    second.release()


def test_failed_run_error_is_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "secret-token-value")
    layout = _layout(tmp_path)
    day = date(2026, 7, 30)

    class FailingAkshare(FakeProviderSet):
        def fetch_akshare_daily(self, codes, start, end):
            raise RuntimeError("failure with secret-token-value inside")

    fake = FailingAkshare(
        calendar=[day],
        tushare_daily=[daily_row("603318", day.isoformat())],
    )
    result = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=["603318"],
        provider_set=fake,
        today=day,
    )
    assert result.failure_count >= 1
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        row = metadata._connection.execute(
            "SELECT error FROM ingest_failures LIMIT 1"
        ).fetchone()
        assert row is not None
        assert "secret-token-value" not in (row[0] or "")


def test_update_preserves_confirmed_when_source_transiently_missing(tmp_path):
    layout = _layout(tmp_path)
    calendar = _dates(29, 30)
    fake = FakeProviderSet(
        calendar=calendar,
        tushare_daily=[
            daily_row("603318", "2026-07-29"),
            daily_row("603318", "2026-07-30", preclose="10.20", close="10.30"),
        ],
        akshare_daily=[
            daily_row("603318", "2026-07-29"),
            daily_row("603318", "2026-07-30", preclose="10.20", close="10.30"),
        ],
    )
    first = bootstrap(
        layout=layout,
        start=calendar[0],
        end=calendar[-1],
        codes=["603318"],
        provider_set=fake,
        today=calendar[-1],
    )
    day_31 = date(2026, 7, 31)
    fake.calendar.append(day_31)
    # Current fetch: Tushare returns all three days, AKShare returns ONLY the
    # new day (transient gap for previous dates).
    fake.tushare_daily = [
        daily_row("603318", "2026-07-29"),
        daily_row("603318", "2026-07-30", preclose="10.20", close="10.30"),
        daily_row("603318", day_31.isoformat(), preclose="10.30", close="10.40"),
    ]
    fake.akshare_daily = [
        daily_row("603318", day_31.isoformat(), preclose="10.30", close="10.40")
    ]
    updated = update(
        layout=layout,
        as_of=day_31,
        provider_set=fake,
        today=day_31,
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        new_snapshot = metadata.snapshot_by_id(updated.snapshot_id)
        rows = read_snapshot_daily(layout, new_snapshot)
        row_30 = next(row for row in rows if row["trade_date"] == date(2026, 7, 30))
        assert row_30["reconciliation_status"] == "CONFIRMED"
        assert row_30["close"] == Decimal("10.30")
        # Manifest must keep historical source files for traceability.
        assert first.snapshot_id is not None
        assert len(new_snapshot.source_file_hashes) >= len(
            metadata.snapshot_by_id(first.snapshot_id).source_file_hashes
        )
    from limit_pullback.warehouse.validate import data_validate

    validation = data_validate(layout)
    assert validation.valid is True


def test_limit_pool_same_source_conflict_quarantined(tmp_path):
    layout = _layout(tmp_path)
    day = date(2026, 7, 30)
    pool_a = {
        "code": "603318",
        "trade_date": day,
        "name": "公司A",
        "limit_price": Decimal("10.20"),
        "first_seal_time": None,
        "last_seal_time": None,
        "open_count": None,
        "consecutive_count": None,
        "turnover_rate": None,
        "float_market_cap": None,
        "total_market_cap": None,
        "industry": None,
    }
    pool_b = {**pool_a, "limit_price": Decimal("10.50")}
    fake = FakeProviderSet(
        calendar=[day],
        tushare_daily=[daily_row("603318", day.isoformat())],
        akshare_daily=[daily_row("603318", day.isoformat())],
        pool=[pool_a, pool_b],
    )
    result = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=["603318"],
        provider_set=fake,
        today=day,
    )
    assert result.canonical_pool_rows == 0
    assert result.quarantine_rows >= 1
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        assert metadata.quarantine_count() >= 1
        counts = metadata.count_by_status()
        assert counts.get("QUARANTINED", 0) >= 1
