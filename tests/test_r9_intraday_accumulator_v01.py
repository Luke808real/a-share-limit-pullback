"""Targeted synthetic tests for the minimal R9 intraday accumulator.

No real minute data, no outcome reads, no ledger publication outside tmp_path.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "intraday_v01"))
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r9_intraday_accumulator_v01 as accumulator  # noqa: E402
import r9_protocol_v02 as protocol  # noqa: E402
import r9_ttl_event_eligibility_v01 as ttl  # noqa: E402
from limit_pullback.strategy.engine import make_setup_id  # noqa: E402


CALENDAR = ttl.authorized_run_calendar()
EVENT_DATE = date(2026, 8, 11)

GRID = protocol.r9_full_session_grid()


def _manifest() -> dict:
    return {
        "ASL_CODE_SHA": protocol.ASL_CODE_SHA,
        "source": "tdx_protocol",
        "schema_version": "v1",
        "partition_list": "2026-08-11",
        "partition_hashes": "synthetic",
        "units": "shares/RMB",
        "timezone": "Asia/Shanghai",
        "bar_label_semantics": "RIGHT_LABELED",
        "ingested_at": "2026-08-11T16:00:00+08:00",
    }


def _bar_rows(
    *,
    touch_at: str = "10:00",
    high_above: bool = True,
    trade_date: str = "2026-08-11",
) -> list[dict]:
    """A full right-labeled session; one bar (touch_at) has HIGH >= S1."""
    rows = []
    for clock in GRID:
        high = 10.8 if (high_above and clock == touch_at) else 10.2
        low = 9.8
        close = 10.5 if clock <= "10:30" else 10.4
        rows.append({
            "symbol": "000001.SZ",
            "trade_date": trade_date,
            "bar_time": clock,
            "open": "10.0",
            "high": str(high),
            "low": str(low),
            "close": str(close),
            "volume": "1000",
            "amount": "10500",
        })
    return rows


def _authority(
    *,
    stage: str = "B1_READY",
    minute_s1_price: str | None = None,
) -> accumulator.IntradaySetupAuthority:
    anchor = date(2026, 8, 5)
    candidate = date(2026, 8, 10)
    setup_id = make_setup_id("000001", anchor, Decimal("10.00"), Decimal("0.01"))
    eligibility = ttl.first_observation_eligibility(
        setup_id=setup_id,
        anchor_date=anchor,
        candidate_date=candidate,
        first_observation_stage=stage,
        calendar=CALENDAR,
    )
    return accumulator.IntradaySetupAuthority(
        setup_id=setup_id,
        symbol="000001",
        t0_date=anchor,
        candidate_date=candidate,
        ttl_end_date=eligibility.ttl_end_date,
        first_observation_stage=stage,
        intraday_primary_eligible=eligibility.intraday_primary_eligible,
        intraday_ineligible_reason=eligibility.intraday_ineligible_reason,
        event_search_start=eligibility.event_search_start,
        event_search_end=eligibility.event_search_end,
        s1_price=Decimal("10.50"),
        price_tick=Decimal("0.01"),
        minute_s1_price=minute_s1_price,
    )


# ---- A. Valid event -> APPEND one row ----


def test_a_valid_event_appends_one_row():
    auth = _authority(stage="B1_READY")
    assert auth.intraday_primary_eligible is True
    result = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(touch_at="10:00"),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert result.status == "APPEND"
    assert result.row is not None
    assert result.row["setup_id"] == auth.setup_id
    assert result.row["event_date"] == "2026-08-11"
    assert result.row["checkpoint"] == "10:30"
    assert result.row["activation_time"] == "10:00"
    assert result.row["intraday_primary_feature_status"] == "FEATURE_OBSERVABLE"
    assert result.row["reference_price_10_30"] == "10.5"  # 10:30 completed close
    assert result.row["breakout_hold_ratio"] is not None
    assert set(result.row) == set(protocol.INTRADAY_LEDGER_COLUMNS)


# ---- B. PREOBSERVED (first stage B2_CONFIRMED) -> no row ----


def test_b_preobserved_no_row():
    auth = _authority(stage="B2_CONFIRMED")
    assert auth.intraday_primary_eligible is False
    result = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert result.row is None
    assert "PREOBSERVED_ACTIVATION" in result.status


# ---- C. TTL expired -> no row ----


def test_c_ttl_expired_no_row():
    anchor = date(2026, 7, 29)
    candidate = date(2026, 8, 10)
    setup_id = make_setup_id("000002", anchor, Decimal("11.00"), Decimal("0.01"))
    eligibility = ttl.first_observation_eligibility(
        setup_id=setup_id,
        anchor_date=anchor,
        candidate_date=candidate,
        first_observation_stage="B2_READY",
        calendar=CALENDAR,
    )
    assert eligibility.intraday_primary_eligible is False
    assert eligibility.intraday_ineligible_reason == "ADMINISTRATIVE_TTL_EXPIRED"
    auth = accumulator.IntradaySetupAuthority(
        setup_id=setup_id, symbol="000002", t0_date=anchor,
        candidate_date=candidate, ttl_end_date=eligibility.ttl_end_date,
        first_observation_stage="B2_READY",
        intraday_primary_eligible=eligibility.intraday_primary_eligible,
        intraday_ineligible_reason=eligibility.intraday_ineligible_reason,
        event_search_start=eligibility.event_search_start,
        event_search_end=eligibility.event_search_end,
        s1_price=Decimal("11.50"), price_tick=Decimal("0.01"),
    )
    result = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert result.row is None
    assert "ADMINISTRATIVE_TTL_EXPIRED" in result.status


# ---- D. Event outside window -> no row (event before search start) ----


def test_d_event_outside_window_no_row():
    auth = _authority(stage="B1_READY")
    # event on candidate date itself: session exists but the event is before
    # event_search_start, so the frozen Gate 2B path refuses and no row is written.
    result = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(trade_date="2026-08-10"),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=auth.candidate_date,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert result.row is None
    assert result.status.startswith("EVENT_REJECTED_")


# ---- E. repeat exact -> ALREADY_RECORDED ----


def test_e_repeat_exact_already_recorded():
    auth = _authority(stage="B1_READY")
    first = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(touch_at="10:00"),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert first.status == "APPEND"
    # Second identical accumulation: same event identity + same feature hash.
    second = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(touch_at="10:00"),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={(auth.setup_id, first.event_id, "10:30"): first.feature_hash},
        calendar=CALENDAR,
    )
    assert second.status == "ALREADY_RECORDED"
    assert second.row is None  # ALREADY_RECORDED never emits a new row


# ---- F. feature drift -> BLOCKED_FEATURE_DRIFT ----


def test_f_feature_drift_blocked():
    auth = _authority(stage="B1_READY")
    first = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(touch_at="10:00"),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert first.status == "APPEND"
    wrong_hash = "0" * 64
    with pytest.raises(protocol.FeatureDriftBlocked):
        accumulator.accumulate_intraday_observation(
            authority=auth,
            minute_rows=_bar_rows(touch_at="10:00"),
            minute_manifest=_manifest(),
            right_label_verified=True,
            event_date=EVENT_DATE,
            existing_events={},
            existing_feature_hashes={
                (auth.setup_id, first.event_id, "10:30"): wrong_hash
            },
            calendar=CALENDAR,
        )


# ---- G. minute manifest mismatch -> fail closed ----


def test_g_minute_manifest_mismatch_fails_closed():
    auth = _authority(stage="B1_READY")
    bad_manifest = {**_manifest(), "ASL_CODE_SHA": "0000000000000000000000000000000000000000000000000000000000000000"}
    with pytest.raises(protocol.ProtocolBlocked):
        accumulator.accumulate_intraday_observation(
            authority=auth,
            minute_rows=_bar_rows(),
            minute_manifest=bad_manifest,
            right_label_verified=True,
            event_date=EVENT_DATE,
            existing_events={},
            existing_feature_hashes={},
            calendar=CALENDAR,
        )


# ---- H. S1 / tick reconciliation mismatch -> fail closed ----
# The accumulator takes S1 from caller authority; a caller-side mismatch is
# exercised by the frozen reconciliation helper directly, and the accumulator
# refuses manifest/session mismatch above.  Here we additionally require the
# frozen reconciliation contract to reject a tick-inconsistent S1.


def test_h_s1_tick_reconciliation_mismatch_fails_closed():
    # Reconciliation is integrated inside the accumulator: a minute-side S1
    # that disagrees with the daily authority fails closed on the real path.
    auth = _authority(stage="B1_READY", minute_s1_price="10.51")
    with pytest.raises(protocol.ProtocolBlocked, match="BLOCKED_PRICE_RECONCILIATION"):
        accumulator.accumulate_intraday_observation(
            authority=auth,
            minute_rows=_bar_rows(),
            minute_manifest=_manifest(),
            right_label_verified=True,
            event_date=EVENT_DATE,
            existing_events={},
            existing_feature_hashes={},
            calendar=CALENDAR,
        )
    # Exact reconciliation passes through the accumulator.
    ok = accumulator.accumulate_intraday_observation(
        authority=_authority(stage="B1_READY", minute_s1_price="10.50"),
        minute_rows=_bar_rows(),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert ok.status == "APPEND"


# ---- I. right-label violation -> fail closed ----


def test_i_right_label_violation_fails_closed():
    auth = _authority(stage="B1_READY")
    with pytest.raises(protocol.ProtocolBlocked):
        accumulator.accumulate_intraday_observation(
            authority=auth,
            minute_rows=_bar_rows(),
            minute_manifest=_manifest(),
            right_label_verified=False,
            event_date=EVENT_DATE,
            existing_events={},
            existing_feature_hashes={},
            calendar=CALENDAR,
        )


# ---- J. deterministic serialization ----


def test_j_deterministic_serialization():
    auth = _authority(stage="B1_READY")
    r1 = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(touch_at="10:00"),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    auth2 = _authority(stage="B2_READY")
    r2 = accumulator.accumulate_intraday_observation(
        authority=auth2,
        minute_rows=_bar_rows(touch_at="09:40"),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    rows = [r1.row, r2.row]
    forward = accumulator.serialize_intraday_ledger_rows(rows)
    reverse = accumulator.serialize_intraday_ledger_rows(list(reversed(rows)))
    assert forward == reverse
    assert forward.endswith(b"\n")
    import hashlib
    h1 = hashlib.sha256(forward).hexdigest()
    h2 = hashlib.sha256(reverse).hexdigest()
    assert h1 == h2


# ---- K. atomic append-only: second publish to same destination fails ----


def test_k_atomic_append_only_no_overwrite(tmp_path: Path):
    auth = _authority(stage="B1_READY")
    r = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(touch_at="10:00"),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    destination = tmp_path / "r9_intraday_ledger_2026-08-11_v01.csv"
    accumulator.publish_intraday_ledger(
        destination, [r.row], protocol_repo_root=REPO_ROOT
    )
    with pytest.raises(protocol.ProtocolBlocked):
        accumulator.publish_intraday_ledger(
            destination, [r.row], protocol_repo_root=REPO_ROOT
        )
    assert destination.read_bytes().count(b"\n") == 2  # header + 1 row


# ---- L. no binary B2 rule in implementation ----


def test_l_no_binary_b2_rule_in_source():
    source = Path(__file__).resolve().parents[1] / "research" / \
        "second_launch" / "walk_forward_v01" / "r9_intraday_accumulator_v01.py"
    text = source.read_text()
    for forbidden in ("B2_CONFIRMED", "BUY", "threshold search", "confidence"):
        assert forbidden not in text, f"forbidden token present: {forbidden}"


# ---- Regression: A. no post-10:30 leakage ----


def _bar_rows_pm(strong: bool) -> list[dict]:
    """09:35..10:30 identical; 10:35..15:00 either strong or weak."""
    rows = []
    for clock in GRID:
        am = clock <= "10:30"
        if am:
            high = 10.8 if clock == "10:00" else 10.2
            close = 10.5
            volume = 1000
            amount = 10500
        else:
            high = 12.5 if strong else 10.1
            close = 12.0 if strong else 10.0
            volume = 2000 if strong else 100
            amount = 24000 if strong else 1000
        rows.append({
            "symbol": "000001.SZ",
            "trade_date": "2026-08-11",
            "bar_time": clock,
            "open": "10.0",
            "high": str(high),
            "low": "9.8",
            "close": str(close),
            "volume": str(volume),
            "amount": str(amount),
        })
    return rows


def test_regression_a_no_post_1030_leakage():
    auth = _authority(stage="B1_READY")
    strong = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows_pm(strong=True),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    weak = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows_pm(strong=False),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert strong.status == weak.status == "APPEND"
    for field in (
        "activation_time", "post_activation_bar_n",
        "breakout_hold_ratio", "retest_depth",
        "false_break_duration", "vwap_acceptance_ratio",
        "reference_price_10_30", "feature_hash",
    ):
        assert strong.row[field] == weak.row[field], field


# ---- Regression: B. touch exactly 10:30 ----


def test_regression_b_touch_exactly_1030():
    auth = _authority(stage="B1_READY")
    rows = _bar_rows(touch_at="10:30")
    result = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=rows,
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert result.row is not None
    assert result.row["activation_time"] == "10:30"
    assert result.row["post_activation_bar_n"] == "0"
    assert result.row["intraday_primary_feature_status"] == "NO_POST_ACTIVATION_BAR"
    for field in ("breakout_hold_ratio", "retest_depth",
                  "false_break_duration", "vwap_acceptance_ratio"):
        assert result.row[field] is None or result.row[field] == ""


# ---- Regression: C. session VWAP through 10:30, not post-touch VWAP ----


def test_regression_c_session_vwap_not_post_touch_vwap():
    """Pre-touch and post-touch bars have very different amounts/volumes."""
    rows = []
    for clock in GRID:
        if clock == "10:00":
            high, close = 10.8, 10.6
        else:
            high, close = 10.2, 10.3
        if clock <= "10:00":
            volume, amount = 100, 1000      # pre-touch cheap bars
        else:
            volume, amount = 10000, 110000  # post-touch expensive bars
        rows.append({
            "symbol": "000001.SZ",
            "trade_date": "2026-08-11",
            "bar_time": clock,
            "open": "10.0",
            "high": str(high),
            "low": "9.8",
            "close": str(close),
            "volume": str(volume),
            "amount": str(amount),
        })
    auth = _authority(stage="B1_READY")
    result = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=rows,
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert result.status == "APPEND"
    # Session VWAP through 10:30 (all <=10:30 bars), never post-touch-only.
    import numpy as np
    primary = [r for r in rows if r["bar_time"] <= "10:30"]
    session_vwap = (
        sum(float(r["amount"]) for r in primary)
        / sum(float(r["volume"]) for r in primary)
    )
    post_window = [r for r in primary if r["bar_time"] > "10:00"]
    expected = sum(
        1 for r in post_window if float(r["close"]) >= session_vwap
    ) / len(post_window)
    assert abs(float(result.row["vwap_acceptance_ratio"]) - expected) < 1e-9


# ---- Regression: D. reconciliation inside the accumulator ----


def test_regression_d_reconciliation_inside_accumulator():
    auth = _authority(stage="B1_READY", minute_s1_price="10.50")
    # wrong minute symbol
    bad_rows = [
        {**row, "symbol": "000002.SZ"} for row in _bar_rows()
    ]
    with pytest.raises(protocol.ProtocolBlocked, match="BLOCKED_PRICE_RECONCILIATION"):
        accumulator.accumulate_intraday_observation(
            authority=auth,
            minute_rows=bad_rows,
            minute_manifest=_manifest(),
            right_label_verified=True,
            event_date=EVENT_DATE,
            existing_events={},
            existing_feature_hashes={},
            calendar=CALENDAR,
        )
    # wrong S1
    with pytest.raises(protocol.ProtocolBlocked, match="BLOCKED_PRICE_RECONCILIATION"):
        accumulator.accumulate_intraday_observation(
            authority=_authority(stage="B1_READY", minute_s1_price="10.51"),
            minute_rows=_bar_rows(),
            minute_manifest=_manifest(),
            right_label_verified=True,
            event_date=EVENT_DATE,
            existing_events={},
            existing_feature_hashes={},
            calendar=CALENDAR,
        )
    # bad tick
    bad_tick = _authority(stage="B1_READY", minute_s1_price="10.50")
    bad_tick = accumulator.IntradaySetupAuthority(
        setup_id=bad_tick.setup_id, symbol=bad_tick.symbol, t0_date=bad_tick.t0_date,
        candidate_date=bad_tick.candidate_date, ttl_end_date=bad_tick.ttl_end_date,
        first_observation_stage=bad_tick.first_observation_stage,
        intraday_primary_eligible=bad_tick.intraday_primary_eligible,
        intraday_ineligible_reason=bad_tick.intraday_ineligible_reason,
        event_search_start=bad_tick.event_search_start,
        event_search_end=bad_tick.event_search_end,
        s1_price=Decimal("10.505"), price_tick=Decimal("0.01"),
        minute_s1_price="10.505",
    )
    with pytest.raises(protocol.ProtocolBlocked, match="BLOCKED_PRICE_RECONCILIATION"):
        accumulator.accumulate_intraday_observation(
            authority=bad_tick,
            minute_rows=_bar_rows(),
            minute_manifest=_manifest(),
            right_label_verified=True,
            event_date=EVENT_DATE,
            existing_events={},
            existing_feature_hashes={},
            calendar=CALENDAR,
        )
    # wrong trade_date
    wrong_day = _bar_rows(trade_date="2026-08-12")
    with pytest.raises(protocol.ProtocolBlocked):
        accumulator.accumulate_intraday_observation(
            authority=auth,
            minute_rows=wrong_day,
            minute_manifest=_manifest(),
            right_label_verified=True,
            event_date=EVENT_DATE,
            existing_events={},
            existing_feature_hashes={},
            calendar=CALENDAR,
        )
    # exact reconciled PASS
    ok = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert ok.status == "APPEND"


# ---- Regression: E. ALREADY_RECORDED emits no row ----


def test_regression_e_already_recorded_emits_no_row():
    auth = _authority(stage="B1_READY")
    first = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(touch_at="10:00"),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={},
        calendar=CALENDAR,
    )
    assert first.status == "APPEND"
    assert first.row is not None
    second = accumulator.accumulate_intraday_observation(
        authority=auth,
        minute_rows=_bar_rows(touch_at="10:00"),
        minute_manifest=_manifest(),
        right_label_verified=True,
        event_date=EVENT_DATE,
        existing_events={},
        existing_feature_hashes={
            (auth.setup_id, first.event_id, "10:30"): first.feature_hash,
        },
        calendar=CALENDAR,
    )
    assert second.status == "ALREADY_RECORDED"
    assert second.row is None
