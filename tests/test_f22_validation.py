"""F22 outcome validation V01 — preregistered targeted regression tests.

Covers every branch the frozen prereg / Sol TASK requires (Sol review @3d2c8a7):
  wrong episodes SHA / wrong daily SHA / no DataFrame bypass /
  undefined isolation (INSUFFICIENT_PRE5 vs ZERO_DENOMINATOR vs
  MISSING_B2_BAR) / accounting conservation / OTHER_ERROR fail-before-write /
  CANCEL_GAP strict-denominator exclusion / numeric-R only /
  primary metrics (FAIL_RATE / DELTA_FAIL_RATE / OR_FAILURE exactness) /
  verdict branches (SUPPORTED_DIRECTIONALLY / REJECT) /
  PRIMARY_METRIC_UNDEFINED fail closed (zero WIN cell, N<2) /
  PRIMARY_SMALL_CELL (TRUE_N<20, FALSE_N<20 -> INSUFFICIENT_PRIMARY_N) /
  population filter (B1_READY excluded, B2 stages only) /
  future leakage.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "factor-lab"))

import f22_outcome_validation_v01 as m  # noqa: E402


# ---------- helpers ----------

def _bar_row(code: str, d: str, close: float, volume: float, high: float | None = None,
             open_: float | None = None, low: float | None = None, preclose: float = 10.0) -> dict:
    hi = high if high is not None else max(close, preclose)
    lo = low if low is not None else min(close, preclose)
    op = open_ if open_ is not None else preclose
    return {
        "code": code,
        "trade_date": date.fromisoformat(d),
        "open": op,
        "high": hi,
        "low": lo,
        "close": close,
        "preclose": preclose,
        "volume": volume,
        "trade_status": True,
    }


def _episode_row(code: str, signal: str, outcome: str, stage: str = "B2_READY",
                 r: float = 1.0, days: int = 3, setup_id: str | None = None) -> dict:
    return {
        "code": code,
        "setup_id": setup_id or f"EP-{code}-{signal}",
        "setup_stage": stage,
        "signal_date": signal,  # ISO string, matching frozen episodes parquet
        "days_since_anchor": days,
        "outcome": outcome,
        "r_multiple": r,
    }


def _groups_with(bars: list[dict]) -> dict[str, pd.DataFrame]:
    return {"000001": pd.DataFrame(bars).sort_values("trade_date")}


def _default_bars(b2: str = "2026-01-08") -> list[dict]:
    """9 bars: 5 pre-sessions (vol 100), B2 at b2, 3 future bars (huge vol)."""
    bars = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 100) for d in range(1, 6)]
    bars.append(_bar_row("000001", b2, 11.0, 1000, high=12.0, open_=10.5, low=10.0))
    bars += [_bar_row("000001", d, 11.0, 999999) for d in ("2026-01-09", "2026-01-12", "2026-01-13")]
    return bars


def _episode(code: str = "000001", signal: str = "2026-01-08", outcome: str = "WIN_S1",
             stage: str = "B2_READY") -> dict:
    return _episode_row(code, signal, outcome, stage=stage)


# ---------- 1/2. SHA gates ----------

def test_wrong_episodes_sha_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "episodes.parquet"
    pd.DataFrame([_episode_row("000001", "2026-01-08", "WIN_S1")]).to_parquet(path)
    with pytest.raises(RuntimeError, match="episodes SHA mismatch"):
        m.load_episodes(path, expected_sha="0" * 64)


def test_wrong_daily_sha_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "daily.parquet"
    pd.DataFrame([_bar_row("000001", "2026-01-05", 10.0, 100)]).to_parquet(path)
    with pytest.raises(RuntimeError, match="daily SHA mismatch"):
        m.load_daily(path, expected_sha="0" * 64)


# ---------- 3. no DataFrame bypass ----------

def test_episodes_dataframe_bypass_forbidden() -> None:
    with pytest.raises(TypeError, match="DataFrame bypass forbidden"):
        m.load_episodes(pd.DataFrame())  # type: ignore[arg-type]


def test_daily_dataframe_bypass_forbidden() -> None:
    with pytest.raises(TypeError, match="DataFrame bypass forbidden"):
        m.load_daily(pd.DataFrame())  # type: ignore[arg-type]


# ---------- 4. undefined isolation ----------

def test_insufficient_pre5_reason() -> None:
    bars = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 100) for d in range(1, 5)]
    bars.append(_bar_row("000001", "2026-01-08", 11.0, 1000, high=12.0, open_=10.5))  # b2; only 4 pre sessions
    value, reason = m.compute_f22(_groups_with(bars), _episode())
    assert value is None
    assert reason == "INSUFFICIENT_PRE5"


def test_zero_denominator_reason() -> None:
    bars = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 0) for d in range(1, 6)]
    bars.append(_bar_row("000001", "2026-01-08", 11.0, 1000, high=12.0, open_=10.5))  # b2; pre vols all zero
    value, reason = m.compute_f22(_groups_with(bars), _episode())
    assert value is None
    assert reason == "ZERO_DENOMINATOR"


def test_missing_b2_bar_reason() -> None:
    bars = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 100) for d in range(1, 6)]
    # no bar on signal_date -> MISSING_B2_BAR (frozen undefined category)
    value, reason = m.compute_f22(_groups_with(bars), _episode(signal="2026-01-12"))
    assert value is None
    assert reason == "MISSING_B2_BAR"


def test_no_bars_for_code_reason() -> None:
    value, reason = m.compute_f22({}, _episode())
    assert value is None
    assert reason == "MISSING_B2_BAR"


def test_defined_f22_true() -> None:
    value, reason = m.compute_f22(_groups_with(_default_bars()), _episode())
    assert reason is None
    assert value is True  # upper shadow 1.5 >= body 0.5, vol ratio 1000/100 = 10 >= 1.5


def test_defined_f22_false() -> None:
    bars = _default_bars()
    bars[5] = _bar_row("000001", "2026-01-08", 11.0, 100, high=11.5, open_=10.5)  # shadow 0.5 < body 0.5
    value, reason = m.compute_f22(_groups_with(bars), _episode())
    assert reason is None
    assert value is False


def test_other_error_reason_on_duplicate_dates() -> None:
    bars = _default_bars()
    bars.append(_bar_row("000001", "2026-01-08", 12.0, 500))  # duplicate B2 date -> _ordered ValueError
    value, reason = m.compute_f22(_groups_with(bars), _episode())
    assert value is None
    assert reason is not None and reason.startswith("OTHER_ERROR:")


# ---------- 5. accounting conservation ----------

def test_accounting_invariants_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="ACCOUNTING INVARIANT FAILED"):
        m.check_accounting(100, 80, 15, 4)  # 80 + 15 + 4 != 100


def test_accounting_ok() -> None:
    acct = m.check_accounting(100, 80, 15, 5)
    assert acct["POPULATION_N"] == 100
    assert acct["DEFINED_TRUE_N"] == 80
    assert acct["DEFINED_FALSE_N"] == 15
    assert acct["UNDEFINED_N"] == 5


# ---------- 6. primary metrics ----------

def test_primary_metrics_hand_computed() -> None:
    """Hand-computed: TRUE win=40 loss=60; FALSE win=50 loss=30.
    FR_TRUE = 60/100 = 0.6; FR_FALSE = 30/80 = 0.375; DELTA = 0.225.
    odds_TRUE = 60/40 = 1.5; odds_FALSE = 30/50 = 0.6; OR = 2.5."""
    out = m.primary_metrics_exact(40, 60, 50, 30)
    assert out["FAIL_RATE_TRUE"] == Decimal("0.6")
    assert out["FAIL_RATE_FALSE"] == Decimal("0.375")
    assert out["DELTA_FAIL_RATE"] == Decimal("0.225")
    assert out["OR_FAILURE"] == Decimal("2.5")


def test_primary_metrics_zero_win_cell_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="PRIMARY_METRIC_UNDEFINED"):
        m.primary_metrics_exact(0, 30, 50, 30)  # TRUE WIN=0 -> odds undefined


def test_primary_metrics_zero_loss_cell_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="PRIMARY_METRIC_UNDEFINED"):
        m.primary_metrics_exact(40, 0, 50, 30)  # TRUE LOSS=0 -> odds undefined


def test_primary_metrics_n_lt_2_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="PRIMARY_METRIC_UNDEFINED"):
        m.primary_metrics_exact(1, 0, 50, 30)  # TRUE strict N=1 < 2


def test_primary_metrics_no_continuity_correction() -> None:
    """Zero-cell (LOSS_TRUE=0) must fail closed, NOT be 'fixed' by a
    0.5 correction: OR_FAILURE would otherwise be invented."""
    with pytest.raises(RuntimeError, match="PRIMARY_METRIC_UNDEFINED"):
        m.primary_metrics_exact(40, 0, 50, 30)


# ---------- 7. verdict branches ----------

def test_verdict_supported_directional() -> None:
    assert m.verdict(Decimal("0.1"), Decimal("1.5")) == "SUPPORTED_DIRECTIONALLY"


def test_verdict_reject_delta_nonpositive() -> None:
    assert m.verdict(Decimal("0"), Decimal("1.5")) == "REJECT"
    assert m.verdict(Decimal("-0.1"), Decimal("1.5")) == "REJECT"


def test_verdict_reject_or_not_above_1() -> None:
    assert m.verdict(Decimal("0.1"), Decimal("1.0")) == "REJECT"
    assert m.verdict(Decimal("0.1"), Decimal("0.9")) == "REJECT"


# ---------- 8. CANCEL exclusion / numeric-R only ----------

def test_cancel_gap_excluded_from_strict_denominator() -> None:
    outcomes = pd.Series(["WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID", "CANCEL_GAP_INVALID"])
    r = pd.Series([1.5, -0.5, 0.3, 0.2])
    gm = m.group_metrics(outcomes, r)
    assert gm["STRICT_N"] == 2  # only WIN_S1 + LOSS_INVALID
    assert gm["strict_win_rate"] == 0.5
    assert gm["FAIL_RATE"] == 0.5
    assert gm["CANCEL_GAP_INVALID"] == 2


def test_non_numeric_r_excluded_from_r_population() -> None:
    outcomes = pd.Series(["WIN_S1", "LOSS_INVALID", "WIN_S1"])
    r = pd.Series([1.5, float("nan"), 2.0])
    gm = m.group_metrics(outcomes, r)
    assert gm["R_DEFINED_N"] == 2
    assert gm["P(R>0)"] == 1.0


# ---------- 9. population filter ----------

def test_b1_ready_excluded_from_population(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B1_READY must never enter the domain population: with a full B2-stage
    population present, the B1_READY episode is counted nowhere."""
    pre = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 100) for d in range(1, 10)]
    b2_true = _bar_row("000001", "2026-02-01", 11.0, 1000, high=12.0, open_=10.5)
    b2_false = _bar_row("000001", "2026-02-01", 11.0, 1000, high=11.4, open_=10.5)
    bars_t = [dict(b, code="100001") for b in pre] + [dict(b2_true, code="100001")]
    bars_f = [dict(b, code="100002") for b in pre] + [dict(b2_false, code="100002")]
    daily = pd.DataFrame(bars_t + bars_f)
    rows = []
    for i in range(40):
        rows.append(_episode_row("100001", "2026-02-01", "WIN_S1", setup_id=f"T-W-{i}"))
    for i in range(60):
        rows.append(_episode_row("100001", "2026-02-01", "LOSS_INVALID", setup_id=f"T-L-{i}"))
    for i in range(50):
        rows.append(_episode_row("100002", "2026-02-01", "WIN_S1", setup_id=f"F-W-{i}"))
    for i in range(30):
        rows.append(_episode_row("100002", "2026-02-01", "LOSS_INVALID", setup_id=f"F-L-{i}"))
    rows.append(_episode_row("100001", "2026-02-01", "WIN_S1", stage="B1_READY", setup_id="B1-ROW"))
    ep_df = pd.DataFrame(rows)
    monkeypatch.setattr(m, "load_episodes", lambda path, expected_sha="", expected_total=len(rows): ep_df)
    monkeypatch.setattr(m, "load_daily", lambda path, expected_sha="": daily)
    out_dir = tmp_path / "out"
    result = m.main(tmp_path / "episodes.parquet", tmp_path / "daily.parquet", out_dir)
    assert result["POPULATION_N"] == 180  # B1_READY excluded
    assert result["PRIMARY_TRUE_N"] == 100
    assert result["PRIMARY_FALSE_N"] == 80


