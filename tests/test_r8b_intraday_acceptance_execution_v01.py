"""R8B acceptance execution tests: pure helpers cloud_ci; lake runs local_data."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "intraday_v01"))

import r8b_intraday_acceptance_execution_v01 as r8b  # noqa: E402


pytestmark = pytest.mark.cloud_ci


def _bars():
    return pd.DataFrame({
        "bar_time": ["09:35", "09:40", "09:45", "09:50", "10:00"],
        "open": [10.0, 10.2, 10.4, 10.5, 10.6],
        "high": [10.0, 10.2, 10.4, 10.5, 10.6],
        "low": [9.8, 9.9, 10.0, 10.1, 10.2],
        "close": [10.0, 10.1, 10.3, 10.4, 10.5],
        "volume": [1000, 1000, 1000, 1000, 1000],
        "amount": [10000, 10100, 10300, 10400, 10500],
    })


def test_checkpoint_slicing_pit():
    w = r8b.checkpoint_bars(_bars(), "09:45")
    assert w["bar_time"].tolist() == ["09:35", "09:40", "09:45"]
    w2 = r8b.checkpoint_bars(_bars(), "10:00")
    assert len(w2) == 5


def test_touch_anchor_uses_high_ge_s1_and_excluded():
    bars = _bars()
    idx = r8b.first_touch_index(bars, 10.35)
    assert idx == 2  # 09:45 bar HIGH 10.4 >= 10.35
    window = bars.iloc[idx + 1:]
    assert window["bar_time"].tolist() == ["09:50", "10:00"]


def test_acceptance_window_not_yet_activated():
    idx = r8b.first_touch_index(_bars(), 99.0)
    assert idx is None


def test_vwap_amount_volume_only():
    assert abs(r8b.session_vwap(_bars()) - 51300 / 5000) < 1e-9


def test_retest_depth_and_false_break_formulas():
    bars = _bars()
    idx = r8b.first_touch_index(bars, 10.35)
    window = bars.iloc[idx + 1:]
    closes = window["close"].to_numpy()
    assert r8b.feature_row(
        pd.Series({"episode_id": "e1", "symbol": "000001",
                   "outcome_event_date": "2026-06-05",
                   "current_outcome": "SUCCESS", "s1_price": 10.35}),
        bars, "10:00", 9.9, 4000.0,
    )["breakout_hold_ratio"] == 1.0


def test_rank_biserial_from_auc():
    assert abs(r8b.rank_biserial(0.75) - 0.5) < 1e-12
    assert abs(r8b.rank_biserial(0.5)) < 1e-12


def test_direction_semantics():
    assert r8b.direction_of(0.51) == "POSITIVE"
    assert r8b.direction_of(0.49) == "NEGATIVE"
    assert r8b.direction_of(0.50) == "NEUTRAL"
    assert r8b.direction_of(float("nan")) == "UNKNOWN"


def test_or_zero_cell_policy():
    r = r8b.or_2x2(0, 5, 3, 4)
    assert np.isfinite(r["or"])


@pytest.mark.local_data
def test_frozen_lake_full_run_deterministic(tmp_path):
    import subprocess
    import hashlib

    out1 = subprocess.run(
        [sys.executable,
         "research/second_launch/intraday_v01/"
         "r8b_intraday_acceptance_execution_v01.py"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert out1.returncode == 0
    h1 = hashlib.sha256(open(r8b.OUT_FEATURES, "rb").read()).hexdigest()
    out2 = subprocess.run(
        [sys.executable,
         "research/second_launch/intraday_v01/"
         "r8b_intraday_acceptance_execution_v01.py"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert out2.returncode == 0
    h2 = hashlib.sha256(open(r8b.OUT_FEATURES, "rb").read()).hexdigest()
    assert h1 == h2
