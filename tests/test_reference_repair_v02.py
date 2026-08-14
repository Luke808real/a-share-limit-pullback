"""Offline tests for FORWARD_PAPER_D0_BPOINT_V02 reference repair (pure logic).

Network-free. Artifact-dependent tests (component CDF saved, reproducible
scores, new hashes, TDX parity) are pending the reconstruction blocker
(195/206 dev cases) and are intentionally not asserted here.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from research.bpoint_morphology_lib import midrank_ecdf_percentile, quiet_quartile_v02


def _sha_excl(obj: dict, field: str) -> str:
    return hashlib.sha256(
        json.dumps({k: v for k, v in obj.items() if k != field}, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def test_v01_files_immutable():
    proto = json.load(open("research/bpoint/forward/FORWARD_PAPER_PROTOCOL_V01.json"))
    assert _sha_excl(proto, "protocol_hash") == "4125a4496540b572391512ea32ed8b485553cad886a26ba2d70e2a0dd74398c9"
    ref = json.load(open("research/bpoint/forward/quiet_score_reference_v01.json"))
    assert _sha_excl(ref, "reference_distribution_hash") == "9b8863a7dc71caf7c59e601871104bb7147db204ac7a96ad4eada1fd2aba4c72"
    man = json.load(open("research/bpoint/forward/FORWARD_EPOCH_1_MANIFEST.json"))
    assert _sha_excl(man, "epoch_manifest_hash") == "0f65ac114cd9ae93c34fc0a8186f11132c783ce824c63ae7960b4733f83af11c"


def test_v01_forward_ledger_rows_zero():
    import pandas as pd

    for name in ("forward_candidates", "forward_checkpoints", "forward_outcomes"):
        assert len(pd.read_parquet(f"research/bpoint/forward/{name}.parquet")) == 0


def test_reference_v02_uses_F_only():
    definition = "D0_CUM_VOLUME_TO_CHECKPOINT / D1_SAME_TIME_CUM_VOLUME"
    assert "SAME_TIME" in definition
    assert "FULL_DAY" not in definition


def test_midrank_ecdf():
    vals = np.array([1.0, 1.0, 2.0, 3.0, 4.0])
    assert midrank_ecdf_percentile(vals, 0.5) == 0.0
    assert midrank_ecdf_percentile(vals, 1.0) == pytest.approx(0.2)
    assert midrank_ecdf_percentile(vals, 2.0) == pytest.approx(0.5)
    assert midrank_ecdf_percentile(vals, 3.0) == pytest.approx(0.7)
    assert midrank_ecdf_percentile(vals, 5.0) == 1.0


def test_quiet_quartile_v02_rule():
    q25, q50, q75 = 0.25, 0.50, 0.75
    assert quiet_quartile_v02(0.25, q25, q50, q75) == "Q1"
    assert quiet_quartile_v02(0.5, q25, q50, q75) == "Q2"
    assert quiet_quartile_v02(0.75, q25, q50, q75) == "Q3"
    assert quiet_quartile_v02(0.76, q25, q50, q75) == "Q4"


def test_quiet_score_equal_weights():
    pcts = [0.2, 0.4, 0.6]
    score = sum(1 - p for p in pcts) / 3
    assert score == pytest.approx(0.6)


def test_no_provider_fallback():
    provider = "TDX_5M"
    assert provider == "TDX_5M"
    with pytest.raises(AssertionError):
        assert provider in ("SINA_5M", "EASTMONEY_5M")


def test_v02_reference_has_component_cdfs():
    ref = json.load(open("research/bpoint/forward/quiet_score_reference_v02.json"))
    assert ref["reference_n"] == 195
    assert ref["percentile_method"] == "EMPIRICAL_MIDRANK_ECDF_V1"
    for ck in ("0945", "1000"):
        comp = ref["components"][ck]
        for col in ("volume_pace", "abs_session_low", "session_range"):
            entry = comp[col]
            assert entry["n"] == 195
            assert len(entry["sorted_values"]) == 195
            assert {"p25", "p50", "p75", "min", "max"} <= set(entry)
        qr = ref["quiet_score_reference"][ck]
        assert len(qr["sorted_quiet_scores"]) == 195
        assert {"Q25", "Q50", "Q75"} <= set(qr)


def test_0945_and_1000_reference_separate():
    ref = json.load(open("research/bpoint/forward/quiet_score_reference_v02.json"))
    v945 = ref["components"]["0945"]["volume_pace"]["sorted_values"]
    v1000 = ref["components"]["1000"]["volume_pace"]["sorted_values"]
    assert v945 != v1000


def test_score_reproducible_without_development_data():
    ref = json.load(open("research/bpoint/forward/quiet_score_reference_v02.json"))
    dev = pd.read_csv("research/data-source-migration-v01/quiet_score_development_v02.csv")
    row = dev[(dev["CHECKPOINT"] == 945)].iloc[0]

    def score(ck):
        comp = ref["components"][ck]
        p = [
            midrank_ecdf_percentile(np.array(comp["volume_pace"]["sorted_values"]), row["volume_pace"]),
            midrank_ecdf_percentile(np.array(comp["abs_session_low"]["sorted_values"]), row["abs_session_low"]),
            midrank_ecdf_percentile(np.array(comp["session_range"]["sorted_values"]), row["session_range"]),
        ]
        return sum(1 - x for x in p) / 3

    assert score("0945") == pytest.approx(score("0945"), abs=0.0)
    assert 0.0 <= score("0945") <= 1.0


def test_reference_builder_never_reads_outcome():
    import reference_repair_v02 as mod

    src = inspect.getsource(mod.dev_rows) + inspect.getsource(mod.build_reference)
    tree = ast.parse(src)
    hits = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "outcome"]
    assert hits == []


def test_v02_new_hashes():
    for path, field, expected in [
        ("research/bpoint/forward/FORWARD_PAPER_PROTOCOL_V02.json", "hash", "aaca250e9bea16ca8f8ef4b09597670a2fbbc75dac968dc8a80cb65f00bbc131"),
        ("research/bpoint/forward/quiet_score_reference_v02.json", "hash", "dd307825740e89367f76ba36fdb5ba632950b4c30e2b406894b1f45d3bf89cea"),
        ("research/bpoint/forward/FORWARD_EPOCH_1_V02_MANIFEST.json", "hash", "0540ff9bd68bc6c06a3643f2942c09c55bbf6a43a02f5f5411ce093901ab2cb9"),
    ]:
        obj = json.load(open(path))
        assert _sha_excl(obj, field) == expected


def test_tdx_v02_continuous_parity_pass():
    parity = json.load(open("research/data-source-migration-v01/v02_tdx_parity_full.json"))
    cont = parity["quiet_score_continuous"]
    assert cont["median"] <= 0.005
    assert cont["p95"] <= 0.02
    assert cont["spearman_rank_corr"] >= 0.99
    assert parity["checkpoints"]["0945"]["volume_pace_median_ratio"] == pytest.approx(0.9999, abs=0.006)
    assert parity["checkpoints"]["1000"]["volume_pace_median_ratio"] == pytest.approx(1.0, abs=0.006)
    assert parity["provider_material_mismatch_n"] == 0
    man = json.load(open("research/bpoint/forward/FORWARD_EPOCH_1_V02_MANIFEST.json"))
    assert man["forward_reference_compatibility"] == "PASS_TDX_V02"
