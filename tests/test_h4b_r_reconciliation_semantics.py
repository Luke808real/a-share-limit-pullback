"""Targeted tests locking the H4B reconciliation R-sign vs outcome semantics.

These lock the three fixes Sol required in the final QC:
1. R sign fields in r_distribution() are named positive/negative/zero_r_count
   and NEVER win/loss (JSON authority must be self-explanatory).
2. WIN_S1 rows with negative R are still WIN_S1 (not LOSS_INVALID), and
   LOSS_INVALID rows with R == -1 vs R != -1 are counted separately by
   outcome (never inferred from the whole negative-R vector).
3. Identity counts hold for both outcome groups.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "research" / "factor-lab" / "h4b_r_distribution_reconciliation_v01.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("h4b_recon", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_r_distribution_fields_not_named_win_loss() -> None:
    mod = _load_script()
    out = mod.r_distribution([1.5, -1.0, -0.5, 0.0, 2.0])
    assert out["positive_r_count"] == 2
    assert out["negative_r_count"] == 2
    assert out["zero_r_count"] == 1
    assert "win_count" not in out
    assert "loss_count" not in out


def test_win_s1_negative_r_stays_win_s1() -> None:
    mod = _load_script()
    rows = [
        {"outcome": "WIN_S1", "r": -0.5},  # WIN_S1 with negative R
        {"outcome": "WIN_S1", "r": 2.0},
        {"outcome": "LOSS_INVALID", "r": -1.0},
    ]
    check = mod.win_s1_check(rows)
    assert check["win_s1_n"] == 2
    assert check["win_s1_r_positive_n"] == 1
    assert check["win_s1_r_negative_n"] == 1
    assert check["win_s1_r_zero_n"] == 0
    # identity: n = positive + negative + zero
    assert check["win_s1_n"] == (
        check["win_s1_r_positive_n"]
        + check["win_s1_r_negative_n"]
        + check["win_s1_r_zero_n"]
    )


def test_loss_invalid_minus1_and_non_minus1_counted_separately() -> None:
    mod = _load_script()
    rows = [
        {"outcome": "LOSS_INVALID", "r": -1.0},
        {"outcome": "LOSS_INVALID", "r": -1.0},
        {"outcome": "LOSS_INVALID", "r": -0.4},
        {"outcome": "WIN_S1", "r": -0.4},  # must NOT leak into loss counts
    ]
    check = mod.loss_invalid_check(rows)
    assert check["loss_invalid_n"] == 3
    assert check["loss_r_defined_n"] == 3
    assert check["loss_r_missing_n"] == 0
    assert check["loss_r_eq_minus1_n"] == 2
    assert check["loss_r_non_minus1_n"] == 1
    assert check["loss_r_zero_n"] == 0
    assert check["loss_r_positive_n"] == 0
    assert check["loss_r_negative_n"] == 3
    assert check["non_minus1_min"] == -0.4
    assert check["non_minus1_max"] == -0.4
    # identity: eq_minus1 + non_minus1 == defined
    assert check["loss_r_eq_minus1_n"] + check["loss_r_non_minus1_n"] == check["loss_r_defined_n"]


def test_loss_invalid_all_minus1_when_true() -> None:
    mod = _load_script()
    rows = [{"outcome": "LOSS_INVALID", "r": -1.0}, {"outcome": "LOSS_INVALID", "r": None}]
    check = mod.loss_invalid_check(rows)
    assert check["loss_r_defined_n"] == 1
    assert check["loss_r_missing_n"] == 1
    assert check["loss_r_eq_minus1_n"] == 1
    assert check["loss_r_non_minus1_n"] == 0
    assert "non_minus1_min" not in check
