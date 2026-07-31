from __future__ import annotations

from datetime import date

import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.inspect import inspect_stock
from limit_pullback.providers import (
    AkShareLimitUpPoolProvider,
    BaoStockDailyBarProvider,
)
from limit_pullback.replay import replay_stock


pytestmark = pytest.mark.integration
REAL_CASES = (
    ("001382", date(2026, 7, 29)),
    ("002606", date(2026, 7, 29)),
    ("603123", date(2026, 7, 29)),
    ("603318", date(2026, 7, 30)),
    ("002640", date(2026, 7, 27)),
    ("600199", date(2026, 7, 28)),
    ("002891", date(2026, 7, 28)),
)


@pytest.mark.parametrize(("code", "as_of"), REAL_CASES)
def test_real_single_stock_inspect(code, as_of, project_root):
    output = inspect_stock(
        code=code,
        as_of=as_of,
        days=400,
        config=load_strategy_config(project_root / "config" / "strategy.yaml"),
        daily_provider=BaoStockDailyBarProvider(),
        limit_pool_provider=AkShareLimitUpPoolProvider(),
    )

    assert output.code == code
    assert output.as_of == as_of
    assert output.daily_data.record_count > 0
    assert output.signal.code == code
    assert output.signal.trade_date == as_of


@pytest.mark.parametrize(("code", "as_of"), REAL_CASES)
def test_real_single_stock_replay(code, as_of, project_root):
    output = replay_stock(
        code=code,
        start=None,
        as_of=as_of,
        lookback_calendar_days=400,
        config=load_strategy_config(project_root / "config" / "strategy.yaml"),
        daily_provider=BaoStockDailyBarProvider(),
        limit_pool_provider=AkShareLimitUpPoolProvider(),
    )

    assert output.code == code
    assert output.requested_as_of == as_of
    assert output.actual_last_bar_date <= as_of
    assert output.timeline[-1].trade_date == output.actual_last_bar_date
    assert output.daily_provider_version != "not-installed"
    assert output.limit_pool_provider_version != "not-installed"
