from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from limit_pullback.screen.runner import run_screen
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.pipeline import bootstrap
from limit_pullback.warehouse.pipeline import update
from tests.warehouse_fakes import FakeProviderSet, daily_row


def _weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _chain_rows(code: str, dates: list[date]) -> list[dict]:
    rows: list[dict] = []
    previous_close = Decimal("10.00")
    for index, trade_date in enumerate(dates):
        preclose = previous_close
        if index > 0 and index % 30 == 0:
            close = (preclose * Decimal("1.10")).quantize(Decimal("0.01"))
        else:
            close = (preclose + Decimal("0.10")).quantize(Decimal("0.01"))
        high = (max(close, preclose) + Decimal("0.05")).quantize(Decimal("0.01"))
        low = (min(close, preclose) - Decimal("0.05")).quantize(Decimal("0.01"))
        rows.append(
            daily_row(
                code,
                trade_date.isoformat(),
                open_price=str(close),
                high=str(high),
                low=str(low),
                close=str(close),
                preclose=str(preclose),
                volume="1000000",
                amount="10000000",
            )
        )
        previous_close = close
    return rows


def _pool_rows(code: str, dates: list[date], rows: list[dict]) -> list[dict]:
    by_date = {row["trade_date"]: row for row in rows}
    pool: list[dict] = []
    for index, trade_date in enumerate(dates):
        if index > 0 and index % 30 == 0:
            row = by_date[trade_date]
            pool.append(
                {
                    "code": code,
                    "trade_date": trade_date,
                    "name": "测试公司",
                    "limit_price": row["close"],
                    "first_seal_time": None,
                    "last_seal_time": None,
                    "open_count": 0,
                    "consecutive_count": 1,
                    "turnover_rate": None,
                    "float_market_cap": None,
                    "total_market_cap": None,
                    "industry": "测试",
                }
            )
    return pool


def _build_warehouse(
    tmp_path,
    *,
    long_codes=("603318", "002640"),
    short_code="600199",
    snapshot_status="SCREEN_READY",
):
    layout = WarehouseLayout(tmp_path / "data")
    dates = _weekdays(date(2026, 1, 5), 135)
    tushare: list[dict] = []
    akshare: list[dict] = []
    baostock: list[dict] = []
    pool: list[dict] = []
    for code in long_codes:
        rows = _chain_rows(code, dates)
        tushare.extend(rows)
        akshare.extend(rows)
        baostock.extend(rows)
        pool.extend(_pool_rows(code, dates, rows))
    short_dates = dates[:10]
    short_rows = _chain_rows(short_code, short_dates)
    tushare.extend(short_rows)
    akshare.extend(short_rows)
    baostock.extend(short_rows)
    fake = FakeProviderSet(
        calendar=dates,
        tushare_daily=tushare,
        akshare_daily=akshare,
        baostock_daily=baostock,
        pool=pool,
    )
    result = bootstrap(
        layout=layout,
        start=dates[0],
        end=dates[-1],
        codes=[*long_codes, short_code],
        provider_set=fake,
        today=dates[-1],
        snapshot_status=snapshot_status,
    )
    assert result.snapshot_id is not None
    return layout, dates, result.snapshot_id


def _rows_of(run_file):
    from pathlib import Path

    payload = json.loads(Path(run_file).read_text(encoding="utf-8"))
    return {
        (row["code"], row["trade_date"]): row
        for row in payload["rows"]
    }


def test_screen_offline_deterministic_and_verify_replay(tmp_path):
    layout, dates, snapshot_id = _build_warehouse(tmp_path)
    first = run_screen(
        layout=layout,
        as_of=dates[-1],
        start=dates[0],
        rebuild=True,
        snapshot_id=snapshot_id,
        verify_replay=True,
    )
    assert first.universe_size == 3
    assert first.rows_count > 0
    assert first.verify_replay_matched is True
    assert first.new_anchor_count >= 2  # two long codes with anchors
    assert first.output_path is not None

    cached = run_screen(
        layout=layout,
        as_of=dates[-1],
        start=dates[0],
        rebuild=True,
        snapshot_id=snapshot_id,
    )
    assert cached.reused is True
    assert cached.output_hash == first.output_hash

    # Determinism across identical warehouses.
    import tempfile
    from pathlib import Path

    other = Path(tempfile.mkdtemp())
    other_layout, _, other_snapshot = _build_warehouse(other)
    other_run = run_screen(
        layout=other_layout,
        as_of=dates[-1],
        start=dates[0],
        rebuild=True,
        snapshot_id=other_snapshot,
    )
    assert other_run.output_hash == first.output_hash


