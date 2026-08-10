"""Official ASL Query API -> V Flash frozen daily fact contract (PRIMARY path).

Production read boundary: ``ashare_lake.query.load()`` / ``scan()`` ONLY.
This module NEVER opens files under ``curated/**/*.parquet`` directly:
physical parquet discovery / partition pruning / schema loading / dataset
reads belong to ASL.

V Flash keeps only its owned semantics:

* symbol -> six-digit code
* frozen sequential previous-valid-close (predecessor before START is
  resolved through the official Query API, lazily)
* frozen pct_change
* PIT trading_status trust interpretation (pure helpers reused verbatim
  from ``asl_adapter``, the migration fallback reader)
* SH/SZ main-board AS_OF pre-ST scope
* missing-session fail-closed guard (MISSING_REQUIRED_BAR)

Historical strategy bars are always queried with ``adjust=None`` and
``universe=None``: ST/suspended historical bars stay in real price history
(``universe="all_a"`` is never used for strategy input).

The module emits facts compatible with the existing ``AslDailySlice`` /
``AslDailyBarRow`` contract so downstream snapshot code (e.g.
``asl_rows_to_canonical_rows``) is unchanged.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

try:
    import polars as pl
    import polars.exceptions as _pl_exc

    from ashare_lake.domain.schemas import SchemaValidationError
    from ashare_lake.query import load, resolve_config, scan
    from ashare_lake.query.reader import ReaderError

    _ASL_QUERY_OK = True
except ImportError:  # pragma: no cover - default V Flash env without ASL
    pl = None  # type: ignore[assignment]
    _pl_exc = None  # type: ignore[assignment]
    SchemaValidationError = ()  # type: ignore[assignment,misc]
    ReaderError = ()  # type: ignore[assignment,misc]
    load = None  # type: ignore[assignment]
    resolve_config = None  # type: ignore[assignment]
    scan = None  # type: ignore[assignment]
    _ASL_QUERY_OK = False

#: Query-layer errors that mean "malformed/inconsistent ASL data" and must
#: surface through V Flash's typed fail-closed contract.
_QUERY_ERRORS = (
    (ReaderError, SchemaValidationError, _pl_exc.SchemaError)
    if _ASL_QUERY_OK
    else ()
)


def _ensure_query_api() -> None:
    """Fail closed with the V Flash typed error when the official ASL Query
    API is not importable in this environment."""

    if not _ASL_QUERY_OK:
        raise AslAdapterError(
            "ASL_QUERY_API_UNAVAILABLE: ashare_lake.query is not installed"
        )

from limit_pullback.warehouse.asl_adapter import (
    AMOUNT_QUANTUM,
    CONTRACT_VERSION,
    FROZEN_UNIVERSE_PREFIXES,
    PCT_QUANTUM,
    PRICE_QUANTUM,
    TESTED_COMPAT_REVISION,
    AslDailyBarRow,
    AslDailySlice,
    AslStatusCoverage,
    AslStatusRow,
    AslAdapterError,
    MissingRequiredBar,
    _checked_status,
    _classify_status_provenance,
    _parse_fetched_at,
    _pct_change,
    _quantize,
    _status_mapping,
    _strict_bool,
)

#: Bounded symbol chunk size (internal; official query API does the reads).
ASL_QUERY_CHUNK_SIZE = 512

#: Predecessor lookup: any bar before START that ASL carries (this lake's
#: bars begin 2024-01-02; the hive partition prune bounds the scan).
PREDECESSOR_END_OFFSET_DAYS = 1


def _symbol(code: str) -> str:
    return code + (".SH" if code.startswith("6") else ".SZ")


def _code(symbol: str) -> str:
    return str(symbol).split(".")[0].zfill(6)


def _field_decimal(
    value: Any, code: str, day: date, field: str
) -> Decimal:
    """Parsable-value fail-closed contract (unparsable/None fails closed)."""

    if value is None:
        raise AslAdapterError(
            f"UNPARSABLE_VALUE:{code}:{day}:{field}:{value!r}"
        )
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - unparsable fails closed
        raise AslAdapterError(
            f"UNPARSABLE_VALUE:{code}:{day}:{field}:{value!r}"
        ) from exc


def _wrap_query_errors(fn):
    """Preserve V Flash's typed fail-closed contract for ASL query errors."""

    try:
        return fn()
    except _QUERY_ERRORS as exc:
        raise AslAdapterError(str(exc)) from exc


