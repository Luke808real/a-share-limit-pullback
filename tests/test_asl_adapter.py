"""Phase-1A unit tests for the read-only ASL adapter (offline, synthetic).

Covers review-round-1 blockers: required-dataset fail-closed, missing-bar
gate, status semantics, predecessor seeding, duplicate PK guards, partition
pruning, turnover contract, and compatibility gating.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from limit_pullback.warehouse.asl_adapter import (
    AslAdapterError,
    TESTED_COMPAT_REVISION,
    CONTRACT_VERSION,
    AslDailySlice,
    load_asl_daily_slice,
)

WEEKEND = (date(2026, 6, 13), date(2026, 6, 14))


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)


def _default_bars() -> dict[str, list[dict]]:
    """Every code has a bar on every default trading day (6/11, 6/12, 6/15)."""

    return {
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
    }


def _build_lake(
    root: Path,
    *,
    trading_days: list[date] | None = None,
    bars: dict[str, list[dict]] | None = None,
    versions: dict[str, str] | None = None,
    status_rows: list[dict] | None = None,
    instruments: list[dict] | None = None,
    with_status: bool = True,
    drop_datasets: tuple[str, ...] = (),
) -> None:
    trading_days = trading_days or [date(2026, 6, 11), date(2026, 6, 12), date(2026, 6, 15)]
    if "instruments" not in drop_datasets:
        _write(
            root / "curated" / "instruments" / "part-merged.parquet",
            instruments
            or [
                {"symbol": "000001.SZ", "list_date": None, "delist_date": None},
                {"symbol": "000010.SZ", "list_date": None, "delist_date": None},
                {"symbol": "000524.SZ", "list_date": None, "delist_date": None},
                {"symbol": "300750.SZ", "list_date": None, "delist_date": None},
                {"symbol": "605198.SH", "list_date": None, "delist_date": None},
            ],
        )
    if "trading_calendar" not in drop_datasets:
        _write(
            root / "curated" / "trading_calendar" / "trade_date=2026" / "part-merged.parquet",
            [
                {"trade_date": day, "is_trading": day in trading_days}
                for day in [
                    date(2026, 6, 11), date(2026, 6, 12),
                    *WEEKEND, date(2026, 6, 15),
                    date(2026, 6, 16), date(2026, 6, 17),
                ]
            ],
        )

    bars = bars if bars is not None else _default_bars()
    versions = versions or {}
    if "daily_bars" not in drop_datasets:
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
                        "amount": row.get("amount"),
                        "source": "tdx_protocol",
                        "data_version": versions.get(symbol, "v2"),
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

    if with_status and "trading_status" not in drop_datasets:
        _write(
            root / "curated" / "trading_status" / "trade_date=2026-06" / "part-merged.parquet",
            status_rows
            or [
                {"symbol": "000010.SZ", "trade_date": date(2026, 6, 12), "is_trading": True, "status": "st"},
                {"symbol": "000010.SZ", "trade_date": date(2026, 6, 15), "is_trading": True, "status": "*st"},
                {"symbol": "000524.SZ", "trade_date": date(2026, 6, 12), "is_trading": False, "status": "suspended"},
                {"symbol": "000524.SZ", "trade_date": date(2026, 6, 15), "is_trading": True, "status": "normal"},
            ],
        )


def _load(root: Path, **kwargs) -> AslDailySlice:
    return load_asl_daily_slice(
        root,
        as_of=date(2026, 6, 15),
        start=date(2026, 6, 11),
        **kwargs,
    )


def _row(slice_: AslDailySlice, code: str, day: date):
    return next(
        row for row in slice_.rows if row.code == code and row.trade_date == day
    )


def _bar_rows(code: str, days: list[date], close: str) -> list[dict]:
    return [
        {"trade_date": day, "open": close, "high": close, "low": close,
         "close": close, "volume": 10000, "amount": 100000.0}
        for day in days
    ]


def test_symbol_normalization_and_universe_prefix_exclusion(tmp_path):
    _build_lake(tmp_path)
    result = _load(
        tmp_path,
        codes=["000001", "300750", "999999", "600999"],
    )
    assert "300750" in result.excluded_codes
    assert "999999" in result.excluded_codes  # outside frozen prefixes
    assert "600999" in result.missing_symbols  # frozen prefix, absent from ASL
    assert all(row.code != "300750" for row in result.rows)
    assert {row.code for row in result.rows} == {"000001"}


def test_decimal_price_quantization_and_units(tmp_path):
    _build_lake(tmp_path)
    row = _row(_load(tmp_path), "000001", date(2026, 6, 11))
    assert row.open == Decimal("11.3000")
    assert row.high == Decimal("11.4000")
    assert row.volume == Decimal("100000")
    assert row.amount == Decimal("1129999.50000000")


def test_volume_unit_contract_v1_fails_closed(tmp_path):
    _build_lake(tmp_path, versions={"000001.SZ": "v1"})
    with pytest.raises(AslAdapterError, match="data_version"):
        _load(tmp_path)


@pytest.mark.parametrize("dataset", ["instruments", "trading_calendar", "daily_bars", "trading_status"])
def test_missing_required_dataset_fails_closed(tmp_path, dataset):
    _build_lake(tmp_path, drop_datasets=(dataset,))
    with pytest.raises(AslAdapterError, match=f"required ASL dataset missing: {dataset}"):
        _load(tmp_path)


def test_missing_required_column_fails_closed(tmp_path):
    _build_lake(tmp_path)
    # Rewrite one daily partition without the data_version column.
    path = tmp_path / "curated" / "daily_bars" / "trade_date=2026-06-11" / "part-merged.parquet"
    table = pq.ParquetFile(path).read()
    _write(
        path,
        [
            {k: v for k, v in row.items() if k != "data_version"}
            for row in table.to_pylist()
        ],
    )
    with pytest.raises(AslAdapterError, match="daily_bars missing required columns"):
        _load(tmp_path)


def test_missing_bar_suspended_allowed(tmp_path):
    bars = _default_bars()
    bars["000524.SZ"] = [
        {"trade_date": date(2026, 6, 11), "open": 9.00, "high": 9.10, "low": 8.95, "close": 9.00, "volume": 80000, "amount": 720000.0},
        {"trade_date": date(2026, 6, 15), "open": 9.10, "high": 9.25, "low": 9.05, "close": 9.20, "volume": 90000, "amount": 825000.0},
    ]
    _build_lake(tmp_path, bars=bars)
    result = _load(tmp_path)
    assert (("000524", date(2026, 6, 12))) in result.suspended_sessions
    assert any(
        item.code == "000524"
        and item.trade_date == date(2026, 6, 12)
        and item.reason == "SUSPENDED_BY_STATUS"
        for item in result.missing_required_bars
    )


def test_missing_bar_normal_status_blocks(tmp_path):
    bars = {"600999.SZ": _bar_rows("600999.SZ", [date(2026, 6, 11)], "5.00")}
    _build_lake(
        tmp_path,
        bars=bars,
        instruments=[
            {"symbol": "600999.SZ", "list_date": None, "delist_date": None},
        ],
        status_rows=[
            {"symbol": "600999.SZ", "trade_date": date(2026, 6, 12), "is_trading": True, "status": "normal"},
        ],
    )
    with pytest.raises(AslAdapterError, match="MISSING_REQUIRED_BAR:600999:2026-06-12"):
        _load(tmp_path, codes=["600999"])


def test_missing_bar_no_status_blocks(tmp_path):
    bars = {"600999.SZ": _bar_rows("600999.SZ", [date(2026, 6, 11)], "5.00")}
    _build_lake(
        tmp_path,
        bars=bars,
        instruments=[
            {"symbol": "600999.SZ", "list_date": None, "delist_date": None},
        ],
        status_rows=[],
    )
    with pytest.raises(AslAdapterError, match="MISSING_REQUIRED_BAR:600999:2026-06-12"):
        _load(tmp_path, codes=["600999"])


def test_missing_bar_not_listed_allowed(tmp_path):
    bars = {"600999.SZ": _bar_rows("600999.SZ", [date(2026, 6, 15)], "5.00")}
    _build_lake(
        tmp_path,
        bars=bars,
        instruments=[
            {"symbol": "600999.SZ", "list_date": date(2026, 6, 15), "delist_date": None},
        ],
        status_rows=[],
    )
    result = _load(tmp_path, codes=["600999"])
    reasons = {
        (item.code, item.trade_date): item.reason
        for item in result.missing_required_bars
    }
    assert reasons[("600999", date(2026, 6, 11))] == "NOT_LISTED"
    assert reasons[("600999", date(2026, 6, 12))] == "NOT_LISTED"
    row = _row(result, "600999", date(2026, 6, 15))
    assert row.trade_date == date(2026, 6, 15)
    assert row.close == Decimal("5.0000")


def test_status_semantics_explicit_cases(tmp_path):
    _build_lake(
        tmp_path,
        status_rows=[
            {"symbol": "000001.SZ", "trade_date": date(2026, 6, 11), "is_trading": True, "status": "normal"},
            {"symbol": "000010.SZ", "trade_date": date(2026, 6, 12), "is_trading": True, "status": "st"},
            {"symbol": "000524.SZ", "trade_date": date(2026, 6, 12), "is_trading": False, "status": "suspended"},
            {"symbol": "605198.SH", "trade_date": date(2026, 6, 11), "is_trading": False, "status": "st"},
        ],
    )
    result = _load(tmp_path)
    normal = _row(result, "000001", date(2026, 6, 11))
    assert (normal.trade_status, normal.is_st) == (True, False)
    st = _row(result, "000010", date(2026, 6, 12))
    assert (st.trade_status, st.is_st) == (True, True)
    suspended = _row(result, "000524", date(2026, 6, 12))
    assert (suspended.trade_status, suspended.is_st) == (False, None)
    st_not_trading = _row(result, "605198", date(2026, 6, 11))
    assert (st_not_trading.trade_status, st_not_trading.is_st) == (False, True)


def test_missing_status_row_positive_bar_unknown_st(tmp_path):
    _build_lake(tmp_path, status_rows=[])
    result = _load(tmp_path)
    row = _row(result, "000001", date(2026, 6, 11))
    assert row.trade_status is True
    assert row.is_st is None  # never claims normal from absence


def test_missing_status_row_zero_volume_bar_suspended(tmp_path):
    bars = _default_bars()
    bars["605198.SH"][1] = {
        "trade_date": date(2026, 6, 12), "open": 50.0, "high": 50.0,
        "low": 50.0, "close": 50.0, "volume": 0, "amount": 0.0,
    }
    _build_lake(tmp_path, bars=bars, status_rows=[])
    result = _load(tmp_path)
    row = _row(result, "605198", date(2026, 6, 12))
    assert row.trade_status is False
    assert row.is_st is None


def test_unknown_status_fails_closed(tmp_path):
    _build_lake(
        tmp_path,
        status_rows=[
            {"symbol": "000001.SZ", "trade_date": date(2026, 6, 11), "is_trading": True, "status": "halted"},
        ],
    )
    with pytest.raises(AslAdapterError, match="UNSUPPORTED_STATUS"):
        _load(tmp_path)


def test_unknown_status_with_missing_bar_still_blocks(tmp_path):
    """Review round 2: status vocabulary is validated BEFORE missing-bar
    interpretation, so an unknown status must raise even when the bar is
    absent and is_trading=False."""

    bars = {"600999.SZ": _bar_rows("600999.SZ", [date(2026, 6, 11)], "5.00")}
    _build_lake(
        tmp_path,
        bars=bars,
        instruments=[
            {"symbol": "600999.SZ", "list_date": None, "delist_date": None},
        ],
        status_rows=[
            {"symbol": "600999.SZ", "trade_date": date(2026, 6, 12), "is_trading": False, "status": "halted"},
        ],
    )
    with pytest.raises(AslAdapterError, match="UNSUPPORTED_STATUS:600999:2026-06-12"):
        _load(tmp_path, codes=["600999"])


def test_preclose_seed_previous_session_valid(tmp_path):
    _build_lake(tmp_path)
    result = load_asl_daily_slice(
        tmp_path,
        as_of=date(2026, 6, 15),
        start=date(2026, 6, 12),
    )
    row = _row(result, "000001", date(2026, 6, 12))
    assert row.row_status == "VALID_ROW"
    assert row.preclose == Decimal("11.3000")  # seeded from 6/11 close


def test_preclose_seed_earlier_valid_after_suspension(tmp_path):
    bars = {
        "600999.SZ": [
            {"trade_date": date(2026, 6, 11), "open": 9.00, "high": 9.10, "low": 8.95, "close": 9.00, "volume": 80000, "amount": 720000.0},
            {"trade_date": date(2026, 6, 15), "open": 9.10, "high": 9.25, "low": 9.05, "close": 9.20, "volume": 90000, "amount": 825000.0},
        ],
    }
    _build_lake(
        tmp_path,
        bars=bars,
        instruments=[
            {"symbol": "600999.SZ", "list_date": None, "delist_date": None},
        ],
        status_rows=[
            {"symbol": "600999.SZ", "trade_date": date(2026, 6, 12), "is_trading": False, "status": "suspended"},
        ],
    )
    result = load_asl_daily_slice(
        tmp_path,
        as_of=date(2026, 6, 15),
        start=date(2026, 6, 12),
        codes=["600999"],
    )
    row = _row(result, "600999", date(2026, 6, 15))
    assert row.preclose == Decimal("9.0000")  # earlier valid close, not guessed


def test_preclose_seed_multiple_session_gap(tmp_path):
    bars = {
        "600999.SZ": [
            {"trade_date": date(2026, 6, 11), "open": 9.00, "high": 9.10, "low": 8.95, "close": 9.00, "volume": 80000, "amount": 720000.0},
            {"trade_date": date(2026, 6, 17), "open": 9.50, "high": 9.60, "low": 9.40, "close": 9.50, "volume": 90000, "amount": 850000.0},
        ],
    }
    _build_lake(
        tmp_path,
        trading_days=[date(2026, 6, 11), date(2026, 6, 12), date(2026, 6, 15), date(2026, 6, 17)],
        bars=bars,
        instruments=[
            {"symbol": "600999.SZ", "list_date": None, "delist_date": None},
        ],
        status_rows=[
            {"symbol": "600999.SZ", "trade_date": date(2026, 6, 12), "is_trading": False, "status": "suspended"},
            {"symbol": "600999.SZ", "trade_date": date(2026, 6, 15), "is_trading": False, "status": "suspended"},
        ],
    )
    result = load_asl_daily_slice(
        tmp_path,
        as_of=date(2026, 6, 17),
        start=date(2026, 6, 12),
        codes=["600999"],
    )
    row = _row(result, "600999", date(2026, 6, 17))
    assert row.preclose == Decimal("9.0000")  # last valid close before the halt
    assert len(result.suspended_sessions) == 2


def test_preclose_no_predecessor_anywhere(tmp_path):
    bars = {
        "600999.SZ": [
            {"trade_date": date(2026, 6, 12), "open": 9.20, "high": 9.30, "low": 9.10, "close": 9.20, "volume": 80000, "amount": 730000.0},
            {"trade_date": date(2026, 6, 15), "open": 9.20, "high": 9.30, "low": 9.10, "close": 9.20, "volume": 80000, "amount": 730000.0},
        ],
    }
    _build_lake(
        tmp_path,
        bars=bars,
        instruments=[
            {"symbol": "600999.SZ", "list_date": None, "delist_date": None},
        ],
        status_rows=[],
    )
    result = load_asl_daily_slice(
        tmp_path,
        as_of=date(2026, 6, 15),
        start=date(2026, 6, 12),
        codes=["600999"],
    )
    first = _row(result, "600999", date(2026, 6, 12))
    assert first.row_status == "MISSING_PRECLOSE"
    assert first.preclose is None
    second = _row(result, "600999", date(2026, 6, 15))
    assert second.preclose == Decimal("9.2000")


def test_duplicate_daily_bars_pk_fails_closed(tmp_path):
    _build_lake(tmp_path)
    part = tmp_path / "curated" / "daily_bars" / "trade_date=2026-06-11"
    _write(
        part / "part-duplicate.parquet",
        [
            {
                "symbol": "000001.SZ", "trade_date": date(2026, 6, 11),
                "open": 11.3, "high": 11.4, "low": 11.2, "close": 11.3,
                "volume": 100000, "amount": 1129999.5, "source": "tdx_protocol",
                "data_version": "v2", "fetched_at": "2026-08-07T00:00:00Z",
            }
        ],
    )
    with pytest.raises(AslAdapterError, match="duplicate daily_bars PK: 000001 2026-06-11"):
        _load(tmp_path)


def test_duplicate_trading_status_pk_fails_closed(tmp_path):
    _build_lake(tmp_path)
    part = tmp_path / "curated" / "trading_status" / "trade_date=2026-06"
    _write(
        part / "part-duplicate.parquet",
        [
            {"symbol": "000010.SZ", "trade_date": date(2026, 6, 12), "is_trading": True, "status": "st"},
        ],
    )
    with pytest.raises(AslAdapterError, match="duplicate trading_status PK: 000010 2026-06-12"):
        _load(tmp_path)


def test_partition_pruning_out_of_range_not_read(tmp_path):
    _build_lake(tmp_path)
    # Valid predecessor bars for EVERY code far before the window: the
    # backward search resolves all codes here and stops, so older partitions
    # (including corrupt ones) are never opened.
    predecessor_bars = []
    for symbol in ("000001.SZ", "000010.SZ", "000524.SZ", "605198.SH", "300750.SZ"):
        predecessor_bars.append(
            {
                "symbol": symbol, "trade_date": date(2025, 1, 3),
                "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0,
                "volume": 1000, "amount": 10000.0, "source": "tdx_protocol",
                "data_version": "v2", "fetched_at": "2026-08-07T00:00:00Z",
            }
        )
    _write(
        tmp_path / "curated" / "daily_bars" / "trade_date=2025-01-03" / "part-merged.parquet",
        predecessor_bars,
    )
    # Corrupt files in partitions that must never be opened: the search stops
    # at 2025-01-03 (all codes resolved), the window reads stay in 2026-06,
    # so any read of these would raise and fail the test.
    out_of_range = [
        tmp_path / "curated" / "daily_bars" / "trade_date=2025-01-02" / "part-bad.parquet",
        tmp_path / "curated" / "trading_calendar" / "trade_date=2019" / "part-bad.parquet",
        tmp_path / "curated" / "trading_status" / "trade_date=2025-05" / "part-bad.parquet",
    ]
    for path in out_of_range:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"NOT A PARQUET FILE" * 100)
    result = _load(tmp_path)
    assert all(row.trade_date >= date(2026, 6, 11) for row in result.rows)
    assert all(row.trade_date != date(2025, 1, 3) for row in result.rows)
    # The far-back predecessor feeds the first window session's preclose.
    first = _row(result, "000001", date(2026, 6, 11))
    assert first.preclose == Decimal("10.0000")


def test_predecessor_far_beyond_400_days_still_found(tmp_path):
    """Review round 2: no day-count cutoff.  A predecessor more than 400
    calendar days before the window must still seed the chain."""

    bars = {
        "600999.SZ": [
            {"trade_date": date(2025, 1, 10), "open": 7.00, "high": 7.10, "low": 6.95, "close": 7.00, "volume": 50000, "amount": 350000.0},
            {"trade_date": date(2026, 6, 12), "open": 7.50, "high": 7.60, "low": 7.40, "close": 7.50, "volume": 60000, "amount": 450000.0},
            {"trade_date": date(2026, 6, 15), "open": 7.60, "high": 7.70, "low": 7.50, "close": 7.60, "volume": 60000, "amount": 456000.0},
        ],
    }
    _build_lake(
        tmp_path,
        bars=bars,
        instruments=[
            {"symbol": "600999.SZ", "list_date": None, "delist_date": None},
        ],
        status_rows=[],
    )
    result = load_asl_daily_slice(
        tmp_path,
        as_of=date(2026, 6, 15),
        start=date(2026, 6, 12),
        codes=["600999"],
    )
    row = _row(result, "600999", date(2026, 6, 12))
    assert row.row_status == "VALID_ROW"
    # 2025-01-10 is ~517 calendar days before 2026-06-12 and there is no bar
    # in between: the frozen contract still requires THIS close as preclose.
    assert row.preclose == Decimal("7.0000")


def test_turnover_rate_always_none(tmp_path):
    _build_lake(tmp_path)
    result = _load(tmp_path)
    assert result.rows
    for row in result.rows:
        assert row.turnover_rate is None


def test_fetched_at_parsed_timezone_aware(tmp_path):
    _build_lake(tmp_path)
    row = _row(_load(tmp_path), "000001", date(2026, 6, 11))
    assert isinstance(row.asl_fetched_at, datetime)
    assert row.asl_fetched_at.tzinfo is not None
    assert row.asl_fetched_at == datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)


def test_preclose_frozen_contract_sequential(tmp_path):
    _build_lake(tmp_path)
    result = _load(tmp_path)
    d11 = _row(result, "000001", date(2026, 6, 11))
    assert d11.preclose is None  # first emitted session: no predecessor in window
    d12 = _row(result, "000001", date(2026, 6, 12))
    assert d12.preclose == Decimal("11.3000")
    d15 = _row(result, "000001", date(2026, 6, 15))
    assert d15.preclose == Decimal("11.2400")


def test_corporate_action_preclose_not_adjusted(tmp_path):
    """Frozen ADR-008 rule: preclose is the previous close, never adjusted."""

    _build_lake(tmp_path)
    ex_div = _row(_load(tmp_path), "000001", date(2026, 6, 12))
    assert ex_div.preclose == Decimal("11.3000")  # previous close, NOT 11.24
    expected_pct = ((Decimal("11.24") - Decimal("11.30")) / Decimal("11.30") * 100).quantize(
        Decimal("0.0001")
    )
    assert ex_div.pct_change == expected_pct


def test_deterministic_output(tmp_path):
    _build_lake(tmp_path)
    first = _load(tmp_path)
    second = _load(tmp_path)
    assert first.rows == second.rows
    assert first.suspended_sessions == second.suspended_sessions
    assert first.missing_required_bars == second.missing_required_bars
    assert first.status_coverage == second.status_coverage


def test_no_future_rows_beyond_as_of(tmp_path):
    _build_lake(tmp_path)
    result = load_asl_daily_slice(
        tmp_path,
        as_of=date(2026, 6, 12),
        start=date(2026, 6, 11),
    )
    assert all(row.trade_date <= date(2026, 6, 12) for row in result.rows)
    assert all(row.trade_date != date(2026, 6, 15) for row in result.rows)


def test_api_shape_and_revision_contract(tmp_path):
    _build_lake(tmp_path)
    result = _load(tmp_path)
    assert result.contract_version == CONTRACT_VERSION
    assert result.tested_compat_revision == TESTED_COMPAT_REVISION
    assert result.as_of == date(2026, 6, 15)
    assert result.universe_prefixes == (
        "000", "001", "002", "003", "600", "601", "603", "605",
    )


def test_adapter_does_not_import_strategy_modules(tmp_path):
    """Importing the adapter must not pull in strategy modules (fresh process)."""

    import os
    import subprocess
    import sys

    src = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src)
    code = (
        "import sys;"
        "import limit_pullback.warehouse.asl_adapter;"
        "names=[m for m in sys.modules"
        " if m.startswith('limit_pullback.strategy')];"
        "print('STRATEGY_IMPORTS=' + ','.join(sorted(names)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "STRATEGY_IMPORTS="