# ---------- 10. OTHER_ERROR fail-before-write ----------

def test_main_other_error_fails_closed_before_artifact(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ep = pd.DataFrame([_episode_row("000001", "2026-01-12", "WIN_S1")])  # signal date has no B2 bar? actually it does
    # craft: duplicate-date daily rows -> OTHER_ERROR inside compute_f22
    bars = _default_bars()
    bars.append(_bar_row("000001", "2026-01-08", 12.0, 500))
    daily = _daily_frame_from_bars(bars)
    monkeypatch.setattr(m, "load_episodes", lambda path, expected_sha="", expected_total=1: ep)
    monkeypatch.setattr(m, "load_daily", lambda path, expected_sha="": daily)
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="OTHER_ERROR count > 0"):
        m.main(tmp_path / "episodes.parquet", tmp_path / "daily.parquet", out_dir)
    assert not (out_dir / "f22-outcome-validation-v01.json").exists()
    assert not (out_dir / "f22-outcome-validation-v01.md").exists()


def test_main_primary_metric_undefined_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """TRUE group with win=0 (zero odds cell) must abort before artifact write."""
    ep = pd.DataFrame([
        _episode_row("000001", "2026-01-08", "LOSS_INVALID"),  # 01-08 is F22_TRUE (default bars)
        _episode_row("000001", "2026-01-09", "WIN_S1"),        # 01-09 is F22_FALSE (future flat bar)
    ])
    daily = _daily_frame_from_bars(_default_bars(b2="2026-01-08"))
    monkeypatch.setattr(m, "load_episodes", lambda path, expected_sha="", expected_total=2: ep)
    monkeypatch.setattr(m, "load_daily", lambda path, expected_sha="": daily)
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="PRIMARY_METRIC_UNDEFINED"):
        m.main(tmp_path / "episodes.parquet", tmp_path / "daily.parquet", out_dir)
    assert not (out_dir / "f22-outcome-validation-v01.json").exists()