def _load_instruments(asl_root: Path) -> dict[str, dict[str, Any]]:
    """{code: {symbol, list_date, delist_date}} via the official query API."""

    _ensure_query_api()

    def _run():
        return load("instruments", data_root=asl_root)

    df = _wrap_query_errors(_run)
    out: dict[str, dict[str, Any]] = {}
    for record in df.to_dicts():
        symbol = str(record["symbol"])
        code = _code(symbol)
        if code in out:
            raise AslAdapterError(f"duplicate instruments PK: {code} ({symbol!r})")
        out[code] = {
            "symbol": symbol,
            "list_date": record.get("list_date"),
            "delist_date": record.get("delist_date"),
        }
    return out


def _load_calendar_sessions(
    asl_root: Path, start: date | None, as_of: date
) -> tuple[date, ...]:
    _ensure_query_api()

    def _run():
        return load(
            "trading_calendar",
            start=start,
            end=as_of,
            data_root=asl_root,
        )

    df = _wrap_query_errors(_run)
    sessions: set[date] = set()
    for record in df.to_dicts():
        day = record["trade_date"]
        is_trading = _strict_bool(
            record["is_trading"], where=f"trading_calendar:{day}"
        )
        if not is_trading:
            continue
        if day in sessions:
            raise AslAdapterError(f"duplicate trading_calendar PK: {day}")
        sessions.add(day)
    return tuple(sorted(sessions))


def _query_status_rows(
    asl_root: Path,
    codes: Sequence[str],
    start: date | None,
    as_of: date,
) -> dict[tuple[str, date], AslStatusRow]:
    """Trust-classified trading_status rows via the official query API."""

    _ensure_query_api()

    def _run():
        return load(
            "trading_status",
            symbols=[_symbol(c) for c in codes],
            start=start,
            end=as_of,
            data_root=asl_root,
        )

    df = _wrap_query_errors(_run)
    out: dict[tuple[str, date], AslStatusRow] = {}
    for record in df.to_dicts():
        code = _code(str(record["symbol"]))
        day = record["trade_date"]
        if day > as_of:
            continue
        if start is not None and day < start:
            continue
        is_trading = _strict_bool(
            record["is_trading"], where=f"trading_status:{code}:{day}"
        )
        status = _checked_status(str(record["status"] or ""), code=code, day=day)
        source = str(record["source"] or "").lower()
        fetched_at = _parse_fetched_at(record["fetched_at"])
        if fetched_at is None:
            raise AslAdapterError(
                f"UNTRUSTED_STATUS_PROVENANCE:{code}:{day}:fetched_at="
                f"{record['fetched_at']!r}"
            )
        key = (code, day)
        if key in out:
            raise AslAdapterError(f"duplicate trading_status PK: {code} {day}")
        out[key] = AslStatusRow(
            code=code,
            trade_date=day,
            is_trading=is_trading,
            status=status,
            source=source,
            data_version=str(record.get("data_version") or ""),
            fetched_at=fetched_at,
            trust=_classify_status_provenance(
                code=code,
                day=day,
                status=status,
                is_trading=is_trading,
                source=source,
                fetched_at=fetched_at,
            ),
        )
    return out


