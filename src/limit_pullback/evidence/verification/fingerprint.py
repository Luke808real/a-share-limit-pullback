"""Version fingerprint for formal runs (P2)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def build_version_fingerprint(
    *,
    runtime_commit: str | None,
    strategy_version: str | None,
    config_hash: str | None,
    asl_version: str | None,
    data_snapshot_id: str | None,
    universe_id: str | None,
    universe_hash: str | None,
    predecessor_generation_id: str | None,
    engine_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The architecture §97 fingerprint items, present or explicitly None."""

    return {
        "runtime_commit": runtime_commit,
        "strategy_version": strategy_version,
        "config_hash": config_hash,
        "asl_version": asl_version,
        "data_snapshot_id": data_snapshot_id,
        "universe_id": universe_id,
        "universe_hash": universe_hash,
        "predecessor_generation_id": predecessor_generation_id,
        "engine_versions": dict(engine_versions or {}),
    }


def fingerprint_hash(fingerprint: dict[str, Any]) -> str:
    """Deterministic hash of a canonical fingerprint serialization."""

    canonical = json.dumps(
        fingerprint,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["build_version_fingerprint", "fingerprint_hash"]
