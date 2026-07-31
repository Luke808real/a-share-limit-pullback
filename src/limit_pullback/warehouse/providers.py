"""Provider-set protocol and the real three-provider implementation."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from limit_pullback.warehouse.akshare_provider import AkshareWarehouseProvider
from limit_pullback.warehouse.baostock_provider import BaostockWarehouseProvider
from limit_pullback.warehouse.models import ProbeResult
from limit_pullback.warehouse.tushare_provider import TushareProProvider


class WarehouseProviderSet(Protocol):
    """Everything the pipeline needs from the three fixed data sources."""

    def provider_versions(self) -> dict[str, str]: ...

    def probe(self) -> ProbeResult: ...

    def fetch_trade_calendar(self, start: date, end: date) -> list[date]: ...

    def fetch_stock_basic(self, codes: tuple[str, ...]) -> list[dict[str, Any]]: ...

    def fetch_tushare_daily(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]: ...

    def fetch_tushare_adj_factor(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]: ...

    def fetch_tushare_daily_basic(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]: ...

    def fetch_tushare_suspension(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]: ...

    def fetch_tushare_price_limits(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]: ...

    def fetch_akshare_daily(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]: ...

    def fetch_akshare_limit_up_pool(
        self, dates: list[date], codes: tuple[str, ...]
    ) -> list[dict[str, Any]]: ...

    def fetch_baostock_daily(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]: ...


class RealWarehouseProviderSet:
    """Wraps Tushare, AKShare and BaoStock with strict normalization."""

    def __init__(
        self,
        *,
        tushare: TushareProProvider | None = None,
        akshare: AkshareWarehouseProvider | None = None,
        baostock: BaostockWarehouseProvider | None = None,
    ) -> None:
        self._tushare = tushare or TushareProProvider()
        self._akshare = akshare or AkshareWarehouseProvider()
        self._baostock = baostock or BaostockWarehouseProvider()

    def provider_versions(self) -> dict[str, str]:
        return {
            self._tushare.provider_name: self._tushare.provider_version,
            self._akshare.provider_name: self._akshare.provider_version,
            self._baostock.provider_name: self._baostock.provider_version,
        }

    def probe(self) -> ProbeResult:
        return self._tushare.probe_all()

    def fetch_trade_calendar(self, start: date, end: date) -> list[date]:
        return self._tushare.fetch_trade_calendar(start, end)

    def fetch_stock_basic(self, codes: tuple[str, ...]) -> list[dict[str, Any]]:
        return self._tushare.fetch_stock_basic(codes)

    def fetch_tushare_daily(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._tushare.fetch_daily(codes, start, end)

    def fetch_tushare_adj_factor(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._tushare.fetch_adj_factor(codes, start, end)

    def fetch_tushare_daily_basic(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._tushare.fetch_daily_basic(codes, start, end)

    def fetch_tushare_suspension(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._tushare.fetch_suspension(codes, start, end)

    def fetch_tushare_price_limits(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._tushare.fetch_price_limits(codes, start, end)

    def fetch_akshare_daily(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._akshare.fetch_daily(codes, start, end)

    def fetch_akshare_limit_up_pool(
        self, dates: list[date], codes: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        return self._akshare.fetch_limit_up_pool(dates, codes)

    def fetch_baostock_daily(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        return self._baostock.fetch_daily(codes, start, end)
