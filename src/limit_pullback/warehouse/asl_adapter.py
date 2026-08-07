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
* All scalar values must be parsable into the expected Decimal/int forms;
  unparsable values raise :class:`AslAdapterError` (no silent NaN).
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

PIT status provenance contract (review round 3):

* ASL upstream documents: EastMoney daily status is the CURRENT ST list
  (not historical); historical ST comes from the Baostock ST-history
  backfill; historical suspension comes from ``derived_bar_gap``.
* Every ``trading_status`` row is read WITH provenance (``source``,
  ``data_version``, ``fetched_at``) and classified before use:
  - ``source == "baostock"``: trusted historical ST; accepted ONLY as
    ``status in {st, *st}`` with ``is_trading == True``; any other
    combination raises.
  - ``source == "derived_bar_gap"``: trusted historical suspension; accepted
    ONLY as ``status == "suspended"`` with ``is_trading == False``; any other
    combination raises.
  - daily current-state sources (``eastmoney`` / the daily status step label
    ``tdx_protocol``): trusted ONLY when the observation is same-session,
    i.e. ``trade_date == fetched_at`` converted to Asia/Shanghai.  Any other
    row is classified NON_PIT_EASTMONEY_STATUS and IGNORED (never used for
    is_st / trade_status / suspension, never called normal).
  - unknown source: classified UNKNOWN_STATUS, ignored, counted.
* A missing daily bar may be authorized ONLY by a TRUSTED non-trading status
  row (derived_bar_gap suspended, or same-day daily-status suspended);
  historical/current-state rows can never authorize an absence.
* ``trading_status.fetched_at`` must exist, parse, and be timezone-aware;
  malformed provenance raises (UNTRUSTED_STATUS_PROVENANCE).
* ``is_trading`` accepts actual Booleans only (strict bool contract).

Preclose seeding (review round 2): the frozen contract's predecessor is the
LAST VALID CLOSE PER CODE before the requested window -- possibly thousands
of sessions earlier (suspension, halt, holiday).  The search traverses ASL
daily-bar day partitions newest -> oldest, pruning by requested code and by
the instrument listing boundary, and stops as soon as every relevant code is
resolved; there is NO day-count correctness cutoff.  A code with no
predecessor anywhere in the available ASL history (or before its listing
boundary) is classified MISSING_PRECLOSE, never guessed.

Determinism: the returned slice is a pure function of
(asl_root, tested_compat_revision, start, as_of, universe prefixes).
``tested_compat_revision`` is declarative provenance for the ASL revision the
adapter was developed and parity-tested against; the actual runtime contract
validated from the lake itself is: required datasets present, required
columns present, scalar values parsable, ``daily_bars.data_version == v2``
(shares unit semantics).  Arrow schema *types* are not explicitly validated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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

KNOWN_STATUS = frozenset({"normal", "st", "*st", "suspended"})
BAOSTOCK_STATUS_SOURCE = "baostock"
DERIVED_BAR_GAP_STATUS_SOURCE = "derived_bar_gap"
#: The daily trading-status step currently stamps the tdx_protocol client
#: label although the data is the EastMoney current-state ST/suspend feed.
DAILY_STATUS_SOURCES = frozenset({"eastmoney", "tdx_protocol"})
SHANGHAI_TZ = timezone(timedelta(hours=8))

TRUSTED_STATUS_KINDS = frozenset(
    {"BAOSTOCK_ST", "DERIVED_GAP_SUSPENDED", "EASTMONEY_SAME_DAY"}
)

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


def _to_decimal(
    value: object | None,
    *,
    code: str,
    day: date,
    field: str,
) -> Decimal | None:
    """Parse one scalar into Decimal; unparsable values fail closed."""

    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 — any malformed value fails closed
        raise AslAdapterError(
            f"UNPARSABLE_VALUE:{code}:{day}:{field}:{value!r}"
        ) from exc


def _checked_status(status: str, *, code: str, day: date) -> str:
    """Validate the status vocabulary BEFORE any branch uses it."""

    status_lower = status.lower()
    if status_lower not in KNOWN_STATUS:
        raise AslAdapterError(
            f"UNSUPPORTED_STATUS:{code}:{day}:{status!r}"
        )
    return status_lower


