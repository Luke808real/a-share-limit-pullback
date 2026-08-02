from __future__ import annotations

from decimal import Decimal
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from limit_pullback.diagnosis import (
    analyze_episodes,
    render_diagnosis_markdown,
    run_diagnosis,
    verify_episode_artifact,
)


def _row(
    *,
    stage: str = "B2_READY",
    actionable: bool = True,
    setup_quality: str = "75",
    entry_quality: str = "75",
    room: str = "SUFFICIENT",
    outcome: str = "WIN_S1",
    r: str = "2.00",
    conservative_r: str = "2.00",
    signal_days: int = 1,
) -> dict[str, object]:
    return {
        "setup_stage": stage,
        "is_entry_candidate": actionable,
        "setup_quality_score": setup_quality,
        "entry_quality_score": entry_quality,
        "entry_room_state": room,
        "days_since_anchor": 2,
        "preferred_entry": "10.00",
        "invalid_price": "9.50",
        "s1_price": "11.00",
        "fill_status": "FILLED",
        "outcome": outcome,
        "r_multiple": r,
        "conservative_r_multiple": conservative_r,
        "mfe_pct": "0.0500",
        "mae_pct": "-0.0100",
        "raw_signal_days": signal_days,
        "quality_flags": json.dumps(["MISSING_SCORE_FIELD:test"]),
        "eligibility_reason": None,
        "pattern_1d": "S1_BEFORE_INVALID",
        "pattern_3d": "S1_BEFORE_INVALID",
        "pattern_5d": "NEITHER",
        "pattern_10d": "NEITHER",
    }


def test_actionable_and_non_actionable_b2_ready_are_separate():
    rows = [
        _row(actionable=True),
        _row(actionable=False, room="NONE"),
        _row(actionable=False, outcome="LOSS_INVALID", r="-1.00", conservative_r="-1.00"),
    ]

    result = analyze_episodes(rows)
    split = result["b2_ready_actionable_vs_non_actionable"]

    assert split["ACTIONABLE"]["stats"]["episodes"] == 1
    assert split["NON_ACTIONABLE"]["stats"]["episodes"] == 2
    assert split["NON_ACTIONABLE"]["entry_room_distribution"]["NONE"] == 1
    assert result["b2_ready_structural_reference"]["episodes"] == 3


def test_stage_bucket_counts_and_empty_bucket_are_deterministic():
    rows = [
        _row(stage="B1_READY", setup_quality="55"),
        _row(stage="B2_READY", setup_quality="85"),
    ]

    result = analyze_episodes(rows)
    grid = result["stage_setup_quality"]

    assert grid["B1_READY"]["<60"]["episodes"] == 1
    assert grid["B2_READY"][">=80"]["episodes"] == 1
    assert grid["B1_READY"]["60-70"]["episodes"] == 0
    assert grid["B1_READY"]["60-70"]["sample_flags"] == [
        "SMALL_SAMPLE",
        "LOW_CONFIDENCE",
    ]


def test_expectancy_decomposition_matches_stats():
    rows = [
        _row(r="2.00", conservative_r="2.00"),
        _row(r="2.00", conservative_r="2.00"),
        _row(outcome="LOSS_INVALID", r="-1.00", conservative_r="-1.00"),
        _row(outcome="LOSS_INVALID", r="-1.00", conservative_r="-1.00"),
        _row(outcome="LOSS_INVALID", r="-1.00", conservative_r="-1.00"),
    ]

    result = analyze_episodes(rows)
    cell = result["expectancy_decomposition"]["stage"]["B2_READY"]

    assert cell["win_rate"] == "0.4000"
    assert cell["loss_rate"] == "0.6000"
    assert cell["win_contribution"] == "0.8000"
    assert cell["loss_contribution"] == "0.6000"
    assert cell["expectancy_R"] == "0.2000"
    assert cell["diagnosis"] == "NONE"


def test_sample_size_flags_cover_boundaries():
    def loss_rows(count: int) -> list[dict[str, object]]:
        return [
            _row(outcome="LOSS_INVALID", r="-1.00", conservative_r="-1.00")
            for _ in range(count)
        ]

    small = analyze_episodes(loss_rows(29))
    low = analyze_episodes(loss_rows(30))
    adequate = analyze_episodes(loss_rows(100))

    assert small["expectancy_decomposition"]["stage"]["B2_READY"]["sample_flags"] == [
        "SMALL_SAMPLE",
        "LOW_CONFIDENCE",
    ]
    assert low["expectancy_decomposition"]["stage"]["B2_READY"]["sample_flags"] == [
        "LOW_CONFIDENCE"
    ]
    assert adequate["expectancy_decomposition"]["stage"]["B2_READY"]["sample_flags"] == []


def test_diagnosis_payload_and_markdown_are_deterministic():
    rows = [_row(), _row(stage="B1_READY", setup_quality="65")]

    first = analyze_episodes(rows, artifact_sha256="hash")
    second = analyze_episodes(rows, artifact_sha256="hash")

    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert render_diagnosis_markdown(first) == render_diagnosis_markdown(second)
    assert render_diagnosis_markdown(first).startswith(
        "DESCRIPTIVE DIAGNOSIS ONLY\n\nNOT STRATEGY OPTIMIZATION"
    )


def test_baseline_episode_hash_verification(tmp_path):
    path = tmp_path / "episodes.parquet"
    path.write_bytes(b"frozen-episodes")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()

    assert verify_episode_artifact(path, expected_sha256=expected) == expected
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_episode_artifact(path, expected_sha256="0" * 64)


def test_run_diagnosis_writes_json_and_markdown(tmp_path):
    source = tmp_path / "episodes.parquet"
    table = pa.Table.from_pylist([_row()])
    pq.write_table(table, source)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()

    payload = run_diagnosis(
        source,
        output_dir=tmp_path / "diagnosis",
        expected_sha256=expected,
    )

    json_path = tmp_path / "diagnosis" / "diagnosis.json"
    markdown_path = tmp_path / "diagnosis" / "diagnosis.md"
    assert json_path.is_file()
    assert markdown_path.is_file()
    assert payload["artifact"]["sha256"] == expected
    assert json.loads(json_path.read_text())["output_files"]["diagnosis_json"] == str(
        json_path
    )
    assert json.loads(json_path.read_text())["diagnosis_mode"] == (
        "DESCRIPTIVE DIAGNOSIS ONLY"
    )
    assert markdown_path.read_text().startswith(
        "DESCRIPTIVE DIAGNOSIS ONLY\n\nNOT STRATEGY OPTIMIZATION"
    )
