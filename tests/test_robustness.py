from __future__ import annotations

from decimal import Decimal
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq

from limit_pullback.robustness import (
    FIXED_SCORE_BUCKETS,
    analyze_robustness,
    render_robustness_markdown,
    run_robustness,
)


def _row(
    *,
    code: str = "000001",
    stage: str = "B1_READY",
    signal_date: str = "2024-01-02",
    setup_quality: str = "85",
    entry_quality: str = "85",
    actionable: bool = True,
    fill_type: str = "NONE",
    outcome: str = "WIN_S1",
    r: str | None = "1.00",
) -> dict[str, object]:
    return {
        "code": code,
        "setup_stage": stage,
        "signal_date": signal_date,
        "setup_quality_score": setup_quality,
        "entry_quality_score": entry_quality,
        "is_entry_candidate": actionable,
        "preferred_entry": "10.00",
        "invalid_price": "9.50",
        "s1_price": "11.00",
        "fill_status": "FILLED" if fill_type != "NONE" else "NO_FILL",
        "fill_type": fill_type,
        "outcome": outcome,
        "r_multiple": r,
        "conservative_r_multiple": r or "-1.00",
        "mfe_pct": "0.01",
        "mae_pct": "-0.01",
        "eligibility_reason": None,
    }


def test_fixed_temporal_cohorts_and_score_buckets_are_deterministic():
    rows = [
        _row(code="000001", signal_date="2024-01-02"),
        _row(code="000002", signal_date="2025-01-02", setup_quality="75"),
        _row(
            code="000003",
            signal_date="2026-01-02",
            stage="B2_READY",
            setup_quality="75",
            entry_quality="65",
        ),
    ]
    result = analyze_robustness(rows, artifact_sha256="hash")
    assert list(result["temporal_stability"]["years"]) == ["2024", "2025", "2026"]
    assert result["temporal_stability"]["years"]["2026"]["B2_READY_SETUP_70_80"]["episodes"] == 1
    assert result["score_monotonicity"]["fixed_buckets"] == list(FIXED_SCORE_BUCKETS)
    assert result["evaluate_strategy_calls"] == 0


def test_ambiguity_break_even_and_fill_types():
    rows = [
        _row(stage="B2_READY", fill_type="BREAKOUT_GAP_FILL", outcome="WIN_S1", r="1.00"),
        _row(stage="B2_READY", fill_type="BREAKOUT_TRIGGER_FILL", outcome="LOSS_INVALID", r="-1.00"),
        _row(stage="B2_READY", outcome="AMBIGUOUS_INTRADAY", r=None),
    ]
    result = analyze_robustness(rows)
    sensitivity = result["b2_ambiguity_sensitivity"]
    assert sensitivity["AMBIGUOUS_BREAK_EVEN_MEAN_R"] == "0.0000"
    assert sensitivity["scenarios"]["0"]["expectancy_R"] == "0.0000"
    fills = result["b2_fill_type"]["fill_types"]
    assert fills["BREAKOUT_GAP_FILL"]["episodes"] == 1
    assert fills["BREAKOUT_TRIGGER_FILL"]["episodes"] == 1


def test_concentration_is_order_independent_and_writes_outputs(tmp_path):
    rows = [
        _row(code="000002", outcome="LOSS_INVALID", r="-1.00"),
        _row(code="000001", outcome="WIN_S1", r="2.00"),
        _row(code="000001", outcome="LOSS_INVALID", r="-1.00"),
    ]
    first = analyze_robustness(rows)
    second = analyze_robustness(list(reversed(rows)))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    concentration = first["concentration"]["B1_READY_SETUP_GE_80"]
    assert concentration["unique_codes"] == 2
    assert concentration["top1_contribution"] == "0.5000"
    assert concentration["median_code_mean_R"] == "-0.2500"

    source = tmp_path / "episodes.parquet"
    pq.write_table(pa.Table.from_pylist(rows), source)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    payload = run_robustness(source, output_dir=tmp_path / "out", expected_sha256=expected)
    assert (tmp_path / "out" / "robustness.json").is_file()
    assert (tmp_path / "out" / "robustness.md").is_file()
    assert render_robustness_markdown(payload).startswith(
        "DESCRIPTIVE ROBUSTNESS CHECK\nNOT STRATEGY OPTIMIZATION\nNOT OUT-OF-SAMPLE VALIDATION"
    )
