from __future__ import annotations

from decimal import Decimal
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq

from limit_pullback.tail_gap_check import analyze_tail_gap, run_tail_gap_check


def _row(
    *,
    code: str = "000001",
    stage: str = "B1_READY",
    year: int = 2024,
    setup: str = "85",
    entry: str = "85",
    actionable: bool = True,
    fill_type: str = "NONE",
    outcome: str = "WIN_S1",
    r: str | None = "1.00",
    fill: str | None = "10.00",
    invalid: str = "9.00",
    s1: str | None = "12.00",
) -> dict[str, object]:
    filled = fill is not None
    return {
        "code": code,
        "setup_id": f"{code}:{year}0101:1",
        "setup_stage": stage,
        "signal_date": f"{year}-01-02",
        "setup_quality_score": setup,
        "entry_quality_score": entry,
        "is_entry_candidate": actionable,
        "preferred_entry": "10.00",
        "invalid_price": invalid,
        "s1_price": s1,
        "fill_status": "FILLED" if filled else "NO_FILL",
        "fill_type": fill_type,
        "fill_price": fill,
        "outcome": outcome,
        "r_multiple": r,
        "conservative_r_multiple": r or "-1.00",
        "mfe_pct": "0.02" if filled else None,
        "mae_pct": "-0.01" if filled else None,
        "eligibility_reason": None,
    }


def test_b1_tail_quantiles_caps_and_risk_geometry():
    rows = [
        _row(r="1.00", invalid="9.00"),
        _row(r="2.00", invalid="9.00"),
        _row(r="4.00", invalid="9.00"),
        _row(r="10.00", invalid="9.90"),
        _row(outcome="LOSS_INVALID", r="-1.00", invalid="9.00"),
    ]
    result = analyze_tail_gap(rows)
    stats = result["b1_r_tail_sanity"]["cohorts"]["B1_READY_ALL"]["overall"]
    assert stats["strict_resolved"] == 5
    assert stats["wins"] == 4
    assert stats["losses"] == 1
    assert stats["winner_R"] == {
        "p50": "3.0000",
        "p75": "5.5000",
        "p90": "8.2000",
        "p95": "9.1000",
        "p99": "9.8200",
        "max": "10.0000",
    }
    assert stats["raw_E_R"] == "3.2000"
    assert stats["cap_3R_E_R"] == "1.6000"
    assert stats["cap_5R_E_R"] == "2.2000"
    assert stats["cap_10R_E_R"] == "3.2000"
    geometry = stats["risk_geometry"]
    assert geometry["R_GE_10_winners"]["median_risk_pct"] == "0.0100"
    assert geometry["normal_winners_R_LT_10"]["median_risk_pct"] == "0.1000"


def test_non_actionable_b1_is_excluded_from_tail_and_concentration():
    rows = [
        _row(code="000001", actionable=True),
        _row(code="000002", actionable=False),
    ]
    result = analyze_tail_gap(rows)
    tail = result["b1_r_tail_sanity"]["cohorts"]["B1_READY_ALL"]["overall"]
    assert tail["episodes"] == 1
    assert tail["risk_geometry"]["episodes"] == 1
    assert result["b1_exploratory_setup_and_entry_ge_80"]["overall"]["episodes"] == 1
    concentration = result["concentration"]["B1_SETUP_GE_80"]
    assert concentration["episodes"] == 1
    assert concentration["unique_codes"] == 1


def test_gap_temporal_trigger_and_concentration():
    rows = [
        _row(stage="B2_READY", setup="75", entry="70", fill_type="BREAKOUT_GAP_FILL", year=2024, r="1.00"),
        _row(stage="B2_READY", setup="75", entry="70", fill_type="BREAKOUT_GAP_FILL", year=2025, outcome="LOSS_INVALID", r="-1.00"),
        _row(stage="B2_READY", setup="75", entry="70", fill_type="BREAKOUT_GAP_FILL", year=2026, outcome="AMBIGUOUS_INTRADAY", r=None),
        _row(stage="B2_READY", fill_type="BREAKOUT_TRIGGER_FILL", year=2024, code="000002", outcome="AMBIGUOUS_INTRADAY", r=None),
        _row(stage="B2_READY", fill_type="BREAKOUT_TRIGGER_FILL", year=2025, code="000003", outcome="AMBIGUOUS_INTRADAY", r=None),
        _row(code="000001", r="2.00"),
        _row(code="000001", outcome="LOSS_INVALID", r="-1.00"),
        _row(code="000002", outcome="LOSS_INVALID", r="-1.00"),
        _row(code="000003", r="3.00", entry="70"),
    ]
    result = analyze_tail_gap(rows)
    gap = result["b2_gap_temporal_stability"]
    assert gap["years"]["2024"]["strict_resolved"] == 1
    assert gap["years"]["2025"]["strict_resolved"] == 1
    assert gap["years"]["2026"]["ambiguous"] == 1
    trigger = result["b2_trigger_5m_candidate"]
    assert trigger["ambiguous_count"] == 2
    assert trigger["signal_years"] == {"2024": 1, "2025": 1}
    assert trigger["unique_codes"] == 2
    concentration = result["concentration"]["B1_SETUP_GE_80"]
    assert concentration["positive_expectancy_code_share"] == "0.6667"
    assert concentration["episode_tail_concentration"]["top_1pct"]["contribution"] == "0.6000"


def test_run_tail_gap_check_writes_verified_outputs(tmp_path):
    rows = [_row()]
    source = tmp_path / "episodes.parquet"
    pq.write_table(pa.Table.from_pylist(rows), source)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    payload = run_tail_gap_check(source, output_dir=tmp_path / "out", expected_sha256=expected)
    assert payload["evaluate_strategy_calls"] == 0
    assert json.loads((tmp_path / "out" / "tail_gap_check.json").read_text())["artifact"]["episode_count"] == 1
    assert (tmp_path / "out" / "tail_gap_check.md").read_text().startswith(
        "DESCRIPTIVE TAIL / GAP CHECK\nNOT STRATEGY OPTIMIZATION\nNOT OUT-OF-SAMPLE VALIDATION"
    )
