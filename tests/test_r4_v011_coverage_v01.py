"""R4 V01.1 coverage extension: T0-type geometry, availability gates,
PIT boundary, provenance negative and baseline invariance tests."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r4_v01_1_coverage_v01 as r4v11  # noqa: E402
import r4_stability_v01 as r4v01  # noqa: E402


# ---- T0-type geometry (contract 2.4) ----


def test_t0_type_one_price():
    assert r4v11.t0_type_of(10.0, 10.0, 10.0, 10.0) == "ONE_PRICE"
    assert r4v11.t0_type_of(11.0, 11.0, 11.0, 11.0) == "ONE_PRICE"


def test_t0_type_t_shape():
    # open at limit (== high), dipped intraday, closed at limit
    assert r4v11.t0_type_of(11.0, 11.0, 10.5, 11.0) == "T_SHAPE"


def test_t0_type_normal_limit():
    assert r4v11.t0_type_of(10.5, 11.0, 10.2, 11.0) == "NORMAL_LIMIT"
    assert r4v11.t0_type_of(10.99, 11.0, 10.6, 11.0) == "NORMAL_LIMIT"


def test_t0_type_float_noise_tolerance():
    # 4-dp rounding absorbs float noise on canonical prices
    assert r4v11.t0_type_of(11.000000001, 11.0, 10.5, 11.0) == "T_SHAPE"
    assert r4v11.t0_type_of(10.500000001, 11.0, 10.2, 11.0) == "NORMAL_LIMIT"
    assert r4v11.t0_type_of(10.0, 10.000000001, 10.0, 10.0) == "ONE_PRICE"


def test_t0_type_classify_uses_only_anchor_bar():
    """PIT boundary: a LATER bar of the same code must not change the type."""
    episodes = pd.DataFrame({
        "episode_id": ["e1"],
        "code": ["600000"],
        "trade_date": [pd.Timestamp("2024-07-01").date()],
        "t0_ca": [False],
    })
    bars = pd.DataFrame({
        "code": ["600000", "600000"],
        "trade_date": [
            pd.Timestamp("2024-07-01").date(),
            pd.Timestamp("2024-07-02").date(),  # future bar (not T0)
        ],
        "open": [11.0, 11.5],
        "high": [11.0, 11.8],
        "low": [10.5, 11.2],
        "close": [11.0, 11.7],
    })
    out = r4v11.classify_episode_t0_types(episodes, bars)
    assert out.loc[0, "t0_type"] == "T_SHAPE"  # 2024-07-01 geometry only


def test_t0_type_ca_excluded_and_missing_bar():
    episodes = pd.DataFrame({
        "episode_id": ["e1", "e2", "e3"],
        "code": ["600000", "600001", "600002"],
        "trade_date": [pd.Timestamp("2024-07-01").date()] * 3,
        "t0_ca": [True, False, False],
    })
    bars = pd.DataFrame({
        "code": ["600001"],
        "trade_date": [pd.Timestamp("2024-07-01").date()],
        "open": [10.5], "high": [11.0], "low": [10.2], "close": [11.0],
    })
    out = r4v11.classify_episode_t0_types(episodes, bars)
    by_id = dict(zip(out["episode_id"], out["t0_type"]))
    assert by_id["e1"] == "CA_EXCLUDED"
    assert by_id["e2"] == "NORMAL_LIMIT"
    assert by_id["e3"] == "MISSING_T0_BAR"


# ---- board composition ----


def test_board_composition_only_main_boards_in_cohort():
    syms = pd.Series(["600000", "601318", "603259", "605117",
                      "000001", "001979", "002594", "003816",
                      "300750", "688981", "920819"])
    counts = r4v11.board_composition(syms)
    assert counts == {"SH_MAIN": 4, "SZ_MAIN": 4, "SZ_CHINEXT": 1,
                      "SH_STAR": 1, "BSE": 1}


# ---- LOW-position decomposition ----


def test_position_decomposition_counts():
    feat = pd.DataFrame({
        "t0_position_20d": [0.1, 0.2, 0.5, np.nan, np.nan],
        "t0_position_20d__missing_reason": [
            None, None, None, "CORPORATE_ACTION_UNKNOWN",
            "CORPORATE_ACTION_EVENT",
        ],
        "anchor_date": ["2024-07-01", "2024-07-02", "2024-07-03",
                        "2024-07-04", "2024-07-05"],
    })
    d = r4v11.position_decomposition(feat)
    assert d["total_n"] == 5
    assert d["nonmissing_n"] == 3
    assert d["missing_n"] == 2
    assert d["missing_CA_UNKNOWN"] == 1
    assert d["missing_CA_EVENT"] == 1
    assert d["low_n"] == 2
    assert d["low_share_of_nonmissing"] == round(2 / 3, 4)


def test_position_low_boundary_is_strict_less_than_one_third():
    feat = pd.DataFrame({
        "t0_position_20d": [1.0 / 3.0 - 1e-9, 1.0 / 3.0],
        "t0_position_20d__missing_reason": [None, None],
        "anchor_date": ["2024-07-01", "2024-07-02"],
    })
    d = r4v11.position_decomposition(feat)
    assert d["low_n"] == 1  # exact 1/3 is MID per frozen boundary


# ---- provenance / hash negative tests ----


def _write_snapshot(tmp_path, rows, snapshot_id):
    df = pd.DataFrame(rows)
    df["dataset_snapshot_id"] = snapshot_id
    p = tmp_path / "snap.parquet"
    df.to_parquet(p, index=False)
    return p, r4v01.sha256_file(p)


def test_gated_bars_hash_mismatch_fails(tmp_path):
    p, _ = _write_snapshot(tmp_path, {"trade_date": ["2024-01-02"],
                                      "open": [1.0]}, "snap-x")
    with pytest.raises(RuntimeError, match="SHA mismatch"):
        r4v11.load_canonical_bars_gated(
            p, ["open"], expected_sha="0" * 64, expected_id="snap-x"
        )


def test_gated_bars_binding_mismatch_fails(tmp_path):
    p, sha = _write_snapshot(tmp_path, {"trade_date": ["2024-01-02"],
                                        "open": [1.0]}, "snap-x")
    with pytest.raises(RuntimeError, match="binding mismatch"):
        r4v11.load_canonical_bars_gated(
            p, ["open"], expected_sha=sha, expected_id="snap-y"
        )


def test_gated_bars_pass(tmp_path):
    p, sha = _write_snapshot(tmp_path, {"trade_date": ["2024-01-02"],
                                        "open": [1.0]}, "snap-x")
    df = r4v11.load_canonical_bars_gated(
        p, ["open"], expected_sha=sha, expected_id="snap-x"
    )
    assert len(df) == 1


# ---- baseline invariance ----


def test_input_gate_pins_frozen_feature_outcome():
    feat, out = r3a.run_input_gate()
    assert len(feat) == 8682 and len(out) == 8682
    assert set(feat["episode_id"]) == set(out["episode_id"])


def test_frozen_files_sha_match_pins():
    from r3a_univariate_screen_v01 import FEATURE_CSV, OUTCOME_CSV

    assert r3a.sha256_file(FEATURE_CSV) == r3a.EXPECTED_FEATURE_SHA256
    assert r3a.sha256_file(OUTCOME_CSV) == r3a.EXPECTED_OUTCOME_SHA256
