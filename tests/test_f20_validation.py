"""F20 outcome validation V01 — prereg-compliance regression tests.

Covers every regression the Sol review required (review @648aa06):
  wrong episodes SHA / wrong daily SHA / no DataFrame bypass /
  undefined isolation (INSUFFICIENT_PRE20 vs ZERO_DENOMINATOR) /
  accounting invariants / average-rank ties / CANCEL exclusion /
  numeric-R only / undefined rho fail closed / future leakage /
  quartile outcome-independence.
"""

from __future__ import annotations

import math
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "factor-lab"))

import f20_outcome_validation_v01 as m  # noqa: E402


# ---------- helpers ----------

def _daily_frame(bars: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(bars)


def _bar_row(code: str, d: str, close: float, volume: float, preclose: float = 10.0) -> dict:
    return {
        "code": code,
        "trade_date": date.fromisoformat(d),
        "open": preclose,
        "high": max(close, preclose),
        "low": min(close, preclose),
        "close": close,
        "preclose": preclose,
        "volume": volume,
        "trade_status": True,
    }


def _episode_row(code: str, anchor: str, signal: str, outcome: str, stage: str = "B2_READY",
                 r: float = 1.0, days: int = 3) -> dict:
    return {
        "code": code,
        "setup_id": f"EP-{code}-{signal}",
        "setup_stage": stage,
        "signal_date": signal,  # ISO string, matching frozen episodes parquet
        "anchor_date": anchor,
        "days_since_anchor": days,
        "outcome": outcome,
        "r_multiple": r,
    }


# ---------- 1/2. SHA gates ----------

def test_wrong_episodes_sha_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "episodes.parquet"
    pd.DataFrame([_episode_row("000001", "2026-01-05", "2026-01-08", "WIN_S1")]).to_parquet(path)
    with pytest.raises(RuntimeError, match="episodes SHA mismatch"):
        m.load_episodes(path, expected_sha="0" * 64)


def test_wrong_daily_sha_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "daily.parquet"
    _daily_frame([_bar_row("000001", "2026-01-05", 10.0, 100)]).to_parquet(path)
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

def _groups_with(bars: list[dict]) -> dict[str, pd.DataFrame]:
    return {"000001": pd.DataFrame(bars).sort_values("trade_date")}


def test_insufficient_pre20_reason() -> None:
    bars = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 100) for d in range(1, 6)]
    bars.append(_bar_row("000001", "2026-01-08", 11.0, 500))  # b2 = signal date
    groups = _groups_with(bars)
    ep = _episode_row("000001", "2026-01-02", "2026-01-08", "WIN_S1")
    value, reason = m.compute_f20(groups, ep)
    assert value is None
    assert reason == "INSUFFICIENT_PRE20"


def test_zero_denominator_reason() -> None:
    bars = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 0) for d in range(1, 22)]
    bars.append(_bar_row("000001", "2026-01-23", 11.0, 500))  # b2; 20 pre bars all zero volume
    groups = _groups_with(bars)
    ep = _episode_row("000001", "2026-01-02", "2026-01-23", "WIN_S1")
    value, reason = m.compute_f20(groups, ep)
    assert value is None
    assert reason == "ZERO_DENOMINATOR"


def test_defined_f20_value() -> None:
    bars = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 100) for d in range(1, 22)]
    bars.append(_bar_row("000001", "2026-01-23", 11.0, 500))  # b2; mean(pre20)=100
    groups = _groups_with(bars)
    ep = _episode_row("000001", "2026-01-02", "2026-01-23", "WIN_S1")
    value, reason = m.compute_f20(groups, ep)
    assert reason is None
    assert value == Decimal("5")


# ---------- 5. accounting invariants ----------

def test_accounting_invariants_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="ACCOUNTING INVARIANT FAILED"):
        m.check_accounting(100, 80, 15, 70, 70, 10)  # 80 + 15 != 100


def test_accounting_cancel_gap_invariant_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="ACCOUNTING INVARIANT FAILED"):
        m.check_accounting(100, 80, 20, 70, 70, 5)  # 70 + 5 != 80


# ---------- 6. average-rank ties / frozen spearman ----------

def test_frozen_spearman_tie_case_hand_computed() -> None:
    """Hand-computed tie case (no scipy oracle, per audit requirement).

    x = [1, 1, 2, 3], y = [1, 2, 2, 3]
    rank_x = [1.5, 1.5, 3, 4] (mean 2.5)
    rank_y = [1, 2.5, 2.5, 4] (mean 2.5)
    cov = (-1)(-1.5) + (-1)(0) + (0.5)(0) + (1.5)(1.5) = 3.75
    var_x = 1 + 1 + 0.25 + 2.25 = 4.5; var_y = 2.25 + 0 + 0 + 2.25 = 4.5
    rho = 3.75 / sqrt(4.5 * 4.5) = 3.75 / 4.5 = 5/6 ≈ 0.833333
    """
    x = pd.Series([1.0, 1.0, 2.0, 3.0])
    y = pd.Series([1.0, 2.0, 2.0, 3.0])
    assert m.frozen_spearman(x, y) == pytest.approx(5 / 6)


def test_frozen_spearman_n_lt_2_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="PRIMARY_RHO_UNDEFINED"):
        m.frozen_spearman(pd.Series([1.0]), pd.Series([2.0]))


def test_frozen_spearman_constant_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="PRIMARY_RHO_UNDEFINED"):
        m.frozen_spearman(pd.Series([1.0, 1.0, 1.0]), pd.Series([1.0, 2.0, 3.0]))


