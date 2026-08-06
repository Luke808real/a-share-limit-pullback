"""TDX daily-bar adapter for ADR-008 (primary).

The raw TDX daily endpoint reports volume in lots (手); the canonical layer
requires shares (股).  The multiplier lives here, in the formal shared code,
and must never be re-implemented at call sites.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Mapping, Sequence

from limit_pullback.providers.errors import (
    ProviderConnectionError,
    ProviderError,
    ProviderMalformedRowError,
    ProviderUnexpectedError,
)
from limit_pullback.warehouse.units import as_text, decimal_from

PROVIDER_NAME = "TDX"
TDX_DAILY_VOLUME_UNIT = "LOTS"
TDX_DAILY_VOLUME_MULTIPLIER = Decimal("100")
TDX_DAILY_NORMALIZED_UNIT = "SHARES"
PRICE_QUANTUM = Decimal("0.0001")
AMOUNT_QUANTUM = Decimal("0.00000001")

DEFAULT_TDX_SERVERS = (
    ("180.153.18.170", 7709),
    ("119.147.212.81", 7709),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _quantize(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def normalize_tdx_daily_row(
    raw: Mapping[str, Any],
    *,
    provider_server: str = "unknown",
    fetched_at: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Convert one raw TDX row into the typed ADR-008 row shape.

    Raises ``ProviderMalformedRowError`` for rows that cannot be normalized;
    nothing is silently dropped.
    """

    code = str(raw.get("code") or "").strip().zfill(6)
    trade_date = raw.get("trade_date")
    if isinstance(trade_date, str):
        try:
            trade_date = date.fromisoformat(trade_date)
        except ValueError as exc:
            raise ProviderMalformedRowError(
                f"invalid trade_date {trade_date!r}",
                provider=PROVIDER_NAME,
                run_id=run_id,
            ) from exc
    if not code or trade_date is None:
        raise ProviderMalformedRowError(
            "missing code or trade_date",
            provider=PROVIDER_NAME,
            run_id=run_id,
        )
    prices = {
        field: decimal_from(raw.get(field))
        for field in ("open", "high", "low", "close")
    }
    volume_raw = decimal_from(raw.get("volume_lots"))
    amount = decimal_from(raw.get("amount"))
    if any(value is None for value in prices.values()) or volume_raw is None or amount is None:
        raise ProviderMalformedRowError(
            "incomplete OHLC/volume/amount fields",
            provider=PROVIDER_NAME,
            run_id=run_id,
        )
    prices = {
        field: _quantize(value, PRICE_QUANTUM)
        for field, value in prices.items()
    }
    raw_hash = as_text(raw.get("raw_hash"))
    if not raw_hash:
        raise ProviderMalformedRowError(
            "missing raw_hash",
            provider=PROVIDER_NAME,
            run_id=run_id,
        )
    return {
        "code": code,
        "trade_date": trade_date,
        "open": prices["open"],
        "high": prices["high"],
        "low": prices["low"],
        "close": prices["close"],
        "volume": _quantize(
            volume_raw * TDX_DAILY_VOLUME_MULTIPLIER,
            Decimal("1"),
        ),
        "amount": _quantize(amount, AMOUNT_QUANTUM),
        "provider": PROVIDER_NAME,
        "provider_server": provider_server,
        "fetched_at": (fetched_at or _utc_now()).isoformat(timespec="seconds"),
        "raw_hash": raw_hash,
        "source_unit": TDX_DAILY_VOLUME_UNIT,
        "normalized_unit": TDX_DAILY_NORMALIZED_UNIT,
        "price_domain": "RAW_UNADJUSTED",
    }


def fetch_tdx_daily(
    codes: Sequence[str],
    *,
    sessions: Sequence[date],
    servers: Sequence[tuple[str, int]] = DEFAULT_TDX_SERVERS,
    connect_timeout: float = 5.0,
    run_id: str | None = None,
    clock: Callable[[], datetime] = _utc_now,
    api_factory: Callable[[], Any] | None = None,
    normalize: bool = True,
) -> tuple[list[dict[str, Any]], list[ProviderError]]:
    """Fetch TDX daily bars for one universe.

    Returns ``(rows, failures)``.  Per-code errors are never swallowed: each
    becomes a typed failure record.  Server failover stays within TDX (same
    provider); it is never treated as a Tencent fallback.
    """

    from pytdx.hq import TdxHq_API
    from pytdx.params import TDXParams

    normalized_codes = tuple(sorted({str(code).zfill(6) for code in codes}))
    session_set = set(sessions)
    failures: list[ProviderError] = []
    rows: list[dict[str, Any]] = []
    api: Any = None
    last_connect_error: ProviderError | None = None
    for server_index, server in enumerate(servers, start=1):
        try:
            api = (api_factory or TdxHq_API)()
            if not api.connect(*server, time_out=connect_timeout):
                raise ProviderConnectionError(
                    f"connect refused by {server[0]}:{server[1]}",
                    provider=PROVIDER_NAME,
                    requested_from=min(sessions) if sessions else None,
                    requested_to=max(sessions) if sessions else None,
                    attempt=server_index,
                    run_id=run_id,
                )
            last_connect_error = None
            break
        except ProviderError as exc:
            last_connect_error = exc
            continue
        except Exception as exc:
            last_connect_error = ProviderUnexpectedError.wrap(
                exc,
                provider=PROVIDER_NAME,
                requested_from=min(sessions) if sessions else None,
                requested_to=max(sessions) if sessions else None,
                attempt=server_index,
                run_id=run_id,
            )
            continue
    if api is None or last_connect_error is not None:
        failures.append(
            last_connect_error
            or ProviderConnectionError(
                "no TDX server available",
                provider=PROVIDER_NAME,
                run_id=run_id,
            )
        )
        return [], failures

    fetched_at = clock()
    for code in normalized_codes:
        market = TDXParams.MARKET_SH if code.startswith(("6", "9")) else TDXParams.MARKET_SZ
        try:
            bars = api.get_security_bars(
                TDXParams.KLINE_TYPE_RI_K,
                market,
                code,
                0,
                5,
            ) or []
        except Exception as exc:
            failures.append(
                ProviderUnexpectedError.wrap(
                    exc,
                    provider=PROVIDER_NAME,
                    requested_from=min(sessions) if sessions else None,
                    requested_to=max(sessions) if sessions else None,
                    attempt=1,
                    run_id=run_id,
                )
            )
            continue
        for bar in bars:
            day = date(int(bar["year"]), int(bar["month"]), int(bar["day"]))
            if day not in session_set:
                continue
            raw = {
                "code": code,
                "trade_date": day,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume_lots": bar["vol"],
                "amount": bar["amount"],
                "raw_hash": hashlib.sha256(
                    json.dumps(
                        dict(bar),
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest(),
            }
            if normalize:
                try:
                    rows.append(
                        normalize_tdx_daily_row(
                            raw,
                            provider_server=(
                                f"{servers[server_index - 1][0]}:{servers[server_index - 1][1]}"
                                if server_index - 1 < len(servers)
                                else "unknown"
                            ),
                            fetched_at=fetched_at,
                            run_id=run_id,
                        )
                    )
                except ProviderMalformedRowError as exc:
                    failures.append(exc)
            else:
                rows.append(raw)
    try:
        api.disconnect()
    except Exception:
        pass
    rows.sort(key=lambda row: (row["code"], row["trade_date"]))
    return rows, failures