def _query_bars(
    asl_root: Path,
    symbols: Sequence[str],
    start: date | None,
    end: date | None,
) -> list[dict[str, Any]]:
    """Official daily_bars query (adjust=None, universe=None)."""

    _ensure_query_api()

    def _run():
        return load(
            "daily_bars",
            symbols=list(symbols),
            start=start,
            end=end,
            adjust=None,
            universe=None,
            data_root=asl_root,
        )

    df = _wrap_query_errors(_run)
    out: list[dict[str, Any]] = []
    seen: dict[tuple[str, date], int] = {}
    for record in df.to_dicts():
        code = _code(str(record["symbol"]))
        day = record["trade_date"]
        if str(record.get("data_version") or "") != "v2":
            raise AslAdapterError(
                f"daily_bars.data_version={record.get('data_version')!r} != v2 "
                f"(first at {code} {day}); volume unit not guaranteed"
            )
        pk = (code, day)
        seen[pk] = seen.get(pk, 0) + 1
        if seen[pk] > 1:
            raise AslAdapterError(
                f"duplicate daily_bars PK: {code} {day} (count {seen[pk]})"
            )
        out.append(
            {
                "code": code,
                "trade_date": day,
                "open": record["open"],
                "high": record["high"],
                "low": record["low"],
                "close": record["close"],
                "volume": record["volume"],
                "amount": record.get("amount"),
                "source": str(record.get("source") or ""),
                "data_version": str(record.get("data_version") or ""),
                "fetched_at": record.get("fetched_at"),
            }
        )
    out.sort(key=lambda row: (row["code"], row["trade_date"]))
    return out


def _predecessor_closes(
    asl_root: Path,
    symbols: Sequence[str],
    before: date,
) -> dict[str, Decimal]:
    """Latest valid close per symbol strictly before *before* (lazy scan,
    bounded reduce — never materializes the full pre-START history)."""

    if not symbols:
        return {}
    _ensure_query_api()

    def _run():
        return scan(
            "daily_bars",
            symbols=list(symbols),
            end=before - timedelta(days=PREDECESSOR_END_OFFSET_DAYS),
            data_root=asl_root,
        )

    lazy = _wrap_query_errors(_run)
    reduced = (
        lazy.filter(pl.col("close") > 0)
        .sort("trade_date")
        .group_by("symbol")
        .last()
        .select(["symbol", "close"])
        .collect()
    )
    return {
        _code(str(record["symbol"])): Decimal(str(record["close"]))
        for record in reduced.to_dicts()
    }


def query_asof_scope(
    asl_root: str | Path,
    as_of: date,
    universe_prefixes: Sequence[str] = FROZEN_UNIVERSE_PREFIXES,
) -> tuple[str, ...]:
    """AS_OF pre-ST market scope from the official Query API only.

    Rules (unchanged): SH/SZ main-board prefix, instrument exists, listed on
    *as_of*, not delisted, AS_OF bar exists with positive volume.  ST is NOT
    applied here.  Fail closed when the AS_OF market data is not readable
    (trading day with zero AS_OF bars for the main-board scope).
    """

    root = Path(asl_root).expanduser().resolve()
    instruments = _load_instruments(root)
    sessions = _load_calendar_sessions(root, None, as_of)
    prefix_tuple = tuple(universe_prefixes)
    universe_codes = {
        code
        for code, inst in instruments.items()
        if code.startswith(prefix_tuple)
    }
    asof_bars = _query_bars(
        root,
        [_symbol(code) for code in sorted(universe_codes)],
        as_of,
        as_of,
    )
    if as_of in sessions and not asof_bars:
        raise AslAdapterError(
            f"MISSING_REQUIRED_BAR:AS_OF_SCOPE:{as_of}:"
            "zero AS_OF daily_bars rows for the main-board scope"
        )
    asof_volume: dict[str, Decimal] = {}
    for row in asof_bars:
        code = row["code"]
        try:
            volume = Decimal(str(row["volume"]))
        except Exception as exc:  # noqa: BLE001 - unparsable fails closed
            raise AslAdapterError(
                f"UNPARSABLE_VALUE:{code}:{as_of}:volume:{row['volume']!r}"
            ) from exc
        asof_volume[code] = volume

    out: list[str] = []
    for code, inst in instruments.items():
        if code not in universe_codes:
            continue
        if inst["list_date"] is not None and as_of < inst["list_date"]:
            continue
        if inst["delist_date"] is not None and as_of >= inst["delist_date"]:
            continue
        volume = asof_volume.get(code)
        if volume is None or volume <= 0:
            continue
        out.append(code)
    return tuple(sorted(out))


