"""TTL T0 fixed-cohort transition result V01 — targeted tests.

Covers every prereg gate: 8 followups -> administratively immature,
9 followups -> fixed cohort, mature never-signal retained as no-event,
label != stage fail, duplicate stage fail, B2_READY without B1 fail,
B2_CONFIRMED without B2_READY fail, stage time reversal fail,
stored/recomputed event time mismatch fail, event time > 9 fail,
fixed denominator identical k=1..9, monotonicity, exact-event cumulative
identity, T9 + no-event conservation.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "factor-lab"))

import ttl_t0_transition_v01 as m  # noqa: E402


def _reg_row(setup_id: str, code: str = "000001", anchor: str = "2026-01-01") -> dict:
    return {"setup_id": setup_id, "code": code, "anchor_date": anchor}


def _ep_row(setup_id: str, label: str, signal: str, anchor: str = "2026-01-01",
            days: int = 1, stage: str | None = None) -> dict:
    return {
        "setup_id": setup_id,
        "execution_label": label,
        "setup_stage": stage if stage is not None else label,
        "signal_date": signal,
        "anchor_date": anchor,
        "days_since_anchor": days,
        "code": "000001",
    }


def _daily_sessions(dates: list[str]) -> dict[str, tuple]:
    """Minimal CONFIRMED session authority for one code (Bar-like objects
    with .trade_date, matching _iter_confirmed_code_bars output)."""
    from datetime import date as _d
    class Bar:
        def __init__(self, d: str):
            self.trade_date = _d.fromisoformat(d)
    return {"000001": tuple(Bar(d) for d in dates)}


def _session_dates(daily: dict[str, tuple]) -> dict[str, tuple]:
    """Convert Bar-like daily into date tuples (what build_followup_authority
    produces and recompute_event_times consumes)."""
    return {code: tuple(b.trade_date for b in bars) for code, bars in daily.items()}


# ---------- maturity ----------

def test_eight_followups_immature() -> None:
    reg = pd.DataFrame([_reg_row("S1", anchor="2026-07-10")])
    # sessions 07-13..07-22 = 8 after 07-10
    daily = _daily_sessions(["2026-07-01", "2026-07-13", "2026-07-14", "2026-07-15",
                             "2026-07-16", "2026-07-17", "2026-07-20", "2026-07-21", "2026-07-22"])
    out, _ = m.build_followup_authority(reg, daily)
    assert out["FOLLOWUP_SESSIONS_AVAILABLE"].iloc[0] == 8
    assert (out["FOLLOWUP_SESSIONS_AVAILABLE"] >= 9).sum() == 0


def test_nine_followups_fixed_cohort() -> None:
    reg = pd.DataFrame([_reg_row("S1", anchor="2026-07-10")])
    daily = _daily_sessions(["2026-07-01", "2026-07-13", "2026-07-14", "2026-07-15",
                             "2026-07-16", "2026-07-17", "2026-07-20", "2026-07-21",
                             "2026-07-22", "2026-07-23"])
    out, _ = m.build_followup_authority(reg, daily)
    assert out["FOLLOWUP_SESSIONS_AVAILABLE"].iloc[0] == 9
    assert (out["FOLLOWUP_SESSIONS_AVAILABLE"] >= 9).sum() == 1


# ---------- event input gates ----------

def test_label_stage_mismatch_fails() -> None:
    ep = pd.DataFrame([_ep_row("S1", "B1_READY", "2026-01-05", stage="B2_READY")])
    reg = pd.DataFrame([_reg_row("S1")])
    with pytest.raises(RuntimeError, match="LABEL_STAGE_MISMATCH_N"):
        m.load_primary_events(ep, reg)


def test_duplicate_stage_fails() -> None:
    ep = pd.DataFrame([
        _ep_row("S1", "B1_READY", "2026-01-05"),
        _ep_row("S1", "B1_READY", "2026-01-06"),
    ])
    reg = pd.DataFrame([_reg_row("S1")])
    with pytest.raises(RuntimeError, match="DUPLICATE_VIOLATION_N"):
        m.load_primary_events(ep, reg)


def test_setup_not_in_registry_fails() -> None:
    ep = pd.DataFrame([_ep_row("S9", "B1_READY", "2026-01-05")])
    reg = pd.DataFrame([_reg_row("S1")])
    with pytest.raises(RuntimeError, match="not in registry"):
        m.load_primary_events(ep, reg)


def test_b2_ready_without_b1_fails() -> None:
    ep = pd.DataFrame([_ep_row("S1", "B2_READY", "2026-01-06")])
    reg = pd.DataFrame([_reg_row("S1")])
    with pytest.raises(RuntimeError, match="STAGE_PREREQUISITE_VIOLATION_N"):
        m.load_primary_events(ep, reg)


def test_b2_confirmed_without_b2_ready_fails() -> None:
    ep = pd.DataFrame([
        _ep_row("S1", "B1_READY", "2026-01-05"),
        _ep_row("S1", "B2_CONFIRMED", "2026-01-07"),
    ])
    reg = pd.DataFrame([_reg_row("S1")])
    with pytest.raises(RuntimeError, match="STAGE_PREREQUISITE_VIOLATION_N"):
        m.load_primary_events(ep, reg)


def test_stage_time_reversal_fails() -> None:
    ep = pd.DataFrame([
        _ep_row("S1", "B1_READY", "2026-01-07", days=4),
        _ep_row("S1", "B2_READY", "2026-01-05", days=2),
    ])
    reg = pd.DataFrame([_reg_row("S1")])
    with pytest.raises(RuntimeError, match="STAGE_ORDER_VIOLATION_N"):
        m.load_primary_events(ep, reg)


# ---------- event time reconciliation ----------

def test_event_time_mismatch_fails() -> None:
    ep = pd.DataFrame([_ep_row("S1", "B1_READY", "2026-01-05", days=3)])  # stored 3, recomputed 2
    reg = pd.DataFrame([_reg_row("S1")])
    primary = m.load_primary_events(ep, reg)
    daily = _daily_sessions(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"])
    with pytest.raises(RuntimeError, match="EVENT_TIME_MISMATCH_N"):
        m.recompute_event_times(primary, _session_dates(daily))


def test_event_time_gt_9_fails() -> None:
    ep = pd.DataFrame([_ep_row("S1", "B1_READY", "2026-01-16", days=10)])
    reg = pd.DataFrame([_reg_row("S1")])
    primary = m.load_primary_events(ep, reg)
    daily = _daily_sessions(["2026-01-01", "2026-01-05", "2026-01-06", "2026-01-07",
                             "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13",
                             "2026-01-14", "2026-01-15", "2026-01-16"])
    with pytest.raises(RuntimeError, match="event time out of"):
        m.recompute_event_times(primary, _session_dates(daily))


def test_event_time_match_ok() -> None:
    ep = pd.DataFrame([
        _ep_row("S1", "B1_READY", "2026-01-05", days=2),
        _ep_row("S1", "B2_READY", "2026-01-07", days=4),
    ])
    reg = pd.DataFrame([_reg_row("S1")])
    primary = m.load_primary_events(ep, reg)
    daily = _daily_sessions(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    out = m.recompute_event_times(primary, _session_dates(daily))
    assert (out["RECOMPUTED_EVENT_TIME"] == out["days_since_anchor"]).all()
    assert out["_MAX_ABS_DIFF"].max() == 0


# ---------- primary result / QA ----------

def _result_harness(matured: list[dict], events: list[dict]) -> dict:
    reg = pd.DataFrame(matured)
    reg["FOLLOWUP_SESSIONS_AVAILABLE"] = [r.get("followup", 9) for r in matured]
    reg["FULL_WINDOW_MATURED"] = reg["FOLLOWUP_SESSIONS_AVAILABLE"] >= 9
    ep = pd.DataFrame(events)
    return m.compute_result(reg, ep)


def test_fixed_denominator_and_monotonicity() -> None:
    matured = [{"setup_id": f"S{i}", "code": "000001", "anchor_date": "2026-01-01"} for i in range(3)]
    events = [
        _ep_row("S0", "B1_READY", "2026-01-03", days=2),
        _ep_row("S0", "B2_READY", "2026-01-05", days=4),
        _ep_row("S1", "B1_READY", "2026-01-02", days=1),
        _ep_row("S1", "B2_READY", "2026-01-04", days=3),
        _ep_row("S2", "B1_READY", "2026-01-05", days=4),
    ]
    for e in events:
        e["RECOMPUTED_EVENT_TIME"] = e["days_since_anchor"]
    r = _result_harness(matured, events)
    assert r["FIXED_MATURED_N"] == 3
    b1 = r["STAGES"]["B1_READY"]
    assert b1["BY_K_N"][1] == 1 and b1["BY_K_N"][2] == 2 and b1["BY_K_N"][3] == 2 and b1["BY_K_N"][4] == 3
    # monotonic non-decreasing
    assert all(b1["BY_K_N"][k] <= b1["BY_K_N"][k + 1] for k in range(1, 9))
    assert b1["NO_EVENT_BY_T9_N"] == 0
    assert b1["BY_T9_N"] + b1["NO_EVENT_BY_T9_N"] == 3


def test_mature_never_signal_retained_as_no_event() -> None:
    matured = [
        {"setup_id": "S0", "code": "000001", "anchor_date": "2026-01-01"},  # has B1
        {"setup_id": "S1", "code": "000002", "anchor_date": "2026-01-01"},  # never signals
    ]
    events = [_ep_row("S0", "B1_READY", "2026-01-02", days=1)]
    events[0]["RECOMPUTED_EVENT_TIME"] = 1
    r = _result_harness(matured, events)
    assert r["FIXED_MATURED_N"] == 2
    b1 = r["STAGES"]["B1_READY"]
    assert b1["BY_T9_N"] == 1
    assert b1["NO_EVENT_BY_T9_N"] == 1  # S1 retained as no-event, not dropped


def test_exact_event_cumulative_identity() -> None:
    matured = [{"setup_id": f"S{i}", "code": "000001", "anchor_date": "2026-01-01"} for i in range(4)]
    events = [
        _ep_row("S0", "B1_READY", "2026-01-02", days=1),
        _ep_row("S1", "B1_READY", "2026-01-02", days=1),
        _ep_row("S2", "B1_READY", "2026-01-03", days=2),
        _ep_row("S3", "B1_READY", "2026-01-05", days=4),
        _ep_row("S3", "B2_READY", "2026-01-07", days=6),
    ]
    for e in events:
        e["RECOMPUTED_EVENT_TIME"] = e["days_since_anchor"]
    r = _result_harness(matured, events)
    b1 = r["STAGES"]["B1_READY"]
    # exact events: T1=2, T2=1, T3=0, T4=1 -> cumulative: k1=2, k2=3, k3=3, k4=4
    assert b1["EXACT_EVENT_N"][1] == 2
    assert b1["EXACT_EVENT_N"][2] == 1
    assert b1["EXACT_EVENT_N"][4] == 1
    assert b1["BY_K_N"][1] == 2 and b1["BY_K_N"][2] == 3 and b1["BY_K_N"][3] == 3 and b1["BY_K_N"][4] == 4
    # cumulative identity BY_K_N == sum(exact <= k)
    assert all(
        b1["BY_K_N"][k] == sum(b1["EXACT_EVENT_N"][kk] for kk in range(1, k + 1))
        for k in range(1, 10)
    )
    assert b1["BY_T9_N"] + b1["NO_EVENT_BY_T9_N"] == 4


def test_t9_no_event_conservation_fails() -> None:
    matured = [
        {"setup_id": "S0", "code": "000001", "anchor_date": "2026-01-01"},
        {"setup_id": "S1", "code": "000001", "anchor_date": "2026-01-01"},
        {"setup_id": "S2", "code": "000001", "anchor_date": "2026-01-01"},
    ]
    events = [
        _ep_row("S0", "B1_READY", "2026-01-02", days=1),
        _ep_row("S1", "B1_READY", "2026-01-03", days=2),
    ]
    for e in events:
        e["RECOMPUTED_EVENT_TIME"] = e["days_since_anchor"]
    r = _result_harness(matured, events)
    b1 = r["STAGES"]["B1_READY"]
    assert b1["BY_T9_N"] == 2
    assert b1["NO_EVENT_BY_T9_N"] == 1
    assert b1["BY_T9_N"] + b1["NO_EVENT_BY_T9_N"] == 3  # conservation holds
