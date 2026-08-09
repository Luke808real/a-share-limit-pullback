"""Minimal prospective R9 setup-ledger accumulator.

The accumulator consumes one immutable post-close Gate 2A slice and a caller-
supplied factor bundle for that same slice.  It deliberately has no historical
case-set, outcome, provider, or replay dependency.  Gate 2A owns membership,
Gate 2B owns eligibility/lifecycle, and the frozen protocol owns scoring and
publication guards.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import r9_population_generator_v01 as population
import r9_protocol_v02 as protocol
import r9_ttl_event_eligibility_v01 as ttl


REPO_ROOT = Path(__file__).resolve().parents[3]
FACTOR_FIELDS = (
    "B4",
    "B5",
    "B6",
    "B7",
    "median_range_ratio",
    "quiet_days_n",
)
FeatureIdentity = tuple[str, date, str]


class SetupAccumulatorBlocked(protocol.ProtocolBlocked):
    """A prospective setup row or artifact cannot be safely published."""


@dataclass(frozen=True)
class ProspectiveFactorBundle:
    """Exactly the six setup-time factors for one immutable daily identity."""

    setup_id: str
    candidate_date: date
    source_manifest_hash: str
    B4: Decimal | int | float
    B5: Decimal | int | float
    B6: Decimal | int | float
    B7: Decimal | int | float
    median_range_ratio: Decimal | int | float
    quiet_days_n: Decimal | int | float

    @property
    def identity_key(self) -> FeatureIdentity:
        return (
            self.setup_id,
            self.candidate_date,
            _canonical_manifest(self.source_manifest_hash),
        )


@dataclass(frozen=True)
class SetupAccumulationResult:
    """Rows and append decisions produced from one post-close slice."""

    rows: tuple[dict[str, str | None], ...]
    observation_statuses: tuple[tuple[str, str], ...]
    feature_hashes: tuple[tuple[FeatureIdentity, str], ...]

    @property
    def status_by_observation(self) -> dict[str, str]:
        return dict(self.observation_statuses)


def _canonical_manifest(value: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SetupAccumulatorBlocked(
            "STATUS=BLOCKED_SETUP_SOURCE_RECONCILIATION: "
            "source_manifest_hash must be a SHA256 digest"
        )
    return digest


def _canonical_decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise SetupAccumulatorBlocked(f"invalid prospective factor: {field}")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SetupAccumulatorBlocked(f"invalid prospective factor: {field}") from exc
    if not parsed.is_finite():
        raise SetupAccumulatorBlocked(f"invalid prospective factor: {field}")
    return parsed


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _validated_factor_values(bundle: ProspectiveFactorBundle) -> dict[str, Decimal]:
    if not bundle.setup_id:
        raise SetupAccumulatorBlocked(
            "STATUS=BLOCKED_SETUP_SOURCE_RECONCILIATION: setup_id is required"
        )
    if (
        not isinstance(bundle.candidate_date, date)
        or isinstance(bundle.candidate_date, datetime)
    ):
        raise SetupAccumulatorBlocked(
            "STATUS=BLOCKED_SETUP_SOURCE_RECONCILIATION: candidate_date is invalid"
        )
    _canonical_manifest(bundle.source_manifest_hash)
    values = {
        field: _canonical_decimal(getattr(bundle, field), field=field)
        for field in FACTOR_FIELDS
    }
    quiet_days = values["quiet_days_n"]
    if quiet_days < 0 or quiet_days != quiet_days.to_integral_value():
        raise SetupAccumulatorBlocked("invalid prospective factor: quiet_days_n")
    return values


def _normalized_key(key: object) -> FeatureIdentity:
    if not isinstance(key, tuple) or len(key) != 3:
        raise SetupAccumulatorBlocked(
            "STATUS=BLOCKED_SETUP_SOURCE_RECONCILIATION: "
            "factor bundle key must be (setup_id, candidate_date, source_manifest_hash)"
        )
    setup_id, candidate_date, source_manifest_hash = key
    if (
        not isinstance(setup_id, str)
        or not isinstance(candidate_date, date)
        or isinstance(candidate_date, datetime)
    ):
        raise SetupAccumulatorBlocked(
            "STATUS=BLOCKED_SETUP_SOURCE_RECONCILIATION: factor bundle key is invalid"
        )
    return setup_id, candidate_date, _canonical_manifest(source_manifest_hash)


def _index_factor_bundles(
    factor_bundles: Mapping[tuple[str, date, str], ProspectiveFactorBundle],
) -> dict[FeatureIdentity, ProspectiveFactorBundle]:
    indexed: dict[FeatureIdentity, ProspectiveFactorBundle] = {}
    for raw_key, bundle in factor_bundles.items():
        key = _normalized_key(raw_key)
        _validated_factor_values(bundle)
        if bundle.identity_key != key:
            raise SetupAccumulatorBlocked(
                "STATUS=BLOCKED_SETUP_SOURCE_RECONCILIATION: "
                "factor bundle key does not match its payload"
            )
        if key in indexed:
            raise SetupAccumulatorBlocked(
                "STATUS=BLOCKED_SETUP_SOURCE_RECONCILIATION: duplicate factor identity"
            )
        indexed[key] = bundle
    return indexed


def _factor_for_observation(
    indexed: Mapping[FeatureIdentity, ProspectiveFactorBundle],
    observation: population.ProspectiveObservation,
) -> ProspectiveFactorBundle:
    key = (
        observation.setup_id,
        observation.candidate_date,
        observation.source_manifest_hash,
    )
    bundle = indexed.get(key)
    if bundle is not None:
        return bundle
    same_observation = any(
        candidate_key[:2] == key[:2] for candidate_key in indexed
    )
    detail = "source_manifest_hash mismatch" if same_observation else "factor bundle is missing"
    raise SetupAccumulatorBlocked(
        f"STATUS=BLOCKED_SETUP_SOURCE_RECONCILIATION: {detail}"
    )


def _feature_hash(
    observation: population.ProspectiveObservation,
    bundle: ProspectiveFactorBundle,
    values: Mapping[str, Decimal],
) -> str:
    payload = {
        "setup_id": observation.setup_id,
        "candidate_date": observation.candidate_date.isoformat(),
        "source_manifest_hash": observation.source_manifest_hash,
        **{field: _decimal_text(values[field]) for field in FACTOR_FIELDS},
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _CapturingDailySource:
    """Capture the same PIT slice that Gate 2A receives, without re-reading it."""

    def __init__(self, source: population.DailyPITSource) -> None:
        self._source = source
        self.slice: population.DailyPITSlice | None = None

    def daily_slice(self, *, as_of: date) -> population.DailyPITSlice:
        if self.slice is not None:
            raise SetupAccumulatorBlocked("daily PIT source was requested more than once")
        self.slice = self._source.daily_slice(as_of=as_of)
        return self.slice


def _serialize_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return _decimal_text(value)
    return str(value)


def _row_sort_key(row: Mapping[str, object]) -> tuple[str, str]:
    return str(row["setup_id"]), str(row["candidate_date"])


def serialize_setup_ledger_rows(
    rows: Sequence[Mapping[str, object]],
) -> bytes:
    """Serialize rows with the exact frozen header and stable CSV bytes."""

    fieldnames = tuple(protocol.SETUP_LEDGER_COLUMNS)
    normalized_rows = sorted(rows, key=_row_sort_key)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for row in normalized_rows:
        if set(row) != set(fieldnames):
            raise SetupAccumulatorBlocked("setup ledger schema mismatch")
        writer.writerow({
            field: _serialize_value(row[field])
            for field in fieldnames
        })
    return output.getvalue().encode("utf-8")


def validate_setup_ledger_artifact(path: Path) -> None:
    """Validate the temporary artifact before atomic publication."""

    try:
        payload = path.read_bytes()
        if not payload.endswith(b"\n"):
            raise SetupAccumulatorBlocked("setup ledger must end with a newline")
        rows = list(csv.reader(payload.decode("utf-8").splitlines()))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise SetupAccumulatorBlocked("setup ledger artifact is unreadable") from exc
    if not rows or rows[0] != list(protocol.SETUP_LEDGER_COLUMNS):
        raise SetupAccumulatorBlocked("setup ledger header mismatch")
    expected_width = len(protocol.SETUP_LEDGER_COLUMNS)
    seen: set[tuple[str, str]] = set()
    for row in rows[1:]:
        if len(row) != expected_width:
            raise SetupAccumulatorBlocked("setup ledger row schema mismatch")
        identity = (row[0], row[3])
        if identity in seen:
            raise SetupAccumulatorBlocked("duplicate setup ledger identity")
        seen.add(identity)


def accumulate_setup_ledger(
    *,
    as_of: date,
    daily_source: population.DailyPITSource,
    factor_bundles: Mapping[tuple[str, date, str], ProspectiveFactorBundle],
    existing_observations: Mapping[str, population.ProspectiveObservation] | None = None,
    existing_feature_hashes: Mapping[FeatureIdentity, str] | None = None,
) -> SetupAccumulationResult:
    """Build append-only setup rows from exactly one post-close PIT slice."""

    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        raise SetupAccumulatorBlocked("as_of must be a date")
    indexed_bundles = _index_factor_bundles(factor_bundles)
    prior_observations = existing_observations or {}
    prior_hashes: dict[FeatureIdentity, str] = {}
    for raw_key, value in (existing_feature_hashes or {}).items():
        key = _normalized_key(raw_key)
        digest = str(value).strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise SetupAccumulatorBlocked("STATUS=BLOCKED_FEATURE_DRIFT: invalid prior feature hash")
        prior_hashes[key] = digest

    captured = _CapturingDailySource(daily_source)
    observations = population.generate_setups(as_of=as_of, daily_source=captured)
    if captured.slice is None:
        raise SetupAccumulatorBlocked("daily PIT source did not provide a slice")
    candidates_by_setup = {
        candidate.setup_id: candidate
        for candidate in captured.slice.candidates
    }
    calendar = ttl.authorized_run_calendar()
    rows: list[dict[str, str | None]] = []
    statuses: list[tuple[str, str]] = []
    feature_hashes: list[tuple[FeatureIdentity, str]] = []

    for observation in observations:
        bundle = _factor_for_observation(indexed_bundles, observation)
        values = _validated_factor_values(bundle)
        identity = bundle.identity_key
        feature_hash = _feature_hash(observation, bundle, values)
        prior_hash = prior_hashes.get(identity)
        if prior_hash is not None and prior_hash != feature_hash:
            raise SetupAccumulatorBlocked("STATUS=BLOCKED_FEATURE_DRIFT")
        feature_hashes.append((identity, feature_hash))

        status = population.append_first_eligible_observation(
            prior_observations,
            observation,
        )
        statuses.append((observation.observation_id, status))
        if status != "APPEND":
            continue

        candidate = candidates_by_setup.get(observation.setup_id)
        if candidate is None:
            raise SetupAccumulatorBlocked(
                "STATUS=BLOCKED_SETUP_SOURCE_RECONCILIATION: "
                "Gate 2A candidate metadata is missing"
            )
        protocol.assert_prospective_origin(
            origin=protocol.R9_ROW_ORIGIN,
            row_date=observation.candidate_date,
            run_calendar=calendar,
        )
        eligibility = ttl.first_observation_eligibility(
            setup_id=observation.setup_id,
            anchor_date=observation.anchor_date,
            candidate_date=observation.candidate_date,
            first_observation_stage=candidate.setup_stage,
            calendar=calendar,
        )
        lifecycle = ttl.finalize_ttl_lifecycle(
            eligibility=eligibility,
            calendar=calendar,
            as_of=observation.candidate_date,
            ttl_end_session_closed=(
                observation.candidate_date == eligibility.ttl_end_date
            ),
            event=None,
            structural_invalidation_date=None,
        )
        rows.append({
            "setup_id": observation.setup_id,
            "symbol": observation.symbol,
            "t0_date": observation.anchor_date,
            "candidate_date": observation.candidate_date,
            "setup_created_as_of": observation.as_of,
            "ttl_end_date": eligibility.ttl_end_date,
            "administrative_ttl_version": ttl.R9_ADMINISTRATIVE_TTL_VERSION,
            "ttl_anchor": ttl.TTL_ANCHOR,
            "ttl_calendar_manifest_hash": eligibility.calendar_manifest_hash,
            "setup_status": lifecycle.setup_status,
            "r9_active_population": lifecycle.r9_active_population,
            "daily_population_eligible": eligibility.daily_population_eligible,
            "intraday_primary_eligible": eligibility.intraday_primary_eligible,
            "intraday_ineligible_reason": eligibility.intraday_ineligible_reason,
            "event_search_start": eligibility.event_search_start,
            "event_search_end": eligibility.event_search_end,
            "daily_feature_hash": feature_hash,
            "B4": _decimal_text(values["B4"]),
            "B5": _decimal_text(values["B5"]),
            "B6": _decimal_text(values["B6"]),
            "B7": _decimal_text(values["B7"]),
            "median_range_ratio": _decimal_text(values["median_range_ratio"]),
            "quiet_days_n": _decimal_text(values["quiet_days_n"]),
            "M0_score": _decimal_text(protocol.frozen_daily_score("M0", values)),
            "M1_score": _decimal_text(protocol.frozen_daily_score("M1", values)),
            "M2_score": _decimal_text(protocol.frozen_daily_score("M2", values)),
            "activation_status": lifecycle.activation_status,
            "event_id": lifecycle.event_id,
            "source_manifest_hash": observation.source_manifest_hash,
        })

    return SetupAccumulationResult(
        rows=tuple(sorted(rows, key=_row_sort_key)),
        observation_statuses=tuple(sorted(statuses)),
        feature_hashes=tuple(sorted(feature_hashes)),
    )


def publish_setup_ledger(
    destination: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    protocol_repo_root: Path = REPO_ROOT,
) -> str:
    """Publish one immutable versioned artifact through the frozen guard."""

    protocol.validate_atomic_publication_contract(protocol.ATOMIC_PUBLICATION_STEPS)
    payload = serialize_setup_ledger_rows(rows)
    return protocol.atomic_publish_bytes(
        destination,
        payload,
        validate_temporary=validate_setup_ledger_artifact,
        protocol_repo_root=protocol_repo_root,
    )
