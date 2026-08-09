"""Pure PIT producer for the six frozen prospective R9 setup predictors.

The caller supplies one immutable Gate 2A slice, its observations, and the
bounded daily-bar / adjustment-factor prefixes needed for the same ``as_of``
date.  This module has no filesystem, provider, historical-label, or replay
dependency.  Every Gate 2A observation either receives one complete factor
bundle or the whole daily production call fails closed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pandas as pd

import extract_daily_factors_v01 as r2_formulas
import r9_population_generator_v01 as population
import r9_setup_accumulator_v01 as accumulator


PRODUCER_VERSION = "R9_PROSPECTIVE_FACTOR_PRODUCER_V01"
B4_MIN, B4_MAX = 2, 5
B5_DEPTH = -0.04
B6_RATIO = 0.85
B7_LOOKBACK = 60
R5_CA_TOL = 0.005
R5_BOUNDARY_EPS = 1e-9


class ProspectiveFactorProducerBlocked(RuntimeError):
    """A PIT package or factor cannot be safely produced."""


@dataclass(frozen=True)
class PITDailyBar:
    """One canonical daily bar available to the producer."""

    symbol: str
    trade_date: date
    high: Decimal | int | float | str | None
    low: Decimal | int | float | str | None
    close: Decimal | int | float | str | None
    preclose: Decimal | int | float | str | None
    volume: Decimal | int | float | str | None


@dataclass(frozen=True)
class PITAdjustmentFactor:
    """One adjustment factor observation in the bounded PIT prefix."""

    symbol: str
    trade_date: date
    adj_factor: Decimal | int | float | str | None


def _date(value: object, *, field: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ProspectiveFactorProducerBlocked(
            f"STATUS=BLOCKED_PIT_INPUT: {field} must be a date"
        )
    return value


def _sha256(value: object, *, field: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ProspectiveFactorProducerBlocked(
            f"STATUS=BLOCKED_PIT_INPUT: {field} must be a SHA256 digest"
        )
    return digest


def _symbol(value: object) -> str:
    symbol = str(value).strip().zfill(6)
    if len(symbol) != 6 or not symbol.isdigit():
        raise ProspectiveFactorProducerBlocked(
            "STATUS=BLOCKED_PIT_INPUT: symbol must be six digits"
        )
    return symbol


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_text(value: object) -> str | None:
    if value is None:
        return None
    parsed = _decimal_or_none(value)
    if parsed is None:
        return str(value).strip().lower()
    if parsed == 0:
        return "0"
    text = format(parsed.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _canonical_bar_record(row: PITDailyBar) -> dict[str, str | None]:
    return {
        "symbol": _symbol(row.symbol),
        "trade_date": _date(row.trade_date, field="bar.trade_date").isoformat(),
        "high": _decimal_text(row.high),
        "low": _decimal_text(row.low),
        "close": _decimal_text(row.close),
        "preclose": _decimal_text(row.preclose),
        "volume": _decimal_text(row.volume),
    }


def _canonical_adjustment_record(row: PITAdjustmentFactor) -> dict[str, str | None]:
    return {
        "symbol": _symbol(row.symbol),
        "trade_date": _date(
            row.trade_date,
            field="adjustment_factor.trade_date",
        ).isoformat(),
        "adj_factor": _decimal_text(row.adj_factor),
    }


def _hash_records(records: Sequence[dict[str, str | None]]) -> str:
    encoded = json.dumps(
        list(records),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_daily_bar_prefix_hash(rows: Sequence[PITDailyBar]) -> str:
    records = sorted(
        (_canonical_bar_record(row) for row in rows),
        key=lambda row: (row["symbol"], row["trade_date"]),
    )
    return _hash_records(records)


def canonical_adjustment_factor_prefix_hash(
    rows: Sequence[PITAdjustmentFactor],
) -> str:
    records = sorted(
        (_canonical_adjustment_record(row) for row in rows),
        key=lambda row: (row["symbol"], row["trade_date"]),
    )
    return _hash_records(records)


def build_source_manifest_hash(
    *,
    as_of: date,
    daily_coverage_through: date,
    factor_coverage_through: date,
    candidate_state_source_hash: str,
    limit_pool_source_hash: str,
    daily_bar_prefix_hash: str,
    adjustment_factor_prefix_hash: str,
    configuration_version_hash: str,
    source_vintage: str,
) -> str:
    """Build the deterministic composite hash shared with Gate 2A."""

    payload = {
        "manifest_version": PRODUCER_VERSION,
        "as_of": _date(as_of, field="as_of").isoformat(),
        "daily_coverage_through": _date(
            daily_coverage_through,
            field="daily_coverage_through",
        ).isoformat(),
        "factor_coverage_through": _date(
            factor_coverage_through,
            field="factor_coverage_through",
        ).isoformat(),
        "candidate_state_source_hash": _sha256(
            candidate_state_source_hash,
            field="candidate_state_source_hash",
        ),
        "limit_pool_source_hash": _sha256(
            limit_pool_source_hash,
            field="limit_pool_source_hash",
        ),
        "daily_bar_prefix_hash": _sha256(
            daily_bar_prefix_hash,
            field="daily_bar_prefix_hash",
        ),
        "adjustment_factor_prefix_hash": _sha256(
            adjustment_factor_prefix_hash,
            field="adjustment_factor_prefix_hash",
        ),
        "configuration_version_hash": _sha256(
            configuration_version_hash,
            field="configuration_version_hash",
        ),
        "source_vintage": str(source_vintage).strip(),
    }
    if not payload["source_vintage"]:
        raise ProspectiveFactorProducerBlocked(
            "STATUS=BLOCKED_PIT_INPUT: source_vintage is required"
        )
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PITFactorInput:
    """Immutable caller-owned PIT package for one Gate 2A session."""

    as_of: date
    daily_coverage_through: date
    factor_coverage_through: date
    candidate_state_source_hash: str
    limit_pool_source_hash: str
    daily_bar_prefix_hash: str
    adjustment_factor_prefix_hash: str
    configuration_version_hash: str
    source_vintage: str
    source_manifest_hash: str
    gate2a_slice: population.DailyPITSlice
    gate2a_observations: tuple[population.ProspectiveObservation, ...]
    daily_bars: tuple[PITDailyBar, ...]
    adjustment_factors: tuple[PITAdjustmentFactor, ...]

    def __post_init__(self) -> None:
        as_of = _date(self.as_of, field="as_of")
        for field in ("daily_coverage_through", "factor_coverage_through"):
            coverage = _date(getattr(self, field), field=field)
            if coverage > as_of:
                raise ProspectiveFactorProducerBlocked(
                    f"STATUS=BLOCKED_FUTURE_DATA: {field}={coverage} > as_of={as_of}"
                )
        _sha256(self.source_manifest_hash, field="source_manifest_hash")
        for field in (
            "candidate_state_source_hash",
            "limit_pool_source_hash",
            "daily_bar_prefix_hash",
            "adjustment_factor_prefix_hash",
            "configuration_version_hash",
        ):
            _sha256(getattr(self, field), field=field)
        if not str(self.source_vintage).strip():
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_PIT_INPUT: source_vintage is required"
            )
        if not isinstance(self.daily_bars, tuple):
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_PIT_INPUT: daily_bars must be an immutable tuple"
            )
        if not isinstance(self.adjustment_factors, tuple):
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_PIT_INPUT: adjustment_factors must be an immutable tuple"
            )
        if not isinstance(self.gate2a_observations, tuple):
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_PIT_INPUT: observations must be an immutable tuple"
            )
        if self.gate2a_slice.as_of != as_of:
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_CANDIDATE_DATE_MISMATCH: Gate 2A as_of differs"
            )
        if self.gate2a_slice.source_manifest_hash != self.source_manifest_hash:
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_MANIFEST_MISMATCH: Gate 2A manifest differs"
            )
        if self.gate2a_slice.daily_coverage_through != self.daily_coverage_through:
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_MANIFEST_MISMATCH: Gate 2A daily coverage differs"
            )
        for row in self.daily_bars:
            row_date = _date(row.trade_date, field="bar.trade_date")
            if row_date > as_of:
                raise ProspectiveFactorProducerBlocked(
                    f"STATUS=BLOCKED_FUTURE_DATA: daily bar {row_date} > as_of={as_of}"
                )
            if row_date > self.daily_coverage_through:
                raise ProspectiveFactorProducerBlocked(
                    "STATUS=BLOCKED_SOURCE_COVERAGE_MISMATCH: daily bar exceeds coverage"
                )
        for row in self.adjustment_factors:
            row_date = _date(row.trade_date, field="adjustment_factor.trade_date")
            if row_date > as_of:
                raise ProspectiveFactorProducerBlocked(
                    f"STATUS=BLOCKED_FUTURE_DATA: adjustment factor {row_date} > as_of={as_of}"
                )
            if row_date > self.factor_coverage_through:
                raise ProspectiveFactorProducerBlocked(
                    "STATUS=BLOCKED_SOURCE_COVERAGE_MISMATCH: adjustment factor exceeds coverage"
                )
        if canonical_daily_bar_prefix_hash(self.daily_bars) != str(
            self.daily_bar_prefix_hash
        ).lower():
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_MANIFEST_MISMATCH: daily bar prefix hash differs"
            )
        if canonical_adjustment_factor_prefix_hash(self.adjustment_factors) != str(
            self.adjustment_factor_prefix_hash
        ).lower():
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_MANIFEST_MISMATCH: adjustment prefix hash differs"
            )
        expected_manifest = build_source_manifest_hash(
            as_of=as_of,
            daily_coverage_through=self.daily_coverage_through,
            factor_coverage_through=self.factor_coverage_through,
            candidate_state_source_hash=self.candidate_state_source_hash,
            limit_pool_source_hash=self.limit_pool_source_hash,
            daily_bar_prefix_hash=self.daily_bar_prefix_hash,
            adjustment_factor_prefix_hash=self.adjustment_factor_prefix_hash,
            configuration_version_hash=self.configuration_version_hash,
            source_vintage=self.source_vintage,
        )
        if expected_manifest != str(self.source_manifest_hash).lower():
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_MANIFEST_MISMATCH: composite source manifest differs"
            )


class _FixedSliceSource:
    def __init__(self, daily: population.DailyPITSlice):
        self.daily = daily

    def daily_slice(self, *, as_of: date) -> population.DailyPITSlice:
        return self.daily


def _gate2a_observations(
    package: PITFactorInput,
) -> tuple[population.ProspectiveObservation, ...]:
    try:
        expected = population.generate_setups(
            as_of=package.as_of,
            daily_source=_FixedSliceSource(package.gate2a_slice),
        )
    except population.PopulationGeneratorBlocked as exc:
        raise ProspectiveFactorProducerBlocked(
            f"STATUS=BLOCKED_GATE2A_RECONCILIATION: {exc}"
        ) from exc
    supplied = tuple(sorted(
        package.gate2a_observations,
        key=lambda row: (row.setup_id, row.candidate_date, row.observation_id),
    ))
    if any(row.candidate_date != package.as_of for row in supplied):
        raise ProspectiveFactorProducerBlocked(
            "STATUS=BLOCKED_CANDIDATE_DATE_MISMATCH: observation date differs from as_of"
        )
    if any(row.source_manifest_hash != package.source_manifest_hash for row in supplied):
        raise ProspectiveFactorProducerBlocked(
            "STATUS=BLOCKED_MANIFEST_MISMATCH: observation manifest differs"
        )
    if supplied != expected:
        raise ProspectiveFactorProducerBlocked(
            "STATUS=BLOCKED_GATE2A_RECONCILIATION: supplied observations differ"
        )
    return expected


def _index_bars(
    rows: Sequence[PITDailyBar],
) -> dict[str, tuple[PITDailyBar, ...]]:
    grouped: dict[str, list[PITDailyBar]] = {}
    seen: set[tuple[str, date]] = set()
    for row in rows:
        code = _symbol(row.symbol)
        trade_date = _date(row.trade_date, field="bar.trade_date")
        key = (code, trade_date)
        if key in seen:
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_PROSPECTIVE_FACTOR_UNAVAILABLE: "
                f"symbol={code} factor=daily_bar missing_reason=DUPLICATE_BAR"
            )
        seen.add(key)
        grouped.setdefault(code, []).append(row)
    return {
        code: tuple(sorted(values, key=lambda row: row.trade_date))
        for code, values in grouped.items()
    }


def _index_adjustments(
    rows: Sequence[PITAdjustmentFactor],
) -> dict[str, dict[date, Decimal | None]]:
    grouped: dict[str, dict[date, Decimal | None]] = {}
    for row in rows:
        code = _symbol(row.symbol)
        trade_date = _date(
            row.trade_date,
            field="adjustment_factor.trade_date",
        )
        value = _decimal_or_none(row.adj_factor)
        existing = grouped.setdefault(code, {}).get(trade_date, "__missing__")
        if existing != "__missing__" and existing != value:
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_PROSPECTIVE_FACTOR_UNAVAILABLE: "
                f"symbol={code} factor=median_range_ratio "
                "missing_reason=CONFLICTING_ADJUSTMENT_FACTOR"
            )
        grouped[code][trade_date] = value
    return grouped


def _unavailable(setup_id: str, factor: str, reason: str) -> None:
    raise ProspectiveFactorProducerBlocked(
        "STATUS=BLOCKED_PROSPECTIVE_FACTOR_UNAVAILABLE: "
        f"setup_id={setup_id} factor={factor} missing_reason={reason}"
    )


def _required_decimal(
    value: object,
    *,
    setup_id: str,
    factor: str,
    missing_reason: str = "MISSING_REQUIRED_SOURCE_DATA",
) -> Decimal:
    parsed = _decimal_or_none(value)
    if parsed is None:
        _unavailable(setup_id, factor, missing_reason)
    return parsed


def _r5_ca_event(
    *,
    preclose: object,
    previous_close: object,
) -> bool:
    current = _decimal_or_none(preclose)
    previous = _decimal_or_none(previous_close)
    if current is None or previous is None:
        return False
    return abs(float(current) - float(previous)) > (
        R5_CA_TOL * abs(float(previous))
    )


def _r2_frame(rows: Sequence[PITDailyBar]) -> pd.DataFrame:
    normalized = []
    for row in rows:
        normalized.append({
            "trade_date": _date(row.trade_date, field="bar.trade_date"),
            "high": _decimal_or_none(row.high),
            "low": _decimal_or_none(row.low),
            "close": _decimal_or_none(row.close),
            "preclose": _decimal_or_none(row.preclose),
            "volume": _decimal_or_none(row.volume),
        })
    return pd.DataFrame(normalized, columns=[
        "trade_date", "high", "low", "close", "preclose", "volume",
    ])


def _r2_context(
    *,
    observation: population.ProspectiveObservation,
    bars: Sequence[PITDailyBar],
    i0: int,
    iD: int,
    adjustments: dict[str, dict[date, Decimal | None]],
) -> Any:
    return SimpleNamespace(
        case=SimpleNamespace(symbol=observation.symbol),
        bars=_r2_frame(bars),
        i0=i0,
        iD=iD,
        adj=adjustments,
    )


def _r2_value(
    result: Any,
    *,
    setup_id: str,
    factor: str,
) -> Decimal | int:
    if result.value is None:
        _unavailable(
            setup_id,
            factor,
            result.missing_reason or "MISSING_REQUIRED_SOURCE_DATA",
        )
    value = result.value
    if isinstance(value, float) and not pd.notna(value):
        _unavailable(setup_id, factor, "NONFINITE_RESULT")
    return value


def _produce_one(
    observation: population.ProspectiveObservation,
    *,
    bars: Sequence[PITDailyBar],
    adjustments: dict[str, dict[date, Decimal | None]],
    source_manifest_hash: str,
) -> accumulator.ProspectiveFactorBundle:
    ordered = tuple(sorted(bars, key=lambda row: row.trade_date))
    dates = [row.trade_date for row in ordered]
    try:
        i0 = dates.index(observation.anchor_date)
    except ValueError:
        _unavailable(observation.setup_id, "B4", "MISSING_T0_BAR")
    try:
        iD = dates.index(observation.candidate_date)
    except ValueError:
        _unavailable(observation.setup_id, "B4", "MISSING_D_BAR")
    if iD <= i0:
        _unavailable(observation.setup_id, "median_range_ratio", "EMPTY_PULLBACK_WINDOW")
    t0 = ordered[i0]
    dbar = ordered[iD]
    if i0 == 0:
        _unavailable(observation.setup_id, "B5", "MISSING_PREDECESSOR")
    previous_t0 = ordered[i0 - 1]
    if iD == 0:
        _unavailable(observation.setup_id, "B5", "MISSING_PREDECESSOR")
    previous_d = ordered[iD - 1]

    t0_close = _required_decimal(
        t0.close,
        setup_id=observation.setup_id,
        factor="B5",
        missing_reason="MISSING_T0_BAR",
    )
    d_close = _required_decimal(
        dbar.close,
        setup_id=observation.setup_id,
        factor="B5",
        missing_reason="MISSING_D_BAR",
    )
    _required_decimal(
        t0.preclose,
        setup_id=observation.setup_id,
        factor="B5",
        missing_reason="MISSING_PRECLOSE",
    )
    _required_decimal(
        dbar.preclose,
        setup_id=observation.setup_id,
        factor="B5",
        missing_reason="MISSING_PRECLOSE",
    )
    if _decimal_or_none(previous_t0.close) is None or _decimal_or_none(previous_d.close) is None:
        _unavailable(observation.setup_id, "B5", "MISSING_PREDECESSOR")
    if _r5_ca_event(preclose=t0.preclose, previous_close=previous_t0.close):
        _unavailable(observation.setup_id, "B5", "CA_EVENT_T0")
    if _r5_ca_event(preclose=dbar.preclose, previous_close=previous_d.close):
        _unavailable(observation.setup_id, "B5", "CA_EVENT_D")

    t0_volume = _required_decimal(
        t0.volume,
        setup_id=observation.setup_id,
        factor="B6",
        missing_reason="MISSING_T0_BAR",
    )
    d_volume = _required_decimal(
        dbar.volume,
        setup_id=observation.setup_id,
        factor="B6",
        missing_reason="MISSING_D_BAR",
    )
    if t0_volume <= 0 or d_volume <= 0:
        _unavailable(observation.setup_id, "B6", "NONPOSITIVE_VOLUME")

    days_since_t0 = iD - i0
    b4 = Decimal(int(B4_MIN <= days_since_t0 <= B4_MAX))
    b5 = Decimal(int(
        float(d_close) / float(t0_close) - 1.0
        >= B5_DEPTH - R5_BOUNDARY_EPS
    ))
    b6 = Decimal(int(
        bool(b5)
        and float(d_volume) / float(t0_volume)
        <= B6_RATIO + R5_BOUNDARY_EPS
    ))

    pre_t0 = ordered[:i0]
    if not pre_t0:
        _unavailable(observation.setup_id, "B7", "NO_REFERENCE")
    reference_rows = pre_t0[-B7_LOOKBACK:]
    reference_highs = [
        _decimal_or_none(row.high)
        for row in reference_rows
    ]
    reference_highs = [value for value in reference_highs if value is not None]
    if not reference_highs:
        _unavailable(observation.setup_id, "B7", "NO_REFERENCE")
    b7_reference = max(reference_highs)
    b7 = Decimal(int(d_close > b7_reference))

    for row in ordered[i0 + 1:iD + 1]:
        if _decimal_or_none(row.volume) is None:
            _unavailable(
                observation.setup_id,
                "quiet_days_n",
                "MISSING_VOLUME",
            )
    for row in ordered[i0:iD + 1]:
        for field in ("high", "low", "preclose"):
            if _decimal_or_none(getattr(row, field)) is None:
                _unavailable(
                    observation.setup_id,
                    "median_range_ratio",
                    f"MISSING_{field.upper()}",
                )
    context = _r2_context(
        observation=observation,
        bars=ordered,
        i0=i0,
        iD=iD,
        adjustments=adjustments,
    )
    median = _r2_value(
        r2_formulas.f_median_range_ratio(context),
        setup_id=observation.setup_id,
        factor="median_range_ratio",
    )
    quiet = _r2_value(
        r2_formulas.f_quiet_days_n(context),
        setup_id=observation.setup_id,
        factor="quiet_days_n",
    )
    return accumulator.ProspectiveFactorBundle(
        setup_id=observation.setup_id,
        candidate_date=observation.candidate_date,
        source_manifest_hash=source_manifest_hash,
        B4=b4,
        B5=b5,
        B6=b6,
        B7=b7,
        median_range_ratio=median,
        quiet_days_n=quiet,
    )


def produce_prospective_factor_bundles(
    package: PITFactorInput,
) -> tuple[accumulator.ProspectiveFactorBundle, ...]:
    """Produce exactly one complete bundle for every Gate 2A observation."""

    observations = _gate2a_observations(package)
    bars_by_symbol = _index_bars(package.daily_bars)
    adjustments = _index_adjustments(package.adjustment_factors)
    bundles: list[accumulator.ProspectiveFactorBundle] = []
    for observation in observations:
        bars = bars_by_symbol.get(observation.symbol)
        if bars is None:
            _unavailable(
                observation.setup_id,
                "B4",
                "MISSING_SYMBOL_BAR_PREFIX",
            )
        bundles.append(_produce_one(
            observation,
            bars=bars,
            adjustments=adjustments,
            source_manifest_hash=package.source_manifest_hash,
        ))
    if len(bundles) != len(observations):
        raise ProspectiveFactorProducerBlocked(
            "STATUS=BLOCKED_PROSPECTIVE_FACTOR_UNAVAILABLE: one-to-one bundle count drift"
        )
    return tuple(sorted(bundles, key=lambda row: row.identity_key))


def factor_bundle_mapping(
    bundles: Sequence[accumulator.ProspectiveFactorBundle],
) -> dict[tuple[str, date, str], accumulator.ProspectiveFactorBundle]:
    """Return the exact mapping shape accepted by the setup accumulator."""

    result: dict[tuple[str, date, str], accumulator.ProspectiveFactorBundle] = {}
    for bundle in bundles:
        key = bundle.identity_key
        if key in result:
            raise ProspectiveFactorProducerBlocked(
                "STATUS=BLOCKED_PROSPECTIVE_FACTOR_UNAVAILABLE: duplicate bundle identity"
            )
        result[key] = bundle
    return result
