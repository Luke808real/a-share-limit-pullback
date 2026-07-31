from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from limit_pullback.models.enums import DataQuality
from limit_pullback.models.market import DailyBarsRequest, LimitUpPoolRequest
from limit_pullback.providers.akshare_limit_pool import (
    AkShareLimitUpPoolProvider,
)
from limit_pullback.providers.baostock_daily import BaoStockDailyBarProvider


FETCHED_AT = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)


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
    def __init__(self, query_result):
        self.query_result = query_result
        self.query_args = None
        self.logged_out = False

    def login(self):
        print("login success!")
        return FakeBaoResult((), ())

    def query_history_k_data_plus(self, *args, **kwargs):
        self.query_args = (args, kwargs)
        return self.query_result

    def logout(self):
        print("logout success!")
        self.logged_out = True


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
    fields = (
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
    client = FakeBaoClient(FakeBaoResult(fields, rows))
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
    assert capsys.readouterr().out == ""


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
