"""R1A.4 artifact provenance freeze tests (offline, synthetic)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "outcome_v01"))

import build_second_launch_outcome_v01 as gen  # noqa: E402
from tests.test_interim_reproducible_package import (  # noqa: E402
    REPO_TMP,
    _pin_synthetic_hashes,
    _setup,
)


@pytest.fixture(autouse=True)
def _clean_repo_tmp():
    REPO_TMP.mkdir(parents=True, exist_ok=True)
    yield
    shutil.rmtree(REPO_TMP, ignore_errors=True)


def _build(tmp_path, monkeypatch):
    cases_path, feature, label, quarantine, out = _setup(tmp_path)
    _pin_synthetic_hashes(monkeypatch, feature, label)
    manifest = gen.build_interim_reproducible_package(
        case_set_path=cases_path,
        case_set_expected_sha256=None,
        case_set_expected_row_n=None,
        feature_snapshot_path=feature,
        label_snapshot_path=label,
        quarantine_path=quarantine,
        out_dir=out,
    )
    return manifest, out, feature, label


def test_manifest_paths_are_repo_relative(tmp_path, monkeypatch):
    manifest, out, *_ = _build(tmp_path, monkeypatch)
    gen.validate_manifest_paths_portable(manifest)
    assert manifest["artifact_path"].startswith("research/")
    assert manifest["quarantine_path"].startswith("research/")
    assert manifest["parent_case_set_path"].startswith("research/")
    assert "\\" not in json.dumps(manifest)


def test_absolute_quarantine_path_rejected(tmp_path, monkeypatch):
    cases_path, feature, label, _, out = _setup(tmp_path)
    _pin_synthetic_hashes(monkeypatch, feature, label)
    outside = tmp_path / "quarantine.csv"
    pd.DataFrame(
        [
            {
                "episode_id": "E:1",
                "symbol": "600000",
                "candidate_date": "2026-03-02",
                "conflict_class": "PATTERN_CHANGED",
                "quarantine_reason": "x",
                "source_forensic_artifact": "x",
            }
        ]
    ).to_csv(outside, index=False)
    with pytest.raises(RuntimeError, match="outside repo"):
        gen.build_interim_reproducible_package(
            case_set_path=cases_path,
            case_set_expected_sha256=None,
            case_set_expected_row_n=None,
            feature_snapshot_path=feature,
            label_snapshot_path=label,
            quarantine_path=outside,
            out_dir=out,
        )


def test_artifact_csv_sha_verifies(tmp_path, monkeypatch):
    manifest, out, feature, label = _build(tmp_path, monkeypatch)
    verified = gen.verify_interim_manifest_artifacts(
        manifest_path=out / "manifest_v01b_reproducible.json",
        feature_snapshot_path=feature,
        label_snapshot_path=label,
    )
    assert verified["artifact_id"] == "SECOND_LAUNCH_OUTCOME_V01B_REPRODUCIBLE"


def test_mutated_artifact_csv_fails_closed(tmp_path, monkeypatch):
    manifest, out, feature, label = _build(tmp_path, monkeypatch)
    csv_path = out / "second_launch_outcome_v01b_reproducible.csv"
    mutated = csv_path.read_bytes().replace(b"NO_LAUNCH", b"NO_LAUNCX", 1)
    csv_path.write_bytes(mutated)
    with pytest.raises(RuntimeError, match="artifact_sha256"):
        gen.verify_interim_manifest_artifacts(
            manifest_path=out / "manifest_v01b_reproducible.json",
            feature_snapshot_path=feature,
            label_snapshot_path=label,
        )


def test_mutated_quarantine_fails_closed(tmp_path, monkeypatch):
    manifest, out, feature, label = _build(tmp_path, monkeypatch)
    quarantine = out.parent / "quarantine.csv"
    quarantine.write_text(
        quarantine.read_text().replace("PATTERN_CHANGED", "OTHER", 1),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="quarantine_sha256"):
        gen.verify_interim_manifest_artifacts(
            manifest_path=out / "manifest_v01b_reproducible.json",
            feature_snapshot_path=feature,
            label_snapshot_path=label,
        )


def test_mutated_generator_fails_closed(tmp_path, monkeypatch):
    manifest, out, feature, label = _build(tmp_path, monkeypatch)
    generator_copy = tmp_path / "generator_mutated.py"
    generator_copy.write_bytes(
        (gen.REPO_ROOT / gen.GENERATOR_PATH).read_bytes() + b"\n# mutated\n"
    )
    with pytest.raises(RuntimeError, match="generator_sha256"):
        gen.verify_interim_manifest_artifacts(
            manifest_path=out / "manifest_v01b_reproducible.json",
            generator_path=generator_copy,
            feature_snapshot_path=feature,
            label_snapshot_path=label,
        )


def test_duplicate_quarantine_id_blocks(tmp_path, monkeypatch):
    cases_path, feature, label, quarantine, out = _setup(tmp_path)
    _pin_synthetic_hashes(monkeypatch, feature, label)
    dup = pd.read_csv(quarantine, dtype={"episode_id": str})
    dup = pd.concat([dup, dup.iloc[[0]]], ignore_index=True)
    dup.to_csv(quarantine, index=False)
    with pytest.raises(RuntimeError, match="duplicate episode_id"):
        gen.build_interim_reproducible_package(
            case_set_path=cases_path,
            case_set_expected_sha256=None,
            case_set_expected_row_n=None,
            feature_snapshot_path=feature,
            label_snapshot_path=label,
            quarantine_path=quarantine,
            out_dir=out,
        )


def test_null_quarantine_id_blocks(tmp_path, monkeypatch):
    cases_path, feature, label, quarantine, out = _setup(tmp_path)
    _pin_synthetic_hashes(monkeypatch, feature, label)
    nulled = pd.read_csv(quarantine, dtype={"episode_id": str})
    nulled.loc[0, "episode_id"] = ""
    nulled.to_csv(quarantine, index=False)
    with pytest.raises(RuntimeError, match="null episode_id"):
        gen.build_interim_reproducible_package(
            case_set_path=cases_path,
            case_set_expected_sha256=None,
            case_set_expected_row_n=None,
            feature_snapshot_path=feature,
            label_snapshot_path=label,
            quarantine_path=quarantine,
            out_dir=out,
        )
