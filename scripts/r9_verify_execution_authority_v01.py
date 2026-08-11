#!/usr/bin/env python3
"""Fail-closed R9 execution authority verifier (V01).

Machine-verifies that the State worktree and the R9 worktree that an R9
runner will execute against match the frozen execution authority, without
relying on agent memory or on the current PWD HEAD.

Both ``--state-worktree`` and ``--r9-worktree`` are mandatory and explicit;
the verifier never defaults either path to the current working directory.
The State worktree must be exactly at ``state_engine_sha`` with an empty
porcelain and byte-identical required blobs.  The R9 worktree may sit on the
frozen R9 code authority, on any frozen receipt descendant, or on a future
receipt descendant of ``latest_review_artifact_head``, but its required code
blobs must equal the pinned frozen blobs and the workspace must be clean.

Exit code 0 only when both gates pass; any failure exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

MANIFEST_VERSION = "R9_EXECUTION_AUTHORITY_MANIFEST_V01"


class GateError(RuntimeError):
    """A gate failure with a machine-readable reason."""


def _git(worktree: Path, *args: str) -> str:
    """Run git inside a worktree; raise GateError on failure."""
    result = subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateError(
            f"git {' '.join(args)!r} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _load_manifest(path: Path) -> dict:
    if not path.is_file():
        raise GateError(f"manifest missing: {path}")
    raw = path.read_text(encoding="utf-8")
    manifest = json.loads(raw)
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise GateError(
            f"manifest version mismatch: {manifest.get('manifest_version')!r}"
        )
    required = (
        "state_engine_sha",
        "state_required_blobs",
        "r9_protocol_sha",
        "r9_code_authority_sha",
        "r9_required_blobs",
        "latest_review_artifact_head",
    )
    missing = [key for key in required if key not in manifest]
    if missing:
        raise GateError(f"manifest missing keys: {missing}")
    return manifest


def _worktree_porcelain(worktree: Path) -> str:
    return _git(worktree, "status", "--porcelain")


def _assert_state_gate(
    worktree: Path,
    manifest: Mapping,
) -> None:
    """State authority gate: exact pinned HEAD, clean, pinned blobs."""
    head = _git(worktree, "rev-parse", "HEAD")
    if head != manifest["state_engine_sha"]:
        raise GateError(
            f"STATE_HEAD_MISMATCH: HEAD={head} "
            f"pinned={manifest['state_engine_sha']}"
        )
    porcelain = _worktree_porcelain(worktree)
    if porcelain:
        raise GateError(
            f"STATE_WORKTREE_DIRTY: porcelain non-empty "
            f"({len(porcelain.splitlines())} entries)"
        )
    for rel, pinned in manifest["state_required_blobs"].items():
        path = worktree / rel
        if not path.is_file():
            raise GateError(f"STATE_BLOB_MISMATCH: missing file {rel}")
        head_blob = _git(worktree, "rev-parse", f"HEAD:{rel}")
        worktree_blob = _git(worktree, "hash-object", str(path))
        if head_blob != pinned:
            raise GateError(
                f"STATE_BLOB_MISMATCH: HEAD blob {rel}={head_blob} "
                f"pinned={pinned}"
            )
        if worktree_blob != pinned:
            raise GateError(
                f"STATE_BLOB_MISMATCH: worktree blob {rel}={worktree_blob} "
                f"pinned={pinned}"
            )


def _is_frozen_r9_head(head: str, manifest: Mapping, worktree: Path) -> bool:
    """R9 HEAD is a frozen code/receipt commit or a receipt descendant."""
    frozen = {
        "2748d74499beddaf29c4afcaf74a92a55958d668",
        "2823ccaf3d0fc6b1f33048135c834c1b759a6a7c",
        "e86e1fc7fec0b67d0a6b8f55dfb189b1cd48626e",
        manifest["latest_review_artifact_head"],
    }
    if head in frozen:
        return True
    # Future receipt descendant: latest review head is an ancestor of HEAD.
    base = manifest["latest_review_artifact_head"]
    try:
        _git(worktree, "merge-base", "--is-ancestor", base, head)
    except GateError:
        return False
    return True


def _assert_r9_gate(
    worktree: Path,
    manifest: Mapping,
) -> None:
    """R9 authority gate: frozen-code descendant, pinned blobs, clean."""
    head = _git(worktree, "rev-parse", "HEAD")
    if not _is_frozen_r9_head(head, manifest, worktree):
        raise GateError(
            f"R9_HEAD_UNRECOGNIZED: HEAD={head} is not a frozen "
            f"R9 code/receipt head nor a receipt descendant"
        )
    porcelain = _worktree_porcelain(worktree)
    if porcelain:
        raise GateError(
            f"R9_WORKTREE_DIRTY: porcelain non-empty "
            f"({len(porcelain.splitlines())} entries)"
        )
    for rel, pinned in manifest["r9_required_blobs"].items():
        path = worktree / rel
        if not path.is_file():
            raise GateError(f"R9_BLOB_MISMATCH: missing file {rel}")
        head_blob = _git(worktree, "rev-parse", f"HEAD:{rel}")
        worktree_blob = _git(worktree, "hash-object", str(path))
        if head_blob != pinned:
            raise GateError(
                f"R9_BLOB_MISMATCH: HEAD blob {rel}={head_blob} "
                f"pinned={pinned}"
            )
        if worktree_blob != pinned:
            raise GateError(
                f"R9_BLOB_MISMATCH: worktree blob {rel}={worktree_blob} "
                f"pinned={pinned}"
            )


def verify(
    state_worktree: Path,
    r9_worktree: Path,
    manifest_path: Path,
) -> str:
    """Run both gates and return the combined verdict line."""
    manifest = _load_manifest(manifest_path)
    state_reason: str | None = None
    r9_reason: str | None = None
    try:
        _assert_state_gate(state_worktree, manifest)
    except GateError as exc:
        state_reason = str(exc)
    try:
        _assert_r9_gate(r9_worktree, manifest)
    except GateError as exc:
        r9_reason = str(exc)

    print(f"STATE_AUTHORITY_GATE={'PASS' if state_reason is None else 'FAIL'}")
    if state_reason is not None:
        print(f"STATE_AUTHORITY_GATE reason={state_reason}")
    print(f"R9_AUTHORITY_GATE={'PASS' if r9_reason is None else 'FAIL'}")
    if r9_reason is not None:
        print(f"R9_AUTHORITY_GATE reason={r9_reason}")
    verdict = (
        "PASS"
        if state_reason is None and r9_reason is None
        else "FAIL"
    )
    print(f"EXECUTION_AUTHORITY_GATE={verdict}")
    return verdict


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed R9 execution authority verifier V01"
    )
    parser.add_argument(
        "--state-worktree",
        required=True,
        help="absolute path of the State worktree (no default)",
    )
    parser.add_argument(
        "--r9-worktree",
        required=True,
        help="absolute path of the R9 worktree (no default)",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="manifest path; defaults to the manifest beside this file",
    )
    args = parser.parse_args(argv)

    if args.manifest is None:
        manifest_path = (
            Path(__file__).resolve().parent.parent
            / "research"
            / "second_launch"
            / "walk_forward_v01"
            / "r9_execution_authority_manifest_v01.json"
        )
    else:
        manifest_path = Path(args.manifest).resolve()

    state_worktree = Path(args.state_worktree).resolve()
    r9_worktree = Path(args.r9_worktree).resolve()
    if not state_worktree.is_dir():
        print("STATE_AUTHORITY_GATE=FAIL")
        print(f"STATE_AUTHORITY_GATE reason=STATE_WORKTREE_MISSING")
        return 1
    if not r9_worktree.is_dir():
        print("R9_AUTHORITY_GATE=FAIL")
        print(f"R9_AUTHORITY_GATE reason=R9_WORKTREE_MISSING")
        return 1

    verdict = verify(state_worktree, r9_worktree, manifest_path)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
