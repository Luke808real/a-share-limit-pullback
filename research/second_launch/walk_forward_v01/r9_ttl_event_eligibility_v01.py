"""Pure R9 Gate 2B administrative TTL and prospective event contract.

This module has no provider, ledger, outcome, TradePlan, or strategy-engine
dependency.  It consumes an already frozen exchange-session calendar and an
already determined structural invalidation date, if one exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
import hashlib
from zoneinfo import ZoneInfo

from limit_pullback.models.enums import SetupStage


R9_ADMINISTRATIVE_TTL_VERSION = "R9_V01_ADMINISTRATIVE_TTL"
TTL_SELECTION_BASIS = "OWNER_PROSPECTIVE_DESIGN"
TTL_ANCHOR = "anchor_date/T0"
T0_AGE = 0
R9_OBSERVATION_TTL = 7
TTL_UNIT = "SUBSEQUENT_A_SHARE_TRADING_SESSIONS"
TTL_WINDOW = "T+1...T+7"
STRUCTURAL_INVALIDATION_STATUS = "DEFERRED_TO_EXISTING_STATE_SEMANTICS"
REPEAT_CONFIRMATION_CREATES_NEW_EVENT = False
PRIMARY_CHECKPOINT = "10:30"
R9_EVENT_TIMEZONE = "Asia/Shanghai"
RIGHT_LABELED_5M_GRID = (
    *(f"09:{minute:02d}" for minute in range(35, 60, 5)),
    *(f"10:{minute:02d}" for minute in range(0, 60, 5)),
    *(f"11:{minute:02d}" for minute in range(0, 35, 5)),
    *(f"13:{minute:02d}" for minute in range(5, 60, 5)),
    *(f"14:{minute:02d}" for minute in range(0, 60, 5)),
    "15:00",
)
ACTIONABLE_FIRST_OBSERVATION_STAGES = frozenset({
    SetupStage.B1_READY,
    SetupStage.B2_READY,
    SetupStage.B2_CONFIRMED,
})

PROTOCOL_FREEZE_DATE = date(2026, 8, 9)
PROTOCOL_FREEZE_CALENDAR_VERSION = "R9_PROTOCOL_FREEZE_CALENDAR_V01"
PROTOCOL_FREEZE_CALENDAR_SOURCE = "OWNER_FROZEN_A_SHARE_SESSION_WITNESS"
PROTOCOL_FREEZE_CALENDAR_ARTIFACT = "r9_protocol_freeze_calendar_v01.csv"
PROTOCOL_FREEZE_CALENDAR_SESSIONS = (
    date(2026, 8, 10),
    date(2026, 8, 11),
    date(2026, 8, 12),
    date(2026, 8, 13),
    date(2026, 8, 14),
    date(2026, 8, 17),
    date(2026, 8, 18),
    date(2026, 8, 19),
    date(2026, 8, 20),
    date(2026, 8, 21),
)
PROTOCOL_FREEZE_CALENDAR_MANIFEST_HASH = (
    "9304f0409d7e95b54e2ba90f361d0228624cb313722ad4a97a2fa1b891087d2e"
)
RUN_CALENDAR_VERSION_PREFIX = "R9_RUN_CALENDAR_"


class Gate2BBlocked(RuntimeError):
    """A Gate 2B TTL, calendar, or prospective-event rule was violated."""


def canonical_clock(value: str | datetime | time) -> str:
    """Normalize one Asia/Shanghai right-labeled 5m event clock."""

    localized = _localized_datetime_or_none(value)
    if localized is not None:
        clock = localized.strftime("%H:%M")
        _assert_right_labeled_5m_clock(clock)
        return clock
    if isinstance(value, time):
        if value.tzinfo is not None:
            raise Gate2BBlocked("time-only event clock must be an Asia/Shanghai local clock")
        _assert_exact_bar_boundary(value)
        clock = value.strftime("%H:%M")
        _assert_right_labeled_5m_clock(clock)
        return clock
    text = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed_clock = datetime.strptime(text, fmt)
            _assert_exact_bar_boundary(parsed_clock)
            clock = parsed_clock.strftime("%H:%M")
            _assert_right_labeled_5m_clock(clock)
            return clock
        except ValueError:
            pass
    raise Gate2BBlocked(f"invalid first-touch clock: {value!r}")


def _assert_right_labeled_5m_clock(clock: str) -> None:
    if clock not in RIGHT_LABELED_5M_GRID:
        raise Gate2BBlocked("event clock is not a right-labeled 5m session bar")


def _assert_exact_bar_boundary(value: datetime | time) -> None:
    if value.second or value.microsecond:
        raise Gate2BBlocked("event clock must be an exact right-labeled bar boundary")


def _localized_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise Gate2BBlocked("datetime event clock requires timezone")
    localized = value.astimezone(ZoneInfo(R9_EVENT_TIMEZONE))
    _assert_exact_bar_boundary(localized)
    return localized


def _localized_datetime_or_none(value: str | datetime | time) -> datetime | None:
    if isinstance(value, datetime):
        return _localized_datetime(value)
    if isinstance(value, time):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None
    return _localized_datetime(parsed)


def _assert_datetime_matches_event_date(
    value: str | datetime | time,
    event_date: date,
) -> None:
    localized = _localized_datetime_or_none(value)
    if localized is not None and localized.date() != event_date:
        raise Gate2BBlocked("event datetime date does not match event_date")


def calendar_manifest_hash(version: str, sessions: Sequence[date]) -> str:
    payload = f"{version}\n" + "\n".join(
        session.isoformat() for session in sessions
    ) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FrozenAshareTradingCalendar:
    """An ordered, hash-pinned exchange session calendar supplied to R9."""

    version: str
    sessions: tuple[date, ...]
    manifest_hash: str


def freeze_calendar(
    *,
    version: str,
    sessions: Sequence[date],
) -> FrozenAshareTradingCalendar:
    frozen = FrozenAshareTradingCalendar(
        version=version,
        sessions=tuple(sessions),
        manifest_hash=calendar_manifest_hash(version, sessions),
    )
    validate_frozen_calendar(frozen)
    return frozen


def validate_frozen_calendar(calendar: FrozenAshareTradingCalendar) -> None:
    if not calendar.version:
        raise Gate2BBlocked("frozen calendar version is required")
    if not calendar.sessions:
        raise Gate2BBlocked("frozen calendar has no sessions")
    if tuple(sorted(calendar.sessions)) != calendar.sessions:
        raise Gate2BBlocked("frozen calendar must be strictly ordered")
    if len(set(calendar.sessions)) != len(calendar.sessions):
        raise Gate2BBlocked("frozen calendar has duplicate sessions")
    expected = calendar_manifest_hash(calendar.version, calendar.sessions)
    if calendar.manifest_hash != expected:
        raise Gate2BBlocked("frozen calendar manifest hash mismatch")


def validate_run_calendar(calendar: FrozenAshareTradingCalendar) -> None:
    """Validate an explicit, versioned calendar used by a future R9 run.

    The short protocol-freeze witness establishes ``OOS_START`` only.  A run
    calendar must therefore carry its own provenance/version and manifest hash;
    callers cannot silently reuse the boundary witness as the future calendar.
    """

    validate_frozen_calendar(calendar)
    if not calendar.version.startswith(RUN_CALENDAR_VERSION_PREFIX):
        raise Gate2BBlocked("R9 run calendar provenance/version is required")


def protocol_freeze_calendar() -> FrozenAshareTradingCalendar:
    calendar = FrozenAshareTradingCalendar(
        version=PROTOCOL_FREEZE_CALENDAR_VERSION,
        sessions=PROTOCOL_FREEZE_CALENDAR_SESSIONS,
        manifest_hash=PROTOCOL_FREEZE_CALENDAR_MANIFEST_HASH,
    )
    validate_frozen_calendar(calendar)
    return calendar


def _session_index(value: date, calendar: FrozenAshareTradingCalendar) -> int:
    validate_frozen_calendar(calendar)
    try:
        return calendar.sessions.index(value)
    except ValueError as exc:
        raise Gate2BBlocked("date is absent from frozen A-share calendar") from exc


def next_exchange_session_strictly_after(
    value: date,
    calendar: FrozenAshareTradingCalendar,
) -> date:
    validate_frozen_calendar(calendar)
    for session in calendar.sessions:
        if session > value:
            return session
    raise Gate2BBlocked("frozen calendar has no session strictly after date")


def administrative_ttl_end_date(
    anchor_date: date,
    calendar: FrozenAshareTradingCalendar,
) -> date:
    """Return calendar[index(T0)+7]; never use calendar-day arithmetic."""

    anchor_index = _session_index(anchor_date, calendar)
    end_index = anchor_index + R9_OBSERVATION_TTL
    if end_index >= len(calendar.sessions):
        raise Gate2BBlocked("frozen calendar is insufficient for administrative TTL")
    return calendar.sessions[end_index]


def _stage(value: SetupStage | str) -> SetupStage:
    try:
        return SetupStage(str(value))
    except ValueError as exc:
        raise Gate2BBlocked("invalid first-observation setup stage") from exc


def _assert_calendar_matches(
    expected_hash: str,
    calendar: FrozenAshareTradingCalendar,
) -> None:
    validate_frozen_calendar(calendar)
    if expected_hash != calendar.manifest_hash:
        raise Gate2BBlocked("frozen calendar hash drift")


@dataclass(frozen=True)
class FirstObservationEligibility:
    """Daily and intraday permissions derived from immutable first observation."""

    setup_id: str
    anchor_date: date
    candidate_date: date
    first_observation_stage: SetupStage
    ttl_end_date: date
    calendar_manifest_hash: str
    daily_population_eligible: bool
    r9_active_population: bool
    setup_status: str
    intraday_primary_eligible: bool
    intraday_ineligible_reason: str | None
    event_search_start: date | None
    event_search_end: date | None
    event_search_status: str


def first_observation_eligibility(
    *,
    setup_id: str,
    anchor_date: date,
    candidate_date: date,
    first_observation_stage: SetupStage | str,
    calendar: FrozenAshareTradingCalendar,
) -> FirstObservationEligibility:
    """Freeze event eligibility without changing the P1 daily identity."""

    stage = _stage(first_observation_stage)
    if stage not in ACTIONABLE_FIRST_OBSERVATION_STAGES:
        raise Gate2BBlocked("first observation is not a Gate 2A population stage")
    _session_index(candidate_date, calendar)
    ttl_end = administrative_ttl_end_date(anchor_date, calendar)
    if candidate_date <= anchor_date:
        raise Gate2BBlocked("candidate date must be strictly after anchor date")
    base = dict(
        setup_id=setup_id,
        anchor_date=anchor_date,
        candidate_date=candidate_date,
        first_observation_stage=stage,
        ttl_end_date=ttl_end,
        calendar_manifest_hash=calendar.manifest_hash,
        daily_population_eligible=True,
    )
    if candidate_date > ttl_end:
        return FirstObservationEligibility(
            **base,
            r9_active_population=False,
            setup_status="FIRST_OBSERVED_AFTER_ADMINISTRATIVE_EXPIRY",
            intraday_primary_eligible=False,
            intraday_ineligible_reason="ADMINISTRATIVE_TTL_EXPIRED",
            event_search_start=None,
            event_search_end=None,
            event_search_status="CLOSED_ADMINISTRATIVE_EXPIRY",
        )
    if stage is SetupStage.B2_CONFIRMED:
        return FirstObservationEligibility(
            **base,
            r9_active_population=True,
            setup_status="ACTIVE",
            intraday_primary_eligible=False,
            intraday_ineligible_reason="PREOBSERVED_ACTIVATION",
            event_search_start=None,
            event_search_end=None,
            event_search_status="CLOSED_PREOBSERVED_ACTIVATION",
        )
    sessions_in_window = tuple(
        session
        for session in calendar.sessions
        if candidate_date < session <= ttl_end
    )
    if not sessions_in_window:
        return FirstObservationEligibility(
            **base,
            r9_active_population=True,
            setup_status="ACTIVE",
            intraday_primary_eligible=False,
            intraday_ineligible_reason="NO_ELIGIBLE_SESSION_WITHIN_TTL",
            event_search_start=None,
            event_search_end=ttl_end,
            event_search_status="NO_ELIGIBLE_SESSION_WITHIN_TTL",
        )
    return FirstObservationEligibility(
        **base,
        r9_active_population=True,
        setup_status="ACTIVE",
        intraday_primary_eligible=True,
        intraday_ineligible_reason=None,
        event_search_start=sessions_in_window[0],
        event_search_end=ttl_end,
        event_search_status="OPEN",
    )


@dataclass(frozen=True)
class FirstS1TouchEvent:
    """A Gate 2B-window-valid first S1 touch only."""

    setup_id: str
    event_date: date
    first_touch_time: str
    post_activation_bar_n: int
    calendar_manifest_hash: str
    right_labeled_grid_verified: bool
    intraday_primary_feature_status: str

    @property
    def event_id(self) -> str:
        return (
            f"{self.setup_id}:S1:{self.event_date:%Y%m%d}:"
            f"{self.first_touch_time.replace(':', '')}"
        )


def _feature_status(first_touch_time: str, post_activation_bar_n: int) -> str:
    if first_touch_time > PRIMARY_CHECKPOINT:
        return "POST_CHECKPOINT_NOT_OBSERVABLE"
    if post_activation_bar_n <= 0:
        return "NO_POST_ACTIVATION_BAR"
    return "FEATURE_OBSERVABLE"


def eligible_first_s1_touch(
    *,
    eligibility: FirstObservationEligibility,
    calendar: FrozenAshareTradingCalendar,
    event_date: date,
    first_touch_time: str | datetime | time,
    post_activation_bar_n: int,
    right_labeled_grid_verified: bool,
    structural_invalidation_date: date | None = None,
) -> FirstS1TouchEvent:
    """Validate an event is prospective, in-window, and not structurally ended."""

    _assert_calendar_matches(eligibility.calendar_manifest_hash, calendar)
    if not right_labeled_grid_verified:
        raise Gate2BBlocked("right-labeled minute grid is not verified")
    if (
        isinstance(post_activation_bar_n, bool)
        or not isinstance(post_activation_bar_n, int)
        or post_activation_bar_n < 0
    ):
        raise Gate2BBlocked("post-activation bar count must be a non-negative integer")
    if not eligibility.r9_active_population:
        raise Gate2BBlocked(eligibility.setup_status)
    if eligibility.intraday_ineligible_reason is not None:
        raise Gate2BBlocked(eligibility.intraday_ineligible_reason)
    if eligibility.event_search_start is None or eligibility.event_search_end is None:
        raise Gate2BBlocked(eligibility.event_search_status)
    _session_index(event_date, calendar)
    if event_date < eligibility.event_search_start:
        raise Gate2BBlocked("event is before prospective intraday eligibility")
    if event_date > eligibility.event_search_end:
        raise Gate2BBlocked("event is after administrative TTL")
    if structural_invalidation_date is not None:
        _session_index(structural_invalidation_date, calendar)
        if structural_invalidation_date < event_date:
            raise Gate2BBlocked("STRUCTURAL_INVALIDATION_PRECEDES_EVENT")
        if structural_invalidation_date == event_date:
            raise Gate2BBlocked("SAME_SESSION_STRUCTURAL_INVALIDATION_AMBIGUITY")
    _assert_datetime_matches_event_date(first_touch_time, event_date)
    clock = canonical_clock(first_touch_time)
    return FirstS1TouchEvent(
        setup_id=eligibility.setup_id,
        event_date=event_date,
        first_touch_time=clock,
        post_activation_bar_n=post_activation_bar_n,
        calendar_manifest_hash=calendar.manifest_hash,
        right_labeled_grid_verified=right_labeled_grid_verified,
        intraday_primary_feature_status=_feature_status(clock, post_activation_bar_n),
    )


def validate_registered_first_s1_touch(
    event: FirstS1TouchEvent,
    *,
    eligibility: FirstObservationEligibility,
    calendar: FrozenAshareTradingCalendar,
    structural_invalidation_date: date | None = None,
) -> None:
    """Revalidate event provenance before a later lifecycle finalization."""

    if event.setup_id != eligibility.setup_id:
        raise Gate2BBlocked("event setup_id does not match first observation")
    if event.calendar_manifest_hash != eligibility.calendar_manifest_hash:
        raise Gate2BBlocked("event calendar manifest hash drift")
    expected = eligible_first_s1_touch(
        eligibility=eligibility,
        calendar=calendar,
        event_date=event.event_date,
        first_touch_time=event.first_touch_time,
        post_activation_bar_n=event.post_activation_bar_n,
        right_labeled_grid_verified=event.right_labeled_grid_verified,
        structural_invalidation_date=structural_invalidation_date,
    )
    if event != expected:
        raise Gate2BBlocked("registered event payload drift")


def register_first_eligible_s1_touch(
    existing: Mapping[str, FirstS1TouchEvent],
    *,
    eligibility: FirstObservationEligibility,
    calendar: FrozenAshareTradingCalendar,
    event_date: date,
    first_touch_time: str | datetime | time,
    post_activation_bar_n: int,
    right_labeled_grid_verified: bool,
    structural_invalidation_date: date | None = None,
) -> FirstS1TouchEvent:
    """Append one eligible event, never a later replacement or reconfirmation."""

    candidate = eligible_first_s1_touch(
        eligibility=eligibility,
        calendar=calendar,
        event_date=event_date,
        first_touch_time=first_touch_time,
        post_activation_bar_n=post_activation_bar_n,
        right_labeled_grid_verified=right_labeled_grid_verified,
        structural_invalidation_date=structural_invalidation_date,
    )
    prior = existing.get(candidate.setup_id)
    if prior is None:
        return candidate
    if prior == candidate:
        return prior
    raise Gate2BBlocked("REPEAT_CONFIRMATION_CREATES_NEW_EVENT=FALSE")


@dataclass(frozen=True)
class TTLFinalization:
    """Lifecycle status kept separate from P1 daily identity."""

    setup_status: str
    activation_status: str
    r9_active_population: bool
    event_id: str | None = None


def finalize_ttl_lifecycle(
    *,
    eligibility: FirstObservationEligibility,
    calendar: FrozenAshareTradingCalendar,
    as_of: date,
    ttl_end_session_closed: bool,
    event: FirstS1TouchEvent | None = None,
    structural_invalidation_date: date | None = None,
) -> TTLFinalization:
    """Apply existing structural-end date before owner TTL finalization."""

    _assert_calendar_matches(eligibility.calendar_manifest_hash, calendar)
    _session_index(as_of, calendar)
    if eligibility.candidate_date > as_of:
        raise Gate2BBlocked("first observation is after finalization as_of")
    if structural_invalidation_date is not None and structural_invalidation_date > as_of:
        raise Gate2BBlocked("structural invalidation is after finalization as_of")
    if event is not None:
        if event.event_date > as_of:
            raise Gate2BBlocked("event is after finalization as_of")
        validate_registered_first_s1_touch(
            event,
            eligibility=eligibility,
            calendar=calendar,
            structural_invalidation_date=structural_invalidation_date,
        )
    if eligibility.setup_status == "FIRST_OBSERVED_AFTER_ADMINISTRATIVE_EXPIRY":
        return TTLFinalization(
            setup_status=eligibility.setup_status,
            activation_status="NOT_ACTIVE_AFTER_ADMINISTRATIVE_EXPIRY",
            r9_active_population=False,
        )
    if structural_invalidation_date is not None:
        _session_index(structural_invalidation_date, calendar)
        if (
            structural_invalidation_date <= eligibility.ttl_end_date
            and structural_invalidation_date <= as_of
        ):
            if event is not None:
                return TTLFinalization(
                    setup_status="STRUCTURALLY_INVALIDATED",
                    activation_status="FIRST_VALID_S1_TOUCH",
                    r9_active_population=True,
                    event_id=event.event_id,
                )
            return TTLFinalization(
                setup_status="STRUCTURALLY_INVALIDATED",
                activation_status="STRUCTURAL_INVALIDATION",
                r9_active_population=True,
            )
    if event is not None:
        return TTLFinalization(
            setup_status="EVENT_RECORDED",
            activation_status="FIRST_VALID_S1_TOUCH",
            r9_active_population=True,
            event_id=event.event_id,
        )
    if eligibility.intraday_ineligible_reason == "PREOBSERVED_ACTIVATION":
        return TTLFinalization(
            setup_status="PREOBSERVED_ACTIVATION",
            activation_status="PREOBSERVED_ACTIVATION",
            r9_active_population=True,
        )
    if as_of < eligibility.ttl_end_date:
        return TTLFinalization("ACTIVE", "PENDING", True)
    if as_of == eligibility.ttl_end_date and not ttl_end_session_closed:
        return TTLFinalization("ACTIVE", "PENDING_TTL_END_SESSION_OPEN", True)
    return TTLFinalization(
        setup_status="NO_ACTIVATION_WITHIN_TTL",
        activation_status="NO_ACTIVATION_WITHIN_TTL",
        r9_active_population=True,
    )


@dataclass(frozen=True)
class PrimaryDailyIdentity:
    """Immutable first daily observation identity; TTL cannot overwrite it."""

    setup_id: str
    candidate_date: date
    daily_feature_hash: str


def preserve_first_daily_identity(
    first: PrimaryDailyIdentity,
    candidate: PrimaryDailyIdentity,
) -> PrimaryDailyIdentity:
    if first.setup_id != candidate.setup_id:
        raise Gate2BBlocked("daily identity setup mismatch")
    if candidate.candidate_date < first.candidate_date:
        raise Gate2BBlocked("FIRST_ELIGIBLE_OBSERVATION_DRIFT")
    if candidate.candidate_date == first.candidate_date and candidate != first:
        raise Gate2BBlocked("PRIMARY_DAILY_IDENTITY_DRIFT")
    return first


def clean_oos_start(
    protocol_freeze_date: date,
    calendar: FrozenAshareTradingCalendar,
) -> date:
    """Derive, never hardcode, the first clean exchange session after freeze."""

    return next_exchange_session_strictly_after(protocol_freeze_date, calendar)


def assert_clean_oos_candidate_date(
    *,
    candidate_date: date,
    protocol_freeze_date: date,
    calendar: FrozenAshareTradingCalendar,
    oos_start: date,
) -> None:
    _session_index(candidate_date, calendar)
    derived_start = clean_oos_start(protocol_freeze_date, calendar)
    if oos_start != derived_start:
        raise Gate2BBlocked("OOS start does not match frozen calendar")
    if candidate_date < oos_start:
        raise Gate2BBlocked("candidate date is before clean R9 OOS start")


PROTOCOL_FREEZE_CALENDAR = protocol_freeze_calendar()
OOS_START = clean_oos_start(PROTOCOL_FREEZE_DATE, PROTOCOL_FREEZE_CALENDAR)
