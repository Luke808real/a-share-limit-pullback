"""Unit tests for the Phase-1A parity harness classifiers (offline)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "research" / "asl_phase1a")
)

from parity import classify_ma_window, last_n_bar_dates  # noqa: E402


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
