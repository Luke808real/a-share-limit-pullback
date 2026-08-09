"""Pure daily setup-observation generator for the R9 Gate 2A contract.

The caller supplies one immutable, post-close daily slice.  This module has
no filesystem, provider, ledger, or state-generation dependency: it selects
the existing V01A structural predicate and produces observations for that
single session only.  A bounded historical replay is therefore an explicit
concatenation of daily calls, rather than a later run that rewrites earlier
rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Protocol

from limit_pullback.models.enums import DataQuality, SetupStage
from limit_pullback.strategy.engine import make_setup_id


GENERATOR_VERSION = "NEW_PROSPECTIVE_V01"
RESEARCH_ONLY = True
ACTIVATION_REQUIRED_FOR_POPULATION = False
PIT_STAGES = frozenset({
    SetupStage.B1_READY,
    SetupStage.B2_READY,
    SetupStage.B2_CONFIRMED,
})
OUTPUT_COLUMNS = (
    "setup_id",
    "symbol",
    "anchor_date",
    "anchor_price",
    "price_tick",
    "candidate_date",
    "as_of",
    "generator_version",
    "source_manifest_hash",
)


class PopulationGeneratorBlocked(RuntimeError):
    """The supplied daily slice violates the frozen Gate 2A contract."""


@dataclass(frozen=True)
class DailySetupInput:
    """One already-computed setup state from the supplied daily prefix."""

    setup_id: str
    symbol: str
    state_as_of: date
    anchor_date: date
    anchor_price: Decimal
    setup_stage: SetupStage | str
    invalid_price: Decimal | None
    s1_price: Decimal | None
    data_quality: DataQuality | str
    price_tick: Decimal = Decimal("0.01")


@dataclass(frozen=True)
class DailyPITSlice:
    """The immutable input boundary for one post-close session.

    Both coverage fields must equal ``as_of``. ``source_manifest_hash`` must
    identify only that source prefix (daily bars, limit-pool inputs,
    configuration, and source vintage). The generator does not accept a
    whole-history mutable hash.
    """

    as_of: date
    daily_coverage_through: date
    limit_pool_coverage_through: date
    source_manifest_hash: str
    candidates: tuple[DailySetupInput, ...]


class DailyPITSource(Protocol):
    """A caller-owned source that exposes exactly one daily input slice."""

    def daily_slice(self, *, as_of: date) -> DailyPITSlice:
        """Return the immutable daily slice whose source prefix ends at as_of."""


@dataclass(frozen=True)
class ProspectiveObservation:
    """A single Gate 2A candidate observation; its date is immutable."""

    setup_id: str
    symbol: str
    anchor_date: date
    anchor_price: Decimal
    price_tick: Decimal
    candidate_date: date
    as_of: date
    generator_version: str
    source_manifest_hash: str

    @property
    def observation_id(self) -> str:
        return f"{self.setup_id}:{self.candidate_date:%Y%m%d}"

    def canonical_record(self) -> dict[str, str]:
        return {
            "observation_id": self.observation_id,
            "setup_id": self.setup_id,
            "symbol": self.symbol,
            "anchor_date": self.anchor_date.isoformat(),
            "anchor_price": str(self.anchor_price),
            "price_tick": str(self.price_tick),
            "candidate_date": self.candidate_date.isoformat(),
            "as_of": self.as_of.isoformat(),
            "generator_version": self.generator_version,
            "source_manifest_hash": self.source_manifest_hash,
        }


@dataclass(frozen=True)
class PopulationViews:
    """Outcome-blind P0 and P1 views assembled from immutable daily rows."""

    raw_pit_observations: tuple[ProspectiveObservation, ...]
    prospective_first_observations: tuple[ProspectiveObservation, ...]

    @property
    def raw_pit_hash(self) -> str:
        return canonical_observation_hash(self.raw_pit_observations)

    @property
    def prospective_first_hash(self) -> str:
        return canonical_observation_hash(self.prospective_first_observations)


def _canonical_symbol(value: str) -> str:
    symbol = str(value).strip().zfill(6)
    if len(symbol) != 6 or not symbol.isdigit():
        raise PopulationGeneratorBlocked("invalid six-digit setup symbol")
    return symbol


def _decimal(value: Decimal, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PopulationGeneratorBlocked(f"invalid {field}") from exc


def _stage(value: SetupStage | str) -> SetupStage:
    try:
        return SetupStage(str(value))
    except ValueError as exc:
        raise PopulationGeneratorBlocked("invalid setup stage") from exc


def _quality(value: DataQuality | str) -> DataQuality:
    try:
        return DataQuality(str(value))
    except ValueError as exc:
        raise PopulationGeneratorBlocked("invalid data quality") from exc


def _validate_manifest_hash(value: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise PopulationGeneratorBlocked("source_manifest_hash must be a sha256 hex digest")
    return digest


def _expected_setup_id(candidate: DailySetupInput) -> tuple[str, Decimal]:
    symbol = _canonical_symbol(candidate.symbol)
    anchor_price = _decimal(candidate.anchor_price, field="anchor price")
    price_tick = _decimal(candidate.price_tick, field="price tick")
    if price_tick <= 0:
        raise PopulationGeneratorBlocked("price tick must be positive")
    return (
        make_setup_id(symbol, candidate.anchor_date, anchor_price, price_tick),
        anchor_price,
    )


def _validate_candidate_as_of(candidate: DailySetupInput, *, as_of: date) -> None:
    if candidate.state_as_of != as_of:
        raise PopulationGeneratorBlocked("candidate state was not computed at as_of")
    if candidate.anchor_date > as_of:
        raise PopulationGeneratorBlocked("anchor date cannot be after as_of")


def is_raw_pit_candidate(candidate: DailySetupInput) -> bool:
    """Apply only the pre-maturity V01A structural predicate."""

    return (
        _stage(candidate.setup_stage) in PIT_STAGES
        and candidate.invalid_price is not None
        and candidate.s1_price is not None
        and _quality(candidate.data_quality) is not DataQuality.UNUSABLE
    )


def generate_setups(
    *,
    as_of: date,
    daily_source: DailyPITSource,
) -> tuple[ProspectiveObservation, ...]:
    """Generate only the eligible observations for one post-close session.

    The source is asked for ``as_of`` exactly once.  Inputs from a different
    session are rejected rather than silently carried forward, so a rerun at a
    later cutoff cannot alter an earlier observation.
    """

    daily = daily_source.daily_slice(as_of=as_of)
    if daily.as_of != as_of:
        raise PopulationGeneratorBlocked("daily source returned a different as_of")
    if daily.daily_coverage_through != as_of:
        raise PopulationGeneratorBlocked("daily source coverage does not reach as_of")
    if daily.limit_pool_coverage_through != as_of:
        raise PopulationGeneratorBlocked("limit-pool coverage does not reach as_of")
    manifest_hash = _validate_manifest_hash(daily.source_manifest_hash)
    seen: set[str] = set()
    observations: list[ProspectiveObservation] = []
    for candidate in daily.candidates:
        _validate_candidate_as_of(candidate, as_of=as_of)
        expected_setup_id, anchor_price = _expected_setup_id(candidate)
        if candidate.setup_id != expected_setup_id:
            raise PopulationGeneratorBlocked("setup_id does not match authoritative engine key")
        if not is_raw_pit_candidate(candidate):
            continue
        if candidate.setup_id in seen:
            raise PopulationGeneratorBlocked("duplicate daily setup observation")
        seen.add(candidate.setup_id)
        observations.append(
            ProspectiveObservation(
                setup_id=candidate.setup_id,
                symbol=_canonical_symbol(candidate.symbol),
                anchor_date=candidate.anchor_date,
                anchor_price=anchor_price,
                price_tick=_decimal(candidate.price_tick, field="price tick"),
                candidate_date=as_of,
                as_of=as_of,
                generator_version=GENERATOR_VERSION,
                source_manifest_hash=manifest_hash,
            )
        )
    return tuple(sorted(observations, key=lambda row: (row.setup_id, row.symbol)))


def append_first_eligible_observation(
    existing: Mapping[str, ProspectiveObservation],
    candidate: ProspectiveObservation,
) -> str:
    """Protect an append-only primary row without creating a ledger here."""

    _validate_observation(candidate)
    prior = existing.get(candidate.setup_id)
    if prior is None:
        return "APPEND"
    _validate_observation(prior)
    if prior.observation_id == candidate.observation_id:
        if prior == candidate:
            return "ALREADY_RECORDED"
        raise PopulationGeneratorBlocked("identical observation_id payload drift")
    if candidate.candidate_date < prior.candidate_date:
        raise PopulationGeneratorBlocked("FIRST_ELIGIBLE_OBSERVATION_DRIFT")
    return "PRESERVE_FIRST"


def _validate_observation(row: ProspectiveObservation) -> None:
    if row.candidate_date != row.as_of:
        raise PopulationGeneratorBlocked("observation must be generated on its candidate date")
    if row.generator_version != GENERATOR_VERSION:
        raise PopulationGeneratorBlocked("unexpected generator version")
    _validate_manifest_hash(row.source_manifest_hash)
    price_tick = _decimal(row.price_tick, field="price tick")
    if price_tick <= 0:
        raise PopulationGeneratorBlocked("price tick must be positive")
    expected = make_setup_id(
        _canonical_symbol(row.symbol),
        row.anchor_date,
        _decimal(row.anchor_price, field="anchor price"),
        price_tick,
    )
    if row.setup_id != expected:
        raise PopulationGeneratorBlocked("observation setup_id drift")


def population_views(
    observations: Sequence[ProspectiveObservation],
) -> PopulationViews:
    """Build P0 and immutable earliest-per-setup P1 from daily observations."""

    ordered = tuple(sorted(
        observations,
        key=lambda row: (row.setup_id, row.candidate_date, row.observation_id),
    ))
    seen_observations: set[str] = set()
    first_by_setup: dict[str, ProspectiveObservation] = {}
    for row in ordered:
        _validate_observation(row)
        if row.observation_id in seen_observations:
            raise PopulationGeneratorBlocked("duplicate observation_id")
        seen_observations.add(row.observation_id)
        first_by_setup.setdefault(row.setup_id, row)
    first = tuple(first_by_setup[key] for key in sorted(first_by_setup))
    return PopulationViews(
        raw_pit_observations=ordered,
        prospective_first_observations=first,
    )


def bounded_replay(
    *,
    as_of_dates: Sequence[date],
    daily_source: DailyPITSource,
) -> PopulationViews:
    """Mechanically concatenate a supplied, strictly increasing date window."""

    dates = tuple(as_of_dates)
    if not dates or tuple(sorted(dates)) != dates or len(set(dates)) != len(dates):
        raise PopulationGeneratorBlocked("bounded replay dates must be strict and unique")
    rows: list[ProspectiveObservation] = []
    for as_of in dates:
        rows.extend(generate_setups(as_of=as_of, daily_source=daily_source))
    return population_views(rows)


def canonical_observation_hash(rows: Sequence[ProspectiveObservation]) -> str:
    """Hash sorted serialized observations for deterministic replay checks."""

    for row in rows:
        _validate_observation(row)
    payload = [
        row.canonical_record()
        for row in sorted(rows, key=lambda row: (row.setup_id, row.candidate_date))
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
