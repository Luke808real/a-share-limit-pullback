"""R8A intraday acceptance contract & data readiness tests.

All inputs are committed artifacts (case set / outcome / manifest) -> cloud_ci.
"""

from __future__ import annotations

import inspect
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "intraday_v01"))

import r8a_intraday_contract_v01 as r8a  # noqa: E402


pytestmark = pytest.mark.cloud_ci


def _bars():
    return pd.DataFrame({
        "bar_end": ["09:35", "09:40", "09:45", "09:50", "10:00"],
        "high": [10.0, 10.2, 10.4, 10.5, 10.6],
        "low": [9.8, 9.9, 10.0, 10.1, 10.2],
        "close": [10.0, 10.1, 10.3, 10.4, 10.5],
    })


# ---- right-label checkpoint slicing (PIT) ----


def test_checkpoint_0945_no_future_bars():
    w = r8a.completed_bars_through(_bars(), "09:45")
    assert w["bar_end"].tolist() == ["09:35", "09:40", "09:45"]


def test_checkpoint_1000_no_future_bars():
    w = r8a.completed_bars_through(_bars(), "10:00")
    assert w["bar_end"].tolist() == ["09:35", "09:40", "09:45", "09:50",
                                     "10:00"]


# ---- activation anchor ----


def test_activation_touch_uses_high_ge_s1():
    anchor = r8a.first_s1_touch_bar(_bars(), s1=10.35)
    assert anchor is not None
    assert anchor["bar_end"] == "09:45"  # first bar with HIGH >= 10.35


def test_activation_touch_anchor_excluded_from_acceptance():
    bars = _bars()
    anchor = r8a.first_s1_touch_bar(bars, s1=10.35)
    idx = bars.index[bars["bar_end"] == anchor["bar_end"]][0]
    window = r8a.acceptance_window_bars(bars, idx)
    assert window["bar_end"].tolist() == ["09:50", "10:00"]


def test_not_yet_activated_not_acceptance_zero():
    # no HIGH >= S1 -> NOT_YET_ACTIVATED, not acceptance=0
    assert r8a.activation_state(_bars(), s1=99.0, checkpoint="11:30") == (
        "NOT_YET_ACTIVATED")
    assert r8a.activation_state(_bars(), s1=10.35, checkpoint="09:45") == (
        "ACTIVATED")


# ---- F7 formulas ----


def test_breakout_hold_ratio_formula():
    window = pd.DataFrame({"close": [10.4, 10.2, 10.6]})
    assert abs(r8a.breakout_hold_ratio(window, 10.35) - 2 / 3) < 1e-12
    assert np.isnan(r8a.breakout_hold_ratio(pd.DataFrame(
        {"close": []}), 10.35))


def test_vwap_amount_volume_semantics():
    assert abs(r8a.vwap_of(np.array([1000.0, 2000.0]),
                           np.array([100.0, 100.0])) - 15.0) < 1e-12
    # no close-weighted proxy anywhere in the module
    src = inspect.getsource(r8a)
    assert "close-weighted" not in src.lower() or "NO close-weighted proxy" in src


def test_vwap_acceptance_ratio():
    window = pd.DataFrame({"close": [15.0, 14.0, 16.0]})
    assert abs(r8a.vwap_acceptance_ratio(window, 15.0) - 2 / 3) < 1e-12


def test_retest_depth_formula():
    window = pd.DataFrame({"low": [10.3, 10.2, 10.1]})
    assert abs(r8a.retest_depth(window, 10.35) - (10.1 / 10.35 - 1)) < 1e-12


def test_false_break_duration_formula():
    window = pd.DataFrame({"close": [10.4, 10.2, 10.1, 10.5, 10.2]})
    assert r8a.false_break_duration(window, 10.35) == 2


# ---- V01B golden direction semantics ----


def test_v01b_reclaim_rebreak_direction():
    assert r8a.vwap_reclaim_rebreak(14.9, 15.1, 15.0) == "RECLAIM"
    assert r8a.vwap_reclaim_rebreak(15.1, 14.9, 15.0) == "REBREAK"
    assert r8a.vwap_reclaim_rebreak(14.9, 14.8, 15.0) == "NO_CROSS"


# ---- EOD leakage / composite / threshold bans ----


def test_no_eod_leakage_in_registry():
    rows = pd.DataFrame(r8a.FEATURE_ROWS)
    banned = ["eod", "afternoon_return", "full_day", "close_location"]
    for f in banned:
        assert f not in " ".join(rows["formula"].astype(str)).lower()
    src = inspect.getsource(r8a)
    assert "afternoon_return" not in src.lower()


