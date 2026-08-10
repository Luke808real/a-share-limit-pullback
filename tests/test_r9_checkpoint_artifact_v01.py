"""Immutable R9 checkpoint artifact contract tests."""

from __future__ import annotations

import sys
from datetime import date, time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))

import r9_checkpoint_artifact_v01 as checkpoint  # noqa: E402


def _bars(*times: str) -> list[dict]:
    return [{"bar_time": time.fromisoformat(t), "high": 10.0, "low": 9.0} for t in times]


def test_artifact_requires_max_bar_time_on_or_before_1030(tmp_path):
    with pytest.raises(checkpoint.CheckpointArtifactError):
        checkpoint.create_checkpoint_artifact(
            target_session=date(2026, 8, 10),
            symbol_set=["600000.SH"],
            bars=_bars("10:35"),  # post-checkpoint -> refused
            source="test",
            source_data_hash="h",
            asl_project_sha="a" * 64,
            r9_head="r" * 64,
            protocol_freeze="r9-protocol-freeze-v04",
            out_path=tmp_path / "cp.json",
        )


def test_artifact_is_append_only_and_self_verifying(tmp_path):
    path = checkpoint.create_checkpoint_artifact(
        target_session=date(2026, 8, 10),
        symbol_set=["600000.SH"],
        bars=_bars("10:30"),
        source="test",
        source_data_hash="h",
        asl_project_sha="a" * 64,
        r9_head="r" * 64,
        protocol_freeze="r9-protocol-freeze-v04",
        out_path=tmp_path / "cp.json",
    )
    payload = checkpoint.load_checkpoint_artifact(path)
    assert payload["checkpoint_time"] == "10:30:00"
    assert payload["max_bar_time"] == "10:30:00"
    assert payload["target_session"] == "2026-08-10"

    # Append-only: a second creation for the same path must refuse.
    with pytest.raises(checkpoint.CheckpointArtifactError):
        checkpoint.create_checkpoint_artifact(
            target_session=date(2026, 8, 10),
            symbol_set=["600000.SH"],
            bars=_bars("10:30"),
            source="test",
            source_data_hash="h",
            asl_project_sha="a" * 64,
            r9_head="r" * 64,
            protocol_freeze="r9-protocol-freeze-v04",
            out_path=path,
        )


def test_tampered_artifact_fails_verification(tmp_path):
    path = checkpoint.create_checkpoint_artifact(
        target_session=date(2026, 8, 10),
        symbol_set=["600000.SH"],
        bars=_bars("10:30"),
        source="test",
        source_data_hash="h",
        asl_project_sha="a" * 64,
        r9_head="r" * 64,
        protocol_freeze="r9-protocol-freeze-v04",
        out_path=tmp_path / "cp.json",
    )
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("2026-08-10", "2026-08-11"), encoding="utf-8")
    with pytest.raises(checkpoint.CheckpointArtifactError):
        checkpoint.load_checkpoint_artifact(path)
