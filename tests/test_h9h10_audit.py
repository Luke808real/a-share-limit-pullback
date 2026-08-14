"""Targeted audit tests for the H9/H10 research-QC fixes.

Branch fix/factor-lab-h9-h10-audit-v01. Covers:
1. H10 >=80 vs <80 mutually-exclusive comparator with missing kept apart;
2. H10 minimal by_setup_stage strata (small cells -> None);
3. H9 fail-closed: data errors raise, only the factor's own None return
   counts as undefined.
"""
from __future__ import annotations

import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tests.synthetic_data import business_dates, make_bar

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(REPO / rel))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


h10 = _load("h10_audit_v01", "research/factor-lab/h10_quality_robustness_v01.py")
h9 = _load("h9_audit_v01", "research/factor-lab/h9_triple_volume_v01.py")


# --- H10 comparator --------------------------------------------------------


def test_h10_parse_score_missing_paths() -> None:
    assert h10.parse_score(None) is None
    assert h10.parse_score("") is None
    assert h10.parse_score("not-a-number") is None
    assert h10.parse_score("85.5") == 85.5
    assert h10.parse_score(90) == 90.0


def test_h10_score_strata_mutually_exclusive_and_missing_separate() -> None:
    rows = [
        ("WIN_S1", 90.0),
        ("LOSS_INVALID", 85.0),
        ("WIN_S1", 79.5),
        ("CANCEL_GAP_INVALID", 50.0),
        ("WIN_S1", None),
        ("LOSS_INVALID", None),
    ]
    out = h10.score_strata(rows, min_n=1)
    assert out["defined_n"] == 4
    assert out["missing_n"] == 2
    assert out["ge80_n"] == 2
    assert out["lt80_n"] == 2
    assert out["ge80_n"] + out["lt80_n"] == out["defined_n"]
    assert out["ge80_win"] == 0.5
    assert out["lt80_win"] == 0.5
    assert out["delta_ge80_vs_lt80"] == 0.0


def test_h10_score_strata_small_strata_null() -> None:
    rows = [("WIN_S1", 90.0), ("LOSS_INVALID", 85.0), ("WIN_S1", 60.0)]
    out = h10.score_strata(rows, min_n=20)
    assert out["defined_n"] == 3 and out["missing_n"] == 0
    assert out["ge80_win"] is None
    assert out["lt80_win"] is None
    assert out["delta_ge80_vs_lt80"] is None


def test_h10_stage_strata_structure_and_small_cells() -> None:
    rows = []
    for i in range(60):
        rows.append(
            (
                "B1_READY",
                "WIN_S1" if i % 2 == 0 else "LOSS_INVALID",
                90.0 if i % 3 == 0 else 60.0,
            )
        )
    for i in range(25):
        rows.append(("B2_READY", "LOSS_INVALID", 85.0))
    for i in range(3):
        rows.append(("B2_CONFIRMED", "WIN_S1", 80.0))
    out = h10.stage_strata(rows, min_n=20)
    assert set(out) == {"B1_READY", "B2_READY", "B2_CONFIRMED"}
    b1 = out["B1_READY"]
    assert b1["all_n"] == 60
    assert b1["setup_defined_n"] == 60
    assert b1["setup_ge80_n"] == 20
    assert b1["setup_lt80_n"] == 40
    assert b1["setup_ge80_win"] is not None
    assert b1["setup_lt80_win"] is not None
    assert b1["setup_delta"] is not None
    small = out["B2_CONFIRMED"]
    assert small["all_n"] == 3
    assert small["all_win"] is None
    assert small["setup_ge80_win"] is None
    assert small["setup_lt80_win"] is None
    assert small["setup_delta"] is None


# --- H9 fail-closed --------------------------------------------------------


def _bars(closes: list[str], volumes: list[str], days) -> list:
    bars = []
    preclose = Decimal("10.00")
    for day, close_s, vol_s in zip(days, closes, volumes, strict=True):
        close = Decimal(close_s)
        bars.append(
            make_bar(
                day,
                open_price=close_s,
                high=str(close + Decimal("0.10")),
                low=str(close - Decimal("0.10")),
                close=close_s,
                preclose=str(preclose),
                volume=vol_s,
            )
        )
        preclose = close
    return bars


def test_h9_compute_f19_empty_pullback_is_none() -> None:
    days = business_dates(date(2026, 1, 5), 4)
    bars = _bars(["10.00", "10.50", "9.80", "10.20"], ["100", "80", "60", "300"], days)
    # anchor = days[1], b2 = days[2]: pullback window empty -> factor None
    assert h9.compute_f19(bars, days[1], days[2]) is None


def test_h9_compute_f19_ratio() -> None:
    days = business_dates(date(2026, 1, 5), 5)
    bars = _bars(
        ["10.00", "10.50", "9.80", "9.60", "10.20"],
        ["100", "80", "60", "70", "300"],
        days,
    )
    assert h9.compute_f19(bars, days[1], days[4]) == Decimal("300") / Decimal("65")


def test_h9_compute_f19_missing_anchor_raises() -> None:
    days = business_dates(date(2026, 1, 5), 5)
    bars = _bars(["10.00", "10.50", "9.80", "9.60", "10.20"], ["100", "80", "60", "70", "300"], days)
    with pytest.raises(ValueError, match="anchor bar missing"):
        h9.compute_f19(bars, date(2030, 1, 2), days[4])


def test_h9_compute_f19_missing_b2_raises() -> None:
    days = business_dates(date(2026, 1, 5), 5)
    bars = _bars(["10.00", "10.50", "9.80", "9.60", "10.20"], ["100", "80", "60", "70", "300"], days)
    with pytest.raises(ValueError, match="b2 bar missing"):
        h9.compute_f19(bars, days[1], date(2030, 1, 1))


def test_h9_compute_f19_duplicate_dates_raise() -> None:
    days = business_dates(date(2026, 1, 5), 5)
    bars = _bars(["10.00", "10.50", "9.80", "9.60", "10.20"], ["100", "80", "60", "70", "300"], days)
    dup = make_bar(
        bars[-1].trade_date,
        open_price="10.20",
        high="10.30",
        low="10.10",
        close="10.20",
        preclose="10.20",
        volume="999",
    )
    with pytest.raises(ValueError, match="duplicate trade dates"):
        h9.compute_f19(bars + [dup], days[1], days[4])


def test_h9_compute_f19_multi_code_raises() -> None:
    days = business_dates(date(2026, 1, 5), 5)
    bars = _bars(["10.00", "10.50", "9.80", "9.60", "10.20"], ["100", "80", "60", "70", "300"], days)
    mixed = [bar.model_copy(update={"code": "000002"}) for bar in bars[2:]] + bars[:2]
    with pytest.raises(ValueError, match="exactly one code"):
        h9.compute_f19(mixed, days[1], days[4])