# ---------- 7. CANCEL exclusion ----------

def test_cancel_gap_excluded_from_strict_denominator() -> None:
    outcomes = pd.Series(["WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID", "CANCEL_GAP_INVALID"])
    r = pd.Series([1.5, -0.5, 0.3, 0.2])
    gm = m.group_metrics(outcomes, r)
    assert gm["STRICT_N"] == 2  # only WIN_S1 + LOSS_INVALID
    assert gm["strict_win_rate"] == 0.5
    assert gm["CANCEL_GAP_INVALID"] == 2


# ---------- 8. numeric-R only ----------

def test_non_numeric_r_excluded_from_r_population() -> None:
    outcomes = pd.Series(["WIN_S1", "LOSS_INVALID", "WIN_S1"])
    r = pd.Series([1.5, float("nan"), 2.0])
    gm = m.group_metrics(outcomes, r)
    assert gm["R_DEFINED_N"] == 2
    assert gm["P(R>0)"] == 1.0


# ---------- 9. undefined rho fail closed ----------

def test_spearman_block_constant_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="PRIMARY_RHO_UNDEFINED"):
        m.spearman_block(pd.Series([1.0, 2.0, 3.0]), pd.Series([0, 0, 0]), "strict")


def test_nonfinite_rho_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """nonfinite rho must raise PRIMARY_RHO_UNDEFINED (audit requirement)."""
    monkeypatch.setattr(m.math, "isfinite", lambda value: False)
    with pytest.raises(RuntimeError, match="PRIMARY_RHO_UNDEFINED"):
        m.frozen_spearman(pd.Series([1.0, 2.0, 3.0]), pd.Series([2.0, 4.0, 6.0]))


# ---------- 9b. B1_READY not excluded before materialization ----------

def test_b1_ready_materializes_f20() -> None:
    """B1_READY episodes must NOT be excluded before F20 materialization:
    with >=20 pre-B2 sessions they are F20-defined (no NON_B2_STAGE filter)."""
    bars = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 100) for d in range(1, 22)]
    bars.append(_bar_row("000001", "2026-01-23", 11.0, 500))
    groups = _groups_with(bars)
    ep = _episode_row("000001", "2026-01-02", "2026-01-23", "WIN_S1", stage="B1_READY")
    value, reason = m.compute_f20(groups, ep)
    assert reason is None
    assert value == Decimal("5")


# ---------- 9c. OTHER_ERROR blocks artifact ----------

def test_other_error_reason_on_b2_bar_missing() -> None:
    """Missing B2 bar must surface as OTHER_ERROR (main() then fails closed)."""
    bars = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 100) for d in range(1, 22)]
    groups = _groups_with(bars)  # no bar on signal_date -> B2 bar missing
    ep = _episode_row("000001", "2026-01-02", "2026-01-25", "WIN_S1")
    value, reason = m.compute_f20(groups, ep)
    assert value is None
    assert reason is not None and reason.startswith("OTHER_ERROR:")


# ---------- 9d. verdict branches ----------

def test_verdict_both_positive_supported() -> None:
    assert m.verdict(0.1, 0.1) == "SUPPORTED_DIRECTIONALLY"


def test_verdict_any_nonpositive_rejects() -> None:
    assert m.verdict(0.1, -0.1) == "REJECT"
    assert m.verdict(-0.1, 0.1) == "REJECT"
    assert m.verdict(-0.1, -0.1) == "REJECT"
    assert m.verdict(0.0, 0.1) == "REJECT"


# ---------- 10. future leakage ----------

def test_bars_pit_truncates_at_as_of() -> None:
    bars = [_bar_row("000001", "2026-01-05", 10.0, 100), _bar_row("000001", "2026-01-08", 10.0, 100),
            _bar_row("000001", "2026-01-09", 10.0, 100)]
    grp = pd.DataFrame(bars)
    pit = m.bars_pit_f20(grp, date(2026, 1, 8))
    assert [b.trade_date.isoformat() for b in pit] == ["2026-01-05", "2026-01-08"]


def test_future_huge_volume_does_not_affect_f20() -> None:
    bars = [_bar_row("000001", f"2026-01-{d:02d}", 10.0, 100) for d in range(1, 22)]
    bars.append(_bar_row("000001", "2026-01-23", 11.0, 500))          # b2
    bars.append(_bar_row("000001", "2026-01-26", 12.0, 999999))        # future bar
    groups = _groups_with(bars)
    ep = _episode_row("000001", "2026-01-02", "2026-01-23", "WIN_S1")
    value, reason = m.compute_f20(groups, ep)
    assert reason is None
    assert value == Decimal("5")  # future volume never participates


# ---------- 11. quartile outcome-independence ----------

def test_quartile_boundaries_from_f20_distribution_only() -> None:
    df = pd.DataFrame({
        "f20": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0],
        "outcome": ["WIN_S1"] * 6 + ["LOSS_INVALID"] * 6,
        "r_multiple": [1.0] * 12,
    })
    rows = m.quartile_rows(df)
    f20 = pd.to_numeric(df["f20"])
    assert rows[0]["bounds"] is None
    assert rows[1]["bounds"] == pytest.approx(float(f20.quantile(0.25)))
    assert rows[2]["bounds"] == pytest.approx(float(f20.quantile(0.50)))
    assert rows[3]["bounds"] == pytest.approx(float(f20.quantile(0.75)))
    assert sum(r["N"] for r in rows) == 12
    assert all("STRICT_N" in r and "R_DEFINED_N" in r for r in rows)
