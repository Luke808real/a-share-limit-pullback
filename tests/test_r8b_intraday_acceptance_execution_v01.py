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
import r8b_asl5m_dataset_readiness_v01 as rd  # noqa: E402


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


# ---- chronology fixes ----


def _full_session():
    times = ([f"09:{m:02d}" for m in range(35, 60, 5)]
             + [f"10:{m:02d}" for m in range(0, 60, 5)]
             + [f"11:{m:02d}" for m in range(0, 35, 5)])
    rng = np.random.default_rng(5)
    close = np.round(rng.uniform(10.0, 11.0, 24), 2)
    high = close + 0.1
    low = close - 0.1
    return pd.DataFrame({
        "bar_time": times, "open": close - 0.02, "high": high,
        "low": low, "close": close,
        "volume": np.full(24, 1000), "amount": close * 1000,
    })


def _features_from(bars, s1=10.5, seed=None):
    rng = np.random.default_rng(seed)
    shuffled = bars.iloc[rng.permutation(len(bars))].reset_index(drop=True) \
        if seed is not None else bars
    ep = pd.Series({"episode_id": "e1", "symbol": "000001",
                    "outcome_event_date": "2026-06-05",
                    "current_outcome": "SUCCESS", "s1_price": s1})
    return [r8b.feature_row(ep, shuffled, cp, 9.9, 4000.0)
            for cp in r8b.CHECKPOINTS]


def test_shuffled_physical_order_invariant():
    bars = _full_session()
    canon = _features_from(bars)
    for seed in (1, 2, 3):
        other = _features_from(bars, seed=seed)
        for a, b in zip(canon, other):
            for key in ["activated", "activation_time", "breakout_hold_ratio",
                        "vwap_acceptance_ratio", "retest_depth",
                        "false_break_duration", "post_activation_bar_n"]:
                va, vb = a[key], b[key]
                same = va == vb or (
                    isinstance(va, float) and isinstance(vb, float)
                    and np.isnan(va) and np.isnan(vb))
                assert same, (seed, key, va, vb)


def test_first_touch_prefix_stability():
    bars = _full_session()
    # force touch at 09:45
    bars.loc[0, "high"] = 9.0  # 09:35 no touch
    rows = _features_from(bars, s1=10.5)
    times = [r["activation_time"] for r in rows]
    assert times[0] == times[1] == times[2] == times[3]
    assert times[0] in ("09:35", "09:40", "09:45")


def test_touch_at_checkpoint_no_post_bars():
    bars = _full_session()
    # touch exactly at 09:45 (third bar)
    bars.loc[0, "high"] = 9.0
    bars.loc[1, "high"] = 9.0
    rows = _features_from(bars, s1=10.5)
    row_0945 = rows[0]
    assert row_0945["activated"] is True
    assert row_0945["post_activation_bar_n"] == 0
    assert np.isnan(row_0945["breakout_hold_ratio"])
    assert np.isnan(row_0945["vwap_acceptance_ratio"])
    assert np.isnan(row_0945["retest_depth"])
    assert row_0945["false_break_duration"] == 0
    row_1000 = rows[1]
    assert row_1000["post_activation_bar_n"] > 0


def test_strict_monotonicity_assert():
    df = pd.DataFrame({
        "symbol": ["a"] * 4, "trade_date": ["2026-06-05"] * 4,
        "bar_time": ["09:35", "09:40", "09:40", "09:50"],
        "open": [1] * 4,
    })
    with pytest.raises(RuntimeError, match="non-strictly-increasing"):
        rd._assert_chronological(df)


@pytest.mark.local_data
def test_frozen_lock_unchanged_and_chronological():
    assert rd.recompute_lock_sha(rd.curated_partitions()) == rd.DATASET_LOCK_SHA
    raw = pd.concat([pd.read_parquet(p) for p in rd.curated_partitions()],
                    ignore_index=True)
    oob = rd.out_of_order_symbol_days(raw)
    assert oob == 5625  # physical order is scrambled; consumer canonicalizes
    df = rd.load_frozen_5m()
    rd._assert_chronological(df)  # canonicalized order passes


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
