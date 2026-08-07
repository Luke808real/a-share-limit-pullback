"""Phase-1A read-only adapter: ASL curated Parquet lake -> frozen V Flash daily facts.

Scope (Phase 1A): reads ONLY the ASL curated datasets ``daily_bars``,
``instruments``, ``trading_calendar`` and ``trading_status``.
``corporate_actions`` / ``adj_factors`` are deliberately NOT consumed: the
frozen ADR-008 preclose contract (``warehouse/continuity.py``) is a sequential
previous-close chain that does NOT adjust for corporate actions.

The adapter is NOT wired into production.  It never writes canonical data,
never promotes snapshots, never mutates ASL data, never calls network
providers, never repairs ASL, never fills missing rows silently, never
estimates turnover and never computes strategy state.

Fail-closed contract (review round 1):

* All four required datasets must exist and expose the required columns;
  any missing dataset raises :class:`AslAdapterError` (no empty valid slice).
* ``daily_bars.data_version`` must be ``v2`` (shares); any other value raises.
* Duplicate primary keys in ``daily_bars`` / ``trading_status`` /
  ``trading_calendar`` / ``instruments`` raise with deterministic evidence.
* A calendar trading session without a daily bar raises unless the absence
  is explicitly proven non-trading (suspended by ``trading_status``, not yet
  listed, or delisted); such proven absences are recorded in
  ``AslDailySlice.missing_required_bars``.
* Unknown ``trading_status.status`` vocabulary raises.

Status semantics (review round 1):

* explicit ``normal`` + ``is_trading=True``  -> trade_status=True,  is_st=False
* explicit ``st`` / ``*st`` + ``is_trading=True`` -> trade_status=True, is_st=True
* ``is_trading=False`` or ``suspended``    -> trade_status=False;
  is_st=True only when the row also says st/*st (ST knowledge is preserved
  independently of tradeability).
* missing status row + positive trading bar -> trade_status=True, is_st=None
  (the adapter never claims "normal" from absence).
* zero-volume bar with no status row -> treated as a suspended placeholder
  (trade_status=False).

Preclose seeding (review round 1): the frozen contract's predecessor is the
last valid close per code BEFORE the requested window -- possibly several
sessions earlier (suspension, halt, holiday).  The search is bounded by
``PREDECESSOR_LOOKBACK_DAYS`` behind ``start`` and uses partition pruning; a
code with no predecessor inside the bound is classified MISSING_PRECLOSE,
never guessed.

Determinism: the returned slice is a pure function of
(asl_root, tested_compat_revision, start, as_of, universe prefixes).
``tested_compat_revision`` is declarative provenance for the ASL revision the
adapter was developed and parity-tested against; the actual runtime contract
(datasets, columns, types, data_version) is validated from the lake itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Literal, Sequence

import pyarrow.parquet as pq

TESTED_COMPAT_REVISION = "ba5681a"
CONTRACT_VERSION = "VFLASH_ASL_PHASE1A_V1"

#: Frozen phase-2d0 universe prefix contract (SH/SZ main board only).
FROZEN_UNIVERSE_PREFIXES = (
    "000", "001", "002", "003",
    "600", "601", "603", "605",
)

PRICE_QUANTUM = Decimal("0.0001")
AMOUNT_QUANTUM = Decimal("0.00000001")
PCT_QUANTUM = Decimal("0.0001")

#: ASL daily_bars volume-unit contract: ``data_version == "v2"`` guarantees
#: volume in shares (see ASL docs/datasets/schema.md "成交量单位").
DAILY_BARS_SHARES_VERSION = "v2"

#: Bounded predecessor-search window behind the requested start.  This is a
#: search bound, not a correctness boundary: no predecessor inside the bound
#: yields MISSING_PRECLOSE, never a guess.
PREDECESSOR_LOOKBACK_DAYS = 400

KNOWN_STATUS = frozenset({"normal", "st", "*st", "suspended"})

RowStatus = Literal[
    "VALID_ROW",
    "MISSING_REQUIRED_AMOUNT",
    "MISSING_PRECLOSE",
]

_SYMBOL_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")
_PARTITION_RE = re.compile(r"^trade_date=(.+)$")
_DAY_KEY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_KEY = re.compile(r"^\d{4}-\d{2}$")
_YEAR_KEY = re.compile(r"^\d{4}$")


class AslAdapterError(RuntimeError):
    """Adapter-specific fail-closed error (never raised on strategy paths)."""


def _quantize(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _pct_change(close: Decimal, preclose: Decimal) -> Decimal | None:
    """Frozen rule from warehouse/continuity.py ``_pct_change``."""

    if preclose <= 0:
        return None
    return ((close - preclose) / preclose * Decimal("100")).quantize(
        PCT_QUANTUM, rounding=ROUND_HALF_UP
    )


def _parse_fetched_at(value: object | None) -> datetime | None:
    """Parse an ASL ``fetched_at`` (timestamp with UTC tz) to an aware datetime."""

    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


@dataclass(frozen=True)
class AslDailyBarRow:
    """One adapter-emitted daily fact.

    Field set follows the V Flash canonical daily contract (price decimal
    0.0001, volume shares, amount yuan 1e-8, pct_change 0.0001 percent);
    canonical persistence metadata (snapshot ids, reconciliation status) is
    out of scope for the Phase-1A adapter.
    """

    code: str
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    preclose: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    pct_change: Decimal | None
    trade_status: bool | None
    is_st: bool | None
    row_status: RowStatus
    reason: str | None
    # Provenance carried verbatim from the ASL row (input, not generated).
    asl_source: str | None
    asl_data_version: str | None
    asl_fetched_at: datetime | None
    #: Always None in Phase 1A.  ASL has no PIT-safe per-stock turnover field;
    #: no estimate may enter this contract.
    turnover_rate: Decimal | None = None


@dataclass(frozen=True)
class AslStatusCoverage:
    """Explicit trading-status coverage facts (never silently assumed)."""

    dataset_present: bool
    status_rows_in_window: int
    sessions_with_status_row: int
    sessions_without_status_row: int
    mode: str


@dataclass(frozen=True)
class MissingRequiredBar:
    """A calendar session with no daily bar whose absence is EXPLICITLY proven
    non-trading.  Any other absent bar raises :class:`AslAdapterError`."""

    code: str
    trade_date: date
    reason: str  # SUSPENDED_BY_STATUS | NOT_LISTED | DELISTED


@dataclass(frozen=True)
class AslDailySlice:
    contract_version: str
    tested_compat_revision: str
    asl_root: str
    start: date | None
    as_of: date
    universe_prefixes: tuple[str, ...]
    rows: tuple[AslDailyBarRow, ...]
    excluded_codes: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    status_coverage: AslStatusCoverage
    suspended_sessions: tuple[tuple[str, date], ...]
    missing_required_bars: tuple[MissingRequiredBar, ...]
    warnings: tuple[str, ...]


REQUIRED_COLUMNS = {
    "instruments": ("symbol", "list_date", "delist_date"),
    "trading_calendar": ("trade_date", "is_trading"),
    "daily_bars": (
        "symbol", "trade_date", "open", "high", "low", "close",
        "volume", "amount", "data_version",
    ),
    "trading_status": ("symbol", "trade_date", "is_trading", "status"),
}


def _validate_required_datasets(
    root: Path, lo: date | None, start: date | None, hi: date
) -> None:
    """Fail closed unless every required dataset exists with its columns.

    Schema is a dataset-level contract validated on the first in-range file;
    any later file that diverges fails closed at read time (ParquetFile raises
    on missing columns).  Out-of-range partitions are never opened, which also
    keeps reads bounded.
    """

    for dataset, columns in REQUIRED_COLUMNS.items():
        if dataset == "instruments":
            files = sorted((root / "curated" / dataset).rglob("*.parquet"))
            if not files:
                raise AslAdapterError(
                    f"required ASL dataset missing: {dataset}"
                )
            probe = files[0]
        else:
            kind = {
                "trading_calendar": "year",
                "daily_bars": "day",
                "trading_status": "month",
            }[dataset]
            partitions = _hive_partitions(root / "curated" / dataset, kind)
            # daily_bars is read over [lo, hi] (predecessor + window);
            # calendar/status are only read over the requested window.
            range_lo = lo if dataset == "daily_bars" else start
            in_range = [
                path
                for key, path in sorted(partitions.items())
                if _overlaps(key, kind, range_lo, hi)
            ]
            if not in_range:
                raise AslAdapterError(
                    f"required ASL dataset missing: {dataset} "
                    "(no in-range partitions)"
                )
            in_range_files = sorted(in_range[0].glob("*.parquet"))
            if not in_range_files:
                raise AslAdapterError(
                    f"required ASL dataset missing: {dataset} "
                    "(in-range partition empty)"
                )
            probe = in_range_files[0]
        names = set(pq.ParquetFile(probe).schema.names)
        missing = [column for column in columns if column not in names]
        if missing:
            raise AslAdapterError(
                f"{dataset} missing required columns {missing} in {probe.name}"
            )


def _hive_partitions(base: Path, kind: str) -> dict[str, Path]:
    """Map ``trade_date=<key>`` partition dirs to paths; fail on unknown layout."""

    pattern = {"day": _DAY_KEY, "month": _MONTH_KEY, "year": _YEAR_KEY}[kind]
    out: dict[str, Path] = {}
    if not base.exists():
        return out
    for child in sorted(base.iterdir()):
        if child.is_file():
            continue
        match = _PARTITION_RE.match(child.name)
        if match is None or pattern.match(match.group(1)) is None:
            raise AslAdapterError(
                f"unrecognized {kind} partition entry in {base}: {child.name!r}"
            )
        out[match.group(1)] = child
    return out


def _overlaps(key: str, kind: str, lo: date | None, hi: date | None) -> bool:
    if lo is None and hi is None:
        return True
    if kind == "day":
        day = date.fromisoformat(key)
        if lo is not None and day < lo:
            return False
        if hi is not None and day > hi:
            return False
        return True
    if kind == "month":
        year, month = int(key[:4]), int(key[5:7])
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    else:  # year
        year = int(key)
        start = date(year, 1, 1)
        end = date(year + 1, 1, 1)
    if lo is not None and end <= lo:
        return False
    if hi is not None and start > hi:
        return False
    return True


def _read_instruments(root: Path) -> dict[str, tuple[str, date | None, date | None]]:
    """{code: (symbol, list_date, delist_date)}; duplicate symbol -> fail closed."""

    result: dict[str, tuple[str, date | None, date | None]] = {}
    for path in sorted((root / "curated" / "instruments").rglob("*.parquet")):
        table = pq.ParquetFile(path).read(
            columns=["symbol", "list_date", "delist_date"]
        )
        for symbol, list_date, delist_date in zip(
            table.column("symbol").to_pylist(),
            table.column("list_date").to_pylist(),
            table.column("delist_date").to_pylist(),
            strict=True,
        ):
            match = _SYMBOL_RE.match(str(symbol))
            if match is None:
                continue
            code = match.group(1)
            if code in result:
                raise AslAdapterError(
                    f"duplicate instruments PK: {code} (symbol {symbol!r})"
                )
            result[code] = (
                str(symbol),
                list_date if isinstance(list_date, date) else None,
                delist_date if isinstance(delist_date, date) else None,
            )
    return result


def _read_calendar_sessions(
    root: Path, start: date | None, as_of: date
) -> tuple[date, ...]:
    """Trading sessions from ASL trading_calendar (year partitions, pruned)."""

    sessions: set[date] = set()
    partitions = _hive_partitions(root / "curated" / "trading_calendar", "year")
    for key, path in sorted(partitions.items()):
        if not _overlaps(key, "year", start, as_of):
            continue
        for file_path in sorted(path.glob("*.parquet")):
            table = pq.ParquetFile(file_path).read(
                columns=["trade_date", "is_trading"]
            )
            for trade_date, is_trading in zip(
                table.column("trade_date").to_pylist(),
                table.column("is_trading").to_pylist(),
                strict=True,
            ):
                if not is_trading:
                    continue
                day = trade_date if isinstance(trade_date, date) else date.fromisoformat(str(trade_date))
                if day > as_of:
                    continue
                if start is not None and day < start:
                    continue
                if day in sessions:
                    raise AslAdapterError(
                        f"duplicate trading_calendar PK: {day}"
                    )
                sessions.add(day)
    return tuple(sorted(sessions))


def _read_status_rows(
    root: Path,
    codes: set[str],
    start: date | None,
    as_of: date,
) -> dict[tuple[str, date], tuple[bool, str]]:
    """{(code, trade_date): (is_trading, status)}; duplicate PK -> fail closed."""

    result: dict[tuple[str, date], tuple[bool, str]] = {}
    partitions = _hive_partitions(root / "curated" / "trading_status", "month")
    for key, path in sorted(partitions.items()):
        if not _overlaps(key, "month", start, as_of):
            continue
        for file_path in sorted(path.glob("*.parquet")):
            table = pq.ParquetFile(file_path).read(
                columns=["symbol", "trade_date", "is_trading", "status"]
            )
            for symbol, trade_date, is_trading, status in zip(
                table.column("symbol").to_pylist(),
                table.column("trade_date").to_pylist(),
                table.column("is_trading").to_pylist(),
                table.column("status").to_pylist(),
                strict=True,
            ):
                match = _SYMBOL_RE.match(str(symbol))
                if match is None or match.group(1) not in codes:
                    continue
                day = trade_date if isinstance(trade_date, date) else date.fromisoformat(str(trade_date))
                if day > as_of:
                    continue
                if start is not None and day < start:
                    continue
                key_row = (match.group(1), day)
                if key_row in result:
                    raise AslAdapterError(
                        f"duplicate trading_status PK: {key_row[0]} {day}"
                    )
                result[key_row] = (bool(is_trading), str(status or ""))
    return result


def _read_bars(
    root: Path,
    codes: set[str],
    lo: date | None,
    hi: date,
) -> list[dict[str, object]]:
    """ASL daily_bars rows for *codes* in [lo, hi] (day partitions, pruned)."""

    rows: list[dict[str, object]] = []
    seen: dict[tuple[str, date], int] = {}
    partitions = _hive_partitions(root / "curated" / "daily_bars", "day")
    for key, path in sorted(partitions.items()):
        if not _overlaps(key, "day", lo, hi):
            continue
        for file_path in sorted(path.glob("*.parquet")):
            table = pq.ParquetFile(file_path).read(
                columns=[
                    "symbol", "trade_date", "open", "high", "low", "close",
                    "volume", "amount", "source", "data_version", "fetched_at",
                ]
            )
            for record in table.to_pylist():
                match = _SYMBOL_RE.match(str(record["symbol"]))
                if match is None or match.group(1) not in codes:
                    continue
                day = record["trade_date"]
                if not isinstance(day, date):
                    day = date.fromisoformat(str(day))
                if day > hi:
                    continue
                if lo is not None and day < lo:
                    continue
                data_version = str(record.get("data_version") or "")
                if data_version != DAILY_BARS_SHARES_VERSION:
                    raise AslAdapterError(
                        f"daily_bars.data_version={data_version!r} != v2 "
                        f"(first at {match.group(1)} {day}); volume unit not guaranteed"
                    )
                pk = (match.group(1), day)
                seen[pk] = seen.get(pk, 0) + 1
                if seen[pk] > 1:
                    raise AslAdapterError(
                        f"duplicate daily_bars PK: {pk[0]} {day} "
                        f"(count {seen[pk]})"
                    )
                record["code"] = match.group(1)
                record["trade_date"] = day
                rows.append(record)
    rows.sort(key=lambda row: (str(row["code"]), row["trade_date"]))
    return rows


def _status_mapping(
    status_row: tuple[bool, str] | None,
    *,
    code: str,
    day: date,
    volume: Decimal,
) -> tuple[bool | None, bool | None]:
    """Review-round-1 status semantics; unknown vocabulary fails closed."""

    if status_row is None:
        if volume == 0:
            return False, None  # zero-volume placeholder without status row
        return True, None  # positive bar, ST unknown: never claim normal
    is_trading, status = status_row
    status_lower = status.lower()
    if status_lower not in KNOWN_STATUS:
        raise AslAdapterError(
            f"UNSUPPORTED_STATUS:{code}:{day}:{status!r}"
        )
    if not is_trading or status_lower == "suspended":
        return False, True if status_lower in {"st", "*st"} else None
    if status_lower == "normal":
        return True, False
    return True, True  # st / *st and trading


def load_asl_daily_slice(
    asl_root: str | Path,
    *,
    as_of: date,
    start: date | None = None,
    codes: Sequence[str] | None = None,
    universe_prefixes: Sequence[str] = FROZEN_UNIVERSE_PREFIXES,
    tested_compat_revision: str = TESTED_COMPAT_REVISION,
) -> AslDailySlice:
    """Build a frozen-contract daily slice from an ASL lake (read-only).

    Raises :class:`AslAdapterError` on any hard contract violation (missing
    required dataset/column, non-v2 bars, duplicate PK, unknown status
    vocabulary, or a calendar session with no bar whose absence is not
    explicitly proven non-trading).
    """

    root = Path(asl_root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"asl root does not exist: {root}")
    prefixes = tuple(universe_prefixes)
    lo = start - timedelta(days=PREDECESSOR_LOOKBACK_DAYS) if start else None
    _validate_required_datasets(root, lo, start, as_of)

    instruments = _read_instruments(root)
    if codes is None:
        requested: tuple[str, ...] = tuple(
            sorted(code for code in instruments if code.startswith(prefixes))
        )
    else:
        requested = tuple(
            sorted(
                str(code).zfill(6)
                for code in codes
                if re.fullmatch(r"\d{6}", str(code).zfill(6)) is not None
            )
        )

    in_universe = tuple(code for code in requested if code.startswith(prefixes))
    excluded = tuple(code for code in requested if not code.startswith(prefixes))
    missing = tuple(code for code in in_universe if code not in instruments)
    universe_codes = set(in_universe) - set(missing)

    sessions = _read_calendar_sessions(root, start, as_of)
    status_rows = _read_status_rows(root, universe_codes, start, as_of)
    bars = _read_bars(root, universe_codes, lo, as_of)

    sessions_with_status = {
        key for key in status_rows
        if start is None or key[1] >= start
    }
    sessions_without_status = sum(
        1
        for code in sorted(universe_codes)
        for day in sessions
        if (code, day) not in sessions_with_status
    )
    status_coverage = AslStatusCoverage(
        dataset_present=True,
        status_rows_in_window=len(sessions_with_status),
        sessions_with_status_row=len(sessions_with_status),
        sessions_without_status_row=sessions_without_status,
        mode="MISSING_STATUS_ROW_MEANS_UNKNOWN_ST",
    )

    bars_by_code: dict[str, dict[date, dict[str, object]]] = {}
    predecessor_close: dict[str, Decimal] = {}
    for row in bars:
        code = str(row["code"])
        day = row["trade_date"]
        close = Decimal(str(row["close"]))
        if start is not None and day < start:
            if close > 0:
                predecessor_close[code] = close
            continue
        bars_by_code.setdefault(code, {})[day] = row

    emitted: list[AslDailyBarRow] = []
    suspended_sessions: list[tuple[str, date]] = []
    missing_required_bars: list[MissingRequiredBar] = []
    warnings: list[str] = []

    for code in sorted(universe_codes):
        previous_close = predecessor_close.get(code)
        list_date, delist_date = instruments[code][1], instruments[code][2]
        for day in sessions:
            bar = bars_by_code.get(code, {}).get(day)
            if bar is None:
                status_row = status_rows.get((code, day))
                if status_row is not None and (
                    status_row[0] is False
                    or str(status_row[1]).lower() == "suspended"
                ):
                    missing_required_bars.append(
                        MissingRequiredBar(code, day, "SUSPENDED_BY_STATUS")
                    )
                    suspended_sessions.append((code, day))
                    continue
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

            open_value = Decimal(str(bar["open"]))
            high = Decimal(str(bar["high"]))
            low = Decimal(str(bar["low"]))
            close = Decimal(str(bar["close"]))
            volume = Decimal(str(bar["volume"]))
            amount_raw = bar.get("amount")
            amount = (
                _quantize(Decimal(str(amount_raw)), AMOUNT_QUANTUM)
                if amount_raw is not None
                else None
            )

            trade_status, is_st = _status_mapping(
                status_rows.get((code, day)),
                code=code,
                day=day,
                volume=volume,
            )
            if trade_status is False:
                suspended_sessions.append((code, day))

            preclose = previous_close
            if preclose is None:
                row_status: RowStatus = "MISSING_PRECLOSE"
                reason = (
                    "no valid predecessor bar for this code within "
                    f"{PREDECESSOR_LOOKBACK_DAYS} days before start"
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
                    preclose=_quantize(preclose, PRICE_QUANTUM) if preclose is not None else None,
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
                )
            )
            if close > 0:
                previous_close = close

        if not bars_by_code.get(code):
            warnings.append(f"no ASL daily_bars rows for {code} in window")

    return AslDailySlice(
        contract_version=CONTRACT_VERSION,
        tested_compat_revision=tested_compat_revision,
        asl_root=str(root),
        start=start,
        as_of=as_of,
        universe_prefixes=prefixes,
        rows=tuple(emitted),
        excluded_codes=excluded,
        missing_symbols=missing,
        status_coverage=status_coverage,
        suspended_sessions=tuple(sorted(set(suspended_sessions))),
        missing_required_bars=tuple(sorted(
            missing_required_bars,
            key=lambda item: (item.code, item.trade_date),
        )),
        warnings=tuple(sorted(set(warnings))),
    )