def _daily_frame_from_bars(bars: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(bars)


# ---------- 11. small-cell policy + main-level verdict branches ----------

def _main_with_counts(win_true: int, loss_true: int, win_false: int, loss_false: int,
                      monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    """Synthetic main(): TRUE-group episodes on code T1 (B2 = F22_TRUE shape),
    FALSE-group episodes on code F1 (B2 = F22_FALSE shape), exactly the given
    strict outcome counts. Both codes share the same B2 date."""
    pre = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 100) for d in range(1, 10)]
    b2_true = _bar_row("000001", "2026-02-01", 11.0, 1000, high=12.0, open_=10.5)
    b2_false = _bar_row("000001", "2026-02-01", 11.0, 1000, high=11.4, open_=10.5)  # shadow 0.4 < body 0.5
    bars_t = [dict(b, code="100001") for b in pre] + [dict(b2_true, code="100001")]
    bars_f = [dict(b, code="100002") for b in pre] + [dict(b2_false, code="100002")]
    daily = pd.DataFrame(bars_t + bars_f)

    rows = []
    for i in range(win_true):
        rows.append(_episode_row("100001", "2026-02-01", "WIN_S1", setup_id=f"T-W-{i}"))
    for i in range(loss_true):
        rows.append(_episode_row("100001", "2026-02-01", "LOSS_INVALID", setup_id=f"T-L-{i}"))
    for i in range(win_false):
        rows.append(_episode_row("100002", "2026-02-01", "WIN_S1", setup_id=f"F-W-{i}"))
    for i in range(loss_false):
        rows.append(_episode_row("100002", "2026-02-01", "LOSS_INVALID", setup_id=f"F-L-{i}"))
    ep_df = pd.DataFrame(rows)

    monkeypatch.setattr(m, "load_episodes", lambda path, expected_sha="", expected_total=len(rows): ep_df)
    monkeypatch.setattr(m, "load_daily", lambda path, expected_sha="": daily)
    out_dir = tmp_path / "out"
    return m.main(tmp_path / "episodes.parquet", tmp_path / "daily.parquet", out_dir)


