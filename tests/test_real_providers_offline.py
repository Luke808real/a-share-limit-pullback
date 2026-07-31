from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import sys

import pytest

from limit_pullback.inspect import _missing_fields
from limit_pullback.models.enums import DataQuality
from limit_pullback.models.market import DailyBarsRequest, LimitUpPoolRequest
from limit_pullback.providers.akshare_limit_pool import (
    AkShareLimitUpPoolProvider,
)
from limit_pullback.providers.baostock_daily import BaoStockDailyBarProvider
from limit_pullback.providers.base import ProviderError


FETCHED_AT = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)
BAO_FIELDS = (
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "turn",
    "tradestatus",
    "pctChg",
    "isST",
)


def _bao_row(
    trade_date,
    *,
    open_price="8.80",
    high="9.10",
    low="8.70",
    close="9.00",
    preclose="8.80",
    volume="123456",
    amount="1111111.23",
    trade_status="1",
):
    return (
        trade_date,
        "sz.002606",
        open_price,
        high,
        low,
        close,
        preclose,
        volume,
        amount,
        "2.50",
        trade_status,
        "2.2727",
        "0",
    )


class FakeBaoResult:
    def __init__(self, fields, rows, error_code="0", error_msg="success"):
        self.fields = fields
        self._rows = iter(rows)
        self._current = None
        self.error_code = error_code
        self.error_msg = error_msg

    def next(self):
        try:
            self._current = next(self._rows)
        except StopIteration:
            return False
        return True

    def get_row_data(self):
        return self._current


class FakeBaoClient:
    def __init__(
        self,
        query_result,
        *,
        login_result=None,
        logout_result=None,
        login_error=None,
        query_error=None,
        logout_error=None,
    ):
        self.query_result = query_result
        self.login_result = login_result
        self.logout_result = logout_result
        self.login_error = login_error
        self.query_error = query_error
        self.logout_error = logout_error
        self.query_args = None
        self.logged_out = False
        self.login_calls = 0
        self.query_calls = 0
        self.logout_calls = 0

    def login(self):
        self.login_calls += 1
        print("login success!")
        print("login diagnostics", file=sys.stderr)
        if self.login_error is not None:
            raise self.login_error
        return self.login_result or FakeBaoResult((), ())

    def query_history_k_data_plus(self, *args, **kwargs):
        self.query_calls += 1
        self.query_args = (args, kwargs)
        if self.query_error is not None:
            raise self.query_error
        return self.query_result

    def logout(self):
        self.logout_calls += 1
        print("logout success!")
        print("logout diagnostics", file=sys.stderr)
        self.logged_out = True
        if self.logout_error is not None:
            raise self.logout_error
        return self.logout_result


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return self.rows


class FakeAkClient:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.requested_date = None

    def stock_zt_pool_em(self, *, date):
        self.requested_date = date
        if self.error is not None:
            raise self.error
        return FakeFrame(self.rows)


def test_baostock_maps_raw_daily_fields_and_skips_non_trading_rows(capsys):
    rows = (
        (
            "2026-07-28",
            "sz.002606",
            "",
            "",
            "",
            "",
            "8.80",
            "0",
            "0",
            "",
            "0",
            "",
            "0",
        ),
        (
            "2026-07-29",
            "sz.002606",
            "8.80",
            "9.10",
            "8.70",
            "9.00",
            "8.80",
            "123456",
            "1111111.23",
            "2.50",
            "1",
            "2.2727",
            "0",
        ),
    )
    client = FakeBaoClient(FakeBaoResult(BAO_FIELDS, rows))
    provider = BaoStockDailyBarProvider(
        client=client,
        clock=lambda: FETCHED_AT,
    )

    result = provider.fetch_daily_bars(
        DailyBarsRequest(
            codes=("002606",),
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 29),
        )
    )

    assert len(result.bars) == 1
    bar = result.bars[0]
    assert bar.close == Decimal("9.00")
    assert bar.preclose == Decimal("8.80")
    assert bar.trade_status is True
    assert bar.is_st is False
    assert bar.source == "BAOSTOCK"
    assert result.quality is DataQuality.PARTIAL
    assert result.quality_flags == (
        "NON_TRADING_BAR_SKIPPED:002606:2026-07-28",
    )
    assert client.query_args[1]["adjustflag"] == "3"
    assert client.logged_out
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_baostock_identical_duplicates_are_deduped_and_sorted():
    row_28 = _bao_row("2026-07-28", close="8.80", preclose="8.70")
    row_29 = _bao_row("2026-07-29")
    client = FakeBaoClient(
        FakeBaoResult(BAO_FIELDS, (row_29, row_28, row_29))
    )
    provider = BaoStockDailyBarProvider(
        client=client,
        clock=lambda: FETCHED_AT,
    )

    result = provider.fetch_daily_bars(
        DailyBarsRequest(
            codes=("002606",),
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 29),
        )
    )

    assert tuple(bar.trade_date for bar in result.bars) == (
        date(2026, 7, 28),
        date(2026, 7, 29),
    )
    assert result.quality is DataQuality.PARTIAL
    assert result.quality_flags == (
        "DUPLICATE_DAILY_ROW_DEDUPED:002606:2026-07-29",
    )


