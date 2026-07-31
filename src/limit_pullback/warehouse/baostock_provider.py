"""BaoStock raw daily-bar provider reused for the warehouse."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from limit_pullback.models.market import DailyBarsRequest
from limit_pullback.providers.baostock_daily import BaoStockDailyBarProvider
from limit_pullback.warehouse.units import normalize_baostock_bar


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class BaostockWarehouseProvider:
    provider_name = "BAOSTOCK"

    def __init__(
        self,
        *,
        daily_provider: BaoStockDailyBarProvider | None = None,
        clock=None,
    ) -> None:
        self._daily_provider = daily_provider or BaoStockDailyBarProvider(
            clock=clock or _now_utc
        )

    @property
    def provider_version(self) -> str:
        return self._daily_provider.provider_version

    def fetch_daily(self, codes: tuple[str, ...], start: date, end: date) -> list[dict[str, Any]]:
        result = self._daily_provider.fetch_daily_bars(
            DailyBarsRequest(codes=codes, start_date=start, end_date=end)
        )
        return [normalize_baostock_bar(bar) for bar in result.bars]
