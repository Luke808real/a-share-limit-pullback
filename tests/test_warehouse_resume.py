from __future__ import annotations

from datetime import date

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.pipeline import bootstrap
from limit_pullback.warehouse.snapshot import read_snapshot_daily
from tests.warehouse_fakes import FakeProviderSet, daily_row


def _layout(tmp_path):
    return WarehouseLayout(tmp_path / "data")


def _rows(code, days):
    return [daily_row(code, day.isoformat()) for day in days]


def test_bootstrap_resume_retries_only_failed_codes(tmp_path):
    layout = _layout(tmp_path)
    days = [date(2026, 7, 29), date(2026, 7, 30)]
    codes = ("603318", "002640", "600199")

    class FlakyAkshare(FakeProviderSet):
        def __init__(self, *args, fail_code=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.fail_code = fail_code
            self.fail_mode = True

        def fetch_akshare_daily(self, requested, start, end):
            if self.fail_mode and self.fail_code in requested:
                raise RuntimeError("temporary akshare failure")
            return super().fetch_akshare_daily(requested, start, end)

    fake = FlakyAkshare(
        calendar=days,
        tushare_daily=[row for code in codes for row in _rows(code, days)],
        akshare_daily=[row for code in codes for row in _rows(code, days)],
        baostock_daily=[row for code in codes for row in _rows(code, days)],
        fail_code="002640",
    )
    first = bootstrap(
        layout=layout,
        start=days[0],
        end=days[-1],
        codes=codes,
        provider_set=fake,
        today=days[-1],
    )
    assert first.failure_count >= 1
    assert first.pending_failures >= 1
    assert first.snapshot_id is not None
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        assert metadata.failure_count(first.run_id) >= 1

    # The provider recovers; re-running the same run retries only the failed
    # code while preserving confirmed data from the first attempt.
    fake.fail_mode = False
    second = bootstrap(
        layout=layout,
        start=days[0],
        end=days[-1],
        codes=codes,
        provider_set=fake,
        today=days[-1],
    )
    assert second.reused is False
    assert second.pending_failures == 0
    assert second.snapshot_id is not None
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        rows = metadata._connection.execute(
            "SELECT status FROM ingest_failures WHERE run_id = ?",
            [first.run_id],
        ).fetchall()
        assert all(row[0] == "RESOLVED" for row in rows)
        snapshot = metadata.snapshot_by_id(second.snapshot_id)
        assert snapshot is not None
        daily = read_snapshot_daily(layout, snapshot)
        code_640 = [row for row in daily if row["code"] == "002640"]
        assert code_640
        assert all(row["reconciliation_status"] == "CONFIRMED" for row in code_640)

    # First-attempt batch files must still exist (no data discarded).
    akshare_files = list(layout.raw_akshare_dir.glob("daily_bars/*.parquet"))
    assert len(akshare_files) >= 2


def test_all_main_board_bootstrap_uses_stock_basic_universe(tmp_path):
    layout = _layout(tmp_path)
    day = date(2026, 7, 30)
    stock_basic = [
        {"code": "603318", "name": "a", "industry": "x", "market": "主板", "list_date": None, "is_st": False},
        {"code": "002640", "name": "b", "industry": "x", "market": "主板", "list_date": None, "is_st": False},
        {"code": "300001", "name": "c", "industry": "x", "market": "创业板", "list_date": None, "is_st": False},
        {"code": "688001", "name": "d", "industry": "x", "market": "科创板", "list_date": None, "is_st": False},
    ]
    fake = FakeProviderSet(
        calendar=[day],
        tushare_daily=[
            daily_row("603318", day.isoformat()),
            daily_row("002640", day.isoformat()),
        ],
        akshare_daily=[
            daily_row("603318", day.isoformat()),
            daily_row("002640", day.isoformat()),
        ],
        stock_basic=stock_basic,
    )
    result = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=(),
        provider_set=fake,
        today=day,
        all_main_board=True,
    )
    assert result.codes == ("002640", "603318")
    assert "300001" not in result.codes
    assert "688001" not in result.codes


def test_large_universe_uses_bulk_tushare_fetch(tmp_path):
    layout = _layout(tmp_path)
    day = date(2026, 7, 30)
    codes = tuple(f"600{i:03d}" for i in range(250))
    rows = [daily_row(code, day.isoformat()) for code in codes]
    pool = [
        {
            "code": code,
            "trade_date": day,
            "name": "n",
            "limit_price": rows[index]["close"],
            "first_seal_time": None,
            "last_seal_time": None,
            "open_count": 0,
            "consecutive_count": 1,
            "turnover_rate": None,
            "float_market_cap": None,
            "total_market_cap": None,
            "industry": "x",
        }
        for index, code in enumerate(codes)
    ]

    class CountingFake(FakeProviderSet):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.bulk_calls = 0
            self.per_code_calls = 0

        def fetch_tushare_daily_by_trade_date(self, dates):
            self.bulk_calls += 1
            wanted = set(dates)
            return [
                dict(row)
                for row in self.tushare_daily
                if row["trade_date"] in wanted
            ]

        def fetch_tushare_daily(self, requested, start, end):
            self.per_code_calls += 1
            return super().fetch_tushare_daily(requested, start, end)

    fake = CountingFake(
        calendar=[day],
        tushare_daily=rows,
        akshare_daily=rows,
        pool=pool,
    )
    result = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=codes,
        provider_set=fake,
        today=day,
        bulk_threshold=200,
    )
    assert result.snapshot_id is not None
    assert fake.bulk_calls >= 1
    assert fake.per_code_calls == 0
