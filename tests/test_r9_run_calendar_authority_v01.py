"""Adversarial tests for the frozen ASL-backed R9 run-calendar authority."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))

import r9_protocol_v02 as r9  # noqa: E402
import r9_ttl_event_eligibility_v01 as ttl  # noqa: E402


pytestmark = pytest.mark.cloud_ci


def test_authorized_calendar_receipt_and_known_2026_facts_are_pinned():
    calendar = ttl.authorized_run_calendar()
    authority_path = (
        REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"
        / ttl.R9_RUN_CALENDAR_AUTHORITY_ARTIFACT
    )
    receipt = json.loads(authority_path.read_text())
    assert receipt["source_repo"] == "rootSunc/ashare-lake"
    assert receipt["source_commit"] == ttl.R9_RUN_CALENDAR_SOURCE_COMMIT
    assert receipt["source_git_blob_sha"] == ttl.R9_RUN_CALENDAR_SOURCE_GIT_BLOB_SHA
    assert receipt["authority_year"] == "2026"
    assert receipt["calendar_manifest_hash"] == ttl.R9_RUN_CALENDAR_MANIFEST_HASH
    assert receipt["session_n_60_date"] == "2026-11-09"
    assert receipt["required_tail_end_date"] == "2026-11-25"
    assert receipt["calendar_artifact_sha256"] == hashlib.sha256(
        (authority_path.parent / ttl.R9_RUN_CALENDAR_ARTIFACT).read_bytes()
    ).hexdigest()
    assert len(calendar.sessions) == 242
    assert calendar.sessions[0] == date(2026, 1, 5)
    assert calendar.sessions[-1] == date(2026, 12, 31)
    assert date(2026, 8, 10) in calendar.sessions
    assert date(2026, 8, 24) in calendar.sessions
    assert date(2026, 9, 25) not in calendar.sessions
    assert all(
        closed_date not in calendar.sessions
        for closed_date in (
            date(2026, 10, 1),
            date(2026, 10, 2),
            date(2026, 10, 3),
            date(2026, 10, 4),
            date(2026, 10, 5),
            date(2026, 10, 6),
            date(2026, 10, 7),
        )
    )
    assert date(2026, 10, 8) in calendar.sessions
    assert not any(session.year == 2027 for session in calendar.sessions)


def test_authorized_calendar_allows_post_witness_origin():
    calendar = ttl.authorized_run_calendar()
    r9.assert_prospective_origin(
        origin="R9_PROSPECTIVE",
        row_date=date(2026, 8, 24),
        run_calendar=calendar,
    )


def test_corrupted_manifest_fails_as_run_calendar_authority():
    calendar = ttl.authorized_run_calendar()
    with pytest.raises(ttl.Gate2BBlocked, match="BLOCKED_RUN_CALENDAR_AUTHORITY"):
        ttl.validate_run_calendar(replace(calendar, manifest_hash="0" * 64))


def test_self_consistent_forged_calendar_fails_independent_authority_check():
    forged = ttl.freeze_calendar(
        version="R9_RUN_CALENDAR_FAKE_V01",
        sessions=(date(2026, 8, 10), date(2026, 8, 24), date(2026, 8, 25)),
    )
    with pytest.raises(ttl.Gate2BBlocked, match="BLOCKED_RUN_CALENDAR_AUTHORITY"):
        ttl.validate_run_calendar(forged)
    with pytest.raises(ttl.Gate2BBlocked, match="BLOCKED_RUN_CALENDAR_AUTHORITY"):
        ttl.administrative_ttl_end_date(forged.sessions[0], forged)
    with pytest.raises(r9.ProtocolBlocked, match="BLOCKED_RUN_CALENDAR_AUTHORITY"):
        r9.assert_prospective_origin(
            origin="R9_PROSPECTIVE",
            row_date=date(2026, 8, 24),
            run_calendar=forged,
        )


def test_correct_authority_version_with_mutated_sessions_fails():
    authority = ttl.authorized_run_calendar()
    mutated_sessions = authority.sessions[:-1]
    mutated = replace(
        authority,
        sessions=mutated_sessions,
        manifest_hash=ttl.calendar_manifest_hash(authority.version, mutated_sessions),
    )
    with pytest.raises(ttl.Gate2BBlocked, match="BLOCKED_RUN_CALENDAR_AUTHORITY"):
        ttl.validate_run_calendar(mutated)


def test_freeze_boundary_witness_cannot_be_used_as_run_authority():
    with pytest.raises(ttl.Gate2BBlocked, match="BLOCKED_RUN_CALENDAR_AUTHORITY"):
        ttl.validate_run_calendar(ttl.protocol_freeze_calendar())


def test_fwd3_forged_calendar_is_rejected_before_endpoint_calculation():
    forged = ttl.freeze_calendar(
        version="R9_RUN_CALENDAR_FAKE_V01",
        sessions=(date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4)),
    )
    sessions = tuple(
        r9.SubsequentSession(session_date, Decimal(str(101 + index)))
        for index, session_date in enumerate(forged.sessions[1:4])
    )
    with pytest.raises(r9.ProtocolBlocked, match="BLOCKED_RUN_CALENDAR_AUTHORITY"):
        r9.forward_close_return(
            event_date=forged.sessions[0],
            reference_price=Decimal("100"),
            run_calendar=forged,
            subsequent_sessions=sessions,
            horizon=3,
        )


def test_authorized_fwd3_and_fwd5_keep_exact_session_contract():
    calendar = ttl.authorized_run_calendar()
    event_index = calendar.sessions.index(date(2026, 8, 10))
    sessions = tuple(
        r9.SubsequentSession(session_date, Decimal(str(101 + index)))
        for index, session_date in enumerate(calendar.sessions[event_index + 1:event_index + 6])
    )
    assert r9.forward_close_return(
        event_date=date(2026, 8, 10),
        reference_price=Decimal("100"),
        run_calendar=calendar,
        subsequent_sessions=sessions,
        horizon=3,
    ) == ("MATURED", Decimal("0.03"))
    assert r9.forward_close_return(
        event_date=date(2026, 8, 10),
        reference_price=Decimal("100"),
        run_calendar=calendar,
        subsequent_sessions=sessions,
        horizon=5,
    ) == ("MATURED", Decimal("0.05"))
