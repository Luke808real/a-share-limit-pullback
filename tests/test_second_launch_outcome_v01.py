"""Targeted tests for the R1A.1 provenance-safe label package.

Offline and bounded: synthetic bars for the label logic, plus a small real-data
equivalence check on the 5 golden codes. No full-market computation.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "outcome_v01"))

import build_second_launch_outcome_v01 as gen  # noqa: E402


GOLDEN_CODES = ["002606", "002498", "600468", "600756", "601858"]


def make_bars(
    code: str,
    rows: list[tuple[date, str, str, str, str, str]],
) -> pd.DataFrame:
    """Build a canonical-style bar frame: (trade_date, open, high, low, close, volume)."""
    return pd.DataFrame(
        [
            {
                "code": code,
                "trade_date": d,
                "open": float(o),
                "high": float(h),
                "low": float(lo),
                "close": float(c),
                "preclose": float(c),
                "volume": float(v),
                "amount": float(v),
                "turnover_rate": 0.03,
                "pct_change": 0.0,
                "trade_status": True,
                "is_st": False,
            }
            for d, o, h, lo, c, v in rows
        ]
    )


def make_case(
    episode_id: str,
    symbol: str,
    candidate_date: date,
    s1: str,
    invalid: str,
    *,
    outcome: str = "SUCCESS",
    outcome_reason: str = "",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "episode_id": episode_id,
                "symbol": symbol,
                "name": "",
                "anchor_date": candidate_date,
                "candidate_date": candidate_date,
                "s1_price": s1,
                "invalid_price": invalid,
                "outcome": outcome,
                "outcome_reason": outcome_reason,
                "data_quality": "OK",
                "quality_flags": "[]",
            }
        ]
    )


def test_3d_frozen_equivalence_golden_codes():
    """Recomputed 3D must equal the frozen V01B outcome on the 5 golden codes."""
    cases = gen.load_case_set(gen.CASE_SET_PATH)
    golden = cases[cases["symbol"].isin(GOLDEN_CODES)].copy()
    assert len(golden) == 17
    codes = set(golden["symbol"])
    feature_bars = gen.load_bars_by_code(gen.FEATURE_SNAPSHOT_PATH, codes)
    label_bars = gen.load_bars_by_code(gen.LABEL_SNAPSHOT_PATH, codes)
    rows, _ = gen._build_rows(golden, feature_bars, label_bars)
    mismatches = [
        row for row in rows
        if row["_gate_outcome_3d"] != row["outcome_3d"]
    ]
    assert mismatches == []


def test_5d_horizon_session_counting():
    """Sessions are the stock's own bar rows; a suspended day is not counted."""
    code = "600000"
    bars = make_bars(
        code,
        [
            (date(2026, 3, 2), "10", "10", "10", "10", "100"),
            (date(2026, 3, 3), "10", "10.2", "9.8", "10.1", "150"),
            (date(2026, 3, 4), "10", "10.1", "9.9", "10.0", "120"),
            # 2026-03-05 suspended -> absent row
            (date(2026, 3, 6), "10", "10.1", "9.9", "10.0", "110"),
            (date(2026, 3, 9), "10", "10.0", "9.9", "10.0", "100"),
            (date(2026, 3, 10), "10", "10.0", "9.9", "10.0", "90"),
        ],
    )
    window = gen.future_window(bars, date(2026, 3, 2), gen.HORIZON_5D)
    assert len(window) == 5
    assert list(window["trade_date"]) == [
        date(2026, 3, 3),
        date(2026, 3, 4),
        date(2026, 3, 6),
        date(2026, 3, 9),
        date(2026, 3, 10),
    ]


def test_same_bar_s1_invalid_is_ambiguous():
    """Same-bar S1 + invalid touch => AMBIGUOUS => UNKNOWN (3D and 5D)."""
    code = "600000"
    bars = make_bars(
        code,
        [
            (date(2026, 3, 2), "10", "10", "10", "10", "100"),
            (date(2026, 3, 3), "10", "12", "8", "10", "150"),
            (date(2026, 3, 4), "10", "10", "10", "10", "120"),
        ],
    )
    pattern = gen.recompute_pattern(
        bars, date(2026, 3, 2), gen.HORIZON_3D, s1=10, invalid=9.5
    )
    assert pattern is gen.PatternOutcome.AMBIGUOUS
    label = gen.classify_outcome(pattern, gen.future_window(bars, date(2026, 3, 2), 3), 10, 100, "5 sessions")
    assert label.outcome == "UNKNOWN"
    assert "AMBIGUOUS" in label.reason