def query_daily_facts(
    asl_root: str | Path,
    *,
    as_of: date,
    start: date | None,
    codes: Sequence[str],
    universe_prefixes: Sequence[str] = FROZEN_UNIVERSE_PREFIXES,
    chunk_size: int = ASL_QUERY_CHUNK_SIZE,
) -> Iterator[AslDailySlice]:
    """Official-query daily facts, one AslDailySlice per bounded code chunk.

    Per chunk: predecessor (lazy scan) -> window bars (load) -> trusted
    status (load) -> calendar-gap fail-closed loop -> AslDailySlice with the
    existing AslDailyBarRow contract.
    """

    root = Path(asl_root).expanduser().resolve()
    requested = tuple(
        sorted(
            str(code).zfill(6)
            for code in codes
            if str(code).zfill(6).isdigit() and len(str(code).zfill(6)) == 6
        )
    )
    instruments = _load_instruments(root)
    sessions = _load_calendar_sessions(root, start, as_of)

    for index in range(0, len(requested), chunk_size):
        chunk = requested[index : index + chunk_size]
        symbols = [_symbol(code) for code in chunk]

        predecessor_close = (
            _predecessor_closes(root, symbols, start) if start is not None else {}
        )
        bars = _query_bars(root, symbols, start, as_of)
        status_rows = _query_status_rows(root, chunk, start, as_of)

        bars_by_code: dict[str, dict[date, dict[str, Any]]] = {}
        for row in bars:
            bars_by_code.setdefault(row["code"], {})[row["trade_date"]] = row

        emitted: list[AslDailyBarRow] = []
        suspended_sessions: list[tuple[str, date]] = []
        missing_required_bars: list[MissingRequiredBar] = []
        for code in chunk:
            inst = instruments.get(code)
            previous_close = predecessor_close.get(code)
            for day in sessions:
                bar = bars_by_code.get(code, {}).get(day)
                if bar is None:
                    status_row = status_rows.get((code, day))
                    trusted = (
                        status_row
                        if status_row is not None
                        and status_row.trust
                        in ("BAOSTOCK_ST", "DERIVED_GAP_SUSPENDED", "EASTMONEY_SAME_DAY")
                        else None
                    )
                    if trusted is not None and (
                        trusted.trust == "DERIVED_GAP_SUSPENDED"
                        or (
                            trusted.trust == "EASTMONEY_SAME_DAY"
                            and (
                                not trusted.is_trading
                                or trusted.status == "suspended"
                            )
                        )
                    ):
                        missing_required_bars.append(
                            MissingRequiredBar(code, day, "SUSPENDED_BY_STATUS")
                        )
                        suspended_sessions.append((code, day))
                        continue
                    if inst is not None:
                        list_date, delist_date = inst["list_date"], inst["delist_date"]
                        if list_date is not None and day < list_date:
                            missing_required_bars.append(
                                MissingRequiredBar(code, day, "NOT_LISTED")
                            )
                            continue
                        if delist_date is not None and day >= delist_date:
                            missing_required_bars.append(
                                MissingRequiredBar(code, day, "DELISTED")
                            )
                            continue
                    raise AslAdapterError(
                        f"MISSING_REQUIRED_BAR:{code}:{day}:"
                        f"status_row={status_row}"
                    )

                open_value = _field_decimal(bar["open"], code, day, "open")
                high = _field_decimal(bar["high"], code, day, "high")
                low = _field_decimal(bar["low"], code, day, "low")
                close = _field_decimal(bar["close"], code, day, "close")
                volume = _field_decimal(bar["volume"], code, day, "volume")
                amount_raw = bar.get("amount")
                amount = (
                    _quantize(
                        _field_decimal(amount_raw, code, day, "amount"),
                        AMOUNT_QUANTUM,
                    )
                    if amount_raw is not None
                    else None
                )
                status_row = status_rows.get((code, day))
                trade_status, is_st = _status_mapping(
                    (
                        status_row
                        if status_row is not None
                        and status_row.trust
                        in ("BAOSTOCK_ST", "DERIVED_GAP_SUSPENDED", "EASTMONEY_SAME_DAY")
                        else None
                    ),
                    code=code,
                    day=day,
                    volume=volume,
                )
                if trade_status is False:
                    suspended_sessions.append((code, day))

                preclose = previous_close
                if preclose is None:
                    row_status: str = "MISSING_PRECLOSE"
                    reason = (
                        "no valid predecessor bar for this code anywhere in the "
                        "available ASL history before the requested window"
                    )
                    pct_change = None
                elif amount is None:
                    row_status = "MISSING_REQUIRED_AMOUNT"
                    reason = "ASL daily_bars.amount is null (e.g. Sina delisted rows)"
                    pct_change = _pct_change(close, preclose)
                else:
                    row_status = "VALID_ROW"
                    reason = None
                    pct_change = _pct_change(close, preclose)

                emitted.append(
                    AslDailyBarRow(
                        code=code,
                        trade_date=day,
                        open=_quantize(open_value, PRICE_QUANTUM),
                        high=_quantize(high, PRICE_QUANTUM),
                        low=_quantize(low, PRICE_QUANTUM),
                        close=_quantize(close, PRICE_QUANTUM),
                        preclose=(
                            _quantize(preclose, PRICE_QUANTUM)
                            if preclose is not None
                            else None
                        ),
                        volume=volume,
                        amount=amount,
                        turnover_rate=None,
                        pct_change=pct_change,
                        trade_status=trade_status,
                        is_st=is_st,
                        row_status=row_status,
                        reason=reason,
                        asl_source=str(bar.get("source") or ""),
                        asl_data_version=str(bar.get("data_version") or ""),
                        asl_fetched_at=_parse_fetched_at(bar.get("fetched_at")),
                        asl_status_trust=(
                            status_row.trust
                            if status_row is not None
                            and status_row.trust
                            in ("BAOSTOCK_ST", "DERIVED_GAP_SUSPENDED", "EASTMONEY_SAME_DAY")
                            else None
                        ),
                    )
                )
                if close > 0:
                    previous_close = close

        coverage = AslStatusCoverage(
            dataset_present=True,
            status_rows_in_window=len(status_rows),
            sessions_with_status_row=sum(
                1
                for (code, day), row in status_rows.items()
                if row.trust
                in ("BAOSTOCK_ST", "DERIVED_GAP_SUSPENDED", "EASTMONEY_SAME_DAY")
            ),
            sessions_without_status_row=(
                len(sessions) * len(chunk)
                - sum(
                    1
                    for (code, day), row in status_rows.items()
                    if row.trust
                    in ("BAOSTOCK_ST", "DERIVED_GAP_SUSPENDED", "EASTMONEY_SAME_DAY")
                )
            ),
            mode="PIT_PROVENANCE_CLASSIFIED",
            trusted_baostock_n=sum(
                1 for row in status_rows.values() if row.trust == "BAOSTOCK_ST"
            ),
            trusted_derived_gap_n=sum(
                1 for row in status_rows.values() if row.trust == "DERIVED_GAP_SUSPENDED"
            ),
            trusted_eastmoney_same_day_n=sum(
                1 for row in status_rows.values() if row.trust == "EASTMONEY_SAME_DAY"
            ),
            non_pit_eastmoney_ignored_n=sum(
                1 for row in status_rows.values() if row.trust == "NON_PIT_EASTMONEY"
            ),
            unknown_status_n=sum(
                1 for row in status_rows.values() if row.trust == "UNKNOWN_STATUS"
            ),
        )
        yield AslDailySlice(
            contract_version=CONTRACT_VERSION,
            tested_compat_revision=TESTED_COMPAT_REVISION,
            asl_root=str(root),
            start=start,
            as_of=as_of,
            universe_prefixes=tuple(universe_prefixes),
            rows=tuple(emitted),
            excluded_codes=(),
            missing_symbols=(),
            status_coverage=coverage,
            suspended_sessions=tuple(sorted(set(suspended_sessions))),
            missing_required_bars=tuple(
                sorted(missing_required_bars, key=lambda item: (item.code, item.trade_date))
            ),
            warnings=(),
        )
