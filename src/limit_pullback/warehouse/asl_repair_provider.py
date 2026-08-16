"""ASL-backed primary provider for the bounded daily-session repair.

Reads the ASL lake (curated ``daily_bars`` + ``instruments`` +
``trading_calendar`` + ``trading_status`` via the frozen Phase-1A adapter,
and ``derived/adj_factors`` for the corporate-action predecessor) strictly
READ-ONLY, and emits V Flash raw daily rows under the ``ASL`` provider name
so the bounded repair pipeline can use the ASL lake as its authoritative
primary source without calling TUSHARE (data layer is fully switched to
ASL; no network provider is ever contacted).

The provider implements only the methods the repair pipeline calls
(``WarehouseProviderSet`` is a structural Protocol). ``daily_basic`` and
``stock_basic`` return empty lists: the ASL contract has no PIT-safe
turnover field (adapter sets ``turnover_rate`` to None) and every bar
carries its own ``is_st`` / ``trade_status`` from trusted PIT status rows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from limit_pullback.warehouse.asl_adapter import (
    CONTRACT_VERSION,
    TESTED_COMPAT_REVISION,
    load_asl_daily_slice,
)
from limit_pullback.warehouse.parquet import read_rows

ADJ_FACTOR_COLUMNS = ("code", "trade_date", "adj_factor")


class AslRepairProviderError(RuntimeError):
    """Raised when the ASL lake cannot satisfy the repair contract."""


class AslRepairProviderSet:
    """Structural ``WarehouseProviderSet`` backed by the read-only ASL lake."""

    def __init__(
        self,
        asl_root: str | Path,
        *,
        as_of: date,
        repair_dates: Sequence[date],
        universe_prefixes: Sequence[str] | None = None,
    ) -> None:
        self.asl_root = Path(asl_root).expanduser().resolve()
        self.as_of = as_of
        self.repair_dates = tuple(sorted({d for d in repair_dates}))
        self._universe_prefixes = tuple(universe_prefixes or ())
        self._slice_cache: tuple[tuple[date, ...], object] | None = None

    # -- repair pipeline surface -------------------------------------------

    def provider_versions(self) -> dict[str, str]:
        return {
            "ASL": TESTED_COMPAT_REVISION,
            "ASL_CONTRACT_VERSION": CONTRACT_VERSION,
        }

    def fetch_stock_basic(
        self, codes: tuple[str, ...], *, listed_only: bool = False
    ) -> list[dict[str, Any]]:
        # Every ASL bar carries its own is_st / trade_status from trusted
        # PIT status rows; no separate stock_basic enrichment is needed.
        return []

    def fetch_tushare_daily_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        wanted = {d for d in dates}
        out: list[dict[str, Any]] = []
        for row in self._slice().rows:
            if row.trade_date not in wanted:
                continue
            if row.row_status != "VALID_ROW":
                # Never fabricate a bar the adapter did not validate.
                continue
            out.append(_asl_row_to_raw(row))
        return out

    def fetch_tushare_daily_basic_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        # ASL has no PIT-safe per-stock turnover field (frozen contract);
        # turnover_rate stays None on every row.
        return []

    def fetch_tushare_adj_factor_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for day in dates:
            partition = (
                self.asl_root / "derived" / "adj_factors"
                / f"trade_date={day.isoformat()}"
            )
            if not partition.is_dir():
                continue
            for path in sorted(partition.glob("*.parquet")):
                for row in read_rows(path):
                    symbol = str(row.get("symbol") or "")
                    code = _code_from_symbol(symbol)
                    if code is None:
                        continue
                    factor = row.get("factor")
                    if factor is None:
                        continue
                    rows.append(
                        {
                            "code": code,
                            "trade_date": day,
                            # ASL parquet stores factor as DOUBLE; the V
                            # Flash raw schema requires Decimal.
                            "adj_factor": Decimal(str(factor)),
                        }
                    )
        return rows

    # -- helpers ------------------------------------------------------------

    def _slice(self):
        if self._slice_cache is not None:
            return self._slice_cache[1]
        start = min(self.repair_dates)
        if self._universe_prefixes:
            slice_ = load_asl_daily_slice(
                self.asl_root,
                as_of=self.as_of,
                start=start,
                codes=None,
                universe_prefixes=self._universe_prefixes,
            )
        else:
            slice_ = load_asl_daily_slice(
                self.asl_root, as_of=self.as_of, start=start
            )
        self._slice_cache = (self.repair_dates, slice_)
        return slice_


def _code_from_symbol(symbol: str) -> str | None:
    """``600000.SH`` -> ``600000``; anything else -> None."""
    parts = symbol.split(".", 1)
    code = parts[0]
    if len(code) == 6 and code.isdigit():
        return code
    return None


def _asl_row_to_raw(row: Any) -> dict[str, Any]:
    """AslDailyBarRow -> V Flash raw daily row (fields match the raw schema)."""
    return {
        "code": row.code,
        "trade_date": row.trade_date,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "preclose": row.preclose,
        "volume": row.volume,
        "amount": row.amount,
        "turnover_rate": row.turnover_rate,
        "pct_change": row.pct_change,
        "trade_status": row.trade_status,
        "is_st": row.is_st,
    }
