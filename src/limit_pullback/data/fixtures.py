"""In-memory CanonicalDataPort adapter for tests and small tools (REF-R3)."""

from __future__ import annotations

from datetime import date

from limit_pullback.domain.provenance import DataProvenance
from limit_pullback.warehouse.models import CanonicalDailyBar


class InMemoryCanonicalAdapter:
    def __init__(
        self,
        bars: tuple[CanonicalDailyBar, ...] = (),
        *,
        provenance: DataProvenance,
    ) -> None:
        self._bars = sorted(
            bars,
            key=lambda bar: (bar.code, bar.trade_date),
        )
        self._provenance = provenance

    def get_daily(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> tuple[CanonicalDailyBar, ...]:
        if start > end:
            raise ValueError("start cannot be after end")
        return tuple(
            bar
            for bar in self._bars
            if bar.code == symbol and start <= bar.trade_date <= end
        )

    def get_daily_universe(self, as_of: date) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    bar.code
                    for bar in self._bars
                    if bar.trade_date <= as_of
                }
            )
        )

    def get_trading_status(self, symbol: str, day: date) -> str | None:
        rows = self.get_daily(symbol, day, day)
        if not rows:
            return None
        row = rows[0]
        if row.is_st is None:
            return "UNKNOWN"
        if row.is_st is True:
            return "ST"
        if row.trade_status is False:
            return "NO_TRADE"
        return "NORMAL"

    def get_corporate_action(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> tuple[object, ...]:
        raise NotImplementedError("future interface")

    def get_minute(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> tuple[object, ...]:
        raise NotImplementedError("future interface")

    def get_data_provenance(self) -> DataProvenance:
        return self._provenance


__all__ = ["InMemoryCanonicalAdapter"]
