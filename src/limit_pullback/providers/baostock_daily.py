"""BaoStock raw daily-bar adapter.

All third-party values are normalized here; the strategy layer never sees
BaoStock result objects or blank/sentinel values.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from limit_pullback.models.enums import DataQuality
from limit_pullback.models.market import DailyBar, DailyBarsRequest, DailyBarsResult
from limit_pullback.providers.base import ProviderError


SOURCE_NAME = "BAOSTOCK"
FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "turn,tradestatus,pctChg,isST"
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _provider_version() -> str:
    try:
        return version("baostock")
    except PackageNotFoundError:
        return "not-installed"


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null", "--"}:
        return None
    return text


def _decimal(value: Any) -> Decimal | None:
    text = _as_text(value)
    if text is None:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _bool01(value: Any) -> bool | None:
    text = _as_text(value)
    if text == "1":
        return True
    if text == "0":
        return False
    return None


def _baostock_code(code: str) -> str:
    if code.startswith("6"):
        return f"sh.{code}"
    if code.startswith(("0", "1", "2", "3")):
        return f"sz.{code}"
    raise ProviderError(f"unsupported A-share code for BaoStock: {code}")


class BaoStockDailyBarProvider:
    """Fixed daily source: raw OHLCV/preclose/trading status/historical ST."""

    provider_name = SOURCE_NAME
    provider_version = _provider_version()

    def __init__(
        self,
        *,
        client: Any | None = None,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        self._client = client
        self._clock = clock

    def _load_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import baostock as bs
        except ImportError as exc:
            raise ProviderError(
                "BaoStock is not installed; install the integration extra"
            ) from exc
        return bs

    @staticmethod
    def _check_result(result: Any, operation: str) -> None:
        if str(getattr(result, "error_code", "")) != "0":
            message = getattr(result, "error_msg", "unknown provider error")
            raise ProviderError(f"BaoStock {operation} failed: {message}")

    @staticmethod
    def _quiet_call(callable_: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Keep third-party login/logout banners out of structured CLI stdout."""

        sink = StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            return callable_(*args, **kwargs)

    def fetch_daily_bars(self, request: DailyBarsRequest) -> DailyBarsResult:
        client = self._load_client()
        fetched_at = self._clock()
        flags: set[str] = set()
        bars: list[DailyBar] = []
        degraded = False

        login_result = self._quiet_call(client.login)
        self._check_result(login_result, "login")
        try:
            for code in request.codes:
                result = self._quiet_call(
                    client.query_history_k_data_plus,
                    _baostock_code(code),
                    FIELDS,
                    start_date=request.start_date.isoformat(),
                    end_date=request.end_date.isoformat(),
                    frequency="d",
                    adjustflag="3",
                )
                self._check_result(result, f"daily query for {code}")
                field_names = tuple(result.fields)
                while result.next():
                    row = dict(zip(field_names, result.get_row_data(), strict=True))
                    trade_date = _as_text(row.get("date"))
                    trade_status = _bool01(row.get("tradestatus"))
                    if trade_date is None:
                        degraded = True
                        flags.add(f"MALFORMED_DAILY_ROW:{code}:missing_date")
                        continue
                    if trade_status is not True:
                        flags.add(f"NON_TRADING_BAR_SKIPPED:{code}:{trade_date}")
                        continue

                    required_names = (
                        "open",
                        "high",
                        "low",
                        "close",
                        "preclose",
                        "volume",
                        "amount",
                    )
                    required = {
                        name: _decimal(row.get(name)) for name in required_names
                    }
                    if any(value is None for value in required.values()):
                        degraded = True
                        missing = ",".join(
                            name for name, value in required.items() if value is None
                        )
                        flags.add(
                            f"MALFORMED_DAILY_ROW:{code}:{trade_date}:{missing}"
                        )
                        continue

                    turnover = _decimal(row.get("turn"))
                    pct_change = _decimal(row.get("pctChg"))
                    is_st = _bool01(row.get("isST"))
                    for field_name, value in (
                        ("turnover_rate", turnover),
                        ("pct_change", pct_change),
                        ("is_st", is_st),
                    ):
                        if value is None:
                            flags.add(
                                f"MISSING_DAILY_FIELD:{code}:{trade_date}:{field_name}"
                            )

                    bars.append(
                        DailyBar(
                            trade_date=trade_date,
                            code=code,
                            open=required["open"],
                            high=required["high"],
                            low=required["low"],
                            close=required["close"],
                            preclose=required["preclose"],
                            volume=required["volume"],
                            amount=required["amount"],
                            turnover_rate=turnover,
                            pct_change=pct_change,
                            trade_status=True,
                            is_st=is_st,
                            source=SOURCE_NAME,
                            fetched_at=fetched_at,
                        )
                    )
        finally:
            self._quiet_call(client.logout)

        bars.sort(key=lambda item: (item.code, item.trade_date))
        if not bars:
            quality = DataQuality.UNUSABLE
            flags.add("NO_DAILY_BARS")
        elif degraded:
            quality = DataQuality.DEGRADED
        elif flags:
            quality = DataQuality.PARTIAL
        else:
            quality = DataQuality.OK
        return DailyBarsResult(
            bars=tuple(bars),
            quality=quality,
            quality_flags=tuple(sorted(flags)),
            fetched_at=fetched_at,
        )