def test_screen_rebuild_equals_incremental_and_future_isolated(tmp_path):
    layout, dates, snapshot_id = _build_warehouse(tmp_path)
    first_date = dates[30]
    mid_date = dates[70]
    final_date = dates[-1]

    run_inc_1 = run_screen(layout=layout, as_of=first_date, snapshot_id=snapshot_id)
    assert run_inc_1.rows_count > 0
    inc_1_rows = _rows_of(run_inc_1.output_path)

    run_inc_2 = run_screen(layout=layout, as_of=mid_date, snapshot_id=snapshot_id)
    assert run_inc_2.rows_count > 0

    run_rebuild = run_screen(
        layout=layout,
        as_of=mid_date,
        start=dates[0],
        rebuild=True,
        snapshot_id=snapshot_id,
        verify_replay=True,
    )
    assert run_rebuild.verify_replay_matched is True
    rebuild_rows = _rows_of(run_rebuild.output_path)

    # Incremental first-window rows are byte-identical inside the rebuild.
    for key, row in inc_1_rows.items():
        assert rebuild_rows[key] == row

    # Rebuild to final date must not alter history produced by earlier runs.
    run_final = run_screen(
        layout=layout,
        as_of=final_date,
        start=dates[0],
        rebuild=True,
        snapshot_id=snapshot_id,
    )
    final_rows = _rows_of(run_final.output_path)
    for key, row in inc_1_rows.items():
        assert final_rows[key] == row


def test_screen_quality_rejections_for_short_history(tmp_path):
    layout, dates, snapshot_id = _build_warehouse(tmp_path)
    result = run_screen(
        layout=layout,
        as_of=dates[-1],
        start=dates[0],
        rebuild=True,
        snapshot_id=snapshot_id,
    )
    assert result.quality_rejection_count > 0  # 600199 has only 10 bars
    assert "INSUFFICIENT_TRADING_HISTORY" in str(
        result.status_counts
    ) or any(
        row["data_quality"] == "UNUSABLE"
        for row in json.loads(
            open(result.output_path, encoding="utf-8").read()
        )["rows"]
    )


def test_screen_requires_snapshot_with_data(tmp_path):
    layout = WarehouseLayout(tmp_path / "empty")
    with pytest.raises(ValueError):
        run_screen(layout=layout, as_of=date(2026, 7, 30))


def test_screen_incremental_after_update_only_advances_new_dates(tmp_path):
    layout, dates, snapshot_id = _build_warehouse(tmp_path)
    mid_date = dates[80]
    first_run = run_screen(layout=layout, as_of=mid_date, snapshot_id=snapshot_id)
    assert first_run.rows_count > 0

    # Extend the warehouse with one more trading day for each code.
    new_date = dates[-1] + timedelta(days=3)
    while new_date.weekday() >= 5:
        new_date += timedelta(days=1)
    update_rows: list[dict] = []
    for code in ("603318", "002640"):
        code_rows = _chain_rows(code, dates)
        code_rows.extend(_chain_rows(code, [new_date]))
        update_rows.extend(code_rows)
    short_rows = _chain_rows("600199", dates[:10])
    short_rows.extend(_chain_rows("600199", [new_date]))
    update_rows.extend(short_rows)
    fake = FakeProviderSet(
        calendar=[*dates, new_date],
        tushare_daily=update_rows,
        akshare_daily=update_rows,
        baostock_daily=update_rows,
    )
    update(
        layout=layout,
        as_of=new_date,
        provider_set=fake,
        today=new_date,
    )
    # PR-A: update() publishes CURRENT; formal consumption requires an
    # explicit promotion to SCREEN_READY (full promotion gate is PR-D).
    from limit_pullback.warehouse.metadata import WarehouseMetadata

    with WarehouseMetadata(layout.duckdb_path) as metadata:
        latest = metadata.latest_snapshot()
        assert latest is not None
        metadata.set_snapshot_status(
            snapshot_id=latest.snapshot_id,
            status="SCREEN_READY",
            reason="test promotion after update",
        )
    incremental = run_screen(layout=layout, as_of=new_date)
    assert incremental.reused is False
    long_code_days = sum(
        1
        for day in [*dates, new_date]
        if mid_date < day <= new_date and day.weekday() < 5
    )
    # Two long-history codes advance through every new trading day; the
    # short-history code only gains its single new bar.
    assert incremental.rows_count == long_code_days * 2 + 1
    rows = _rows_of(incremental.output_path)
    assert all(key[1] > mid_date.isoformat() for key in rows)
