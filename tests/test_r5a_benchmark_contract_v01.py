"""R5A external benchmark contract: registry schema, PIT and fail-closed tests.

No outcome execution. Only contract-level validation.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402
import r5a_benchmark_contract_v01 as r5a  # noqa: E402


pytestmark = pytest.mark.cloud_ci


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


def test_definition_source_semantics():
    """PROJECT_DOCUMENTED requires an explicit mechanical rule; B1/B2/B3 have
    names only -> definition_source must be UNDERDEFINED."""
    src = {r["benchmark_id"]: r["definition_source"] for r in r5a.REGISTRY}
    assert src["B1"] == "UNDERDEFINED"
    assert src["B2"] == "UNDERDEFINED"
    assert src["B3"] == "UNDERDEFINED"
    assert src["B4"] == "PROJECT_FROZEN"
    assert src["B5"] == "PROJECT_FROZEN"
    assert src["B6"] == "PROJECT_FROZEN"
    assert src["B7"] == "MECHANICAL_PROXY"
    for bid in ("B1", "B2", "B3"):
        r = next(x for x in r5a.REGISTRY if x["benchmark_id"] == bid)
        assert "name/listing source = project research plan" in r["exact_rule"]
        assert r["status"] == "UNDERDEFINED"


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


def test_b7_frozen_history_semantics():
    """B7 must fully reuse the frozen PRE_ANCHOR_LEFT_HIGH helper: no
    min-history gate, no CA filtering, NO_REFERENCE only when empty."""
    b7 = next(r for r in r5a.REGISTRY if r["benchmark_id"] == "B7")
    assert b7["status"] == "READY"
    assert "min(60, available)" in b7["exact_rule"]
    assert "no min-history gate" in b7["exact_rule"]
    assert "20~59" in b7["exact_rule"]
    assert "no CA filtering" in b7["exact_rule"]
    assert "NO_REFERENCE" in b7["missing_semantics"]
    assert "PRE_ANCHOR_LEFT_HIGH" in b7["exact_rule"]


def test_b8_data_unavailable_reason():
    b8 = next(r for r in r5a.REGISTRY if r["benchmark_id"] == "B8")
    assert b8["status"] == "DATA_UNAVAILABLE"
    assert b8["definition_source"] == "UNDERDEFINED"


def test_b8_two_independent_limits():
    """B8 has two independent limits: DEFINITION=UNDERDEFINED and
    DATA=DATA_UNAVAILABLE; no mechanical rule was invented."""
    b8 = next(r for r in r5a.REGISTRY if r["benchmark_id"] == "B8")
    assert "DEFINITION=UNDERDEFINED" in b8["exact_rule"]
    assert "DATA=DATA_UNAVAILABLE" in b8["exact_rule"]
    assert "no mechanical rule" in b8["exact_rule"]
    assert "name/listing source = project research plan" in b8["exact_rule"]
    # no invented concrete thresholds / formulas / cutoffs
    assert "0." not in b8["exact_rule"]
    assert ">=" not in b8["exact_rule"]
    assert "top " not in b8["exact_rule"].lower()
    assert "UNDERDEFINED" in b8["known_limitation"]
    assert "DATA_UNAVAILABLE" in b8["known_limitation"]


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


# ---- outcome-blind input gate ----


def test_outcome_read_usecols_guard():
    assert r5a.OUTCOME_IDENTITY_COLUMNS == [
        "episode_id", "anchor_date", "candidate_date", "symbol",
        "feature_snapshot_id",
    ]
    forbidden = {
        "outcome_3d", "outcome_5d", "SUCCESS", "FAILED_BREAKOUT",
        "NO_LAUNCH", "STRUCTURE_FAIL", "MFE", "MAE", "days_to_launch",
    }
    assert not (forbidden & set(r5a.OUTCOME_IDENTITY_COLUMNS))


@pytest.mark.local_data
def test_blind_gate_positive():
    # Hashes the 198MB local canonical snapshot -> Mac-local data gate only.
    r5a.blind_input_gate()  # real frozen files: SHA + 8,682 + 1:1 + binding


def _write_frame(tmp_path, name, df):
    p = tmp_path / name
    df.to_csv(p, index=False)
    return p


def _blind_gate_files(tmp_path, feature_df, outcome_df):
    fp = _write_frame(tmp_path, "feature.csv", feature_df)
    op = _write_frame(tmp_path, "outcome.csv", outcome_df)
    snap = _write_frame(tmp_path, "snap.csv", pd.DataFrame({"x": [1]}))
    return {
        "feature_csv": fp, "outcome_csv": op,
        "expected_feature_sha": r5a.r3a.sha256_file(fp),
        "expected_outcome_sha": r5a.r3a.sha256_file(op),
        "expected_snapshot_id": "snap-x",
        "canonical_snapshot": snap,
        "expected_snapshot_sha": r5a.r3a.sha256_file(snap),
        "expected_rows": 1,
    }


def _ident_df(episodes, anchor="2024-07-01"):
    return pd.DataFrame({
        "episode_id": episodes,
        "anchor_date": [anchor] * len(episodes),
        "candidate_date": ["2024-07-03"] * len(episodes),
        "symbol": ["600000"] * len(episodes),
        "feature_snapshot_id": ["snap-x"] * len(episodes),
    })


def test_blind_feature_sha_mismatch(tmp_path):
    kwargs = _blind_gate_files(
        tmp_path, _ident_df(["e1"]), _ident_df(["e1"])
    )
    kwargs["expected_feature_sha"] = "0" * 64
    with pytest.raises(RuntimeError, match="feature CSV SHA mismatch"):
        r5a.blind_input_gate(**kwargs)


def test_blind_outcome_sha_mismatch(tmp_path):
    kwargs = _blind_gate_files(
        tmp_path, _ident_df(["e1"]), _ident_df(["e1"])
    )
    kwargs["expected_outcome_sha"] = "0" * 64
    with pytest.raises(RuntimeError, match="outcome CSV SHA mismatch"):
        r5a.blind_input_gate(**kwargs)


def test_blind_episode_set_mismatch(tmp_path):
    kwargs = _blind_gate_files(
        tmp_path, _ident_df(["e1"]), _ident_df(["e2"])
    )
    with pytest.raises(RuntimeError, match="not 1:1 exact"):
        r5a.blind_input_gate(**kwargs)


def test_blind_identity_binding_mismatch(tmp_path):
    out_df = _ident_df(["e1"])
    out_df.loc[0, "anchor_date"] = "2024-07-02"
    kwargs = _blind_gate_files(tmp_path, _ident_df(["e1"]), out_df)
    with pytest.raises(RuntimeError, match="identity binding mismatch"):
        r5a.blind_input_gate(**kwargs)


def test_blind_snapshot_binding_mismatch(tmp_path):
    out_df = _ident_df(["e1"])
    out_df.loc[0, "feature_snapshot_id"] = "snap-wrong"
    kwargs = _blind_gate_files(tmp_path, _ident_df(["e1"]), out_df)
    with pytest.raises(RuntimeError, match="feature_snapshot_id binding"):
        r5a.blind_input_gate(**kwargs)


def test_blind_canonical_snapshot_sha_mismatch(tmp_path):
    kwargs = _blind_gate_files(
        tmp_path, _ident_df(["e1"]), _ident_df(["e1"])
    )
    kwargs["expected_snapshot_sha"] = "0" * 64
    with pytest.raises(RuntimeError, match="canonical snapshot SHA mismatch"):
        r5a.blind_input_gate(**kwargs)


# ---- main() fail-closed path ----


def test_main_calls_blind_gate_before_registry_write(tmp_path, monkeypatch):
    calls: list[str] = []
    real_gate = r5a.blind_input_gate

    def spy_gate():
        calls.append("gate")
        return real_gate()

    monkeypatch.setattr(r5a, "OUT_REGISTRY", tmp_path / "r5a_registry.csv")
    monkeypatch.setattr(r5a, "blind_input_gate", spy_gate)
    r5a.main()
    assert calls == ["gate"]
    assert (tmp_path / "r5a_registry.csv").exists()


def test_blind_gate_failure_prevents_registry_write(tmp_path, monkeypatch):
    out = tmp_path / "r5a_registry.csv"

    def boom():
        raise RuntimeError("blind gate failed (fail closed)")

    monkeypatch.setattr(r5a, "OUT_REGISTRY", out)
    monkeypatch.setattr(r5a, "blind_input_gate", boom)
    with pytest.raises(RuntimeError, match="blind gate failed"):
        r5a.main()
    assert not out.exists()
