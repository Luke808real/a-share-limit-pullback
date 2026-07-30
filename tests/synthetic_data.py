from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from limit_pullback.models.market import DailyBar, LimitUpRecord


TZ_SHANGHAI = timezone(timedelta(hours=8))


def business_dates(start: date, count: int) -> tuple[date, ...]:
    output: list[date] = []
    current = start
    while len(output) < count:
        if current.weekday() < 5:
            output.append(current)
        current += timedelta(days=1)
    return tuple(output)


def make_bar(
    trade_date: date,
    *,
    code: str = "600000",
    open_price: str,
    high: str,
    low: str,
    close: str,
    preclose: str,
    volume: str,
) -> DailyBar:
    close_value = Decimal(close)
    volume_value = Decimal(volume)
    return DailyBar(
        trade_date=trade_date,
        code=code,
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=close_value,
        preclose=Decimal(preclose),
        volume=volume_value,
        amount=volume_value * close_value,
        turnover_rate=Decimal("0.03"),
        pct_change=(close_value / Decimal(preclose) - Decimal("1")) * Decimal("100"),
        source="SYNTHETIC",
        fetched_at=datetime.combine(
            trade_date,
            time(16, 0),
            tzinfo=TZ_SHANGHAI,
        ),
    )


def base_setup_bars(
    *,
    include_left_pressure: bool = True,
    code: str = "600000",
) -> list[DailyBar]:
    dates = business_dates(date(2023, 1, 2), 131)
    bars: list[DailyBar] = []
    previous_close = Decimal("10.00")
    for index, trade_date in enumerate(dates[:-1]):
        close = Decimal("10.00")
        high = Decimal("10.10")
        low = Decimal("9.90")
        open_price = Decimal("10.00")
        if include_left_pressure and index == 80:
            open_price = Decimal("11.80")
            high = Decimal("12.20")
            low = Decimal("11.70")
            close = Decimal("12.00")
        bars.append(
            make_bar(
                trade_date,
                code=code,
                open_price=str(open_price),
                high=str(high),
                low=str(low),
                close=str(close),
                preclose=str(previous_close),
                volume="500",
            )
        )
        previous_close = close

    anchor_date = dates[-1]
    bars.append(
        make_bar(
            anchor_date,
            code=code,
            open_price="9.95",
            high="11.00",
            low="9.90",
            close="11.00",
            preclose="10.00",
            volume="1000",
        )
    )
    return bars


def append_pullback_bars(bars: list[DailyBar]) -> list[DailyBar]:
    dates = business_dates(bars[-1].trade_date + timedelta(days=1), 3)
    specs = (
        ("11.05", "11.12", "10.90", "11.00", "11.00", "800"),
        ("10.98", "11.06", "10.84", "10.96", "11.00", "400"),
        ("10.94", "11.02", "10.82", "10.98", "10.96", "300"),
    )
    for trade_date, spec in zip(dates, specs, strict=True):
        open_price, high, low, close, preclose, volume = spec
        bars.append(
            make_bar(
                trade_date,
                open_price=open_price,
                high=high,
                low=low,
                close=close,
                preclose=preclose,
                volume=volume,
            )
        )
    return bars


def append_b2_ready_bar(bars: list[DailyBar]) -> list[DailyBar]:
    trade_date = business_dates(bars[-1].trade_date + timedelta(days=1), 1)[0]
    bars.append(
        make_bar(
            trade_date,
            open_price="10.97",
            high="11.01",
            low="10.90",
            close="10.99",
            preclose="10.98",
            volume="280",
        )
    )
    return bars


def append_b2_confirm_bar(bars: list[DailyBar]) -> list[DailyBar]:
    trade_date = business_dates(bars[-1].trade_date + timedelta(days=1), 1)[0]
    bars.append(
        make_bar(
            trade_date,
            open_price="11.05",
            high="11.35",
            low="10.95",
            close="11.25",
            preclose="10.99",
            volume="500",
        )
    )
    return bars


def append_s2_bar(bars: list[DailyBar]) -> list[DailyBar]:
    trade_date = business_dates(bars[-1].trade_date + timedelta(days=1), 1)[0]
    bars.append(
        make_bar(
            trade_date,
            open_price="11.40",
            high="11.65",
            low="11.05",
            close="11.10",
            preclose="11.25",
            volume="1200",
        )
    )
    return bars


def append_invalid_bar(bars: list[DailyBar]) -> list[DailyBar]:
    trade_date = business_dates(bars[-1].trade_date + timedelta(days=1), 1)[0]
    bars.append(
        make_bar(
            trade_date,
            open_price="10.90",
            high="10.92",
            low="10.30",
            close="10.40",
            preclose="10.98",
            volume="1500",
        )
    )
    return bars


def append_open_space_pullback(bars: list[DailyBar]) -> list[DailyBar]:
    dates = business_dates(bars[-1].trade_date + timedelta(days=1), 3)
    specs = (
        ("11.02", "11.08", "10.92", "11.00", "11.00", "800"),
        ("10.98", "11.04", "10.88", "10.96", "11.00", "400"),
        ("10.95", "11.20", "10.85", "11.20", "10.96", "300"),
    )
    for trade_date, spec in zip(dates, specs, strict=True):
        open_price, high, low, close, preclose, volume = spec
        bars.append(
            make_bar(
                trade_date,
                open_price=open_price,
                high=high,
                low=low,
                close=close,
                preclose=preclose,
                volume=volume,
            )
        )
    return bars


def full_limit_pool(bars: list[DailyBar]) -> tuple[LimitUpRecord, ...]:
    anchor = bars[130]
    records = []
    for code, name in (
        ("600000", "合成股份"),
        ("600001", "合成同行一"),
        ("600002", "合成同行二"),
    ):
        records.append(
            LimitUpRecord(
                trade_date=anchor.trade_date,
                code=code,
                name=name,
                limit_price=Decimal("11.00"),
                first_seal_time=time(10, 15),
                last_seal_time=time(14, 10),
                open_count=1,
                consecutive_count=1,
                turnover_rate=Decimal("0.05"),
                float_market_cap=Decimal("1000000000"),
                total_market_cap=Decimal("2000000000"),
                industry="合成行业",
                source="SYNTHETIC",
                fetched_at=datetime.combine(
                    anchor.trade_date,
                    time(16, 5),
                    tzinfo=TZ_SHANGHAI,
                ),
            )
        )
    return tuple(records)
