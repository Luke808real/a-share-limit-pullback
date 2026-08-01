from __future__ import annotations

from datetime import date
from decimal import Decimal

from limit_pullback.warehouse.reconciliation import (
    CORPORATE_ACTION_PRECLOSE_DIVERGENCE,
    reconcile_daily_rows,
)
from tests.warehouse_fakes import daily_row


def _rows():
    day = date(2026, 7, 30)
    # Tushare uses the adjusted pre_close on the ex-date; AKShare derives the
    # unadjusted previous close. OHLC/volume/amount agree.
    tushare = daily_row(
        "603318",
        day.isoformat(),
        preclose="8.89",
        close="10.20",
        pct="14.74",
    )
    tushare["pct_change"] = Decimal(
        str(((Decimal("10.20") - Decimal("8.89")) / Decimal("8.89") * 100).quantize(Decimal("0.01")))
    )
    akshare = dict(tushare)
    akshare["preclose"] = Decimal("9.31")
    baostock = dict(tushare)
    for row in (tushare, akshare, baostock):
        row["row_hash"] = f"hash-{row['code']}-{row['trade_date']}-{id(row)}"
    return day, tushare, akshare, baostock


def test_corporate_action_preclose_divergence_published_with_marker():
    day, tushare, akshare, baostock = _rows()
    canonical, records, quarantines = reconcile_daily_rows(
        {
            "TUSHARE": [tushare],
            "AKSHARE": [akshare],
            "BAOSTOCK": [baostock],
        },
        adjustment_factor_rows=[
            {"code": "603318", "trade_date": date(2026, 7, 29), "adj_factor": "1.000000"},
            {"code": "603318", "trade_date": day, "adj_factor": "1.100000"},
        ],
    )
    assert len(canonical) == 1
    row = canonical[0]
    assert row["reconciliation_status"] == "CONFIRMED"
    assert row["selected_provider"] == "TUSHARE"
    assert row["close"] == Decimal("10.20")
    assert quarantines == []
    marker = next(
        record
        for record in records
        if CORPORATE_ACTION_PRECLOSE_DIVERGENCE in (record.notes or "")
    )
    assert marker.status == "CONFIRMED"


def test_unconfirmed_preclose_divergence_stays_quarantined():
    day, tushare, akshare, baostock = _rows()
    canonical, records, quarantines = reconcile_daily_rows(
        {
            "TUSHARE": [tushare],
            "AKSHARE": [akshare],
            "BAOSTOCK": [baostock],
        },
        adjustment_factor_rows=[
            {"code": "603318", "trade_date": date(2026, 7, 29), "adj_factor": "1.000000"},
            {"code": "603318", "trade_date": day, "adj_factor": "1.000000"},
        ],
    )
    assert canonical == []
    assert len(quarantines) == 1
    assert "PRECLOSE_DIVERGENCE_UNCONFIRMED" in quarantines[0].reason
    assert any(record.status == "CONFLICTED" for record in records)


def test_inconsistent_pct_change_blocks_publish():
    day, tushare, akshare, baostock = _rows()
    tushare["pct_change"] = Decimal("99.99")
    canonical, _records, quarantines = reconcile_daily_rows(
        {
            "TUSHARE": [tushare],
            "AKSHARE": [akshare],
            "BAOSTOCK": [baostock],
        },
        adjustment_factor_rows=[
            {"code": "603318", "trade_date": date(2026, 7, 29), "adj_factor": "1.000000"},
            {"code": "603318", "trade_date": day, "adj_factor": "1.100000"},
        ],
    )
    assert canonical == []
    assert quarantines


def test_missing_preclose_row_never_published():
    day = date(2026, 7, 30)
    tushare = daily_row("603318", day.isoformat())
    tushare["preclose"] = None
    akshare = dict(tushare)
    akshare["row_hash"] = "hash-akshare"
    tushare["row_hash"] = "hash-tushare"
    canonical, records, _ = reconcile_daily_rows(
        {"TUSHARE": [tushare], "AKSHARE": [akshare]}
    )
    assert canonical == []
    assert any(
        "MISSING_PRECLOSE_NOT_PUBLISHED" in (record.notes or "")
        for record in records
    )
