"""Tencent daily-bar adapter for ADR-008 (confirmation).

Tencent's ``stock_zh_a_hist_tx`` volume has been observed in both SHARES and
LOTS semantics.  The adapter therefore emits the raw volume plus its declared
source unit and leaves unit resolution to the deterministic whole-row
reconciliation step, which validates against the TDX primary row.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import time
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from limit_pullback.providers.errors import (
    ProviderEmptyResultError,
    ProviderError,
    ProviderMalformedRowError,
    ProviderUnexpectedError,
)
from limit_pullback.warehouse.units import as_text, decimal_from

PROVIDER_NAME = "TENCENT"
PRICE_QUANTUM = Decimal("0.0001")
AMOUNT_QUANTUM = Decimal("0.00000001")
LOT_SIZE = Decimal("100")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _quantize(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def normalize_tencent_daily_row(
    raw: Mapping[str, Any],
    *,
    fetched_at: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Convert one raw Tencent row into the typed ADR-008 row shape.

    Volume is kept raw with ``volume_unit=None`` until reconciliation detects
    SHARES vs LOTS against the TDX primary row.
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
    volume_raw = decimal_from(raw.get("volume_shares") or raw.get("volume"))
    amount = decimal_from(raw.get("amount"))
    if any(value is None for value in prices.values()) or volume_raw is None or amount is None:
        raise ProviderMalformedRowError(
            "incomplete OHLC/volume/amount fields",
            provider=PROVIDER_NAME,
            run_id=run_id,
        )
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
        "open": _quantize(prices["open"], PRICE_QUANTUM),
        "high": _quantize(prices["high"], PRICE_QUANTUM),
        "low": _quantize(prices["low"], PRICE_QUANTUM),
        "close": _quantize(prices["close"], PRICE_QUANTUM),
        "volume_raw": volume_raw,
        "volume_unit": None,
        "amount": _quantize(amount, AMOUNT_QUANTUM),
        "provider": PROVIDER_NAME,
        "fetched_at": (fetched_at or _utc_now()).isoformat(timespec="seconds"),
        "raw_hash": raw_hash,
        "source_unit": "UNKNOWN",
        "normalized_unit": "SHARES",
        "price_domain": "RAW_UNADJUSTED",
        "adjust": "",
    }


def detect_tencent_volume_unit(
    raw_volume: Decimal,
    tdx_shares: Decimal,
    *,
    volume_relative_tolerance: Decimal = Decimal("0.005"),
) -> tuple[str, Decimal | None, Decimal | None]:
    """Detect SHARES/LOTS deterministically against the TDX primary volume.

    Returns ``(unit, normalized_shares, ratio)``; ``unit`` is UNKNOWN when the
    raw volume matches neither semantic within tolerance.
    """

    if tdx_shares <= 0 or raw_volume <= 0:
        return "UNKNOWN", None, None
    ratio_shares = tdx_shares / raw_volume
    ratio_lots = tdx_shares / (raw_volume * LOT_SIZE)
    if abs(ratio_shares - Decimal("1")) <= volume_relative_tolerance:
        return "SHARES", _quantize(raw_volume, Decimal("1")), ratio_shares
    if abs(ratio_lots - Decimal("1")) <= volume_relative_tolerance:
        return (
            "LOTS",
            _quantize(raw_volume * LOT_SIZE, Decimal("1")),
            ratio_lots,
        )
    return "UNKNOWN", None, None


def fetch_tencent_daily(
    codes: Sequence[str],
    *,
    sessions: Sequence[date],
    cache_dir: Path | None = None,
    workers: int = 6,
    retries: int = 2,
    run_id: str | None = None,
    clock: Callable[[], datetime] = _utc_now,
    fetch_one: Callable[[str], list[dict[str, Any]]] | None = None,
    normalize: bool = True,
) -> tuple[list[dict[str, Any]], list[ProviderError]]:
    """Fetch Tencent daily bars (confirm path) with typed failures.

    Cached per-code parquet files are reused when present.  Failures are
    returned explicitly; nothing is silently skipped.
    """

    from concurrent.futures import ThreadPoolExecutor, as_completed

    normalized_codes = tuple(sorted({str(code).zfill(6) for code in codes}))
    session_set = set(sessions)
    failures: list[ProviderError] = []
    rows: list[dict[str, Any]] = []
    fetched_at = clock()

    def one(code: str) -> list[dict[str, Any]]:
        if fetch_one is not None:
            return fetch_one(code) or []
        return _fetch_one_tencent(
            code,
            sessions=sessions,
            cache_dir=cache_dir,
            retries=retries,
            run_id=run_id,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, code): code for code in normalized_codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                code_rows = future.result()
            except ProviderError as exc:
                failures.append(exc)
                continue
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
            if normalize:
                for row in code_rows:
                    try:
                        rows.append(
                            normalize_tencent_daily_row(
                                row,
                                fetched_at=fetched_at,
                                run_id=run_id,
                            )
                        )
                    except ProviderMalformedRowError as exc:
                        failures.append(exc)
            else:
                rows.extend(code_rows)
    rows.sort(key=lambda row: (row["code"], row["trade_date"]))
    return rows, failures


def _fetch_one_tencent(
    code: str,
    *,
    sessions: Sequence[date],
    cache_dir: Path | None,
    retries: int,
    run_id: str | None,
) -> list[dict[str, Any]]:
    import akshare as ak

    cached = cache_dir / f"{code}.parquet" if cache_dir is not None else None
    if cached is not None and cached.exists():
        import pandas as pd

        return pd.read_parquet(cached).to_dict(orient="records")
    start = min(sessions).strftime("%Y%m%d") if sessions else None
    end = max(sessions).strftime("%Y%m%d") if sessions else None
    df = None
    last_error: ProviderError | None = None
    for attempt in range(1, retries + 1):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                df = ak.stock_zh_a_hist_tx(
                    symbol=code,
                    start_date=start,
                    end_date=end,
                    adjust="",
                )
            break
        except Exception as exc:
            last_error = ProviderUnexpectedError.wrap(
                exc,
                provider=PROVIDER_NAME,
                requested_from=min(sessions) if sessions else None,
                requested_to=max(sessions) if sessions else None,
                attempt=attempt,
                run_id=run_id,
            )
            time.sleep(1.0)
    if df is None:
        raise last_error or ProviderEmptyResultError(
            f"no rows for {code}",
            provider=PROVIDER_NAME,
            requested_from=min(sessions) if sessions else None,
            requested_to=max(sessions) if sessions else None,
            run_id=run_id,
        )
    out: list[dict[str, Any]] = []
    session_set = set(sessions)
    for _, row in df.iterrows():
        day_text = str(row["date"])
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue
        if day not in session_set:
            continue
        raw = {key: str(value) for key, value in row.items()}
        raw_hash = hashlib.sha256(
            json.dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        out.append(
            {
                "code": code,
                "trade_date": day,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume_shares": row["volume"],
                "amount": row["amount"],
                "raw_hash": raw_hash,
            }
        )
    if out and cached is not None:
        import pandas as pd

        pd.DataFrame(out).to_parquet(cached, index=False)
    return out
