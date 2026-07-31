"""Tushare Pro raw provider.

Only the environment variable ``TUSHARE_TOKEN`` is used for authentication.
Permission failures are reported as capabilities, never as empty data, and no
exception or audit string contains the token.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import time
from typing import Any

from limit_pullback.warehouse.auth import TushareTokenError, redact, tushare_token
from limit_pullback.warehouse.models import ProbeCapability, ProbeResult
from limit_pullback.warehouse.units import (
    normalize_tushare_adj_factor,
    normalize_tushare_daily,
    normalize_tushare_daily_basic,
    normalize_tushare_price_limits,
    normalize_tushare_stock_basic,
    normalize_tushare_suspension,
    parse_date_yyyymmdd,
)

PERMISSION_HINTS = (
    "权限",
    "没有权限",
    "无权",
    "permission",
    "access denied",
    "积分不足",
    "not authorized",
    "forbidden",
)
RATE_LIMIT_HINTS = (
    "每分钟最多访问",
    "访问频率过高",
    "请求过于频繁",
    "接口调用过于频繁",
    "rate limit",
    "too many requests",
    "访问次数",
)


class CapabilityUnavailable(RuntimeError):
    """Structured capability failure with a stable status code."""

    def __init__(
        self,
        capability: str,
        status: str,
        *,
        error_code: str,
        detail: str,
    ) -> None:
        super().__init__(f"{capability}: {status}: {error_code}")
        self.capability = capability
        self.status = status
        self.error_code = error_code
        self.detail = redact(detail)


def _looks_like_permission(message: str) -> bool:
    lowered = message.lower()
    return any(hint.lower() in lowered for hint in PERMISSION_HINTS)


def _looks_retryable(message: str) -> bool:
    lowered = message.lower()
    if any(hint.lower() in lowered for hint in RATE_LIMIT_HINTS):
        return True
    return any(
        token in lowered
        for token in ("timeout", "timed out", "connection", "网络", "超时", "远程主机")
    )


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ts_code(code: str) -> str:
    normalized = code.zfill(6)
    if normalized.startswith(("600", "601", "603", "605")):
        return f"{normalized}.SH"
    if normalized.startswith(("000", "001", "002", "003")):
        return f"{normalized}.SZ"
    raise ValueError(f"unsupported main-board code: {code}")


def _rows(frame: Any) -> list[dict[str, Any]]:
    if not hasattr(frame, "to_dict"):
        raise CapabilityUnavailable(
            "unknown",
            "MALFORMED_RESPONSE",
            error_code="NOT_DATAFRAME",
            detail="provider response is not a DataFrame",
        )
    records = frame.to_dict(orient="records")
    if not isinstance(records, list):
        raise CapabilityUnavailable(
            "unknown",
            "MALFORMED_RESPONSE",
            error_code="NOT_ROW_LIST",
            detail="provider response cannot be converted to rows",
        )
    return records


class TushareProProvider:
    provider_name = "TUSHARE"

    def __init__(
        self,
        *,
        client_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None
        self._clock = clock

    @property
    def provider_version(self) -> str:
        try:
            return version("tushare")
        except PackageNotFoundError:
            return "not-installed"

    def _load_client(self) -> Any:
        if self._client is not None:
            return self._client
        token = tushare_token()
        if self._client_factory is not None:
            self._client = self._client_factory(token)
        else:
            import tushare

            self._client = tushare.pro_api(token)
        return self._client

    def _call(
        self,
        capability: str,
        function: Callable[[], Any],
        *,
        retries: int = 4,
        backoff_seconds: float = 1.5,
    ) -> Any:
        attempts = 0
        while True:
            try:
                client = self._load_client()
                return function(client)
            except TushareTokenError:
                raise
            except CapabilityUnavailable:
                raise
            except Exception as exc:
                message = redact(str(exc))
                if _looks_retryable(message) and attempts < retries:
                    attempts += 1
                    time.sleep(backoff_seconds * (2 ** (attempts - 1)))
                    continue
                if _looks_like_permission(message):
                    raise CapabilityUnavailable(
                        capability,
                        "UNAVAILABLE_PERMISSION",
                        error_code="PERMISSION_DENIED",
                        detail=message,
                    ) from exc
                raise CapabilityUnavailable(
                    capability,
                    "UNAVAILABLE_PROVIDER",
                    error_code=type(exc).__name__,
                    detail=message[:500],
                ) from exc

    def _frame_call(self, capability: str, function: Callable[[Any], Any]) -> Any:
        frame = self._call(capability, function)
        try:
            return _rows(frame)
        except CapabilityUnavailable as exc:
            if exc.capability == "unknown":
                raise CapabilityUnavailable(
                    capability,
                    "MALFORMED_RESPONSE",
                    error_code=exc.error_code,
                    detail=exc.detail,
                ) from exc
            raise

    @staticmethod
    def _d(value: date) -> str:
        return value.strftime("%Y%m%d")

    def probe_all(self) -> ProbeResult:
        capabilities: list[ProbeCapability] = []
        probe_start = date(2026, 1, 5)
        probe_end = date(2026, 1, 9)
        capabilities.append(self._probe("trade_calendar", "trade_calendar", probe_start, probe_end))
        capabilities.append(self._probe("stock_basic", "stock_basic", probe_start, probe_end))
        capabilities.append(self._probe("daily_bars", "daily_bars", probe_start, probe_end))
        capabilities.append(self._probe("adjustment_factor", "adjustment_factor", probe_start, probe_end))
        capabilities.append(self._probe("daily_basic", "daily_basic", probe_start, probe_end))
        capabilities.append(self._probe("suspension", "suspension", probe_start, probe_end))
        capabilities.append(self._probe("price_limits", "price_limits", probe_start, probe_end))
        overall = self._overall(capabilities)
        return ProbeResult(
            provider=self.provider_name,
            provider_version=self.provider_version,
            capabilities=tuple(capabilities),
            overall=overall,
        )

    def _probe(
        self,
        capability: str,
        method: str,
        start: date,
        end: date,
    ) -> ProbeCapability:
        try:
            if method == "trade_calendar":
                self._frame_call(
                    capability,
                    lambda client: client.trade_cal(
                        exchange="SSE",
                        start_date=self._d(start),
                        end_date=self._d(end),
                    ),
                )
            elif method == "stock_basic":
                self._frame_call(
                    capability,
                    lambda client: client.stock_basic(
                        exchange="",
                        list_status="L",
                        fields="ts_code,symbol,name,industry,market,list_date",
                    ),
                )
            elif method == "daily_bars":
                self._frame_call(
                    capability,
                    lambda client: client.daily(
                        ts_code="000001.SZ",
                        start_date=self._d(start),
                        end_date=self._d(end),
                    ),
                )
            elif method == "adjustment_factor":
                self._frame_call(
                    capability,
                    lambda client: client.adj_factor(
                        ts_code="000001.SZ",
                        start_date=self._d(start),
                        end_date=self._d(end),
                    ),
                )
            elif method == "daily_basic":
                self._frame_call(
                    capability,
                    lambda client: client.daily_basic(
                        ts_code="000001.SZ",
                        start_date=self._d(start),
                        end_date=self._d(end),
                    ),
                )
            elif method == "suspension":
                self._frame_call(
                    capability,
                    lambda client: client.suspend_d(
                        ts_code="000001.SZ",
                        start_date=self._d(start),
                        end_date=self._d(end),
                    ),
                )
            elif method == "price_limits":
                self._frame_call(
                    capability,
                    lambda client: client.stk_limit(
                        ts_code="000001.SZ",
                        start_date=self._d(start),
                        end_date=self._d(end),
                    ),
                )
            else:
                raise CapabilityUnavailable(
                    capability,
                    "MALFORMED_RESPONSE",
                    error_code="UNKNOWN_PROBE",
                    detail=f"unknown probe method {method}",
                )
        except CapabilityUnavailable as exc:
            return ProbeCapability(
                capability=capability,
                status=exc.status,
                error_code=exc.error_code,
                detail=exc.detail,
            )
        return ProbeCapability(capability=capability, status="AVAILABLE")

    @staticmethod
    def _overall(capabilities: list[ProbeCapability]) -> str:
        statuses = {item.status for item in capabilities}
        if statuses == {"AVAILABLE"}:
            return "AVAILABLE"
        if "MALFORMED_RESPONSE" in statuses:
            return "MALFORMED_RESPONSE"
        if "UNAVAILABLE_PROVIDER" in statuses:
            return "UNAVAILABLE_PROVIDER"
        if "UNAVAILABLE_PERMISSION" in statuses:
            return "UNAVAILABLE_PERMISSION"
        return "UNAVAILABLE_PROVIDER"

    def fetch_trade_calendar(self, start: date, end: date) -> list[date]:
        dates: set[date] = set()
        for exchange in ("SSE", "SZSE"):
            rows = self._frame_call(
                "trade_calendar",
                lambda client, e=exchange: client.trade_cal(
                    exchange=e,
                    start_date=self._d(start),
                    end_date=self._d(end),
                    fields="exchange,cal_date,is_open",
                ),
            )
            for row in rows:
                if str(row.get("is_open")) == "1":
                    parsed = parse_date_yyyymmdd(row.get("cal_date"))
                    if parsed is not None:
                        dates.add(parsed)
        return sorted(dates)

    def fetch_stock_basic(self, codes: tuple[str, ...]) -> list[dict[str, Any]]:
        rows = self._frame_call(
            "stock_basic",
            lambda client: client.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,symbol,name,industry,market,list_date",
            ),
        )
        wanted = set(codes)
        return [
            normalize_tushare_stock_basic(row)
            for row in rows
            if str(row.get("ts_code", "")).split(".")[0].zfill(6) in wanted
        ]

    def fetch_daily(self, codes: tuple[str, ...], start: date, end: date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code in codes:
            frame_rows = self._frame_call(
                "daily_bars",
                lambda client, c=code: client.daily(
                    ts_code=_ts_code(c),
                    start_date=self._d(start),
                    end_date=self._d(end),
                ),
            )
            rows.extend(normalize_tushare_daily(row) for row in frame_rows)
        return rows

    def fetch_adj_factor(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code in codes:
            frame_rows = self._frame_call(
                "adjustment_factor",
                lambda client, c=code: client.adj_factor(
                    ts_code=_ts_code(c),
                    start_date=self._d(start),
                    end_date=self._d(end),
                ),
            )
            rows.extend(normalize_tushare_adj_factor(row) for row in frame_rows)
        return rows

    def fetch_daily_basic(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code in codes:
            frame_rows = self._frame_call(
                "daily_basic",
                lambda client, c=code: client.daily_basic(
                    ts_code=_ts_code(c),
                    start_date=self._d(start),
                    end_date=self._d(end),
                ),
            )
            rows.extend(normalize_tushare_daily_basic(row) for row in frame_rows)
        return rows

    def fetch_suspension(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code in codes:
            frame_rows = self._frame_call(
                "suspension",
                lambda client, c=code: client.suspend_d(
                    ts_code=_ts_code(c),
                    start_date=self._d(start),
                    end_date=self._d(end),
                ),
            )
            rows.extend(normalize_tushare_suspension(row) for row in frame_rows)
        return rows

    def fetch_price_limits(
        self, codes: tuple[str, ...], start: date, end: date
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code in codes:
            frame_rows = self._frame_call(
                "price_limits",
                lambda client, c=code: client.stk_limit(
                    ts_code=_ts_code(c),
                    start_date=self._d(start),
                    end_date=self._d(end),
                ),
            )
            rows.extend(normalize_tushare_price_limits(row) for row in frame_rows)
        return rows

    def _bulk_by_trade_date(
        self,
        capability: str,
        method_name: str,
        dates: list[date],
        normalizer: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for trade_date in dates:
            frame_rows = self._frame_call(
                capability,
                lambda client, day=trade_date: getattr(client, method_name)(
                    trade_date=day.strftime("%Y%m%d")
                ),
            )
            rows.extend(normalizer(row) for row in frame_rows)
        return rows

    def fetch_daily_by_trade_date(self, dates: list[date]) -> list[dict[str, Any]]:
        return self._bulk_by_trade_date(
            "daily_bars", "daily", dates, normalize_tushare_daily
        )

    def fetch_daily_basic_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        return self._bulk_by_trade_date(
            "daily_basic", "daily_basic", dates, normalize_tushare_daily_basic
        )

    def fetch_adj_factor_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        return self._bulk_by_trade_date(
            "adjustment_factor", "adj_factor", dates, normalize_tushare_adj_factor
        )

    def fetch_suspension_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        return self._bulk_by_trade_date(
            "suspension", "suspend_d", dates, normalize_tushare_suspension
        )

    def fetch_price_limits_by_trade_date(
        self, dates: list[date]
    ) -> list[dict[str, Any]]:
        return self._bulk_by_trade_date(
            "price_limits", "stk_limit", dates, normalize_tushare_price_limits
        )
