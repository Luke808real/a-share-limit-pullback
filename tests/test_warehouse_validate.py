from __future__ import annotations

from datetime import date
from decimal import Decimal

import pyarrow.parquet as pq

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.pipeline import bootstrap
from limit_pullback.warehouse.validate import data_validate
from tests.warehouse_fakes import FakeProviderSet, daily_row


def _bootstrap(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    day = date(2026, 7, 30)
    fake = FakeProviderSet(
        calendar=[day],
        tushare_daily=[daily_row("603318", day.isoformat())],
        akshare_daily=[daily_row("603318", day.isoformat())],
        baostock_daily=[daily_row("603318", day.isoformat())],
    )
    result = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=["603318"],
        provider_set=fake,
        today=day,
    )
    return layout, result


def test_validate_passes_on_clean_warehouse(tmp_path):
    layout, _ = _bootstrap(tmp_path)
    result = data_validate(layout)
    assert result.valid is True
    assert result.issues == ()


def test_validate_detects_tampered_canonical_file(tmp_path):
    layout, result = _bootstrap(tmp_path)
    path = layout.canonical_daily_dir / f"{result.snapshot_id}.parquet"
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["close"] = Decimal("99.99")
    from limit_pullback.warehouse.parquet import write_rows_atomic

    write_rows_atomic(rows, table.schema, path)
    validation = data_validate(layout)
    assert validation.valid is False
    checks = {issue.check for issue in validation.issues}
    assert "CANONICAL_FILE_HASH" in checks
    assert "ROW_HASH" in checks