def test_failed_acceptance():
    """S1 first but close < S1 on the touch day => FAILED_BREAKOUT/FAILED_ACCEPTANCE."""
    code = "600000"
    bars = make_bars(
        code,
        [
            (date(2026, 3, 2), "10", "10", "10", "10", "100"),
            (date(2026, 3, 3), "10", "10.5", "9.8", "9.9", "150"),
            (date(2026, 3, 4), "10", "10", "10", "10", "120"),
        ],
    )
    pattern = gen.recompute_pattern(bars, date(2026, 3, 2), 3, s1=10, invalid=9.5)
    assert pattern is gen.PatternOutcome.S1_BEFORE_INVALID
    label = gen.classify_outcome(pattern, gen.future_window(bars, date(2026, 3, 2), 3), 10, 100, "5 sessions")
    assert label.outcome == "FAILED_BREAKOUT"
    assert "FAILED_ACCEPTANCE" in label.reason


def test_failed_expansion():
    """S1 first, close >= S1 but volume < signal-day volume => FAILED_EXPANSION."""
    code = "600000"
    bars = make_bars(
        code,
        [
            (date(2026, 3, 2), "10", "10", "10", "10", "200"),
            (date(2026, 3, 3), "10", "10.5", "9.9", "10.1", "150"),
            (date(2026, 3, 4), "10", "10", "10", "10", "120"),
        ],
    )
    pattern = gen.recompute_pattern(bars, date(2026, 3, 2), 3, s1=10, invalid=9.5)
    assert pattern is gen.PatternOutcome.S1_BEFORE_INVALID
    label = gen.classify_outcome(pattern, gen.future_window(bars, date(2026, 3, 2), 3), 10, 200, "5 sessions")
    assert label.outcome == "FAILED_BREAKOUT"
    assert "FAILED_EXPANSION" in label.reason


def test_no_launch():
    """No S1 and no invalid touch within the horizon => NO_LAUNCH."""
    code = "600000"
    bars = make_bars(
        code,
        [
            (date(2026, 3, 2), "10", "10", "10", "10", "100"),
            (date(2026, 3, 3), "10", "10.4", "9.7", "10.2", "150"),
            (date(2026, 3, 4), "10", "10.3", "9.8", "10.1", "120"),
            (date(2026, 3, 5), "10", "10.2", "9.9", "10.0", "110"),
        ],
    )
    pattern = gen.recompute_pattern(bars, date(2026, 3, 2), 3, s1=10.5, invalid=9.5)
    assert pattern is gen.PatternOutcome.NEITHER
    label = gen.classify_outcome(pattern, gen.future_window(bars, date(2026, 3, 2), 3), 10.5, 100, "5 sessions")
    assert label.outcome == "NO_LAUNCH"


def test_structure_fail():
    """Invalid first within the horizon => STRUCTURE_FAIL."""
    code = "600000"
    bars = make_bars(
        code,
        [
            (date(2026, 3, 2), "10", "10", "10", "10", "100"),
            (date(2026, 3, 3), "10", "10.2", "9.3", "9.8", "150"),
            (date(2026, 3, 4), "10", "10", "10", "10", "120"),
        ],
    )
    pattern = gen.recompute_pattern(bars, date(2026, 3, 2), 3, s1=10.5, invalid=9.5)
    assert pattern is gen.PatternOutcome.INVALID_BEFORE_S1
    label = gen.classify_outcome(pattern, gen.future_window(bars, date(2026, 3, 2), 3), 10.5, 100, "5 sessions")
    assert label.outcome == "STRUCTURE_FAIL"


def test_right_censoring():
    """Windows shorter than the horizon are right-censored, not fabricated."""
    code = "600000"
    cases = make_case(
        "TEST:20260302:1",
        code,
        date(2026, 3, 2),
        "10.5",
        "9.5",
        outcome="NO_LAUNCH",
        outcome_reason="no S1 and no invalid touch within 3 sessions",
    )
    bars = make_bars(
        code,
        [
            (date(2026, 3, 2), "10", "10", "10", "10", "100"),
            (date(2026, 3, 3), "10", "10.2", "9.8", "10.1", "150"),
            (date(2026, 3, 4), "10", "10.1", "9.9", "10.0", "120"),
            (date(2026, 3, 5), "10", "10.0", "9.9", "10.0", "110"),
        ],
    )
    rows, _ = gen._build_rows(
        cases,
        {code: bars},
        {code: bars},
    )
    row = rows[0]
    assert row["window_incomplete_5d"] is True
    assert row["window_incomplete_10d"] is True
    # No event observed within the truncated window -> event-time right censored.
    assert row["first_event_right_censored_10d"] is True
    assert row["outcome_5d"] == "CENSORED"


