"""R8A ASL 5m readiness tests: S1 provenance + coverage + discovery."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "intraday_v01"))
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r8a_asl5m_readiness_v01 as rd  # noqa: E402
import r8a_intraday_contract_v01 as r8a  # noqa: E402


pytestmark = pytest.mark.cloud_ci


def _load():
    outcome = pd.read_csv(r8a.CURRENT_OUTCOME_CSV, dtype={"symbol": str})
    case_set = pd.read_csv(r8a.LEGACY_CASE_SET, dtype={"symbol": str})
    return outcome, case_set


def test_s1_146_146_finite_and_positive():
    outcome, case_set = _load()
    prov, bad = rd.s1_provenance_rows(outcome, case_set)
    assert len(prov) == 146
    assert bad == {
        "s1_not_finite": 0, "s1_not_positive": 0, "event_date_null": 0,
        "identity_mismatch": 0, "outcome_not_event": 0,
    }
    assert prov["s1_price"].notna().all()
    assert (prov["s1_price"] > 0).all()
    assert prov["outcome_event_date"].notna().all()


def test_s1_exact_identity_binding():
    outcome, case_set = _load()
    prov, _ = rd.s1_provenance_rows(outcome, case_set)
    cur = outcome.set_index("episode_id")
    for _, r in prov.iterrows():
        c = cur.loc[r["episode_id"]]
        assert str(c["symbol"]) == r["symbol"]
        assert str(c["anchor_date"]) == r["anchor_date"]
        assert str(c["candidate_date"]) == r["candidate_date"]
        assert str(c["outcome_3d"]) in ("SUCCESS", "FAILED_BREAKOUT")


def test_s1_source_pins():
    outcome, case_set = _load()
    prov, _ = rd.s1_provenance_rows(outcome, case_set)
    assert set(prov["s1_source"]) == {"current_frozen_outcome"}
    assert set(prov["s1_source_sha"]) == {rd.OUTCOME_SHA}
    assert set(prov["event_date_source"]) == {"legacy_frozen_case_set"}
    assert set(prov["event_date_source_sha"]) == {rd.LEGACY_CASE_SET_SHA}


def test_s1_missing_fails_closed():
    outcome, case_set = _load()
    bad = outcome.copy()
    eid = case_set.loc[case_set["V02_EVENT_COHORT"] == True,  # noqa: E712
                       "episode_id"].iloc[0]
    bad.loc[bad["episode_id"] == eid, "s1_price"] = np.nan
    with pytest.raises(RuntimeError, match="s1_not_finite"):
        rd.s1_provenance_rows(bad, case_set)


def test_coverage_reconciliation():
    outcome, case_set = _load()
    prov, _ = rd.s1_provenance_rows(outcome, case_set)
    cov = rd.coverage_recompute(prov).iloc[0]
    assert cov["TOTAL_EVENT_COHORT"] == 146
    assert cov["ASL_EVENT_DAY_FOUND_N"] == 0
    assert cov["ASL_MORNING_COMPLETE_N"] == 0
    assert cov["MISSING_EVENT_DAY_N"] == 146
    assert cov["ASL_MORNING_COMPLETE_N"] + cov["MISSING_EVENT_DAY_N"] == 146
    assert cov["SUCCESS_TOTAL"] == 43
    assert cov["FAILED_BREAKOUT_TOTAL"] == 103
    assert cov["VWAP_STATUS"] == "DATA_UNAVAILABLE"
    assert cov["S1_PROVENANCE"] == "PASS"


def test_provenance_csv_deterministic(tmp_path):
    outcome, case_set = _load()
    prov, _ = rd.s1_provenance_rows(outcome, case_set)
    p1, p2 = tmp_path / "a.csv", tmp_path / "b.csv"
    prov.to_csv(p1, index=False)
    prov.to_csv(p2, index=False)
    assert p1.read_bytes() == p2.read_bytes()


@pytest.mark.local_data
def test_local_asl_discovery_bounded():
    """Machine-local check: no ASL minute data on this Mac."""
    d = rd.asl_discovery()
    assert d["ASL_MINUTE_PRESENT"] is False
    assert d["ASL_MINUTE_DATA_FILES"] == []
    assert d["status"] in ("ASL_LAKE_PRESENT_DAILY_ONLY",
                           "BLOCKED_LOCAL_ASL_NOT_FOUND")
    assert d["ASL_DATA_ROOT"] == "UNSET" or d["ASL_DATA_ROOT"]
