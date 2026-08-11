"""Targeted tests for the R9 execution authority gate V01 verifier."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.r9_verify_execution_authority_v01 import (
    GateError,
    _assert_r9_gate,
    _assert_state_gate,
    _is_frozen_r9_head,
    main,
    verify,
)


STATE_SHA = "911ebc3f8e6f6d279c873bf910838c85b28763fe"
R9_CODE_SHA = "2748d74499beddaf29c4afcaf74a92a55958d668"
R9_RECEIPT_SHA = "2823ccaf3d0fc6b1f33048135c834c1b759a6a7c"
FC6_SHA = "fc6d096b26d21082903a1c1a262cbee34ee55d32"

STATE_BLOBS = {
    "src/limit_pullback/screen/canonical.py": "8d85aae14dc634d5e3ac513ddf2e9fcddfad6db0",
    "src/limit_pullback/coverage.py": "2b59c9eaf9a6382cbe6bc41222850d6379049a1c",
    "src/limit_pullback/screen/generation.py": "0cf60131f4f4bbf9fd72b374b55f02334ca079a7",
}
R9_BLOBS = {
    "research/second_launch/walk_forward_v01/r9_protocol_v02.py": "43910f4d0809cb00a87846cbdfc31f4710b86579",
    "research/second_launch/walk_forward_v01/r9_intraday_accumulator_v01.py": "960dfeebcd66f36e024756a9126f7d6af8f71d95",
    "research/second_launch/walk_forward_v01/r9_setup_accumulator_v01.py": "81128e6276c4a1cb86aa9284e98e97f96a45103a",
}


def _manifest() -> dict:
    return {
        "manifest_version": "R9_EXECUTION_AUTHORITY_MANIFEST_V01",
        "state_engine_sha": STATE_SHA,
        "state_required_blobs": dict(STATE_BLOBS),
        "r9_protocol_sha": "4d9e8fd7cdf0d3e4c631f8a970451c95f8c56aed",
        "r9_code_authority_sha": R9_CODE_SHA,
        "r9_required_blobs": dict(R9_BLOBS),
        "latest_review_artifact_head": FC6_SHA,
    }


def _write_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest(), sort_keys=True, indent=2))
    return path


def _fake_worktree(tmp_path: Path, *, state: bool = False) -> Path:
    """Create a directory tree with the required files at fake blob paths."""
    wt = tmp_path / ("state-wt" if state else "r9-wt")
    (wt / "src" / "limit_pullback" / "screen").mkdir(parents=True)
    (wt / "research" / "second_launch" / "walk_forward_v01").mkdir(parents=True)
    for rel in (STATE_BLOBS if state else R9_BLOBS):
        path = wt / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel)
    return wt


class _FakeGit:
    """Deterministic git stand-in for gate checks."""

    def __init__(
        self,
        *,
        state_head: str = STATE_SHA,
        r9_head: str = FC6_SHA,
        state_porcelain: str = "",
        r9_porcelain: str = "",
        state_blob_override: dict[str, str] | None = None,
        r9_blob_override: dict[str, str] | None = None,
        ancestor: bool = False,
    ) -> None:
        self.state_head = state_head
        self.r9_head = r9_head
        self.state_porcelain = state_porcelain
        self.r9_porcelain = r9_porcelain
        self.state_blob_override = state_blob_override or {}
        self.r9_blob_override = r9_blob_override or {}
        self.ancestor = ancestor

    def __call__(self, cwd: Path, *args: str) -> str:
        joined = " ".join(args)
        if joined == "status --porcelain":
            if cwd.name == "state-wt":
                return self.state_porcelain
            return self.r9_porcelain
        if "merge-base --is-ancestor" in joined:
            if self.ancestor:
                return ""
            raise GateError("not ancestor")
        if joined == "rev-parse HEAD":
            if cwd.name == "state-wt":
                return self.state_head
            return self.r9_head
        if joined.startswith("rev-parse HEAD:"):
            rel = joined.split("HEAD:", 1)[1]
            if cwd.name == "state-wt":
                return self.state_blob_override.get(rel, STATE_BLOBS[rel])
            return self.r9_blob_override.get(rel, R9_BLOBS[rel])
        if joined.startswith("hash-object "):
            path = Path(joined.split("hash-object ", 1)[1])
            rel = str(path.relative_to(cwd))
            if cwd.name == "state-wt":
                return STATE_BLOBS[rel]
            return R9_BLOBS[rel]
        raise AssertionError(f"unexpected git call: {joined}")


@pytest.fixture(autouse=True)
def _patch_git(monkeypatch):
    import scripts.r9_verify_execution_authority_v01 as verifier

    fake = _FakeGit()
    monkeypatch.setattr(verifier, "_git", fake)
    return fake


def _state_gate(wt: Path, manifest: dict) -> None:
    _assert_state_gate(wt, manifest)


def _r9_gate(wt: Path, manifest: dict) -> None:
    _assert_r9_gate(wt, manifest)


def test_case_a_old_state_head_fails(tmp_path, _patch_git):
    """CASE A: state worktree at old 0f08348 semantics -> FAIL."""
    _patch_git.state_head = "0f08348fd1fa7e04bdf468acc5516d6001e169b9"
    wt = _fake_worktree(tmp_path, state=True)
    with pytest.raises(GateError, match="STATE_HEAD_MISMATCH"):
        _state_gate(wt, _manifest())


def test_case_b_clean_911_state_passes(tmp_path, _patch_git):
    """CASE B: state worktree = 911 clean -> PASS."""
    wt = _fake_worktree(tmp_path, state=True)
    _state_gate(wt, _manifest())


def test_case_c_dirty_911_state_fails(tmp_path, _patch_git):
    """CASE C: 911 worktree dirty -> FAIL."""
    _patch_git.state_porcelain = " M src/limit_pullback/coverage.py"
    wt = _fake_worktree(tmp_path, state=True)
    with pytest.raises(GateError, match="STATE_WORKTREE_DIRTY"):
        _state_gate(wt, _manifest())


def test_case_d_fc6_receipt_descendant_r9_passes(tmp_path, _patch_git):
    """CASE D: R9 receipt descendant fc6 with frozen blobs -> PASS."""
    wt = _fake_worktree(tmp_path)
    _r9_gate(wt, _manifest())
    manifest = _manifest()
    assert _is_frozen_r9_head(FC6_SHA, manifest, wt)
    assert _is_frozen_r9_head(R9_RECEIPT_SHA, manifest, wt)
    assert _is_frozen_r9_head(R9_CODE_SHA, manifest, wt)


def test_case_e_modified_r9_blob_fails(tmp_path, _patch_git):
    """CASE E: one R9 frozen file working-tree modified -> FAIL."""
    _patch_git.r9_blob_override = {
        "research/second_launch/walk_forward_v01/r9_protocol_v02.py": "deadbeef" * 8,
    }
    wt = _fake_worktree(tmp_path)
    with pytest.raises(GateError, match="R9_BLOB_MISMATCH"):
        _r9_gate(wt, _manifest())


def test_case_e2_dirty_r9_worktree_fails(tmp_path, _patch_git):
    """CASE E: dirty R9 worktree -> FAIL (R9_WORKTREE_DIRTY)."""
    _patch_git.r9_porcelain = " M research/second_launch/walk_forward_v01/r9_protocol_v02.py"
    wt = _fake_worktree(tmp_path)
    with pytest.raises(GateError, match="R9_WORKTREE_DIRTY"):
        _r9_gate(wt, _manifest())


def test_case_d2_unknown_r9_head_fails(tmp_path, _patch_git):
    """R9 HEAD outside frozen set and not a descendant -> FAIL."""
    _patch_git.r9_head = "c0ffee" * 8
    _patch_git.ancestor = False
    wt = _fake_worktree(tmp_path)
    with pytest.raises(GateError, match="R9_HEAD_UNRECOGNIZED"):
        _r9_gate(wt, _manifest())


def test_case_d3_future_receipt_descendant_passes(tmp_path, _patch_git):
    """Future receipt descendant of fc6 -> PASS."""
    _patch_git.r9_head = "f00df00d" * 8
    _patch_git.ancestor = True
    wt = _fake_worktree(tmp_path)
    _r9_gate(wt, _manifest())


def test_missing_args_fail():
    """No implicit PWD: both paths must be explicit."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--state-worktree", "/tmp/whatever"])
    assert excinfo.value.code != 0


def test_state_blob_mismatch_fails(tmp_path, _patch_git):
    """State HEAD blob differs from pinned -> FAIL."""
    _patch_git.state_blob_override = {
        "src/limit_pullback/screen/generation.py": "badbad" * 8,
    }
    wt = _fake_worktree(tmp_path, state=True)
    with pytest.raises(GateError, match="STATE_BLOB_MISMATCH"):
        _state_gate(wt, _manifest())


def test_manifest_missing_keys_fails(tmp_path):
    manifest = _manifest()
    del manifest["r9_required_blobs"]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(GateError, match="manifest missing keys"):
        verify(Path("/s"), Path("/r"), path)


def test_manifest_version_mismatch_fails(tmp_path):
    manifest = _manifest()
    manifest["manifest_version"] = "WRONG"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(GateError, match="manifest version mismatch"):
        verify(Path("/s"), Path("/r"), path)
