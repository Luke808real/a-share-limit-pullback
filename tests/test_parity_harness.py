"""Unit tests for the Phase-1A parity harness classifiers (offline)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from decimal import Decimal

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "research" / "asl_phase1a")
)

import pytest  # noqa: E402

from parity import (  # noqa: E402
    _compare_code,
    classify_ma_window,
    classify_status,
    last_n_bar_dates,
    status_gate_issues,
)


def _session_days(count: int, start: date = date(2026, 6, 1)) -> list[date]:
    return [start + timedelta(days=index) for index in range(count)]


def test_last_n_bar_dates_basic():
    days = _session_days(10)
    assert last_n_bar_dates(days, days[7], 5) == tuple(days[3:8])
    assert last_n_bar_dates(days, days[7], 20) is None


def test_ma_window_clean_when_sequences_identical():
    days = _session_days(30)
    assert classify_ma_window(days, days, days[29], 20) == "CLEAN"


def test_ma_window_hole_affected_when_sequences_differ():
    legacy = _session_days(31)  # days 0..30 so the MA20 aging point exists
    adapter = [day for day in legacy if day != legacy[10]]
    assert classify_ma_window(legacy, adapter, legacy[14], 5) == "HOLE_AFFECTED_MA5"


def test_old_hole_ages_out_of_ma5_then_ma10_then_ma20():
    """A single legacy hole must stop contaminating MA5 first, then MA10,
    then MA20, as the hole exits each window."""

    legacy = _session_days(31)  # days 0..30 so the MA20 aging point exists
    adapter = [day for day in legacy if day != legacy[10]]  # hole at day 10
    hole = legacy[10]

    # MA5: hole at day 10 ages out when the last-5 window starts after day 10,
    # i.e. at as_of = day 15 (window days 11..15).
    assert classify_ma_window(legacy, adapter, hole + timedelta(days=4), 5) == "HOLE_AFFECTED_MA5"
    assert classify_ma_window(legacy, adapter, hole + timedelta(days=5), 5) == "CLEAN"

    # MA10: still affected at day 15; ages out at day 20 (window 11..20).
    assert classify_ma_window(legacy, adapter, hole + timedelta(days=5), 10) == "HOLE_AFFECTED_MA10"
    assert classify_ma_window(legacy, adapter, hole + timedelta(days=9), 10) == "HOLE_AFFECTED_MA10"
    assert classify_ma_window(legacy, adapter, hole + timedelta(days=10), 10) == "CLEAN"

    # MA20: still affected at day 20 and day 29; ages out at day 30 (window 11..30).
    assert classify_ma_window(legacy, adapter, hole + timedelta(days=10), 20) == "HOLE_AFFECTED_MA20"
    assert classify_ma_window(legacy, adapter, hole + timedelta(days=19), 20) == "HOLE_AFFECTED_MA20"
    assert classify_ma_window(legacy, adapter, hole + timedelta(days=20), 20) == "CLEAN"


def test_ma_window_insufficient_on_short_series():
    legacy = _session_days(3)
    adapter = _session_days(4)
    assert classify_ma_window(legacy, adapter, legacy[2], 5) == "INSUFFICIENT"


@pytest.mark.parametrize(
    ("legacy_is_st", "adapter_is_st", "expected"),
    [
        (None, None, "EXACT_STATUS_MATCH"),
        (None, True, "LEGACY_UNKNOWN_TO_ASL_TRUE"),
        (None, False, "LEGACY_UNKNOWN_TO_ASL_FALSE"),
        (True, True, "EXACT_STATUS_MATCH"),
        (False, False, "EXACT_STATUS_MATCH"),
        (True, False, "TRUE_STATUS_CONFLICT"),
        (False, True, "TRUE_STATUS_CONFLICT"),
        (True, None, "TRUE_STATUS_CONFLICT"),
        (False, None, "TRUE_STATUS_CONFLICT"),
    ],
)
def test_classify_status_all_combinations(
    legacy_is_st, adapter_is_st, expected
):
    assert classify_status(legacy_is_st, adapter_is_st) == expected


def test_status_gate_issues_unknown_to_known_non_fatal():
    category, issues = status_gate_issues(None, True, True, True)
    assert category == "LEGACY_UNKNOWN_TO_ASL_TRUE"
    assert issues == []


def _row_dict(code, day, close="10.00", preclose="9.90", is_st=None, trade_status=True):
    return {
        "code": code,
        "trade_date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "preclose": preclose,
        "volume": "1000",
        "amount": "10000.00",
        "pct_change": None,
        "trade_status": trade_status,
        "is_st": is_st,
    }


def _config():
    from limit_pullback.config import load_strategy_config

    return load_strategy_config(
        Path(__file__).resolve().parents[1] / "config" / "strategy.yaml"
    )


def _run_compare(legacy_is_st, adapter_is_st, legacy_trade=True, adapter_trade=True):
    day = date(2026, 6, 15)
    prev = date(2026, 6, 11)
    legacy_rows = [
        _row_dict("000001", prev, is_st=legacy_is_st, trade_status=legacy_trade),
        _row_dict("000001", day, is_st=legacy_is_st, trade_status=legacy_trade),
    ]
    adapter_rows = [
        _row_dict("000001", prev, is_st=adapter_is_st, trade_status=adapter_trade),
        _row_dict("000001", day, is_st=adapter_is_st, trade_status=adapter_trade),
    ]
    adapter_by_date = {row["trade_date"]: row for row in adapter_rows}
    hard_failures: list[str] = []
    _compare_code(
        "000001",
        legacy_rows,
        adapter_rows,
        adapter_by_date,
        _config(),
        day,
        set(),
        hard_failures,
    )
    return hard_failures


def test_trade_status_mismatch_is_hard_failure():
    """trade_status mismatch must produce a hard parity failure (BLOCKED)."""

    failures = _run_compare(None, None, legacy_trade=True, adapter_trade=False)
    assert any("TRADE_STATUS_CONFLICT" in failure for failure in failures)


def test_known_is_st_conflict_is_hard_failure():
    """Known legacy is_st mapped to a different known adapter value must
    produce a hard parity failure (BLOCKED)."""

    failures = _run_compare(True, False)
    assert any("TRUE_STATUS_CONFLICT" in failure for failure in failures)


def test_known_is_st_to_none_is_hard_failure():
    """Known legacy is_st mapped to adapter None must be a conflict."""

    failures = _run_compare(True, None)
    assert any("TRUE_STATUS_CONFLICT" in failure for failure in failures)
