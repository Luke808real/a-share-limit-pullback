from __future__ import annotations

from datetime import date
from decimal import Decimal

import pyarrow.parquet as pq

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.pipeline import bootstrap
from limit_pullback.warehouse.validate import (
    PRICE_RELATIVE,
    PRICE_TOLERANCE,
    _previous_close_index,
    data_validate,
)
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


def _bootstrap_with_provider_rows(tmp_path, *, provider: str):
    first_day = date(2026, 7, 29)
    second_day = date(2026, 7, 30)
    rows = [
        daily_row("603318", first_day.isoformat(), close="10.00"),
        daily_row(
            "603318",
            second_day.isoformat(),
            open_price="9.50",
            high="10.00",
            low="9.00",
            close="9.50",
            preclose="8.00",
        ),
    ]
    provider_rows = {
        "tushare_daily": rows if provider == "TUSHARE" else [],
        "akshare_daily": rows if provider == "AKSHARE" else [],
        "baostock_daily": rows if provider == "BAOSTOCK" else [],
    }
    layout = WarehouseLayout(tmp_path / "data")
    bootstrap(
        layout=layout,
        start=first_day,
        end=second_day,
        codes=["603318"],
        provider_set=FakeProviderSet(calendar=[first_day, second_day], **provider_rows),
        today=second_day,
    )
    return layout


def test_validate_allows_tushare_adjusted_preclose(tmp_path):
    layout = _bootstrap_with_provider_rows(tmp_path, provider="TUSHARE")

    validation = data_validate(layout)

    assert validation.valid is True
    assert validation.issues == ()


def test_validate_keeps_akshare_preclose_continuity_check(tmp_path):
    layout = _bootstrap_with_provider_rows(tmp_path, provider="AKSHARE")

    validation = data_validate(layout)

    assert validation.valid is False
    assert {issue.check for issue in validation.issues} == {"PRECLOSE_CONTINUITY"}


def test_previous_close_index_matches_legacy_scan_exactly():
    """The indexed lookup must select the identical predecessor as the old scan."""

    raw_rows_by_provider = {
        "TUSHARE": {
            ("000001", date(2026, 7, 1)): {"close": Decimal("10.00")},
            ("000001", date(2026, 7, 2)): {"close": None},
            ("000001", date(2026, 7, 3)): {"close": Decimal("10.30")},
            ("600000", date(2026, 7, 2)): {"close": Decimal("8.00")},
            ("600000", date(2026, 7, 4)): {"close": Decimal("8.20")},
        },
        "AKSHARE": {
            ("000001", date(2026, 7, 1)): {"close": Decimal("9.90")},
            ("000001", date(2026, 7, 4)): {"close": Decimal("10.40")},
            ("600000", date(2026, 7, 3)): {"close": None},
        },
        "BAOSTOCK": {},
    }

    def legacy_index(rows_by_provider):
        result = {}
        for provider, rows_by_key in rows_by_provider.items():
            provider_result = {}
            for code, trade_date in rows_by_key:
                previous_dates = sorted(
                    earlier_date
                    for other_code, earlier_date in rows_by_key
                    if other_code == code and earlier_date < trade_date
                )
                if previous_dates:
                    provider_result[(code, trade_date)] = rows_by_key[
                        (code, previous_dates[-1])
                    ].get("close")
            result[provider] = provider_result
        return result

    indexed = _previous_close_index(raw_rows_by_provider)
    assert indexed == legacy_index(
        raw_rows_by_provider
    )

    canonical_rows = (
        ("TUSHARE", "000001", date(2026, 7, 1), Decimal("9.90")),
        ("TUSHARE", "000001", date(2026, 7, 2), Decimal("10.00")),
        ("TUSHARE", "000001", date(2026, 7, 3), Decimal("10.05")),
        ("TUSHARE", "000001", date(2026, 7, 4), Decimal("10.31")),
        ("TUSHARE", "600000", date(2026, 7, 4), Decimal("8.25")),
        ("AKSHARE", "000001", date(2026, 7, 4), Decimal("10.00")),
        ("AKSHARE", "600000", date(2026, 7, 3), Decimal("8.00")),
    )

    def continuity_issues(previous_close_for):
        issues = []
        for provider, code, trade_date, preclose in canonical_rows:
            previous_close = previous_close_for(provider, code, trade_date)
            if previous_close is None:
                continue
            difference = abs(preclose - Decimal(previous_close))
            scale = max(abs(preclose), abs(Decimal(previous_close)))
            if difference > max(PRICE_TOLERANCE, PRICE_RELATIVE * scale):
                issues.append((provider, code, trade_date))
        return issues

    legacy = legacy_index(raw_rows_by_provider)
    assert continuity_issues(
        lambda provider, code, trade_date: legacy[provider].get((code, trade_date))
    ) == continuity_issues(
        lambda provider, code, trade_date: indexed[provider].get((code, trade_date))
    )