def test_baostock_conflicting_duplicate_raises_stable_provider_error():
    first = _bao_row("2026-07-29")
    conflicting = _bao_row("2026-07-29", close="9.05")
    provider = BaoStockDailyBarProvider(
        client=FakeBaoClient(
            FakeBaoResult(BAO_FIELDS, (first, conflicting))
        ),
        clock=lambda: FETCHED_AT,
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.fetch_daily_bars(
            DailyBarsRequest(
                codes=("002606",),
                start_date=date(2026, 7, 29),
                end_date=date(2026, 7, 29),
            )
        )

    assert str(exc_info.value) == (
        "CONFLICTING_DUPLICATE_DAILY_ROW:002606:2026-07-29"
    )
    assert "object at 0x" not in str(exc_info.value)


def test_baostock_malformed_required_fields_are_named_and_aggregated():
    malformed = _bao_row(
        "2026-07-28",
        open_price="",
        amount="",
    )
    valid = _bao_row("2026-07-29")
    provider = BaoStockDailyBarProvider(
        client=FakeBaoClient(
            FakeBaoResult(BAO_FIELDS, (malformed, valid))
        ),
        clock=lambda: FETCHED_AT,
    )

    result = provider.fetch_daily_bars(
        DailyBarsRequest(
            codes=("002606",),
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 29),
        )
    )

    assert result.quality is DataQuality.DEGRADED
    assert (
        "MALFORMED_DAILY_ROW:002606:2026-07-28:open,amount"
        in result.quality_flags
    )
    assert _missing_fields(result.quality_flags) == ("amount", "open")


def test_baostock_missing_trade_status_is_malformed_not_non_trading():
    malformed = _bao_row("2026-07-28", trade_status="")
    valid = _bao_row("2026-07-29")
    provider = BaoStockDailyBarProvider(
        client=FakeBaoClient(
            FakeBaoResult(BAO_FIELDS, (malformed, valid))
        ),
        clock=lambda: FETCHED_AT,
    )

    result = provider.fetch_daily_bars(
        DailyBarsRequest(
            codes=("002606",),
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 29),
        )
    )

    assert result.quality is DataQuality.DEGRADED
    assert (
        "MALFORMED_DAILY_ROW:002606:2026-07-28:trade_status"
        in result.quality_flags
    )
    assert not any(
        flag.startswith("NON_TRADING_BAR_SKIPPED:002606:2026-07-28")
        for flag in result.quality_flags
    )
    assert _missing_fields(result.quality_flags) == ("trade_status",)


def test_baostock_missing_date_is_reported_as_a_field():
    missing_date = _bao_row("")
    valid = _bao_row("2026-07-29")
    provider = BaoStockDailyBarProvider(
        client=FakeBaoClient(
            FakeBaoResult(BAO_FIELDS, (missing_date, valid))
        ),
        clock=lambda: FETCHED_AT,
    )

    result = provider.fetch_daily_bars(
        DailyBarsRequest(
            codes=("002606",),
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 29),
        )
    )

    assert result.quality is DataQuality.DEGRADED
    assert (
        "MALFORMED_DAILY_ROW:002606:UNKNOWN:date"
        in result.quality_flags
    )
    assert _missing_fields(result.quality_flags) == ("date",)


def _daily_request():
    return DailyBarsRequest(
        codes=("002606",),
        start_date=date(2026, 7, 29),
        end_date=date(2026, 7, 29),
    )


def test_baostock_login_failure_preserves_original_error_without_logout():
    original = ProviderError("original login failure")
    client = FakeBaoClient(
        FakeBaoResult(BAO_FIELDS, ()),
        login_error=original,
    )

    with pytest.raises(ProviderError) as exc_info:
        BaoStockDailyBarProvider(
            client=client,
            clock=lambda: FETCHED_AT,
        ).fetch_daily_bars(_daily_request())

    assert exc_info.value is original
    assert client.logout_calls == 0


