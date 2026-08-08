"""R5A external benchmark contract: registry schema, PIT and fail-closed tests.

No outcome execution. Only contract-level validation.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r5a_benchmark_contract_v01 as r5a  # noqa: E402


def test_universe_frozen_at_eight():
    ids = [r["benchmark_id"] for r in r5a.REGISTRY]
    assert ids == ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"]
    assert len(r5a.REGISTRY) == 8


def test_status_enum_and_no_triple_volume():
    for r in r5a.REGISTRY:
        assert r["status"] in r5a.VALID_STATUS
    names = {r["benchmark_name"] for r in r5a.REGISTRY}
    assert "TRIPLE_VOLUME" not in names
    assert "SAN_BEI_LIANG" not in names


def test_status_matrix():
    status = {r["benchmark_id"]: r["status"] for r in r5a.REGISTRY}
    assert status["B1"] == "UNDERDEFINED"
    assert status["B2"] == "UNDERDEFINED"
    assert status["B3"] == "UNDERDEFINED"
    assert status["B4"] == "READY"
    assert status["B5"] == "READY"
    assert status["B6"] == "READY"
    assert status["B7"] == "READY"
    assert status["B8"] == "DATA_UNAVAILABLE"


def test_ready_benchmarks_pit_complete():
    for r in r5a.REGISTRY:
        if r["status"] != "READY":
            continue
        assert r["exact_rule"]
        assert r["required_fields"]
        assert r["input_window"]
        assert r["latest_allowed_date"] == "D (candidate_date)"
        assert "PIT-SAFE" in r["pit_status"]
        assert r["data_source"]
        assert r["artifact_sha"]
        assert "D+1" not in r["exact_rule"]
        assert "outcome" not in r["exact_rule"].lower()
        assert "future" not in r["exact_rule"].lower()


def test_b7_proxy_semantics():
    b7 = next(r for r in r5a.REGISTRY if r["benchmark_id"] == "B7")
    assert b7["definition_source"] == "MECHANICAL_PROXY"
    assert b7["benchmark_name"].endswith("_PROXY")
    assert "strict greater" in b7["exact_rule"]
    assert "excludes T0 and D" in b7["exact_rule"]
    assert "close_D >" in b7["exact_rule"]


def test_b8_data_unavailable_reason():
    b8 = next(r for r in r5a.REGISTRY if r["benchmark_id"] == "B8")
    assert b8["status"] == "DATA_UNAVAILABLE"
    assert b8["exact_rule"] == "NOT_RUN: no PIT-safe sector artifact"


def test_registry_validator_clean():
    assert r5a.validate_registry(r5a.REGISTRY) == []


def test_registry_validator_catches_errors():
    bad = [dict(r) for r in r5a.REGISTRY]
    bad[0]["status"] = "MAGIC"
    assert any("invalid status" in v for v in r5a.validate_registry(bad))
    bad2 = [dict(r) for r in r5a.REGISTRY]
    bad2[3]["latest_allowed_date"] = "D+5"
    assert any("latest_allowed_date" in v for v in r5a.validate_registry(bad2))


def test_artifact_sha_pins():
    assert r5a.FEATURE_SHA == r3a.EXPECTED_FEATURE_SHA256
    assert r3a.sha256_file(r3a.FEATURE_CSV) == r5a.FEATURE_SHA
    b4 = next(r for r in r5a.REGISTRY if r["benchmark_id"] == "B4")
    assert b4["artifact_sha"] == r5a.FEATURE_SHA


def test_registry_csv_deterministic(tmp_path):
    df = pd.DataFrame(r5a.REGISTRY)
    p1 = tmp_path / "r1.csv"
    p2 = tmp_path / "r2.csv"
    df.to_csv(p1, index=False)
    df.to_csv(p2, index=False)
    assert p1.read_bytes() == p2.read_bytes()
