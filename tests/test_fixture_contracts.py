from __future__ import annotations

import csv
import socket
from datetime import date, datetime
from decimal import Decimal

import pytest

from limit_pullback.models.market import DailyBar, LimitUpRecord


def test_synthetic_daily_bar_fixture_uses_domain_models(project_root):
    fixture = project_root / "tests" / "fixtures" / "synthetic_bars.csv"
    with fixture.open(encoding="utf-8", newline="") as stream:
        rows = tuple(csv.DictReader(stream))

    bars = tuple(DailyBar.model_validate(row) for row in rows)
    assert len(bars) == 4
    assert bars[0].trade_date == date(2024, 1, 2)
    assert bars[0].close == Decimal("10.00")
    assert bars[0].fetched_at == datetime.fromisoformat(
        "2024-01-02T16:00:00+08:00"
    )


def test_synthetic_limit_pool_fixture_uses_domain_models(project_root):
    fixture = project_root / "tests" / "fixtures" / "synthetic_limit_pool.csv"
    with fixture.open(encoding="utf-8", newline="") as stream:
        rows = tuple(csv.DictReader(stream))

    records = tuple(LimitUpRecord.model_validate(row) for row in rows)
    assert len(records) == 1
    assert records[0].limit_price == Decimal("11.00")
    assert records[0].consecutive_count == 1


def test_socket_network_is_blocked_by_default():
    with pytest.raises(AssertionError, match="network access is forbidden"):
        socket.create_connection(("example.invalid", 80))
