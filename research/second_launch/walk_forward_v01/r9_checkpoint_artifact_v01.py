"""Minimal immutable R9 intraday checkpoint artifact (append-only by design).

The artifact is a deterministic JSON file plus its SHA-256 receipt.  The
normal R9 flow must never overwrite an existing artifact for the same
``target_session`` and ``symbol_set``: ``create_checkpoint_artifact`` refuses
to replace one (append-only), so a persisted checkpoint is trustworthy
evidence that a 10:30 capture existed before the session continued.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


CHECKPOINT_TIME = time(10, 30)
R9_EVENT_TIMEZONE = "Asia/Shanghai"


class CheckpointArtifactError(RuntimeError):
    """A checkpoint artifact cannot be created or read safely."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def source_data_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    """Deterministic SHA-256 over the raw bar rows fed into the checkpoint."""
    payload = json.dumps(
        [dict(sorted(row.items(), key=lambda item: str(item[0]))) for row in rows],
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def artifact_hash(payload: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical artifact payload (sorted JSON)."""
    canonical = json.dumps(
        payload, sort_keys=True, default=str, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_checkpoint_artifact(
    *,
    target_session: date,
    symbol_set: Sequence[str],
    bars: Sequence[Mapping[str, Any]],
    source: str,
    source_data_hash: str,
    asl_project_sha: str,
    r9_head: str,
    protocol_freeze: str,
    out_path: Path,
    created_at: datetime | None = None,
) -> Path:
    """Write one immutable checkpoint artifact; refuse to overwrite it.

    ``max_bar_time`` must be on or before 10:30 (right-labelled 5m bars),
    enforced here so a post-checkpoint capture cannot be mislabeled.
    """
    out_path = Path(out_path)
    if out_path.exists():
        raise CheckpointArtifactError(
            f"checkpoint artifact already exists (append-only): {out_path}"
        )
    max_bar_time = max((row["bar_time"] for row in bars), default=None)
    if max_bar_time is not None:
        if isinstance(max_bar_time, str):
            max_bar_time = time.fromisoformat(max_bar_time)
        elif hasattr(max_bar_time, "time"):  # datetime / pandas Timestamp
            max_bar_time = max_bar_time.time()
        if max_bar_time > CHECKPOINT_TIME:
            raise CheckpointArtifactError(
                f"max_bar_time {max_bar_time} > checkpoint 10:30"
            )
    payload: dict[str, Any] = {
        "kind": "r9_checkpoint_artifact_v01",
        "target_session": target_session.isoformat(),
        "checkpoint_time": CHECKPOINT_TIME.isoformat(),
        "created_at": (created_at or _utcnow()).isoformat(),
        "max_bar_time": max_bar_time.isoformat() if max_bar_time is not None else None,
        "symbol_set": sorted(symbol_set),
        "bar_n": len(bars),
        "source": source,
        "source_data_hash": source_data_hash,
        "ASL_PROJECT_SHA": asl_project_sha,
        "R9_HEAD": r9_head,
        "protocol_freeze": protocol_freeze,
    }
    payload["artifact_hash"] = artifact_hash(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return out_path


def load_checkpoint_artifact(path: Path) -> dict[str, Any]:
    """Load and verify an artifact's self-hash."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    stored = payload.get("artifact_hash")
    recomputed = artifact_hash({k: v for k, v in payload.items() if k != "artifact_hash"})
    if stored is None or stored != recomputed:
        raise CheckpointArtifactError(f"artifact hash mismatch: {path}")
    return payload
