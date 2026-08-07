"""Phase-1A unit tests for the read-only ASL adapter (offline, synthetic)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from limit_pullback.warehouse.asl_adapter import (
    ASL_REVISION_PIN,
    CONTRACT_VERSION,
    AslDailySlice,
    load_asl_daily_slice,
)


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)


def _build_lake(
    root: Path,
    *,
    with_status: bool = True,
    bars: dict[str, list[dict]] | None = None,
    versions: dict[str, str] | None = None,
) -> None:
    """Synthetic ASL lake.

    Calendar: 2026-06-11 (Thu), 2026-06-12 (Fri), 2026-06-15 (Mon) all trade.
    Default bars per symbol: 000001, 000010, 000524, 605198 + 300750
    (outside the frozen universe, must be excluded).
    """

    _write(
        root / "curated" / "instruments" / "part-merged.parquet",
        [
            {"symbol": "000001.SZ"},
            {"symbol": "000010.SZ"},
            {"symbol": "000524.SZ"},
            {"symbol": "300750.SZ"},
            {"symbol": "605198.SH"},
        ],
    )
    _write(
        root / "curated" / "trading_calendar" / "part-merged.parquet",
        [
            {"trade_date": date(2026, 6, 11), "is_trading": True},
            {"trade_date": date(2026, 6, 12), "is_trading": True},
            {"trade_date": date(2026, 6, 13), "is_trading": False},
            {"trade_date": date(2026, 6, 14), "is_trading": False},
            {"trade_date": date(2026, 6, 15), "is_trading": True},
        ],
    )

    default_bars: dict[str, list[dict]] = {
        "000001.SZ": [
            {"trade_date": date(2026, 6, 11), "open": 11.30, "high": 11.40, "low": 11.20, "close": 11.30, "volume": 100000, "amount": 1129999.5},
            # ex-dividend session: the exchange reference price moves, the
            # frozen ADR-008 rule does NOT adjust preclose.
            {"trade_date": date(2026, 6, 12), "open": 11.00, "high": 11.25, "low": 10.88, "close": 11.24, "volume": 200000, "amount": 2222222.25},
            {"trade_date": date(2026, 6, 15), "open": 11.21, "high": 11.21, "low": 10.98, "close": 11.06, "volume": 150000, "amount": 1650000.0},
        ],
        "000010.SZ": [
            {"trade_date": date(2026, 6, 11), "open": 2.00, "high": 2.01, "low": 1.99, "close": 2.00, "volume": 50000, "amount": 100000.0},
            {"trade_date": date(2026, 6, 12), "open": 2.00, "high": 2.06, "low": 2.00, "close": 2.05, "volume": 60000, "amount": 122000.0},
            {"trade_date": date(2026, 6, 15), "open": 2.05, "high": 2.10, "low": 2.04, "close": 2.10, "volume": 70000, "amount": 145000.0},
        ],
        # 000524 has no bar on 6/12 (suspension gap): the chain must carry the
        # 6/11 close forward to 6/15.
        "000524.SZ": [
            {"trade_date": date(2026, 6, 11), "open": 9.00, "high": 9.10, "low": 8.95, "close": 9.00, "volume": 80000, "amount": 720000.0},
            {"trade_date": date(2026, 6, 15), "open": 9.10, "high": 9.25, "low": 9.05, "close": 9.20, "volume": 90000, "amount": 825000.0},
        ],
        "605198.SH": [
            {"trade_date": date(2026, 6, 12), "open": 50.00, "high": 50.50, "low": 49.80, "close": 50.20, "volume": 30000, "amount": 1500000.0},
        ],
        "300750.SZ": [
            {"trade_date": date(2026, 6, 11), "open": 200.0, "high": 205.0, "low": 199.0, "close": 204.0, "volume": 1000000, "amount": 2.03e8},
        ],
    }
    if bars is not None:
        default_bars.update(bars)
    versions = versions or {}
    by_date: dict[date, list[dict]] = {}
    for symbol, rows in default_bars.items():
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

    if with_status:
        _write(
            root / "curated" / "trading_status" / "trade_date=2026-06" / "part-merged.parquet",
            [
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
    result = _load(tmp_path)
    bad = [row for row in result.rows if row.code == "000001"]
    assert bad
    assert all(row.row_status == "UNSUPPORTED_SEMANTICS" for row in bad)
    assert "data_version" in bad[0].reason


def test_missing_status_dataset_fails_closed(tmp_path):
    _build_lake(tmp_path, with_status=False)
    result = _load(tmp_path)
    assert result.status_coverage.mode == "FAIL_CLOSED"
    assert all(row.trade_status is None for row in result.rows)
    assert all(row.is_st is None for row in result.rows)
    assert all(row.row_status == "MISSING_STATUS" for row in result.rows)


def test_missing_amount_behavior(tmp_path):
    _build_lake(
        tmp_path,
        bars={
            "605198.SH": [
                {"trade_date": date(2026, 6, 11), "open": 49.9, "high": 50.1, "low": 49.8, "close": 50.0, "volume": 20000, "amount": 1000000.0},
                {"trade_date": date(2026, 6, 12), "open": 50.0, "high": 50.5, "low": 49.8, "close": 50.2, "volume": 30000, "amount": None},
            ]
        },
    )
    result = _load(tmp_path)
    row = _row(result, "605198", date(2026, 6, 12))
    assert row.row_status == "MISSING_REQUIRED_AMOUNT"
    assert row.amount is None
    assert row.preclose == Decimal("50.0000")


def test_st_mapping(tmp_path):
    _build_lake(tmp_path)
    result = _load(tmp_path)
    st = _row(result, "000010", date(2026, 6, 12))
    assert st.is_st is True
    assert st.trade_status is True
    star_st = _row(result, "000010", date(2026, 6, 15))
    assert star_st.is_st is True
    normal = _row(result, "000001", date(2026, 6, 12))
    assert normal.is_st is False
    assert normal.trade_status is True
    assert result.status_coverage.mode == "ASL_MISSING_ROW_NORMAL_CONVENTION"


def test_suspension_mapping(tmp_path):
    _build_lake(tmp_path)
    result = _load(tmp_path)
    assert (("000524", date(2026, 6, 12))) in result.suspended_sessions
    # No bar row is emitted for the suspended session (ASL has no bar).
    assert all(
        not (row.code == "000524" and row.trade_date == date(2026, 6, 12))
        for row in result.rows
    )
    gap = _row(result, "000524", date(2026, 6, 15))
    assert gap.preclose == Decimal("9.0000")  # chain carried over the gap


def test_turnover_stays_null_by_design(tmp_path):
    _build_lake(tmp_path)
    for row in _load(tmp_path).rows:
        assert getattr(row, "turnover_rate", None) is None
        assert not hasattr(row, "turnover_rate")


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


def test_missing_preclose_first_row(tmp_path):
    _build_lake(tmp_path)
    result = load_asl_daily_slice(
        tmp_path,
        as_of=date(2026, 6, 15),
        start=date(2026, 6, 12),
    )
    row = _row(result, "605198", date(2026, 6, 12))
    assert row.row_status == "MISSING_PRECLOSE"
    assert row.preclose is None
    assert row.pct_change is None


def test_seed_prior_session_feeds_first_emitted_row(tmp_path):
    _build_lake(tmp_path)
    result = load_asl_daily_slice(
        tmp_path,
        as_of=date(2026, 6, 15),
        start=date(2026, 6, 12),
    )
    row = _row(result, "000001", date(2026, 6, 12))
    assert row.row_status == "VALID_ROW"
    assert row.preclose == Decimal("11.3000")  # seeded from 2026-06-11 close
    assert all(
        r.trade_date >= date(2026, 6, 12) for r in result.rows
    )


def test_deterministic_output(tmp_path):
    _build_lake(tmp_path)
    first = _load(tmp_path)
    second = _load(tmp_path)
    assert first.rows == second.rows
    assert first.suspended_sessions == second.suspended_sessions
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


def test_api_shape_and_revision_pin(tmp_path):
    _build_lake(tmp_path)
    result = _load(tmp_path)
    assert result.contract_version == CONTRACT_VERSION
    assert result.asl_revision == ASL_REVISION_PIN
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
