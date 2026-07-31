"""Shared fakes for offline warehouse tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Mapping

from limit_pullback.warehouse.models import ProbeCapability, ProbeResult


def daily_row(
    code: str,
    trade_date: str,
    *,
    open_price: str = "10.00",
    high: str = "10.50",
    low: str = "9.80",
    close: str = "10.20",
    preclose: str = "10.00",
    volume: str = "100000",
    amount: str = "1020000",
    turnover: str | None = "2.50",
    pct: str | None = "2.00",
) -> dict[str, Any]:
    return {
        "code": code,
        "trade_date": date.fromisoformat(trade_date),
        "open": Decimal(open_price),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "preclose": Decimal(preclose),
        "volume": Decimal(volume),
        "amount": Decimal(amount),
        "turnover_rate": Decimal(turnover) if turnover is not None else None,
        "pct_change": Decimal(pct) if pct is not None else None,
        "trade_status": True,
        "is_st": None,
    }


class FakeProviderSet:
    """In-memory provider set returning prebuilt normalized rows."""

    def __init__(
        self,
        *,
        calendar: list[date],
        tushare_daily: list[dict[str, Any]] | None = None,
        akshare_daily: list[dict[str, Any]] | None = None,
        baostock_daily: list[dict[str, Any]] | None = None,
        daily_basic: list[dict[str, Any]] | None = None,
        adj_factor: list[dict[str, Any]] | None = None,
        suspension: list[dict[str, Any]] | None = None,
        price_limits: list[dict[str, Any]] | None = None,
        stock_basic: list[dict[str, Any]] | None = None,
        pool: list[dict[str, Any]] | None = None,
        probe_result: ProbeResult | None = None,
    ) -> None:
        self.calendar = list(calendar)
        self.tushare_daily = list(tushare_daily or [])
        self.akshare_daily = list(akshare_daily or [])
        self.baostock_daily = list(baostock_daily or [])
        self.daily_basic = list(daily_basic or [])
        self.adj_factor = list(adj_factor or [])
        self.suspension = list(suspension or [])
        self.price_limits = list(price_limits or [])
        self.stock_basic = list(stock_basic or [])
        self.pool = list(pool or [])
        self.probe_result = probe_result or ProbeResult(
            provider="TUSHARE",
            provider_version="1.0",
            capabilities=tuple(
                ProbeCapability(capability=capability, status="AVAILABLE")
                for capability in (
                    "trade_calendar",
                    "stock_basic",
                    "daily_bars",
                    "adjustment_factor",
                    "daily_basic",
                    "suspension",
                    "price_limits",
                )
            ),
            overall="AVAILABLE",
        )

    def provider_versions(self) -> dict[str, str]:
        return {"TUSHARE": "1.0", "AKSHARE": "1.0", "BAOSTOCK": "1.0"}

    def probe(self) -> ProbeResult:
        return self.probe_result

    def fetch_trade_calendar(self, start: date, end: date) -> list[date]:
        return [day for day in self.calendar if start <= day <= end]

    def fetch_stock_basic(
        self, codes: tuple[str, ...], *, listed_only: bool = False
    ) -> list[dict[str, Any]]:
        wanted = set(codes)
        rows = self.stock_basic
        if listed_only:
            rows = [row for row in rows if row.get("delist_date") is None]
        if not wanted:
            return [dict(row) for row in rows]
        return [dict(row) for row in rows if row["code"] in wanted]

    def fetch_tushare_daily(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._window(self.tushare_daily, start, end)

    def fetch_tushare_adj_factor(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._window(self.adj_factor, start, end)

    def fetch_tushare_daily_basic(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._window(self.daily_basic, start, end)

    def fetch_tushare_suspension(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._window(self.suspension, start, end)

    def fetch_tushare_price_limits(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._window(self.price_limits, start, end)

    def fetch_akshare_daily(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._window(self.akshare_daily, start, end)

    def fetch_akshare_limit_up_pool(
        self, dates: list[date], codes: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        wanted = set(dates)
        return [dict(row) for row in self.pool if row["trade_date"] in wanted]

    def fetch_baostock_daily(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._window(self.baostock_daily, start, end)

    def fetch_tushare_daily_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        wanted = set(dates)
        return [dict(row) for row in self.tushare_daily if row["trade_date"] in wanted]

    def fetch_tushare_daily_basic_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        wanted = set(dates)
        return [dict(row) for row in self.daily_basic if row["trade_date"] in wanted]

    def fetch_tushare_adj_factor_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        wanted = set(dates)
        return [dict(row) for row in self.adj_factor if row["trade_date"] in wanted]

    def fetch_tushare_suspension_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        wanted = set(dates)
        return [dict(row) for row in self.suspension if row["trade_date"] in wanted]

    def fetch_tushare_price_limits_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        wanted = set(dates)
        return [dict(row) for row in self.price_limits if row["trade_date"] in wanted]

    @staticmethod
    def _window(rows: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
        return [dict(row) for row in rows if start <= row["trade_date"] <= end]


def probe_result_with(status_by_capability: Mapping[str, str]) -> ProbeResult:
    capabilities = [
        ProbeCapability(capability=capability, status=status)
        for capability, status in (
            ("trade_calendar", status_by_capability.get("trade_calendar", "AVAILABLE")),
            ("stock_basic", status_by_capability.get("stock_basic", "AVAILABLE")),
            ("daily_bars", status_by_capability.get("daily_bars", "AVAILABLE")),
            ("adjustment_factor", status_by_capability.get("adjustment_factor", "AVAILABLE")),
            ("daily_basic", status_by_capability.get("daily_basic", "AVAILABLE")),
            ("suspension", status_by_capability.get("suspension", "AVAILABLE")),
            ("price_limits", status_by_capability.get("price_limits", "AVAILABLE")),
        )
    ]
    return ProbeResult(
        provider="TUSHARE",
        provider_version="1.0",
        capabilities=tuple(capabilities),
        overall="AVAILABLE"
        if all(item.status == "AVAILABLE" for item in capabilities)
        else "UNAVAILABLE_PERMISSION",
    )