def _strict_bool(value: object, *, where: str) -> bool:
    """Accept actual Booleans only; strings like ``"False"`` fail closed."""

    if not isinstance(value, bool):
        raise AslAdapterError(f"INVALID_BOOL:{where}:{value!r}")
    return value


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
    #: Trust class of the status row that produced is_st/trade_status
    #: (BAOSTOCK_ST | DERIVED_GAP_SUSPENDED | EASTMONEY_SAME_DAY), or None
    #: when no trusted status row exists (is_st=None semantics).  Evidence
    #: only; does not change PIT behavior.
    asl_status_trust: str | None = None
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
    # PIT provenance counts (review round 3).
    trusted_baostock_n: int
    trusted_derived_gap_n: int
    trusted_eastmoney_same_day_n: int
    non_pit_eastmoney_ignored_n: int
    unknown_status_n: int


@dataclass(frozen=True)
class AslStatusRow:
    """One trading_status row with validated provenance and trust class."""

    code: str
    trade_date: date
    is_trading: bool
    status: str
    source: str
    data_version: str
    fetched_at: datetime
    #: BAOSTOCK_ST | DERIVED_GAP_SUSPENDED | EASTMONEY_SAME_DAY |
    #: NON_PIT_EASTMONEY | UNKNOWN_STATUS
    trust: str


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
    root: Path, start: date | None, hi: date
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
            # daily_bars/calendar/status probes cover the requested window;
            # the predecessor search reads older partitions with its own
            # bounds and validates the same contract at read time.
            in_range = [
                path
                for key, path in sorted(partitions.items())
                if _overlaps(key, kind, start, hi)
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
                _strict_bool(is_trading, where=f"trading_calendar:{trade_date}")
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
) -> dict[tuple[str, date], AslStatusRow]:
    """{(code, trade_date): AslStatusRow with validated provenance}.

    Raises on: duplicate PK, non-Boolean is_trading, unknown status
    vocabulary, unexpected source/semantics combinations, or malformed
    fetched_at.  NON_PIT_EASTMONEY / UNKNOWN_STATUS rows are classified (not
    raised) and later ignored.
    """

    result: dict[tuple[str, date], AslStatusRow] = {}
    partitions = _hive_partitions(root / "curated" / "trading_status", "month")
    for key, path in sorted(partitions.items()):
        if not _overlaps(key, "month", start, as_of):
            continue
        for file_path in sorted(path.glob("*.parquet")):
            table = pq.ParquetFile(file_path).read(
                columns=[
                    "symbol", "trade_date", "is_trading", "status",
                    "source", "data_version", "fetched_at",
                ]
            )
            for symbol, trade_date, is_trading, status, source, data_version, fetched_at in zip(
                table.column("symbol").to_pylist(),
                table.column("trade_date").to_pylist(),
                table.column("is_trading").to_pylist(),
                table.column("status").to_pylist(),
                table.column("source").to_pylist(),
                table.column("data_version").to_pylist(),
                table.column("fetched_at").to_pylist(),
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
                code = match.group(1)
                is_trading_bool = _strict_bool(
                    is_trading, where=f"trading_status:{code}:{day}"
                )
                status_text = _checked_status(str(status or ""), code=code, day=day)
                source_text = str(source or "").lower()
                parsed_fetched_at = _parse_fetched_at(fetched_at)
                if parsed_fetched_at is None:
                    raise AslAdapterError(
                        f"UNTRUSTED_STATUS_PROVENANCE:{code}:{day}:"
                        f"fetched_at={fetched_at!r}"
                    )
                trust = _classify_status_provenance(
                    code=code,
                    day=day,
                    status=status_text,
                    is_trading=is_trading_bool,
                    source=source_text,
                    fetched_at=parsed_fetched_at,
                )
                result[key_row] = AslStatusRow(
                    code=code,
                    trade_date=day,
                    is_trading=is_trading_bool,
                    status=status_text,
                    source=source_text,
                    data_version=str(data_version or ""),
                    fetched_at=parsed_fetched_at,
                    trust=trust,
                )
    return result


def _classify_status_provenance(
    *,
    code: str,
    day: date,
    status: str,
    is_trading: bool,
    source: str,
    fetched_at: datetime,
) -> str:
    """PIT trust classification for one trading_status row.

    Raises on known-source rows with unexpected semantic combinations; a
    daily current-state row whose fetched Shanghai date differs from
    trade_date is classified NON_PIT_EASTMONEY (ignored later); an
    unrecognized source is classified UNKNOWN_STATUS (ignored later).
    """

    if source == BAOSTOCK_STATUS_SOURCE:
        if status not in {"st", "*st"} or not is_trading:
            raise AslAdapterError(
                f"UNEXPECTED_STATUS_SEMANTICS:{code}:{day}:"
                f"source=baostock status={status!r} is_trading={is_trading}"
            )
        return "BAOSTOCK_ST"
    if source == DERIVED_BAR_GAP_STATUS_SOURCE:
        if status != "suspended" or is_trading:
            raise AslAdapterError(
                f"UNEXPECTED_STATUS_SEMANTICS:{code}:{day}:"
                f"source=derived_bar_gap status={status!r} is_trading={is_trading}"
            )
        return "DERIVED_GAP_SUSPENDED"
    if source in DAILY_STATUS_SOURCES:
        shanghai_date = fetched_at.astimezone(SHANGHAI_TZ).date()
        if shanghai_date == day:
            return "EASTMONEY_SAME_DAY"
        return "NON_PIT_EASTMONEY"
    return "UNKNOWN_STATUS"


def _read_bars(
    root: Path,
    codes: set[str],
    lo: date,
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


def _find_predecessor_closes(
    root: Path,
    codes: set[str],
    instruments: dict[str, tuple[str, date | None, date | None]],
    start: date,
) -> dict[str, Decimal]:
    """Last valid close per code strictly before *start* (partition-pruned
    backward search, newest -> oldest).  No day-count cutoff.

    The search stops per code at its listing boundary (no bars can exist
    before ``list_date``) and globally once every relevant code is resolved.
    Codes with no predecessor anywhere in the available ASL history are left
    out of the result (-> MISSING_PRECLOSE at row construction).
    """

    partitions = _hive_partitions(root / "curated" / "daily_bars", "day")
    before_start = sorted(
        (
            (date.fromisoformat(key), path)
            for key, path in partitions.items()
            if date.fromisoformat(key) < start
        ),
        key=lambda item: item[0],
        reverse=True,
    )

    unresolved = set(codes)
    predecessor_close: dict[str, Decimal] = {}
    for partition_date, path in before_start:
        if not unresolved:
            break
        # Listing boundary: a code listed at/after *start* can never have a
        # predecessor; a partition older than list_date cannot contain its bars.
        for code in list(unresolved):
            list_date = instruments[code][1]
            if list_date is not None and list_date >= start:
                unresolved.discard(code)
            elif list_date is not None and partition_date < list_date:
                unresolved.discard(code)
        if not unresolved:
            break
        # Partition-scoped duplicate validation: snapshot the unresolved
        # codes, read ALL of their rows in this partition, validate every PK,
        # and only then choose the positive-close candidate per code.
        partition_codes = set(unresolved)
        partition_rows: list[tuple[str, date, Decimal]] = []
        seen_in_partition: dict[tuple[str, date], int] = {}
        for file_path in sorted(path.glob("*.parquet")):
            table = pq.ParquetFile(file_path).read(
                columns=["symbol", "trade_date", "close", "data_version"]
            )
            for symbol, trade_date, close, data_version in zip(
                table.column("symbol").to_pylist(),
                table.column("trade_date").to_pylist(),
                table.column("close").to_pylist(),
                table.column("data_version").to_pylist(),
                strict=True,
            ):
                match = _SYMBOL_RE.match(str(symbol))
                if match is None or match.group(1) not in partition_codes:
                    continue
                code = match.group(1)
                day = trade_date if isinstance(trade_date, date) else date.fromisoformat(str(trade_date))
                if str(data_version or "") != DAILY_BARS_SHARES_VERSION:
                    raise AslAdapterError(
                        f"daily_bars.data_version={data_version!r} != v2 "
                        f"(first at {code} {day}); volume unit not guaranteed"
                    )
                pk = (code, day)
                seen_in_partition[pk] = seen_in_partition.get(pk, 0) + 1
                if seen_in_partition[pk] > 1:
                    raise AslAdapterError(
                        f"duplicate daily_bars PK: {code} {day} "
                        f"(count {seen_in_partition[pk]})"
                    )
                close_value = _to_decimal(
                    close, code=code, day=day, field="predecessor_close"
                )
                if close_value is not None and close_value > 0:
                    partition_rows.append((code, day, close_value))
        # Whole partition passed validation: resolve candidates now.
        for code, day, close_value in partition_rows:
            if code in unresolved:
                predecessor_close[code] = close_value
                unresolved.discard(code)
    return predecessor_close


def _status_mapping(
    status_row: AslStatusRow | None,
    *,
    code: str,
    day: date,
    volume: Decimal,
) -> tuple[bool | None, bool | None]:
    """Provenance-aware status semantics.

    ``status_row`` must already be trust-classified by the caller (only
    TRUSTED_STATUS_KINDS reach this function); NON_PIT_EASTMONEY and
    UNKNOWN_STATUS rows are never passed here.
    """

    if status_row is None:
        if volume == 0:
            return False, None  # zero-volume placeholder without status row
        return True, None  # positive bar, ST unknown: never claim normal
    if status_row.trust == "BAOSTOCK_ST":
        return True, True
    if status_row.trust == "DERIVED_GAP_SUSPENDED":
        return False, None
    # EASTMONEY_SAME_DAY
    if not status_row.is_trading or status_row.status == "suspended":
        return False, True if status_row.status in {"st", "*st"} else None
    if status_row.status == "normal":
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
    _validate_required_datasets(root, start, as_of)

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
    bars = _read_bars(root, universe_codes, start, as_of)
    predecessor_close = (
        _find_predecessor_closes(root, universe_codes, instruments, start)
        if start is not None
        else {}
    )

    trusted_rows = {
        key: row
        for key, row in status_rows.items()
        if row.trust in TRUSTED_STATUS_KINDS
    }
    sessions_without_status = sum(
        1
        for code in sorted(universe_codes)
        for day in sessions
        if (code, day) not in trusted_rows
    )
    status_coverage = AslStatusCoverage(
        dataset_present=True,
        status_rows_in_window=len(status_rows),
        sessions_with_status_row=len(trusted_rows),
        sessions_without_status_row=sessions_without_status,
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
    if status_coverage.non_pit_eastmoney_ignored_n:
        warnings_note = (
            f"{status_coverage.non_pit_eastmoney_ignored_n} "
            "NON_PIT_EASTMONEY status row(s) ignored (fetched Shanghai date "
            "!= trade_date)"
        )
    else:
        warnings_note = ""
    if status_coverage.unknown_status_n:
        warnings_note = (
            (warnings_note + "; " if warnings_note else "")
            + f"{status_coverage.unknown_status_n} UNKNOWN status source row(s) ignored"
        )

    bars_by_code: dict[str, dict[date, dict[str, object]]] = {}
    for row in bars:
        code = str(row["code"])
        day = row["trade_date"]
        bars_by_code.setdefault(code, {})[day] = row

    emitted: list[AslDailyBarRow] = []
    suspended_sessions: list[tuple[str, date]] = []
    missing_required_bars: list[MissingRequiredBar] = []
    warnings: list[str] = []
    if warnings_note:
        warnings.append(warnings_note)

    for code in sorted(universe_codes):
        previous_close = predecessor_close.get(code)
        list_date, delist_date = instruments[code][1], instruments[code][2]
        for day in sessions:
            bar = bars_by_code.get(code, {}).get(day)
            if bar is None:
                status_row = status_rows.get((code, day))
                trusted = (
                    status_row
                    if status_row is not None
                    and status_row.trust in TRUSTED_STATUS_KINDS
                    else None
                )
                if trusted is not None and (
                    trusted.trust == "DERIVED_GAP_SUSPENDED"
                    or (
                        trusted.trust == "EASTMONEY_SAME_DAY"
                        and (not trusted.is_trading or trusted.status == "suspended")
                    )
                ):
                    # Absence authorized ONLY by a trusted non-trading row
                    # (PIT contract: derived_bar_gap or same-day observation).
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

            open_value = _to_decimal(bar["open"], code=code, day=day, field="open")
            high = _to_decimal(bar["high"], code=code, day=day, field="high")
            low = _to_decimal(bar["low"], code=code, day=day, field="low")
            close = _to_decimal(bar["close"], code=code, day=day, field="close")
            volume = _to_decimal(bar["volume"], code=code, day=day, field="volume")
            amount_raw = bar.get("amount")
            amount = (
                _quantize(
                    _to_decimal(
                        amount_raw, code=code, day=day, field="amount"
                    ),
                    AMOUNT_QUANTUM,
                )
                if amount_raw is not None
                else None
            )
            if (
                open_value is None or high is None or low is None
                or close is None or volume is None
            ):
                raise AslAdapterError(
                    f"MISSING_REQUIRED_BAR_FIELDS:{code}:{day}"
                )

            trade_status, is_st = _status_mapping(
                (
                    status_rows.get((code, day))
                    if status_rows.get((code, day)) is not None
                    and status_rows[(code, day)].trust in TRUSTED_STATUS_KINDS
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
                row_status: RowStatus = "MISSING_PRECLOSE"
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
                    asl_status_trust=(
                        status_rows[(code, day)].trust
                        if status_rows.get((code, day)) is not None
                        and status_rows[(code, day)].trust in TRUSTED_STATUS_KINDS
                        else None
                    ),
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