def test_small_cell_true_n_lt_20(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """TRUE strict N=19 < 20 -> INSUFFICIENT_PRIMARY_N even if direction positive."""
    result = _main_with_counts(10, 9, 40, 20, monkeypatch, tmp_path)
    assert result["STATUS"] == "INSUFFICIENT_PRIMARY_N"
    assert result["VERDICT"] is None
    assert result["PRIMARY_SMALL_CELL"] is True


def test_small_cell_false_n_lt_20(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = _main_with_counts(40, 30, 10, 9, monkeypatch, tmp_path)
    assert result["STATUS"] == "INSUFFICIENT_PRIMARY_N"
    assert result["VERDICT"] is None
    assert result["PRIMARY_SMALL_CELL"] is True


def test_main_supported_directional(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """FR_TRUE=0.6 > FR_FALSE=0.375 and OR=2.5 > 1 with both N>=20 ->
    SUPPORTED_DIRECTIONALLY."""
    result = _main_with_counts(40, 60, 50, 30, monkeypatch, tmp_path)
    assert result["STATUS"] == "SUPPORTED_DIRECTIONALLY"
    assert result["VERDICT"] == "SUPPORTED_DIRECTIONALLY"
    assert result["PRIMARY_SMALL_CELL"] is False
    assert result["DELTA_FAIL_RATE"] == pytest.approx(0.225)
    assert result["OR_FAILURE"] == pytest.approx(2.5)


def test_main_reject(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """DELTA_FAIL_RATE = 0.5 - 0.6 = -0.1 < 0 -> REJECT (direction reversed)."""
    result = _main_with_counts(50, 50, 40, 60, monkeypatch, tmp_path)
    assert result["STATUS"] == "REJECT"
    assert result["VERDICT"] == "REJECT"
    assert result["PRIMARY_SMALL_CELL"] is False


# ---------- 12. future leakage ----------

def test_bars_pit_truncates_at_as_of() -> None:
    bars = [_bar_row("000001", "2026-01-05", 10.0, 100), _bar_row("000001", "2026-01-08", 10.0, 100),
            _bar_row("000001", "2026-01-09", 10.0, 100)]
    grp = pd.DataFrame(bars)
    pit = m.bars_pit_f22(grp, date(2026, 1, 8))
    assert [b.trade_date.isoformat() for b in pit] == ["2026-01-05", "2026-01-08"]


def test_future_huge_volume_does_not_affect_f22() -> None:
    value, reason = m.compute_f22(_groups_with(_default_bars()), _episode())
    assert reason is None
    assert value is True  # future bars with vol 999999 never participate
