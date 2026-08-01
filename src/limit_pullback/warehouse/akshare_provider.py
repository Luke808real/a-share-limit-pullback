"""AKShare / Eastmoney raw provider for daily bars and the limit-up pool."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from limit_pullback.models.market import LimitUpPoolRequest
from limit_pullback.providers.akshare_limit_pool import AkShareLimitUpPoolProvider
from limit_pullback.warehouse.units import (
    normalize_akshare_daily,
    normalize_limit_up_record,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class AkshareWarehouseProvider:
    provider_name = "AKSHARE"

    def __init__(
        self,
        *,
        client: Any | None = None,
        pool_provider: AkShareLimitUpPoolProvider | None = None,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        self._client = client
        self._pool_provider = pool_provider or AkShareLimitUpPoolProvider(clock=clock)
        self._clock = clock

    @property
    def provider_version(self) -> str:
        try:
            return version("akshare")
        except PackageNotFoundError:
            return "not-installed"

    def _load_client(self) -> Any:
        if self._client is not None:
            return self._client
        import akshare

        return akshare

    def fetch_daily(self, codes: tuple[str, ...], start: date, end: date) -> list[dict[str, Any]]:
        client = self._load_client()
        rows: list[dict[str, Any]] = []
        for code in codes:
            frame = client.stock_zh_a_daily(
                symbol=f"{'sh' if code.startswith(('6',)) else 'sz'}{code.zfill(6)}",
                start_date=(start - timedelta(days=10)).strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="",
            )
            for row in frame.to_dict(orient="records"):
                try:
                    rows.append(normalize_akshare_daily(row, code=code))
                except (KeyError, TypeError, ValueError):
                    # Suspended/halted rows may contain NaN placeholders;
                    # they are not valid trading observations.
                    continue
        by_code: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_code.setdefault(str(row["code"]), []).append(row)
        completed: list[dict[str, Any]] = []
        for code_rows in by_code.values():
            code_rows.sort(key=lambda item: item["trade_date"])
            previous_close = None
            for row in code_rows:
                if previous_close is not None and row.get("preclose") is None:
                    row["preclose"] = previous_close
                previous_close = row["close"]
            completed.extend(code_rows)
        rows = [
            row
            for row in completed
            if start <= row["trade_date"] <= end and row.get("preclose") is not None
        ]
        return rows

    def fetch_limit_up_pool(
        self, dates: list[date], codes: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for trade_date in dates:
            result = self._pool_provider.fetch_limit_up_pool(
                LimitUpPoolRequest(trade_date=trade_date, codes=codes)
            )
            rows.extend(normalize_limit_up_record(record) for record in result.records)
        return rows