def test_baostock_query_failure_still_attempts_logout():
    client = FakeBaoClient(
        FakeBaoResult(
            BAO_FIELDS,
            (),
            error_code="100",
            error_msg="query unavailable",
        )
    )

    with pytest.raises(
        ProviderError,
        match="BaoStock daily query for 002606 failed: query unavailable",
    ):
        BaoStockDailyBarProvider(
            client=client,
            clock=lambda: FETCHED_AT,
        ).fetch_daily_bars(_daily_request())

    assert client.logout_calls == 1


def test_baostock_logout_failure_does_not_mask_query_failure():
    client = FakeBaoClient(
        FakeBaoResult(
            BAO_FIELDS,
            (),
            error_code="100",
            error_msg="query unavailable",
        ),
        logout_result=FakeBaoResult(
            (),
            (),
            error_code="200",
            error_msg="logout unavailable",
        ),
    )

    with pytest.raises(ProviderError) as exc_info:
        BaoStockDailyBarProvider(
            client=client,
            clock=lambda: FETCHED_AT,
        ).fetch_daily_bars(_daily_request())

    assert str(exc_info.value) == (
        "BaoStock daily query for 002606 failed: query unavailable"
    )
    assert any(
        "BaoStock logout failed: logout unavailable" in note
        for note in (exc_info.value.__notes__ or ())
    )


def test_baostock_successful_query_surfaces_logout_failure():
    client = FakeBaoClient(
        FakeBaoResult(BAO_FIELDS, (_bao_row("2026-07-29"),)),
        logout_result=FakeBaoResult(
            (),
            (),
            error_code="200",
            error_msg="logout unavailable",
        ),
    )

    with pytest.raises(
        ProviderError,
        match="BaoStock logout failed: logout unavailable",
    ):
        BaoStockDailyBarProvider(
            client=client,
            clock=lambda: FETCHED_AT,
        ).fetch_daily_bars(_daily_request())


def test_akshare_maps_pool_fields_without_dataframe_leakage():
    client = FakeAkClient(
        [
            {
                "代码": "002606",
                "名称": "大连电瓷",
                "最新价": "9.68",
                "首次封板时间": 93105,
                "最后封板时间": "14:25:00",
                "炸板次数": "2",
                "连板数": "1",
                "换手率": "8.75",
                "流通市值": "3210000000",
                "总市值": "4560000000",
                "所属行业": "电网设备",
            },
            {
                "代码": "603123",
                "名称": "非请求股票",
                "最新价": "10.00",
            },
        ]
    )
    provider = AkShareLimitUpPoolProvider(
        client=client,
        clock=lambda: FETCHED_AT,
    )

    result = provider.fetch_limit_up_pool(
        LimitUpPoolRequest(
            trade_date=date(2026, 7, 29),
            codes=("002606",),
        )
    )

    assert client.requested_date == "20260729"
    assert result.quality is DataQuality.OK
    assert len(result.records) == 1
    record = result.records[0]
    assert record.code == "002606"
    assert record.first_seal_time.isoformat() == "09:31:05"
    assert record.last_seal_time.isoformat() == "14:25:00"
    assert record.open_count == 2
    assert record.consecutive_count == 1
    assert record.turnover_rate == Decimal("8.75")
    assert record.industry == "电网设备"


def test_akshare_missing_optional_fields_stay_null_and_are_flagged():
    provider = AkShareLimitUpPoolProvider(
        client=FakeAkClient(
            [{"代码": "002606", "名称": "大连电瓷", "最新价": "9.68"}]
        ),
        clock=lambda: FETCHED_AT,
    )

    result = provider.fetch_limit_up_pool(
        LimitUpPoolRequest(
            trade_date=date(2026, 7, 29),
            codes=("002606",),
        )
    )

    assert result.quality is DataQuality.PARTIAL
    assert result.records[0].first_seal_time is None
    assert result.records[0].consecutive_count is None
    assert "MISSING_LIMIT_FIELD:002606:first_seal_time" in result.quality_flags
    assert "MISSING_LIMIT_FIELD:002606:consecutive_count" in result.quality_flags


def test_akshare_unavailable_returns_price_only_compatible_empty_result():
    provider = AkShareLimitUpPoolProvider(
        client=FakeAkClient(error=RuntimeError("upstream unavailable")),
        clock=lambda: FETCHED_AT,
    )

    result = provider.fetch_limit_up_pool(
        LimitUpPoolRequest(
            trade_date=date(2026, 7, 29),
            codes=("002606",),
        )
    )

    assert result.records == ()
    assert result.quality is DataQuality.PARTIAL
    assert result.quality_flags[0].startswith(
        "LIMIT_POOL_UNAVAILABLE:RuntimeError:"
    )
