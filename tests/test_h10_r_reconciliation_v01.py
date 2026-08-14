"""Targeted tests for H10 R-metric reconciliation v01."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(REPO / rel))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


h10r = _load(
    "h10_r_v01",
    "research/factor-lab/h10_r_reconciliation_v01.py",
)


def test_parse_r_missing_paths() -> None:
    assert h10r.parse_r(None) is None
    assert h10r.parse_r("") is None
    assert h10r.parse_r("oops") is None
    assert h10r.parse_r("-1") == -1.0
    assert h10r.parse_r("6.3035") == 6.3035


def test_r_summary_mean_median_quantiles() -> None:
    out = h10r.r_summary([1.0, 2.0, 3.0, 4.0, 5.0], min_n=1)
    assert out["n"] == 5
    assert out["mean_r"] == 3.0
    assert out["median_r"] == 3.0
    assert out["p25_r"] == 2.0
    assert out["p75_r"] == 4.0
    assert out["p_gt0"] == 1.0
    assert out["p_ge2"] == 0.8
    assert out["mean_pos_r"] == 3.0
    assert out["mean_neg_r"] is None


def test_r_strata_mutually_exclusive_and_identity() -> None:
    rows = [
        ("WIN_S1", 90.0, 2.0),
        ("LOSS_INVALID", 85.0, -1.0),
        ("WIN_S1", 79.5, 1.5),
        ("CANCEL_GAP_INVALID", 50.0, None),
        ("WIN_S1", None, None),
        ("LOSS_INVALID", None, -1.0),
    ]
    out = h10r.r_strata(rows, min_n=1)
    assert out["defined_n"] == 4
    assert out["score_missing_n"] == 2
    assert out["ge80"]["n"] == 2
    assert out["lt80"]["n"] == 2
    assert out["ge80"]["n"] + out["lt80"]["n"] == out["defined_n"]
    # per-stratum accounting identity: N == n_with_r + r_missing_n
    for name in ("ge80", "lt80"):
        cell = out[name]
        assert cell["n"] == cell["n_with_r"] + cell["r_missing_n"]
    assert out["ge80"]["win_share"] == 0.5
    assert out["ge80"]["strict_win_rate"] == 0.5
    assert out["ge80"]["n_with_r"] == 2
    assert out["lt80"]["n_with_r"] == 1
    assert out["lt80"]["r_missing_n"] == 1
    assert out["ge80"]["r"]["mean_r"] == 0.5


def test_tail_contribution_and_trimmed_mean() -> None:
    out = h10r.tail_check([1.0, 2.0, 3.0, 100.0])
    assert out["n"] == 4
    assert out["total_r"] == 106.0
    assert out["top1_n"] == 1
    assert out["top1_contribution"] == round(100.0 / 106.0, 4)
    assert out["trimmed_mean_top1pct"] == 2.0


def test_tail_contribution_non_positive_total_is_none() -> None:
    out = h10r.tail_check([-2.0, -1.0, 0.0])
    assert out["total_r"] == -3.0
    assert out["top1_contribution"] is None
    assert out["top5_contribution"] is None


def test_r_summary_small_n_null() -> None:
    out = h10r.r_summary([1.0, 2.0, 3.0], min_n=20)
    assert out["n"] == 3
    assert out.get("mean_r") is None
    assert out.get("median_r") is None


def test_keyed_strata_small_cell_null() -> None:
    rows = [
        ("1-2", "WIN_S1", 90.0, 2.0),
        ("1-2", "LOSS_INVALID", 85.0, -1.0),
        ("6-10", "LOSS_INVALID", 80.0, -1.0),
    ]
    out = h10r.keyed_strata(rows, min_n=20)
    small = out["6-10"]["ge80"]
    assert small["n"] == 1
    assert small["mean_r"] is None
    assert small["median_r"] is None
    assert small["win_share"] == 0.0
