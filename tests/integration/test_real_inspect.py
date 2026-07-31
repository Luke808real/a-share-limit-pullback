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
AS_OF = date(2026, 7, 29)


@pytest.mark.parametrize("code", ("002606", "603123", "001382"))
def test_real_single_stock_inspect(code, project_root):
    output = inspect_stock(
        code=code,
        as_of=AS_OF,
        days=400,
        config=load_strategy_config(project_root / "config" / "strategy.yaml"),
        daily_provider=BaoStockDailyBarProvider(),
        limit_pool_provider=AkShareLimitUpPoolProvider(),
    )

    assert output.code == code
    assert output.as_of == AS_OF
    assert output.daily_data.record_count > 0
    assert output.signal.code == code
    assert output.signal.trade_date == AS_OF


@pytest.mark.parametrize("code", ("002606", "603123", "001382"))
def test_real_single_stock_replay(code, project_root):
    output = replay_stock(
        code=code,
        start=None,
        as_of=AS_OF,
        lookback_calendar_days=400,
        config=load_strategy_config(project_root / "config" / "strategy.yaml"),
        daily_provider=BaoStockDailyBarProvider(),
        limit_pool_provider=AkShareLimitUpPoolProvider(),
    )

    assert output.code == code
    assert output.requested_as_of == AS_OF
    assert output.actual_last_bar_date <= AS_OF
    assert output.timeline[-1].trade_date == output.actual_last_bar_date
    assert output.daily_provider_version != "not-installed"
    assert output.limit_pool_provider_version != "not-installed"
