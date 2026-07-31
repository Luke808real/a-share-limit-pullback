from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from limit_pullback.warehouse.auth import TushareTokenError
from limit_pullback.warehouse.tushare_provider import TushareProProvider


class FakeTushareClient:
    def __init__(self, behavior):
        self.behavior = behavior

    def _apply(self, method):
        if method in self.behavior:
            return self.behavior[method]()
        return pd.DataFrame()

    def trade_cal(self, **kwargs):
        return self._apply("trade_cal")

    def stock_basic(self, **kwargs):
        return self._apply("stock_basic")

    def daily(self, **kwargs):
        return self._apply("daily")

    def adj_factor(self, **kwargs):
        return self._apply("adj_factor")

    def daily_basic(self, **kwargs):
        return self._apply("daily_basic")

    def suspend_d(self, **kwargs):
        return self._apply("suspend_d")

    def stk_limit(self, **kwargs):
        return self._apply("stk_limit")


def _provider(behavior, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-token")
    return TushareProProvider(
        client_factory=lambda token: FakeTushareClient(behavior)
    )


def test_probe_available_when_empty_dataframes(monkeypatch):
    provider = _provider({}, monkeypatch)
    result = provider.probe_all()
    assert result.overall == "AVAILABLE"
    assert all(item.status == "AVAILABLE" for item in result.capabilities)
    assert len(result.capabilities) == 7


def test_probe_permission_is_not_empty_data(monkeypatch):
    def denied():
        raise Exception("抱歉，您没有访问该接口的权限")

    provider = _provider({"daily": denied}, monkeypatch)
    result = provider.probe_all()
    daily = next(item for item in result.capabilities if item.capability == "daily_bars")
    assert daily.status == "UNAVAILABLE_PERMISSION"
    assert daily.error_code == "PERMISSION_DENIED"


def test_probe_provider_error(monkeypatch):
    def broken():
        raise ConnectionError("upstream timeout")

    provider = _provider({"trade_cal": broken}, monkeypatch)
    result = provider.probe_all()
    calendar = next(
        item for item in result.capabilities if item.capability == "trade_calendar"
    )
    assert calendar.status == "UNAVAILABLE_PROVIDER"
    assert calendar.error_code == "ConnectionError"


def test_probe_malformed_response(monkeypatch):
    provider = _provider({"daily_basic": lambda: {"not": "a frame"}}, monkeypatch)
    result = provider.probe_all()
    daily_basic = next(
        item for item in result.capabilities if item.capability == "daily_basic"
    )
    assert daily_basic.status == "MALFORMED_RESPONSE"
    assert daily_basic.error_code == "NOT_DATAFRAME"


def test_probe_without_token_raises_structured_error(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    provider = TushareProProvider()
    with pytest.raises(TushareTokenError):
        provider.probe_all()


def test_probe_error_message_never_contains_token(capsys, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "super-secret-token")

    def denied():
        raise Exception("denied for super-secret-token reason")

    provider = TushareProProvider(
        client_factory=lambda token: FakeTushareClient({"daily": denied})
    )
    result = provider.probe_all()
    daily = next(item for item in result.capabilities if item.capability == "daily_bars")
    assert "super-secret-token" not in (daily.detail or "")
    output = capsys.readouterr()
    assert "super-secret-token" not in output.out + output.err
