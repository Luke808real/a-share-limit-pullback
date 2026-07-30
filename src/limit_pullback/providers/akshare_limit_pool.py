"""AKShare Eastmoney limit-up-pool adapter for explicitly requested codes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from limit_pullback.models.enums import DataQuality
from limit_pullback.models.market import (
    LimitUpPoolRequest,
    LimitUpPoolResult,
    LimitUpRecord,
)


SOURCE_NAME = "AKSHARE_STOCK_ZT_POOL_EM"
OPTIONAL_FIELDS = {
    "first_seal_time": ("首次封板时间",),
    "last_seal_time": ("最后封板时间",),
    "open_count": ("炸板次数", "开板次数"),
    "consecutive_count": ("连板数",),
    "turnover_rate": ("换手率",),
    "float_market_cap": ("流通市值",),
    "total_market_cap": ("总市值",),
    "industry": ("所属行业", "行业"),
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _provider_version() -> str:
    try:
        return version("akshare")
    except PackageNotFoundError:
        return "not-installed"


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null", "--"}:
        return None
    return text


def _pick(row: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _decimal(value: Any) -> Decimal | None:
    text = _as_text(value)
    if text is None:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _integer(value: Any) -> int | None:
    parsed = _decimal(value)
    if parsed is None or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _clock_time(value: Any) -> time | None:
    text = _as_text(value)
    if text is None:
        return None
    if ":" in text:
        try:
            return time.fromisoformat(text)
        except ValueError:
            return None
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return None
    digits = digits.zfill(6)
    if len(digits) != 6 or digits == "000000":
        return None
    try:
        return time(int(digits[:2]), int(digits[2:4]), int(digits[4:]))
    except ValueError:
        return None


def _rows(frame: Any) -> list[Mapping[str, Any]]:
    if hasattr(frame, "to_dict"):
        rows = frame.to_dict(orient="records")
        if isinstance(rows, list):
            return rows
    if isinstance(frame, list) and all(isinstance(row, Mapping) for row in frame):
        return frame
    raise TypeError("AKShare pool result is not a row-oriented table")


class AkShareLimitUpPoolProvider:
    """Fixed pool source: seal times, opens, boards, caps and industry."""

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
        import akshare

        return akshare

    def fetch_limit_up_pool(
        self,
        request: LimitUpPoolRequest,
    ) -> LimitUpPoolResult:
        fetched_at = self._clock()
        flags: set[str] = set()
        requested_codes = set(request.codes)
        try:
            client = self._load_client()
            frame = client.stock_zt_pool_em(
                date=request.trade_date.strftime("%Y%m%d")
            )
            source_rows = _rows(frame)
        except Exception as exc:
            flags.add(
                f"LIMIT_POOL_UNAVAILABLE:{type(exc).__name__}:{str(exc)[:160]}"
            )
            return LimitUpPoolResult(
                trade_date=request.trade_date,
                records=(),
                quality=DataQuality.PARTIAL,
                quality_flags=tuple(sorted(flags)),
                fetched_at=fetched_at,
            )

        records: list[LimitUpRecord] = []
        degraded = False
        seen_requested_codes: set[str] = set()
        for row in source_rows:
            raw_code = _as_text(_pick(row, ("代码", "股票代码")))
            if raw_code is None:
                degraded = True
                flags.add("MALFORMED_LIMIT_POOL_ROW:missing_code")
                continue
            code = raw_code.split(".")[-1].zfill(6)
            if requested_codes and code not in requested_codes:
                continue
            seen_requested_codes.add(code)
            name = _as_text(_pick(row, ("名称", "股票简称")))
            limit_price = _decimal(_pick(row, ("最新价", "涨停价")))
            if name is None or limit_price is None or limit_price <= 0:
                degraded = True
                missing = "name" if name is None else "limit_price"
                flags.add(f"MALFORMED_LIMIT_POOL_ROW:{code}:{missing}")
                continue

            optional_values: dict[str, Any] = {
                "first_seal_time": _clock_time(
                    _pick(row, OPTIONAL_FIELDS["first_seal_time"])
                ),
                "last_seal_time": _clock_time(
                    _pick(row, OPTIONAL_FIELDS["last_seal_time"])
                ),
                "open_count": _integer(
                    _pick(row, OPTIONAL_FIELDS["open_count"])
                ),
                "consecutive_count": _integer(
                    _pick(row, OPTIONAL_FIELDS["consecutive_count"])
                ),
                "turnover_rate": _decimal(
                    _pick(row, OPTIONAL_FIELDS["turnover_rate"])
                ),
                "float_market_cap": _decimal(
                    _pick(row, OPTIONAL_FIELDS["float_market_cap"])
                ),
                "total_market_cap": _decimal(
                    _pick(row, OPTIONAL_FIELDS["total_market_cap"])
                ),
                "industry": _as_text(_pick(row, OPTIONAL_FIELDS["industry"])),
            }
            for field_name, value in optional_values.items():
                if value is None:
                    flags.add(f"MISSING_LIMIT_FIELD:{code}:{field_name}")

            records.append(
                LimitUpRecord(
                    trade_date=request.trade_date,
                    code=code,
                    name=name,
                    limit_price=limit_price,
                    source=SOURCE_NAME,
                    fetched_at=fetched_at,
                    **optional_values,
                )
            )

        if requested_codes:
            for missing_code in sorted(requested_codes - seen_requested_codes):
                flags.add(f"CODE_NOT_IN_LIMIT_POOL:{missing_code}")
        if degraded:
            quality = DataQuality.DEGRADED
        elif flags:
            quality = DataQuality.PARTIAL
        else:
            quality = DataQuality.OK
        return LimitUpPoolResult(
            trade_date=request.trade_date,
            records=tuple(sorted(records, key=lambda item: item.code)),
            quality=quality,
            quality_flags=tuple(sorted(flags)),
            fetched_at=fetched_at,
        )
