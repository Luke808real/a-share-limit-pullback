"""Read-only ASL adapter for the frozen prospective R9 factor boundary.

The caller owns Gate 2A candidate state.  This module only reads the pinned
ASL Query API, converts the bounded raw prefixes to the existing PIT types,
and reconstructs the already-frozen Gate 2A observations before handing the
package to the existing prospective factor producer.

ASL is deliberately imported lazily.  Cloud contract tests inject a narrow
``load`` backend and therefore do not require the ASL runtime or Polars.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

import r9_population_generator_v01 as population
import r9_prospective_factor_producer_v01 as producer


ASL_CODE_SHA = "04bd94936587b35cae55c833627260866d025184"
ASL_SOURCE_VINTAGE = f"ASL@{ASL_CODE_SHA}"
DAILY_DATASET = "daily_bars"
ADJ_FACTOR_DATASET = "adj_factors"
STORED_ADJUST_TYPE = "hfq"


class ASLPITAdapterBlocked(RuntimeError):
    """The official ASL prefix cannot satisfy the frozen PIT boundary."""


class ASLQueryBackend(Protocol):
    """The only query surface accepted by this adapter."""

    code_sha: str

    def load(self, dataset: str, **kwargs: object) -> object:
        """Load one official ASL dataset."""


class _OfficialQueryBackend:
    def __init__(self, query_module: Any):
        self._query_module = query_module
        self.code_sha = ASL_CODE_SHA

    def load(self, dataset: str, **kwargs: object) -> object:
        return self._query_module.load(dataset, **kwargs)


class _FixedSliceSource:
    def __init__(self, daily: population.DailyPITSlice):
        self._daily = daily

    def daily_slice(self, *, as_of: date) -> population.DailyPITSlice:
        return self._daily


def _official_query_backend() -> ASLQueryBackend:
    """Resolve the official ASL query module only when a real read is needed."""

    try:
        from ashare_lake import query
    except ImportError as exc:
        raise ASLPITAdapterBlocked(
            "STATUS=BLOCKED_PINNED_ASL_RUNTIME_UNAVAILABLE"
        ) from exc
    return _OfficialQueryBackend(query)


def _blocked(message: str) -> ASLPITAdapterBlocked:
    return ASLPITAdapterBlocked(message)


def _require_date(value: object, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise _blocked(f"STATUS=BLOCKED_ASL_SCHEMA: invalid {field}") from exc


def _finite_decimal(value: object, *, field: str) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _candidate_code(value: object) -> str:
    text = str(value).strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    code = text.zfill(6)
    if len(code) != 6 or not code.isdigit():
        raise _blocked(
            f"STATUS=BLOCKED_ASL_SCHEMA: invalid candidate symbol={value!r}"
        )
    return code


def _asl_symbol(code: str) -> str:
    if code.startswith(("60", "68", "69")):
        return f"{code}.SH"
    if code.startswith(("00", "30")):
        return f"{code}.SZ"
    if code.startswith(("43", "83", "87", "88")):
        return f"{code}.BJ"
    raise _blocked(
        f"STATUS=BLOCKED_ASL_SYMBOL_MAPPING: unsupported six-digit symbol={code}"
    )


def _records(frame: object, *, dataset: str) -> tuple[Mapping[str, object], ...]:
    if frame is None:
        return ()
    if hasattr(frame, "to_dicts"):
        rows = frame.to_dicts()
    elif hasattr(frame, "to_dict"):
        try:
            rows = frame.to_dict("records")
        except TypeError:
            rows = frame.to_dict(orient="records")
    elif isinstance(frame, Mapping):
        rows = [frame]
    elif isinstance(frame, Sequence) and not isinstance(frame, (str, bytes, bytearray)):
        rows = frame
    else:
        raise _blocked(
            f"STATUS=BLOCKED_ASL_SCHEMA: {dataset} result is not record-like"
        )
    try:
        result = tuple(rows)
    except TypeError as exc:
        raise _blocked(
            f"STATUS=BLOCKED_ASL_SCHEMA: {dataset} result is not iterable"
        ) from exc
    if any(not isinstance(row, Mapping) for row in result):
        raise _blocked(
            f"STATUS=BLOCKED_ASL_SCHEMA: {dataset} rows must be mappings"
        )
    return result


def _required_field(row: Mapping[str, object], field: str, *, dataset: str) -> object:
    if field not in row:
        raise _blocked(
            f"STATUS=BLOCKED_ASL_SCHEMA: {dataset} missing field={field}"
        )
    return row[field]


def _load_asl(
    backend: ASLQueryBackend,
    dataset: str,
    *,
    as_of: date,
    symbols: tuple[str, ...],
    data_root: Path | None,
) -> object:
    kwargs: dict[str, object] = {
        "start": None,
        "end": as_of,
        "adjust": None,
        "universe": None,
        "symbols": list(symbols),
    }
    if data_root is not None:
        kwargs["data_root"] = data_root
    try:
        return backend.load(dataset, **kwargs)
    except ASLPITAdapterBlocked:
        raise
    except Exception as exc:
        raise _blocked(
            f"STATUS=BLOCKED_ASL_QUERY_UNAVAILABLE: dataset={dataset}"
        ) from exc


def _daily_bars(
    frame: object,
    *,
    as_of: date,
    candidate_codes: frozenset[str],
) -> tuple[producer.PITDailyBar, ...]:
    raw = _records(frame, dataset=DAILY_DATASET)
    seen: set[tuple[str, date]] = set()
    grouped: dict[str, list[tuple[date, Decimal | None, Decimal | None, Decimal | None, Decimal | None]]] = {}
    for row in raw:
        raw_symbol = _required_field(row, "symbol", dataset=DAILY_DATASET)
        code = _candidate_code(raw_symbol)
        if code not in candidate_codes:
            raise _blocked(
                f"STATUS=BLOCKED_ASL_SYMBOL_SCOPE: unexpected symbol={raw_symbol!r}"
            )
        trade_date = _require_date(
            _required_field(row, "trade_date", dataset=DAILY_DATASET),
            field="daily_bars.trade_date",
        )
        if trade_date > as_of:
            raise _blocked(
                f"STATUS=BLOCKED_FUTURE_DATA: daily bar {trade_date} > as_of={as_of}"
            )
        key = (code, trade_date)
        if key in seen:
            raise _blocked(
                "STATUS=BLOCKED_ASL_DUPLICATE_ROW: "
                f"dataset={DAILY_DATASET} symbol={code} trade_date={trade_date}"
            )
        seen.add(key)
        high = _finite_decimal(
            _required_field(row, "high", dataset=DAILY_DATASET),
            field="daily_bars.high",
        )
        low = _finite_decimal(
            _required_field(row, "low", dataset=DAILY_DATASET),
            field="daily_bars.low",
        )
        close = _finite_decimal(
            _required_field(row, "close", dataset=DAILY_DATASET),
            field="daily_bars.close",
        )
        volume = _finite_decimal(
            _required_field(row, "volume", dataset=DAILY_DATASET),
            field="daily_bars.volume",
        )
        grouped.setdefault(code, []).append((trade_date, high, low, close, volume))

    output: list[producer.PITDailyBar] = []
    for code in sorted(candidate_codes):
        ordered = sorted(grouped.get(code, ()), key=lambda item: item[0])
        previous_valid_close: Decimal | None = None
        for trade_date, high, low, close, volume in ordered:
            output.append(
                producer.PITDailyBar(
                    symbol=code,
                    trade_date=trade_date,
                    high=high,
                    low=low,
                    close=close,
                    preclose=previous_valid_close,
                    volume=volume,
                )
            )
            if close is not None:
                previous_valid_close = close
    return tuple(sorted(output, key=lambda row: (row.symbol, row.trade_date)))


def _adjustment_events(
    frame: object,
    *,
    as_of: date,
    candidate_codes: frozenset[str],
) -> dict[str, tuple[tuple[date, Decimal], ...]]:
    raw = _records(frame, dataset=ADJ_FACTOR_DATASET)
    seen: set[tuple[str, date, str]] = set()
    grouped: dict[str, list[tuple[date, Decimal]]] = {}
    for row in raw:
        raw_symbol = _required_field(row, "symbol", dataset=ADJ_FACTOR_DATASET)
        code = _candidate_code(raw_symbol)
        if code not in candidate_codes:
            raise _blocked(
                f"STATUS=BLOCKED_ASL_SYMBOL_SCOPE: unexpected symbol={raw_symbol!r}"
            )
        trade_date = _require_date(
            _required_field(row, "trade_date", dataset=ADJ_FACTOR_DATASET),
            field="adj_factors.trade_date",
        )
        if trade_date > as_of:
            raise _blocked(
                "STATUS=BLOCKED_FUTURE_DATA: "
                f"adjustment factor {trade_date} > as_of={as_of}"
            )
        adjust_type = str(
            _required_field(row, "adjust_type", dataset=ADJ_FACTOR_DATASET)
        ).strip().lower()
        key = (code, trade_date, adjust_type)
        if key in seen:
            raise _blocked(
                "STATUS=BLOCKED_ASL_DUPLICATE_ROW: "
                f"dataset={ADJ_FACTOR_DATASET} symbol={code} trade_date={trade_date}"
            )
        seen.add(key)
        if adjust_type != STORED_ADJUST_TYPE:
            continue
        factor = _finite_decimal(
            _required_field(row, "factor", dataset=ADJ_FACTOR_DATASET),
            field="adj_factors.factor",
        )
        if factor is None:
            raise _blocked(
                "STATUS=BLOCKED_ASL_FACTOR_SCHEMA: "
                f"missing hfq factor symbol={code} trade_date={trade_date}"
            )
        grouped.setdefault(code, []).append((trade_date, factor))
    return {
        code: tuple(sorted(grouped.get(code, ()), key=lambda item: item[0]))
        for code in sorted(candidate_codes)
    }


def _align_adjustments(
    bars: Sequence[producer.PITDailyBar],
    events: Mapping[str, Sequence[tuple[date, Decimal]]],
) -> tuple[producer.PITAdjustmentFactor, ...]:
    """Apply the most recent HFQ event on or before each canonical bar date."""

    bars_by_symbol: dict[str, list[producer.PITDailyBar]] = {}
    for row in bars:
        bars_by_symbol.setdefault(row.symbol, []).append(row)
    aligned: list[producer.PITAdjustmentFactor] = []
    for code in sorted(bars_by_symbol):
        ordered_events = tuple(sorted(events.get(code, ()), key=lambda item: item[0]))
        event_index = 0
        latest: Decimal | None = None
        for bar in sorted(bars_by_symbol[code], key=lambda row: row.trade_date):
            while (
                event_index < len(ordered_events)
                and ordered_events[event_index][0] <= bar.trade_date
            ):
                latest = ordered_events[event_index][1]
                event_index += 1
            if latest is not None:
                aligned.append(
                    producer.PITAdjustmentFactor(
                        symbol=code,
                        trade_date=bar.trade_date,
                        adj_factor=latest,
                    )
                )
    return tuple(sorted(aligned, key=lambda row: (row.symbol, row.trade_date)))


def _validate_candidate_coverage(
    candidates: Sequence[population.DailySetupInput],
    *,
    as_of: date,
    bars: Sequence[producer.PITDailyBar],
    adjustments: Sequence[producer.PITAdjustmentFactor],
) -> None:
    bars_by_symbol: dict[str, tuple[producer.PITDailyBar, ...]] = {}
    for code in {_candidate_code(candidate.symbol) for candidate in candidates}:
        bars_by_symbol[code] = tuple(
            sorted(
                (row for row in bars if row.symbol == code),
                key=lambda row: row.trade_date,
            )
        )
    adj_by_symbol: dict[str, dict[date, Decimal | None]] = {}
    for row in adjustments:
        adj_by_symbol.setdefault(row.symbol, {})[row.trade_date] = _finite_decimal(
            row.adj_factor,
            field="adjustment_factor.adj_factor",
        )

    for candidate in candidates:
        code = _candidate_code(candidate.symbol)
        symbol_bars = bars_by_symbol.get(code, ())
        dates = [row.trade_date for row in symbol_bars]
        if not dates:
            raise _blocked(
                f"STATUS=BLOCKED_ASL_DAILY_COVERAGE: symbol={code} has no bars"
            )
        if as_of not in dates:
            raise _blocked(
                f"STATUS=BLOCKED_ASL_DAILY_COVERAGE: symbol={code} missing D={as_of}"
            )
        try:
            i0 = dates.index(candidate.anchor_date)
        except ValueError as exc:
            raise _blocked(
                "STATUS=BLOCKED_ASL_DAILY_COVERAGE: "
                f"symbol={code} missing T0={candidate.anchor_date}"
            ) from exc
        iD = dates.index(as_of)
        if iD <= i0:
            raise _blocked(
                "STATUS=BLOCKED_ASL_DAILY_COVERAGE: "
                f"symbol={code} requires D after T0"
            )
        if i0 == 0:
            raise _blocked(
                "STATUS=BLOCKED_ASL_DAILY_COVERAGE: "
                f"symbol={code} missing T0 predecessor"
            )
        reference = symbol_bars[max(0, i0 - 60):i0]
        if not any(row.high is not None for row in reference):
            raise _blocked(
                "STATUS=BLOCKED_ASL_DAILY_COVERAGE: "
                f"symbol={code} lacks B7 pre-T0 history"
            )
        adj_map = adj_by_symbol.get(code, {})
        required_dates = (row.trade_date for row in symbol_bars[i0 - 1:iD + 1])
        missing = [trade_date for trade_date in required_dates if adj_map.get(trade_date) is None]
        if missing:
            raise _blocked(
                "STATUS=BLOCKED_ASL_CA_FACTOR_SIDE_MISSING: "
                f"symbol={code} missing required factor date={missing[0]}"
            )


def build_pit_factor_input(
    *,
    as_of: date,
    candidates: tuple[population.DailySetupInput, ...],
    candidate_state_source_hash: str,
    limit_pool_source_hash: str,
    configuration_version_hash: str,
    query_backend: ASLQueryBackend | None = None,
    asl_data_root: Path | None = None,
    asl_code_sha: str = ASL_CODE_SHA,
) -> producer.PITFactorInput:
    """Build the exact existing producer input from caller state plus ASL."""

    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        raise _blocked("STATUS=BLOCKED_ASL_INPUT: as_of must be a date")
    if str(asl_code_sha).strip().lower() != ASL_CODE_SHA:
        raise _blocked("STATUS=BLOCKED_ASL_CODE_REVISION_MISMATCH")
    candidate_rows = tuple(candidates)
    candidate_codes = frozenset(_candidate_code(candidate.symbol) for candidate in candidate_rows)
    for candidate in candidate_rows:
        if candidate.state_as_of != as_of:
            raise _blocked(
                "STATUS=BLOCKED_CANDIDATE_STATE_ASOF_MISMATCH: "
                f"symbol={candidate.symbol} state_as_of={candidate.state_as_of} as_of={as_of}"
            )

    if candidate_rows:
        backend = query_backend or _official_query_backend()
        if str(getattr(backend, "code_sha", "")).strip().lower() != ASL_CODE_SHA:
            raise _blocked("STATUS=BLOCKED_ASL_CODE_REVISION_MISMATCH")
        asl_symbols = tuple(sorted(_asl_symbol(code) for code in candidate_codes))
        daily_frame = _load_asl(
            backend,
            DAILY_DATASET,
            as_of=as_of,
            symbols=asl_symbols,
            data_root=asl_data_root,
        )
        adj_frame = _load_asl(
            backend,
            ADJ_FACTOR_DATASET,
            as_of=as_of,
            symbols=asl_symbols,
            data_root=asl_data_root,
        )
        daily_bars = _daily_bars(
            daily_frame,
            as_of=as_of,
            candidate_codes=candidate_codes,
        )
        events = _adjustment_events(
            adj_frame,
            as_of=as_of,
            candidate_codes=candidate_codes,
        )
        adjustment_factors = _align_adjustments(daily_bars, events)
        _validate_candidate_coverage(
            candidate_rows,
            as_of=as_of,
            bars=daily_bars,
            adjustments=adjustment_factors,
        )
    else:
        daily_bars = ()
        adjustment_factors = ()

    daily_hash = producer.canonical_daily_bar_prefix_hash(daily_bars)
    adjustment_hash = producer.canonical_adjustment_factor_prefix_hash(
        adjustment_factors
    )
    manifest_hash = producer.build_source_manifest_hash(
        as_of=as_of,
        daily_coverage_through=as_of,
        factor_coverage_through=as_of,
        candidate_state_source_hash=candidate_state_source_hash,
        limit_pool_source_hash=limit_pool_source_hash,
        daily_bar_prefix_hash=daily_hash,
        adjustment_factor_prefix_hash=adjustment_hash,
        configuration_version_hash=configuration_version_hash,
        source_vintage=ASL_SOURCE_VINTAGE,
    )
    daily_slice = population.DailyPITSlice(
        as_of=as_of,
        daily_coverage_through=as_of,
        limit_pool_coverage_through=as_of,
        source_manifest_hash=manifest_hash,
        candidates=candidate_rows,
    )
    try:
        observations = population.generate_setups(
            as_of=as_of,
            daily_source=_FixedSliceSource(daily_slice),
        )
        return producer.PITFactorInput(
            as_of=as_of,
            daily_coverage_through=as_of,
            factor_coverage_through=as_of,
            candidate_state_source_hash=candidate_state_source_hash,
            limit_pool_source_hash=limit_pool_source_hash,
            daily_bar_prefix_hash=daily_hash,
            adjustment_factor_prefix_hash=adjustment_hash,
            configuration_version_hash=configuration_version_hash,
            source_vintage=ASL_SOURCE_VINTAGE,
            source_manifest_hash=manifest_hash,
            gate2a_slice=daily_slice,
            gate2a_observations=observations,
            daily_bars=daily_bars,
            adjustment_factors=adjustment_factors,
        )
    except (population.PopulationGeneratorBlocked, producer.ProspectiveFactorProducerBlocked) as exc:
        raise _blocked(f"STATUS=BLOCKED_PIT_INPUT: {exc}") from exc


__all__ = [
    "ADJ_FACTOR_DATASET",
    "ASL_CODE_SHA",
    "ASLQueryBackend",
    "ASLPITAdapterBlocked",
    "ASL_SOURCE_VINTAGE",
    "DAILY_DATASET",
    "STORED_ADJUST_TYPE",
    "build_pit_factor_input",
]
