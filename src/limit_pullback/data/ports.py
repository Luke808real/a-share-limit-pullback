"""CanonicalDataPort: the single concept-level data contract (REF-R3).

Runtime logic depends only on this port, never on ASL DuckDB/Parquet internals
or provider APIs. The port is a concept contract; concrete adapters implement
it. `get_minute` and `get_corporate_action` are future interfaces and raise
NotImplementedError until a real requirement exists.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from limit_pullback.domain.provenance import DataProvenance
from limit_pullback.warehouse.models import CanonicalDailyBar


@runtime_checkable
class CanonicalDataPort(Protocol):
    def get_daily(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> tuple[CanonicalDailyBar, ...]:
        """CONFIRMED canonical daily bars for one symbol in [start, end]."""
        ...

    def get_daily_universe(self, as_of: date) -> tuple[str, ...]:
        """Universe member codes eligible at the given as-of."""
        ...

    def get_trading_status(self, symbol: str, day: date) -> str | None:
        """Trading status vocabulary for (symbol, day); None means UNKNOWN."""
        ...

    def get_corporate_action(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> tuple[object, ...]:
        """Future interface; adapters raise NotImplementedError."""
        ...

    def get_minute(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> tuple[object, ...]:
        """Future interface; adapters raise NotImplementedError."""
        ...

    def get_data_provenance(self) -> DataProvenance:
        """Provenance of the data backing this adapter."""
        ...


__all__ = ["CanonicalDataPort"]
