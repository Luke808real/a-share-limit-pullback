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

Output rows carry a ``row_status`` so consumers can fail closed:

    VALID_ROW
    MISSING_REQUIRED_AMOUNT   ASL bar present but amount is null (e.g. Sina
                              delisted-history rows)
    MISSING_STATUS            trading_status dataset absent/empty for the window
    MISSING_PRECLOSE          no trusted predecessor in the ASL chain
    UNSUPPORTED_SEMANTICS     ASL daily_bars row is not the shares-unit v2
                              contract, or the symbol is not parseable

Determinism: the returned slice is a pure function of
(asl_root, asl_revision, start, as_of, universe prefixes).  All reads are
sorted; no wall clock enters the output (``fetched_at`` is carried verbatim
from ASL rows as input provenance).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Literal, Sequence

import pyarrow.parquet as pq

ASL_REVISION_PIN = "ba5681a"
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

RowStatus = Literal[
    "VALID_ROW",
    "MISSING_REQUIRED_AMOUNT",
    "MISSING_STATUS",
    "MISSING_PRECLOSE",
    "UNSUPPORTED_SEMANTICS",
]

_SYMBOL_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")


def _quantize(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _pct_change(close: Decimal, preclose: Decimal) -> Decimal | None:
    """Frozen rule from warehouse/continuity.py ``_pct_change``."""

    if preclose <= 0:
        return None
    return ((close - preclose) / preclose * Decimal("100")).quantize(
        PCT_QUANTUM, rounding=ROUND_HALF_UP
    )


@dataclass(frozen=True)
class AslDailyBarRow:
    """One adapter-emitted daily fact, V Flash canonical-shaped."""

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
    asl_fetched_at: str | None


@dataclass(frozen=True)
class AslStatusCoverage:
    """Explicit trading-status coverage facts (never silently assumed)."""

    dataset_present: bool
    status_rows_in_window: int
    sessions_with_status_row: int
    sessions_without_status_row: int
    mode: str  # e.g. ASL_MISSING_ROW_NORMAL_CONVENTION / FAIL_CLOSED


@dataclass(frozen=True)
class AslDailySlice:
    contract_version: str
    asl_revision: str
    asl_root: str
    start: date | None
    as_of: date
    universe_prefixes: tuple[str, ...]
    rows: tuple[AslDailyBarRow, ...]
    excluded_codes: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    status_coverage: AslStatusCoverage
    suspended_sessions: tuple[tuple[str, date], ...]
    warnings: tuple[str, ...]


def _list_parquet(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.parquet"))


def _read_instruments(asl_root: Path) -> dict[str, str]:
    """Return {normalized 6-digit code: asl symbol} for instruments rows."""

    files = _list_parquet(asl_root / "curated" / "instruments")
    result: dict[str, str] = {}
    for path in files:
        table = pq.ParquetFile(path).read(columns=["symbol"])
        for raw in table.column("symbol").to_pylist():
            match = _SYMBOL_RE.match(str(raw))
            if match is None:
                continue
            code = match.group(1)
            result.setdefault(code, str(raw))
    return result


def _read_calendar_sessions(
    asl_root: Path, start: date | None, as_of: date
) -> tuple[date, ...]:
    """Trading sessions from ASL trading_calendar (curated only)."""

    sessions: set[date] = set()
    for path in _list_parquet(asl_root / "curated" / "trading_calendar"):
        table = pq.ParquetFile(path).read(columns=["trade_date", "is_trading"])
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
            sessions.add(day)
    return tuple(sorted(sessions))


def _read_status_rows(
    asl_root: Path, codes: set[str], start: date | None, as_of: date
) -> dict[tuple[str, date], tuple[bool, str]]:
    """{(code, trade_date): (is_trading, status)} from ASL trading_status."""

    result: dict[tuple[str, date], tuple[bool, str]] = {}
    for path in _list_parquet(asl_root / "curated" / "trading_status"):
        table = pq.ParquetFile(path).read(
            columns=["symbol", "trade_date", "is_trading", "status"],
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
            result[(match.group(1), day)] = (bool(is_trading), str(status or ""))
    return result


def _read_bars(
    asl_root: Path,
    codes: set[str],
    start: date | None,
    as_of: date,
) -> list[dict[str, object]]:
    """All ASL daily_bars rows for *codes* in [start, as_of]."""

    rows: list[dict[str, object]] = []
    bars_root = asl_root / "curated" / "daily_bars"
    if not bars_root.exists():
        return rows
    for path in _list_parquet(bars_root):
        table = pq.ParquetFile(path).read(
            columns=[
                "symbol", "trade_date", "open", "high", "low", "close",
                "volume", "amount", "source", "data_version", "fetched_at",
            ],
        )
        for record in table.to_pylist():
            match = _SYMBOL_RE.match(str(record["symbol"]))
            if match is None or match.group(1) not in codes:
                continue
            day = record["trade_date"]
            if not isinstance(day, date):
                day = date.fromisoformat(str(day))
            if day > as_of:
                continue
            if start is not None and day < start:
                continue
            record["code"] = match.group(1)
            record["trade_date"] = day
            rows.append(record)
    rows.sort(key=lambda row: (str(row["code"]), row["trade_date"]))
    return rows


def _row_status_for_amount(amount: object | None) -> RowStatus | None:
    if amount is None:
        return "MISSING_REQUIRED_AMOUNT"
    return None


def load_asl_daily_slice(
    asl_root: str | Path,
    *,
    as_of: date,
    start: date | None = None,
    codes: Sequence[str] | None = None,
    universe_prefixes: Sequence[str] = FROZEN_UNIVERSE_PREFIXES,
    asl_revision: str = ASL_REVISION_PIN,
    seed_prior_session: bool = True,
) -> AslDailySlice:
    """Build a frozen-contract daily slice from an ASL lake (read-only).

    Returns one ``AslDailyBarRow`` per (code, session) present in ASL
    ``daily_bars`` with a valid bar.  Sessions absent from ASL bars are not
    invented; suspended sessions surfaced by ASL ``trading_status`` are
    reported in ``suspended_sessions``.

    ``start`` defaults to None (every session up to ``as_of`` in the lake).
    ``codes`` defaults to the full frozen-universe membership found in ASL
    ``instruments``.  Codes outside ``universe_prefixes`` are never emitted.

    ``seed_prior_session`` mirrors ``load_seed_previous_closes``: when a
    ``start`` is given, the single trading session immediately before it is
    read and used ONLY as the preclose-chain seed (never emitted), so the
    first emitted session has a trusted predecessor whenever ASL has one.
    """

    root = Path(asl_root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"asl root does not exist: {root}")
    prefixes = tuple(universe_prefixes)

    instruments = _read_instruments(root)
    if codes is None:
        requested: tuple[str, ...] = tuple(
            sorted(
                code
                for code in instruments
                if code.startswith(prefixes)
            )
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

    calendar_lower = start
    if start is not None and seed_prior_session:
        calendar_lower = start - timedelta(days=14)
    sessions_all = _read_calendar_sessions(root, calendar_lower, as_of)
    sessions = tuple(
        session for session in sessions_all
        if start is None or session >= start
    )
    seed_sessions = tuple(
        session for session in sessions_all
        if start is not None and session < start
    )
    bars_lower = seed_sessions[-1] if seed_sessions else start
    status_rows = _read_status_rows(root, universe_codes, start, as_of)
    bars = _read_bars(root, universe_codes, bars_lower, as_of)

    # Trading-status coverage facts (explicit, never silent).
    status_files = _list_parquet(root / "curated" / "trading_status")
    status_dataset_present = bool(status_files)
    sessions_with_status = {
        (code, day) for (code, day) in status_rows
        if day >= (start or date.min)
    }
    sessions_without_status = sum(
        1
        for code in sorted(universe_codes)
        for day in sessions
        if (code, day) not in sessions_with_status
    )
    status_coverage = AslStatusCoverage(
        dataset_present=status_dataset_present,
        status_rows_in_window=len(sessions_with_status),
        sessions_with_status_row=len(sessions_with_status),
        sessions_without_status_row=sessions_without_status,
        mode=(
            "FAIL_CLOSED"
            if not status_dataset_present
            else "ASL_MISSING_ROW_NORMAL_CONVENTION"
        ),
    )

    bars_by_code: dict[str, dict[date, dict[str, object]]] = {}
    for row in bars:
        bars_by_code.setdefault(str(row["code"]), {})[row["trade_date"]] = row

    emitted: list[AslDailyBarRow] = []
    suspended_sessions: list[tuple[str, date]] = []
    warnings: list[str] = []

    for code in sorted(universe_codes):
        previous_close: Decimal | None = None
        if seed_sessions:
            seed_bar = bars_by_code.get(code, {}).get(seed_sessions[-1])
            if seed_bar is not None:
                seed_close = Decimal(str(seed_bar["close"]))
                if seed_close > 0:
                    previous_close = seed_close
        for day in sessions:
            bar = bars_by_code.get(code, {}).get(day)
            if bar is None:
                continue

            data_version = str(bar.get("data_version") or "")
            if data_version != DAILY_BARS_SHARES_VERSION:
                emitted.append(
                    AslDailyBarRow(
                        code=code,
                        trade_date=day,
                        open=None, high=None, low=None, close=None,
                        preclose=None, volume=None, amount=None,
                        pct_change=None, trade_status=None, is_st=None,
                        row_status="UNSUPPORTED_SEMANTICS",
                        reason=(
                            f"daily_bars.data_version={data_version!r} "
                            f"!= {DAILY_BARS_SHARES_VERSION!r} (volume unit not guaranteed)"
                        ),
                        asl_source=str(bar.get("source") or ""),
                        asl_data_version=data_version,
                        asl_fetched_at=str(bar.get("fetched_at") or ""),
                    )
                )
                continue

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

            status_row = status_rows.get((code, day))
            trade_status: bool | None
            is_st: bool | None
            if status_row is None:
                if status_dataset_present:
                    # ASL convention: a listed symbol with no status row on a
                    # trading day is normal (matches ASL query/universe.py).
                    trade_status = True
                    is_st = False
                else:
                    trade_status = None
                    is_st = None
            else:
                is_trading, status = status_row
                status_lower = status.lower()
                if status_lower in {"st", "*st"}:
                    trade_status = True
                    is_st = True
                elif status_lower == "suspended" or not is_trading:
                    trade_status = False
                    is_st = None
                else:
                    trade_status = True
                    is_st = False

            amount_status = _row_status_for_amount(amount_raw)
            preclose = previous_close
            status_missing = status_row is None and not status_dataset_present
            # Fail-closed precedence (most severe first):
            # UNSUPPORTED_SEMANTICS > MISSING_STATUS > MISSING_PRECLOSE >
            # MISSING_REQUIRED_AMOUNT > VALID_ROW.
            if status_missing:
                row_status: RowStatus = "MISSING_STATUS"
                reason = "trading_status coverage missing for the session window"
                pct_change = _pct_change(close, preclose) if preclose is not None else None
            elif preclose is None:
                row_status: RowStatus = "MISSING_PRECLOSE"
                reason = "no trusted predecessor session in the ASL chain"
                pct_change = None
            elif amount_status is not None:
                row_status = amount_status
                reason = "ASL daily_bars.amount is null (e.g. Sina delisted rows)"
                pct_change = _pct_change(close, preclose)
            else:
                row_status = "VALID_ROW"
                reason = None
                pct_change = _pct_change(close, preclose)

            if trade_status is False:
                suspended_sessions.append((code, day))

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
                    pct_change=pct_change,
                    trade_status=trade_status,
                    is_st=is_st,
                    row_status=row_status,
                    reason=reason,
                    asl_source=str(bar.get("source") or ""),
                    asl_data_version=data_version,
                    asl_fetched_at=str(bar.get("fetched_at") or ""),
                )
            )
            if close > 0:
                previous_close = close

        if not bars_by_code.get(code):
            warnings.append(f"no ASL daily_bars rows for {code} in window")

    # Suspended sessions surfaced by trading_status even when daily_bars has
    # no bar for them (ASL bar-gap derivation writes sparse suspended rows).
    for (code, day), (_is_trading, status) in status_rows.items():
        if str(status).lower() == "suspended":
            suspended_sessions.append((code, day))

    if not status_dataset_present:
        warnings.append(
            "trading_status dataset absent: all rows marked MISSING_STATUS"
        )

    return AslDailySlice(
        contract_version=CONTRACT_VERSION,
        asl_revision=asl_revision,
        asl_root=str(root),
        start=start,
        as_of=as_of,
        universe_prefixes=prefixes,
        rows=tuple(emitted),
        excluded_codes=excluded,
        missing_symbols=missing,
        status_coverage=status_coverage,
        suspended_sessions=tuple(sorted(set(suspended_sessions))),
        warnings=tuple(sorted(set(warnings))),
    )