def test_feature_and_label_snapshots_not_mixed():
    """Signal-day volume comes from the feature snapshot only; late bars from label."""
    code = "600000"
    cases = make_case(
        "TEST:20260302:2",
        code,
        date(2026, 3, 2),
        "10",
        "9.5",
        outcome="SUCCESS",
        outcome_reason="S1 first + close>=S1 + volume>=signal-day volume",
    )
    feature_bars = make_bars(
        code,
        [
            (date(2026, 3, 2), "10", "10", "10", "10", "1000"),
            (date(2026, 3, 3), "10", "10.5", "9.9", "10.1", "1500"),
        ],
    )
    # Label snapshot: signal-day volume DIFFERS (9000) and must NOT be used;
    # the 5th session exists only here.
    label_bars = make_bars(
        code,
        [
            (date(2026, 3, 2), "10", "10", "10", "10", "9000"),
            (date(2026, 3, 3), "10", "10.5", "9.9", "10.1", "1500"),
            (date(2026, 3, 4), "10", "10.4", "9.9", "10.2", "1400"),
            (date(2026, 3, 5), "10", "10.3", "9.9", "10.1", "1300"),
            (date(2026, 3, 6), "10", "10.2", "9.9", "10.1", "1200"),
            (date(2026, 3, 9), "10", "10.1", "9.9", "10.0", "1100"),
        ],
    )
    rows, _ = gen._build_rows(cases, {code: feature_bars}, {code: label_bars})
    row = rows[0]
    # 1500 >= 1000 (feature signal volume) => SUCCESS; using the label signal
    # volume (9000) would yield FAILED_EXPANSION instead.
    assert row["outcome_5d"] == "SUCCESS"
    assert row["window_incomplete_5d"] is False
    assert row["feature_snapshot_id"] == gen.FEATURE_SNAPSHOT_ID
    assert row["label_snapshot_id_5d"] == gen.LABEL_SNAPSHOT_ID


def test_gate_fails_closed_on_blocked_case_set(tmp_path):
    """build_package raises (STATUS=BLOCKED) and writes no 5D CSV when the gate fails."""
    code = "600000"
    cases = make_case(
        "TEST:20260302:3",
        code,
        date(2026, 3, 2),
        "10",
        "9.5",
        outcome="NO_LAUNCH",  # frozen label contradicts the bars below
        outcome_reason="no S1 and no invalid touch within 3 sessions",
    )
    bars = make_bars(
        code,
        [
            (date(2026, 3, 2), "10", "10", "10", "10", "100"),
            (date(2026, 3, 3), "10", "10.5", "9.9", "10.1", "150"),
            (date(2026, 3, 4), "10", "10.4", "9.9", "10.2", "140"),
            (date(2026, 3, 5), "10", "10.3", "9.9", "10.1", "130"),
        ],
    )
    tmp_dir = tmp_path
    (tmp_dir / "cases.csv").write_text(
        cases.to_csv(index=False), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="3D regression mismatch_n"):
        gen.build_package(
            case_set_path=tmp_dir / "cases.csv",
            feature_snapshot_path=gen.FEATURE_SNAPSHOT_PATH,
            label_snapshot_path=gen.LABEL_SNAPSHOT_PATH,
            episodes_path=gen.EPISODES_PATH,
            out_dir=tmp_dir,
            case_set_expected_sha256=None,
            case_set_expected_row_n=None,
        )
    assert not (tmp_dir / "second_launch_outcome_v01.csv").exists()
    # The provenance audit is still written (defect registration).
    assert (tmp_dir / "pattern_provenance_mismatch.csv").exists()


def test_bounded_mode_is_isolated_from_full_artifacts(tmp_path):
    """A bounded (--codes) run must not write or overwrite formal artifacts."""
    real_out = gen.OUT_DIR
    before = {
        p.name: p.read_bytes()
        for p in real_out.iterdir()
        if p.is_file() and p.suffix in {".csv", ".json"}
    }
    manifest = gen.build_package(
        out_dir=tmp_path,
        codes_filter=set(GOLDEN_CODES),
    )
    assert manifest["mode"] == "BOUNDED"
    # Bounded output only inside tmp_path/bounded.
    bounded_files = list((tmp_path / "bounded").iterdir())
    assert len(bounded_files) == 1
    assert "second_launch_outcome_v01_codes" in bounded_files[0].name
    for forbidden in [
        "second_launch_outcome_v01.csv",
        "manifest.json",
        "pattern_provenance_mismatch.csv",
        "case_provenance_conflicts_v01.csv",
    ]:
        assert not (tmp_path / forbidden).exists()
    # The real formal directory is untouched.
    after = {
        p.name: p.read_bytes()
        for p in real_out.iterdir()
        if p.is_file() and p.suffix in {".csv", ".json"}
    }
    assert after == before


