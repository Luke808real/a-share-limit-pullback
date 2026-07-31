"""Phase 2C.2A real acceptance over Tushare, AKShare and BaoStock.

All acceptance artifacts are written under the system temporary directory;
no real market response is ever committed to Git.
"""

from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile

import pytest

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import read_rows
from limit_pullback.warehouse.pipeline import bootstrap, update
from limit_pullback.warehouse.status import data_status
from limit_pullback.warehouse.validate import data_validate

ACCEPTANCE_CODES = ("603918", "603318", "002640", "600199", "002891")


def _raw_daily(layout: WarehouseLayout, provider: str) -> list[dict]:
    rows: list[dict] = []
    for path in layout.raw_dataset_dir(provider, "daily_bars").glob("*.parquet"):
        rows.extend(read_rows(path))
    return rows


@pytest.mark.integration
def test_real_small_scope_acceptance(tmp_path):
    if not os.environ.get("TUSHARE_TOKEN"):
        pytest.skip("TUSHARE_TOKEN is not configured")

    layout = WarehouseLayout(tmp_path / "warehouse")
    start = date(2026, 6, 1)
    end = date(2026, 7, 30)
    today = date.today()

    result = bootstrap(
        layout=layout,
        start=start,
        end=end,
        codes=ACCEPTANCE_CODES,
        today=today,
    )
    assert result.snapshot_id is not None
    assert result.canonical_daily_rows > 0
    assert len(result.raw_files) >= 3

    tushare_rows = _raw_daily(layout, "TUSHARE")
    akshare_rows = _raw_daily(layout, "AKSHARE")
    baostock_rows = _raw_daily(layout, "BAOSTOCK")
    assert tushare_rows and akshare_rows and baostock_rows

    def by_key(rows):
        return {(str(row["code"]), row["trade_date"].isoformat()): row for row in rows}

    tushare_by_key = by_key(tushare_rows)
    akshare_by_key = by_key(akshare_rows)
    baostock_by_key = by_key(baostock_rows)

    close_diffs: list[dict] = []
    unit_rows: list[dict] = []
    for key, tushare_row in tushare_by_key.items():
        row_info = {
            "code": tushare_row["code"],
            "trade_date": tushare_row["trade_date"].isoformat(),
            "tushare_close": str(tushare_row["close"]),
            "tushare_volume": str(tushare_row["volume"]),
            "tushare_amount": str(tushare_row["amount"]),
        }
        if key in akshare_by_key:
            akshare_row = akshare_by_key[key]
            row_info["akshare_close"] = str(akshare_row["close"])
            row_info["akshare_volume"] = str(akshare_row["volume"])
            row_info["akshare_amount"] = str(akshare_row["amount"])
            row_info["close_diff"] = str(
                abs(Decimal(tushare_row["close"]) - Decimal(akshare_row["close"]))
            )
            close_diffs.append(row_info)
        if key in baostock_by_key:
            baostock_row = baostock_by_key[key]
            row_info["baostock_close"] = str(baostock_row["close"])
            row_info["baostock_volume"] = str(baostock_row["volume"])
            row_info["baostock_amount"] = str(baostock_row["amount"])
        unit_rows.append(row_info)

    status = data_status(layout)
    validation = data_validate(layout)

    outdir = Path(tempfile.gettempdir()) / f"phase-2c2a-acceptance-{os.getpid()}"
    outdir.mkdir(parents=True, exist_ok=True)
    summary = {
        "bootstrap": result.model_dump(mode="json"),
        "data_status": status.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
        "provider_freshness": {
            provider: (value.isoformat() if value else None)
            for provider, value in status.latest_available_date_by_provider.items()
        },
        "unit_and_ohlc_comparison_rows": unit_rows,
        "close_diff_samples": close_diffs[:50],
    }
    (outdir / "acceptance.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (outdir / "validation.json").write_text(
        validation.model_dump_json(indent=2), encoding="utf-8"
    )

    assert status.dataset_snapshot_id == result.snapshot_id
    assert validation.valid is True, validation.model_dump_json(indent=2)

    if today > end:
        updated = update(
            layout=layout,
            as_of=today,
            today=today,
        )
        assert updated.snapshot_id is not None
        repeated = update(
            layout=layout,
            as_of=today,
            today=today,
        )
        assert repeated.reused is True
        assert repeated.snapshot_id == updated.snapshot_id
        summary["update"] = {
            "first": updated.model_dump(mode="json"),
            "repeated": repeated.model_dump(mode="json"),
        }
        (outdir / "acceptance.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
            latest = metadata.latest_snapshot()
            assert latest is not None
            assert latest.as_of == today