def test_no_threshold_scan_no_composite():
    rows = pd.DataFrame(r8a.FEATURE_ROWS)
    joined = " ".join(rows["known_limitation"].astype(str) + rows["formula"])
    assert "composite" not in joined.lower()
    src = inspect.getsource(r8a)
    assert "threshold scan" not in src.lower()
    assert "grid" not in src.lower()


def test_all_four_checkpoints_frozen():
    assert r8a.CHECKPOINTS == ["09:45", "10:00", "10:30", "11:30"]
    rows = pd.DataFrame(r8a.FEATURE_ROWS)
    for cp in r8a.CHECKPOINTS:
        assert rows["checkpoint"].astype(str).str.contains(cp).any()


def test_granularity_and_source_frozen():
    assert r8a.R8_GRANULARITY == "5m"
    assert r8a.R8_DATA_STATUS == "BLOCKED_BY_MINUTE_COVERAGE"
    assert "ASL_5M" in r8a.MINUTE_SOURCE


# ---- legacy -> current cohort rebase ----


def test_legacy_to_current_exact_mapping():
    outcome = pd.read_csv(r8a.CURRENT_OUTCOME_CSV, dtype={"symbol": str})
    case_set = pd.read_csv(r8a.LEGACY_CASE_SET, dtype={"symbol": str})
    manifest, stats = r8a.legacy_rebase(outcome, case_set)
    assert stats == {
        "LEGACY_EVENT_N": 146, "MAPPED_TO_8682_N": 146,
        "NOT_IN_CURRENT_COHORT_N": 0, "LABEL_DRIFT_N": 0,
        "IDENTITY_MISMATCH_N": 0,
    }
    assert len(manifest) == 8682
    mapped = manifest[manifest["legacy_event_mapping_status"] == "MAPPED"]
    assert len(mapped) == 146
    assert mapped["outcome_event_date"].notna().all()


def test_label_drift_fails_closed():
    outcome = pd.read_csv(r8a.CURRENT_OUTCOME_CSV, dtype={"symbol": str})
    case_set = pd.read_csv(r8a.LEGACY_CASE_SET, dtype={"symbol": str})
    bad = case_set.copy()
    eid = bad.loc[bad["V02_EVENT_COHORT"] == True, "episode_id"].iloc[0]  # noqa: E712
    bad.loc[bad["episode_id"] == eid, "outcome"] = "NO_LAUNCH"
    with pytest.raises(RuntimeError, match="drift"):
        r8a.legacy_rebase(outcome, bad)


def test_identity_mismatch_fails_closed():
    outcome = pd.read_csv(r8a.CURRENT_OUTCOME_CSV, dtype={"symbol": str})
    case_set = pd.read_csv(r8a.LEGACY_CASE_SET, dtype={"symbol": str})
    bad = case_set.copy()
    eid = bad.loc[bad["V02_EVENT_COHORT"] == True, "episode_id"].iloc[0]  # noqa: E712
    bad.loc[bad["episode_id"] == eid, "symbol"] = "999999"
    with pytest.raises(RuntimeError, match="identity"):
        r8a.legacy_rebase(outcome, bad)


def test_minute_coverage_rows():
    legacy_manifest = pd.read_csv(r8a.LEGACY_MINUTE_MANIFEST,
                                  dtype={"symbol": str})
    rows = r8a.minute_coverage_rows(legacy_manifest)
    asl = [r for r in rows if r["source"] == "ASL_5M"][0]
    assert asl["status"] == "BLOCKED_BY_MINUTE_COVERAGE"
    assert asl["complete_n"] == 0
    legacy5 = [r for r in rows if r["source"] == "LEGACY_5M_PARITY_REFERENCE"][0]
    assert legacy5["complete_n"] == 139
    assert legacy5["success_complete_n"] == 40
    assert legacy5["failed_breakout_complete_n"] == 99


def test_registry_and_artifacts_deterministic(tmp_path):
    rows = pd.DataFrame(r8a.FEATURE_ROWS)
    assert len(rows) == 11
    primary = rows[rows["role"] == "PRIMARY"]
    assert primary["feature_id"].tolist() == ["F7-1", "F7-2", "F7-3", "F7-4"]
    deferred = rows[rows["status"] == "DEFERRED"]
    assert deferred["feature_id"].tolist() == ["D1"]
    p1, p2 = tmp_path / "a.csv", tmp_path / "b.csv"
    rows.to_csv(p1, index=False)
    rows.to_csv(p2, index=False)
    assert p1.read_bytes() == p2.read_bytes()