def test_feature_snapshot_hash_pin_fail_closed(tmp_path, monkeypatch):
    """A feature snapshot hash mismatch must fail closed before any output."""
    monkeypatch.setattr(gen, "EXPECTED_FEATURE_SNAPSHOT_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="feature snapshot hash mismatch"):
        gen.build_package(out_dir=tmp_path)
    assert not (tmp_path / "manifest.json").exists()


def test_label_snapshot_hash_pin_fail_closed(tmp_path, monkeypatch):
    """A label snapshot hash mismatch must fail closed before any output."""
    monkeypatch.setattr(gen, "EXPECTED_LABEL_SNAPSHOT_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="label snapshot hash mismatch"):
        gen.build_package(out_dir=tmp_path)
    assert not (tmp_path / "manifest.json").exists()


def test_incomplete_window_with_observed_event_not_event_censored():
    """8-session window + S1 at T+2: incomplete window, but event NOT censored."""
    code = "600000"
    cases = make_case(
        "TEST:20260302:4",
        code,
        date(2026, 3, 2),
        "10",
        "9.5",
        outcome="SUCCESS",
        outcome_reason="S1 first + close>=S1 + volume>=signal-day volume",
    )
    feature_bars = make_bars(
        code,
        [(date(2026, 3, 2), "10", "10", "10", "10", "100")],
    )
    label_bars = make_bars(
        code,
        [
            (date(2026, 3, 3), "9.9", "9.9", "9.8", "9.9", "80"),
            (date(2026, 3, 4), "10", "10.5", "9.9", "10.1", "150"),
            (date(2026, 3, 5), "10", "10.2", "9.9", "10.0", "120"),
            (date(2026, 3, 6), "10", "10.1", "9.9", "10.0", "110"),
            (date(2026, 3, 9), "10", "10.0", "9.9", "10.0", "100"),
            (date(2026, 3, 10), "10", "10.0", "9.9", "10.0", "90"),
            (date(2026, 3, 11), "10", "10.0", "9.9", "10.0", "90"),
            (date(2026, 3, 12), "10", "10.0", "9.9", "10.0", "90"),
        ],
    )
    rows, _ = gen._build_rows(cases, {code: feature_bars}, {code: label_bars})
    row = rows[0]
    assert row["window_incomplete_10d"] is True
    assert row["first_event_right_censored_10d"] is False
    assert row["time_to_s1_10d"] == 2.0
    assert row["outcome_5d"] == "SUCCESS"


def test_incomplete_window_without_event_is_event_censored():
    """8-session window + no event: incomplete window AND event-time censored."""
    code = "600000"
    cases = make_case(
        "TEST:20260302:5",
        code,
        date(2026, 3, 2),
        "10.5",
        "9.5",
        outcome="NO_LAUNCH",
        outcome_reason="no S1 and no invalid touch within 3 sessions",
    )
    feature_bars = make_bars(
        code,
        [(date(2026, 3, 2), "10", "10", "10", "10", "100")],
    )
    label_bars = make_bars(
        code,
        [
            (date(2026, 3, 3), "10", "10.2", "9.8", "10.1", "80"),
            (date(2026, 3, 4), "10", "10.2", "9.8", "10.1", "80"),
            (date(2026, 3, 5), "10", "10.2", "9.8", "10.1", "80"),
            (date(2026, 3, 6), "10", "10.2", "9.8", "10.1", "80"),
            (date(2026, 3, 9), "10", "10.2", "9.8", "10.1", "80"),
            (date(2026, 3, 10), "10", "10.2", "9.8", "10.1", "80"),
            (date(2026, 3, 11), "10", "10.2", "9.8", "10.1", "80"),
            (date(2026, 3, 12), "10", "10.2", "9.8", "10.1", "80"),
        ],
    )
    rows, _ = gen._build_rows(cases, {code: feature_bars}, {code: label_bars})
    row = rows[0]
    assert row["window_incomplete_10d"] is True
    assert row["first_event_right_censored_10d"] is True
    assert row["time_to_s1_10d"] is None
    assert row["outcome_5d"] == "NO_LAUNCH"
