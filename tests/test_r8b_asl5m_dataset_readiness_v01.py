"""R8B frozen ASL 5m dataset verification tests.

Lake-dependent tests -> local_data; pure helpers -> cloud_ci.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "intraday_v01"))

import r8b_asl5m_dataset_readiness_v01 as rd  # noqa: E402


pytestmark = pytest.mark.cloud_ci


def test_morning_grid_is_24_bars():
    assert len(rd.MORNING_GRID) == 24
    assert rd.MORNING_GRID[0].strftime("%H:%M") == "09:35"
    assert rd.MORNING_GRID[-1].strftime("%H:%M") == "11:30"
    assert sorted(rd.MORNING_GRID) == rd.MORNING_GRID
    # strictly 5-min grid, no 11:35+
    assert "11:35" not in [t.strftime("%H:%M") for t in rd.MORNING_GRID]


def test_lock_metadata_pins():
    rows = pd.read_csv(rd.OUT_LOCK)
    meta = rows.iloc[0]
    assert meta["ASL_CANDIDATE_SHA"] == rd.ASL_CANDIDATE_SHA
    assert meta["source"] == "tdx_protocol"
    assert meta["frequency"] == "5m"
    assert meta["schema_version"] == "v1"
    assert meta["volume_unit"] == "shares"
    assert meta["amount_unit"] == "RMB"
    assert meta["raw_bars_committed"] is False


def test_lock_has_40_partitions():
    rows = pd.read_csv(rd.OUT_LOCK)
    partitions = rows[rows["partition"].notna() & (rows["partition"] != "")]
    assert len(partitions) == 40
    assert partitions["rows"].sum() == 270000


@pytest.mark.local_data
def test_frozen_lake_lock_sha_matches():
    parts = rd.curated_partitions()
    assert rd.recompute_lock_sha(parts) == rd.DATASET_LOCK_SHA


@pytest.mark.local_data
def test_frozen_lake_row_count_and_no_duplicates():
    df = rd.load_frozen_5m()
    assert len(df) == 270000
    assert df.duplicated(subset=["symbol", "trade_date", "bar_time"]).sum() == 0


@pytest.mark.local_data
def test_frozen_coverage_gate():
    cov = rd.coverage_from_frozen().iloc[0]
    assert cov["ASL_EVENT_DAY_FOUND_N"] == 146
    assert cov["ASL_MORNING_COMPLETE_N"] == 146
    assert cov["SUCCESS_MORNING_COMPLETE_N"] == 43
    assert cov["FAILED_BREAKOUT_MORNING_COMPLETE_N"] == 103
    assert cov["VWAP_STATUS"] == "READY"
    assert cov["BAR_SEMANTICS"] == "RIGHT_LABELED_VERIFIED"
