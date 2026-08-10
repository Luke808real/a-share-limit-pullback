"""Provenance regression for the R9 ASL PIT adapter (shadow rehearsal wiring)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r9_asl_pit_data_adapter_v01 as adapter  # noqa: E402


VALIDATED_PROJECT_SHA = "45d40aad8ac94076cb44e0ce852b5e9ad19bcab7"
ORIGINAL_INIT_SHA = "04bd94936587b35cae55c833627260866d025184"


def test_adapter_code_authority_is_validated_project_sha():
    assert adapter.ASL_CODE_SHA == VALIDATED_PROJECT_SHA
    assert adapter.ASL_VALIDATED_PROJECT_SHA == VALIDATED_PROJECT_SHA
    assert adapter.ASL_SOURCE_VINTAGE == f"ASL@{VALIDATED_PROJECT_SHA}"


def test_adapter_data_lineage_is_mixed_not_single_sha():
    lineage = adapter.ASL_DATA_LINEAGE
    assert "MIXED_SHARED_LAKE" in lineage
    assert ORIGINAL_INIT_SHA in lineage  # original init leg preserved
    assert VALIDATED_PROJECT_SHA in lineage
    assert lineage.count("=") >= 5  # several lineage legs, not collapsed to one


def test_revision_gate_rejects_stale_asl_code_sha():
    from datetime import date

    with pytest.raises(adapter.ASLPITAdapterBlocked):
        adapter.build_pit_factor_input(
            as_of=date(2026, 8, 7),
            candidates=(),
            candidate_state_source_hash="a" * 64,
            limit_pool_source_hash="a" * 64,
            configuration_version_hash="a" * 64,
            asl_code_sha=ORIGINAL_INIT_SHA,
        )


def test_revision_gate_accepts_validated_sha_without_backend():
    from datetime import date

    package = adapter.build_pit_factor_input(
        as_of=date(2026, 8, 7),
        candidates=(),
        candidate_state_source_hash="a" * 64,
        limit_pool_source_hash="a" * 64,
        configuration_version_hash="a" * 64,
        query_backend=None,
    )
    assert package.source_vintage == f"ASL@{VALIDATED_PROJECT_SHA}"
