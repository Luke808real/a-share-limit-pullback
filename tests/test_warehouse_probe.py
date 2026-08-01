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


def test_rate_limit_error_is_retried_with_backoff(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-token")
    calls = {"count": 0}

    def flaky_daily():
        calls["count"] += 1
        if calls["count"] < 3:
            raise Exception("抱歉，您每分钟最多访问该接口200次")
        return pd.DataFrame()

    client = FakeTushareClient({"daily": flaky_daily})
    provider = TushareProProvider(client_factory=lambda token: client)
    result = provider.probe_all()
    daily = next(
        item for item in result.capabilities if item.capability == "daily_bars"
    )
    assert daily.status == "AVAILABLE"
    assert calls["count"] == 3


def test_bulk_fetch_skips_malformed_rows(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-token")
    import pandas as pd

    good = pd.DataFrame(
        [
            {
                "ts_code": "603318.SH",
                "trade_date": "20260730",
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "pre_close": 0.95,
                "vol": 100.0,
                "amount": 100.0,
                "pct_chg": 5.0,
            }
        ]
    )
    bad = good.copy()
    bad["trade_date"] = "not-a-date"

    def frame():
        return pd.concat([bad, good], ignore_index=True)

    client = FakeTushareClient({"daily": frame})
    provider = TushareProProvider(client_factory=lambda token: client)
    rows = provider.fetch_daily_by_trade_date([date(2026, 7, 30)])
    assert len(rows) == 1
    assert rows[0]["code"] == "603318"
