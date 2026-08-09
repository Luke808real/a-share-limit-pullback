"""Pure Gate 2B owner-frozen TTL and prospective-event contract tests."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))

import r9_ttl_event_eligibility_v01 as ttl  # noqa: E402
from limit_pullback.models.enums import SetupStage  # noqa: E402


pytestmark = pytest.mark.cloud_ci


T0 = date(2026, 8, 3)
T1 = date(2026, 8, 4)
T2 = date(2026, 8, 5)
T3 = date(2026, 8, 6)
T4 = date(2026, 8, 7)
T5 = date(2026, 8, 10)
T6 = date(2026, 8, 11)
T7 = date(2026, 8, 12)
T8 = date(2026, 8, 13)


def _calendar(*, through_t8: bool = True) -> ttl.FrozenAshareTradingCalendar:
    sessions = (T0, T1, T2, T3, T4, T5, T6, T7, T8)
    return ttl.freeze_calendar(
        version="TEST_FROZEN_A_SHARE_CALENDAR_V01",
        sessions=sessions if through_t8 else sessions[:-1],
    )


def _eligibility(
    *,
    candidate_date: date = T1,
    stage: SetupStage = SetupStage.B1_READY,
) -> ttl.FirstObservationEligibility:
    return ttl.first_observation_eligibility(
        setup_id="600000:20260803:1100",
        anchor_date=T0,
        candidate_date=candidate_date,
        first_observation_stage=stage,
        calendar=_calendar(),
    )


def test_owner_ttl_is_t0_anchored_to_exactly_seven_exchange_sessions():
    calendar = _calendar()
    assert ttl.R9_ADMINISTRATIVE_TTL_VERSION == "R9_V01_ADMINISTRATIVE_TTL"
    assert ttl.TTL_SELECTION_BASIS == "OWNER_PROSPECTIVE_DESIGN"
    assert ttl.TTL_ANCHOR == "anchor_date/T0"
    assert ttl.T0_AGE == 0
    assert ttl.R9_OBSERVATION_TTL == 7
    assert ttl.administrative_ttl_end_date(T0, calendar) == T7
    # T0 Monday to T7 Wednesday proves this is neither a seven-calendar-day
    # window nor a candidate-date reset.
    assert T7 != date(2026, 8, 10)


def test_candidate_at_t5_does_not_reset_ttl_or_extend_halted_symbol_lifetime():
    eligibility = _eligibility(candidate_date=T5)
    assert eligibility.ttl_end_date == T7
    assert eligibility.event_search_start == T6
    assert eligibility.event_search_end == T7
    # A halted symbol could have no T5/T6 bars. It does not enter the API;
    # exchange sessions still reach T7 on the frozen calendar.
    assert ttl.administrative_ttl_end_date(T0, _calendar()) == T7


def test_symbol_halt_does_not_extend_exchange_session_ttl():
    halted_symbol_trade_dates = (T0, T1, T3)
    assert T7 not in halted_symbol_trade_dates
    assert ttl.administrative_ttl_end_date(T0, _calendar()) == T7


def test_candidate_after_ttl_is_retained_for_audit_but_never_active():
    eligibility = _eligibility(candidate_date=T8)
    assert eligibility.daily_population_eligible is True
    assert eligibility.r9_active_population is False
    assert eligibility.setup_status == "FIRST_OBSERVED_AFTER_ADMINISTRATIVE_EXPIRY"
    assert eligibility.event_search_start is None
    final = ttl.finalize_ttl_lifecycle(
        eligibility=eligibility,
        calendar=_calendar(),
        as_of=T8,
        ttl_end_session_closed=True,
    )
    assert final.r9_active_population is False
    assert final.setup_status == "FIRST_OBSERVED_AFTER_ADMINISTRATIVE_EXPIRY"


def test_calendar_is_hash_pinned_ordered_unique_and_sufficient():
    with pytest.raises(ttl.Gate2BBlocked, match="strictly ordered"):
        ttl.freeze_calendar(version="bad", sessions=(T0, T2, T1))
    with pytest.raises(ttl.Gate2BBlocked, match="duplicate"):
        ttl.freeze_calendar(version="bad", sessions=(T0, T1, T1))
    broken_hash = replace(_calendar(), manifest_hash="0" * 64)
    with pytest.raises(ttl.Gate2BBlocked, match="manifest hash mismatch"):
        ttl.validate_frozen_calendar(broken_hash)
    insufficient = ttl.freeze_calendar(
        version="INSUFFICIENT_CALENDAR",
        sessions=(T0, T1, T2, T3, T4, T5, T6),
    )
    with pytest.raises(ttl.Gate2BBlocked, match="insufficient"):
        ttl.administrative_ttl_end_date(T0, insufficient)


def test_b1_and_b2_ready_are_intraday_eligible_only_from_next_exchange_session():
    for stage in (SetupStage.B1_READY, SetupStage.B2_READY):
        eligibility = _eligibility(candidate_date=T1, stage=stage)
        assert eligibility.daily_population_eligible is True
        assert eligibility.intraday_primary_eligible is True
        assert eligibility.event_search_start == T2
        assert eligibility.event_search_end == T7
        with pytest.raises(ttl.Gate2BBlocked, match="before prospective intraday eligibility"):
            ttl.eligible_first_s1_touch(
                eligibility=eligibility,
                calendar=_calendar(),
                event_date=T1,
                first_touch_time="10:00",
                post_activation_bar_n=1,
                right_labeled_grid_verified=True,
            )


def test_first_b2_confirmed_remains_daily_but_is_permanently_intraday_ineligible():
    eligibility = _eligibility(stage=SetupStage.B2_CONFIRMED)
    assert eligibility.daily_population_eligible is True
    assert eligibility.r9_active_population is True
    assert eligibility.intraday_primary_eligible is False
    assert eligibility.intraday_ineligible_reason == "PREOBSERVED_ACTIVATION"
    assert eligibility.event_search_start is None
    with pytest.raises(ttl.Gate2BBlocked, match="PREOBSERVED_ACTIVATION"):
        ttl.eligible_first_s1_touch(
            eligibility=eligibility,
            calendar=_calendar(),
            event_date=T2,
            first_touch_time="10:00",
            post_activation_bar_n=1,
            right_labeled_grid_verified=True,
        )


def test_t7_first_observation_remains_daily_only_when_no_future_ttl_session_exists():
    for stage in (SetupStage.B1_READY, SetupStage.B2_READY):
        eligibility = _eligibility(candidate_date=T7, stage=stage)
        assert eligibility.daily_population_eligible is True
        assert eligibility.r9_active_population is True
        assert eligibility.intraday_primary_eligible is False
        assert eligibility.intraday_ineligible_reason == "NO_ELIGIBLE_SESSION_WITHIN_TTL"
        assert eligibility.event_search_start is None
        assert eligibility.event_search_end == T7
        with pytest.raises(ttl.Gate2BBlocked, match="NO_ELIGIBLE_SESSION_WITHIN_TTL"):
            ttl.eligible_first_s1_touch(
                eligibility=eligibility,
                calendar=_calendar(),
                event_date=T7,
                first_touch_time="10:00",
                post_activation_bar_n=1,
                right_labeled_grid_verified=True,
            )


def test_event_on_t7_is_accepted_but_t8_is_rejected():
    eligibility = _eligibility()
    event = ttl.eligible_first_s1_touch(
        eligibility=eligibility,
        calendar=_calendar(),
        event_date=T7,
        first_touch_time="10:00",
        post_activation_bar_n=1,
        right_labeled_grid_verified=True,
    )
    assert event.event_date == T7
    assert event.intraday_primary_feature_status == "FEATURE_OBSERVABLE"
    with pytest.raises(ttl.Gate2BBlocked, match="after administrative TTL"):
        ttl.eligible_first_s1_touch(
            eligibility=eligibility,
            calendar=_calendar(),
            event_date=T8,
            first_touch_time="10:00",
            post_activation_bar_n=1,
            right_labeled_grid_verified=True,
        )


def test_one_event_is_immutable_and_late_touch_is_retained_without_primary_feature():
    eligibility = _eligibility()
    first = ttl.register_first_eligible_s1_touch(
        {},
        eligibility=eligibility,
        calendar=_calendar(),
        event_date=T2,
        first_touch_time="10:35",
        post_activation_bar_n=1,
        right_labeled_grid_verified=True,
    )
    assert first.intraday_primary_feature_status == "POST_CHECKPOINT_NOT_OBSERVABLE"
    assert ttl.register_first_eligible_s1_touch(
        {first.setup_id: first},
        eligibility=eligibility,
        calendar=_calendar(),
        event_date=T2,
        first_touch_time="10:35",
        post_activation_bar_n=1,
        right_labeled_grid_verified=True,
    ) == first
    with pytest.raises(ttl.Gate2BBlocked, match="REPEAT_CONFIRMATION_CREATES_NEW_EVENT=FALSE"):
        ttl.register_first_eligible_s1_touch(
            {first.setup_id: first},
            eligibility=eligibility,
            calendar=_calendar(),
            event_date=T3,
            first_touch_time="10:00",
            post_activation_bar_n=1,
            right_labeled_grid_verified=True,
        )


def test_event_requires_verified_grid_and_fails_closed_on_structural_ambiguity():
    eligibility = _eligibility()
    with pytest.raises(ttl.Gate2BBlocked, match="right-labeled"):
        ttl.eligible_first_s1_touch(
            eligibility=eligibility,
            calendar=_calendar(),
            event_date=T2,
            first_touch_time="10:00",
            post_activation_bar_n=1,
            right_labeled_grid_verified=False,
        )
    with pytest.raises(ttl.Gate2BBlocked, match="SAME_SESSION_STRUCTURAL_INVALIDATION_AMBIGUITY"):
        ttl.eligible_first_s1_touch(
            eligibility=eligibility,
            calendar=_calendar(),
            event_date=T3,
            first_touch_time="10:00",
            post_activation_bar_n=1,
            right_labeled_grid_verified=True,
            structural_invalidation_date=T3,
        )
    with pytest.raises(ttl.Gate2BBlocked, match="STRUCTURAL_INVALIDATION_PRECEDES_EVENT"):
        ttl.eligible_first_s1_touch(
            eligibility=eligibility,
            calendar=_calendar(),
            event_date=T4,
            first_touch_time="10:00",
            post_activation_bar_n=1,
            right_labeled_grid_verified=True,
            structural_invalidation_date=T3,
        )


def test_event_clock_requires_exact_shanghai_right_labeled_five_minute_boundary():
    assert ttl.canonical_clock(
        datetime(2026, 8, 5, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    ) == "10:00"
    for invalid in (
        "09:31",
        "01:00",
        "10:00:01",
        datetime(2026, 8, 5, 10, 0),
        time(10, 0, 1),
        time(10, 0, tzinfo=ZoneInfo("UTC")),
    ):
        with pytest.raises(ttl.Gate2BBlocked):
            ttl.canonical_clock(invalid)


def test_timestamped_event_clock_must_normalize_to_its_declared_event_date():
    eligibility = _eligibility()
    with pytest.raises(ttl.Gate2BBlocked, match="does not match event_date"):
        ttl.eligible_first_s1_touch(
            eligibility=eligibility,
            calendar=_calendar(),
            event_date=T2,
            first_touch_time=datetime(2026, 8, 6, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            post_activation_bar_n=1,
            right_labeled_grid_verified=True,
        )


def test_finalization_revalidates_forged_event_window_grid_and_same_day_invalidation():
    eligibility = _eligibility()
    valid_event = ttl.eligible_first_s1_touch(
        eligibility=eligibility,
        calendar=_calendar(),
        event_date=T2,
        first_touch_time="10:00",
        post_activation_bar_n=1,
        right_labeled_grid_verified=True,
    )
    for forged in (
        replace(valid_event, event_date=T8),
        replace(valid_event, first_touch_time="09:31"),
        replace(valid_event, post_activation_bar_n=-1),
        replace(valid_event, calendar_manifest_hash="0" * 64),
        replace(valid_event, right_labeled_grid_verified=False),
    ):
        with pytest.raises(ttl.Gate2BBlocked):
            ttl.finalize_ttl_lifecycle(
                eligibility=eligibility,
                calendar=_calendar(),
                as_of=T8,
                ttl_end_session_closed=True,
                event=forged,
            )
    with pytest.raises(ttl.Gate2BBlocked, match="SAME_SESSION_STRUCTURAL_INVALIDATION_AMBIGUITY"):
        ttl.finalize_ttl_lifecycle(
            eligibility=eligibility,
            calendar=_calendar(),
            as_of=T2,
            ttl_end_session_closed=True,
            event=valid_event,
            structural_invalidation_date=T2,
        )


def test_structural_invalidation_precedes_ttl_and_t7_close_finalizes_no_activation():
    eligibility = _eligibility()
    invalidated = ttl.finalize_ttl_lifecycle(
        eligibility=eligibility,
        calendar=_calendar(),
        as_of=T4,
        ttl_end_session_closed=True,
        structural_invalidation_date=T3,
    )
    assert invalidated.setup_status == "STRUCTURALLY_INVALIDATED"
    assert invalidated.activation_status == "STRUCTURAL_INVALIDATION"

    still_open = ttl.finalize_ttl_lifecycle(
        eligibility=eligibility,
        calendar=_calendar(),
        as_of=T7,
        ttl_end_session_closed=False,
    )
    assert still_open.activation_status == "PENDING_TTL_END_SESSION_OPEN"
    no_activation = ttl.finalize_ttl_lifecycle(
        eligibility=eligibility,
        calendar=_calendar(),
        as_of=T7,
        ttl_end_session_closed=True,
    )
    assert no_activation.setup_status == "NO_ACTIVATION_WITHIN_TTL"
    assert no_activation.r9_active_population is True


def test_later_structural_invalidation_cannot_erase_a_prior_immutable_event():
    eligibility = _eligibility()
    event = ttl.eligible_first_s1_touch(
        eligibility=eligibility,
        calendar=_calendar(),
        event_date=T2,
        first_touch_time="10:00",
        post_activation_bar_n=1,
        right_labeled_grid_verified=True,
    )
    final = ttl.finalize_ttl_lifecycle(
        eligibility=eligibility,
        calendar=_calendar(),
        as_of=T4,
        ttl_end_session_closed=True,
        event=event,
        structural_invalidation_date=T3,
    )
    assert final.setup_status == "STRUCTURALLY_INVALIDATED"
    assert final.activation_status == "FIRST_VALID_S1_TOUCH"
    assert final.event_id == event.event_id


def test_finalization_rejects_future_candidate_event_or_structural_invalidation():
    with pytest.raises(ttl.Gate2BBlocked, match="first observation is after finalization"):
        ttl.finalize_ttl_lifecycle(
            eligibility=_eligibility(candidate_date=T5),
            calendar=_calendar(),
            as_of=T4,
            ttl_end_session_closed=True,
        )
    eligibility = _eligibility()
    future_event = ttl.eligible_first_s1_touch(
        eligibility=eligibility,
        calendar=_calendar(),
        event_date=T3,
        first_touch_time="10:00",
        post_activation_bar_n=1,
        right_labeled_grid_verified=True,
    )
    with pytest.raises(ttl.Gate2BBlocked, match="event is after finalization"):
        ttl.finalize_ttl_lifecycle(
            eligibility=eligibility,
            calendar=_calendar(),
            as_of=T2,
            ttl_end_session_closed=True,
            event=future_event,
        )
    with pytest.raises(ttl.Gate2BBlocked, match="structural invalidation is after finalization"):
        ttl.finalize_ttl_lifecycle(
            eligibility=eligibility,
            calendar=_calendar(),
            as_of=T2,
            ttl_end_session_closed=True,
            structural_invalidation_date=T3,
        )


def test_ttl_lifecycle_cannot_replace_first_daily_identity():
    first = ttl.PrimaryDailyIdentity("600000:20260803:1100", T1, "first-hash")
    later = ttl.PrimaryDailyIdentity("600000:20260803:1100", T5, "later-hash")
    assert ttl.preserve_first_daily_identity(first, later) == first
    with pytest.raises(ttl.Gate2BBlocked, match="PRIMARY_DAILY_IDENTITY_DRIFT"):
        ttl.preserve_first_daily_identity(
            first,
            ttl.PrimaryDailyIdentity(first.setup_id, T1, "rewritten-hash"),
        )


def test_oos_start_is_calendar_derived_and_clean_date_must_be_member_after_start():
    calendar = ttl.protocol_freeze_calendar()
    assert calendar.manifest_hash == ttl.PROTOCOL_FREEZE_CALENDAR_MANIFEST_HASH
    assert ttl.OOS_START == ttl.clean_oos_start(ttl.PROTOCOL_FREEZE_DATE, calendar)
    assert ttl.OOS_START == date(2026, 8, 10)
    ttl.assert_clean_oos_candidate_date(
        candidate_date=ttl.OOS_START,
        protocol_freeze_date=ttl.PROTOCOL_FREEZE_DATE,
        calendar=calendar,
        oos_start=ttl.OOS_START,
    )
    with pytest.raises(ttl.Gate2BBlocked, match="absent from frozen A-share calendar"):
        ttl.assert_clean_oos_candidate_date(
            candidate_date=ttl.PROTOCOL_FREEZE_DATE,
            protocol_freeze_date=ttl.PROTOCOL_FREEZE_DATE,
            calendar=calendar,
            oos_start=ttl.OOS_START,
        )


def test_protocol_freeze_calendar_artifact_matches_the_hash_pinned_session_witness():
    path = REPO_ROOT / "research" / "second_launch" / "walk_forward_v01" / ttl.PROTOCOL_FREEZE_CALENDAR_ARTIFACT
    sessions = tuple(date.fromisoformat(value) for value in path.read_text().splitlines()[1:])
    assert sessions == ttl.PROTOCOL_FREEZE_CALENDAR_SESSIONS
    assert ttl.calendar_manifest_hash(ttl.PROTOCOL_FREEZE_CALENDAR_VERSION, sessions) == ttl.PROTOCOL_FREEZE_CALENDAR_MANIFEST_HASH


def test_static_guard_excludes_ttl_search_or_optimization_symbols():
    source = Path(ttl.__file__).read_text()
    for forbidden in ("optimize_ttl", "best_ttl", "ttl_grid"):
        assert forbidden not in source
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any(
        fragment in module
        for module in imported
        for fragment in ("outcome", "pandas", "pyarrow", "trade_plan", "replay")
    )
    assert "timedelta" not in source
    assert ".weekday(" not in source
