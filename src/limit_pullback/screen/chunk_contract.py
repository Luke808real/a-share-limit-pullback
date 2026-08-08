"""PR-E: typed screen-chunk invocation contract (TD-026 hardening).

Every child is launched with an explicit, fully-typed argument list (snapshot,
as_of, codes, config, pool mode, output paths), a supported ``sys.executable
-m`` entry point, and a configurable operational timeout.  Child failures are
never silent: they land in the chunk failure registry and fail the generation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCREEN_CHUNK_TIMEOUT_SECONDS = int(
    os.environ.get(
        "LIMIT_PULLBACK_SCREEN_CHUNK_TIMEOUT_SECONDS",
        "900",
    )
)


class ChunkExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChunkInvocation:
    data_root: Path
    snapshot_id: str
    as_of: date
    start: date | None
    codes: tuple[str, ...]
    config_path: Path
    strategy_commit: str
    chunk_index: int
    codes_path: Path
    manifest_path: Path
    pool_mode: str = "formal"


@dataclass(frozen=True)
class ChunkResult:
    chunk_index: int
    exit_code: int | None
    timed_out: bool
    error: str | None
    elapsed_seconds: float

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.exit_code == 0


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_chunk_command(
    invocation: ChunkInvocation,
) -> tuple[list[str], dict[str, str]]:
    argv = [
        sys.executable,
        "-m",
        "limit_pullback.screen.chunk_child",
        str(invocation.data_root),
        invocation.snapshot_id,
        invocation.as_of.isoformat(),
        invocation.start.isoformat() if invocation.start else "None",
        str(invocation.config_path),
        invocation.strategy_commit,
        str(invocation.chunk_index),
        str(invocation.codes_path),
        str(invocation.manifest_path),
        invocation.pool_mode,
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_package_root())
    return argv, env


def run_chunk(
    invocation: ChunkInvocation,
    *,
    timeout_seconds: int = SCREEN_CHUNK_TIMEOUT_SECONDS,
) -> ChunkResult:
    argv, env = build_chunk_command(invocation)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        return ChunkResult(
            chunk_index=invocation.chunk_index,
            exit_code=completed.returncode,
            timed_out=False,
            error=(
                completed.stderr[-2000:]
                if completed.returncode != 0
                else None
            ),
            elapsed_seconds=time.perf_counter() - started,
        )
    except subprocess.TimeoutExpired as exc:
        if exc.stdout is not None and exc.stderr is not None:
            _ = exc.stdout, exc.stderr
        return ChunkResult(
            chunk_index=invocation.chunk_index,
            exit_code=None,
            timed_out=True,
            error=f"chunk timeout after {timeout_seconds}s",
            elapsed_seconds=time.perf_counter() - started,
        )
    except Exception as exc:
        return ChunkResult(
            chunk_index=invocation.chunk_index,
            exit_code=None,
            timed_out=False,
            error=f"{type(exc).__name__}: {exc}",
            elapsed_seconds=time.perf_counter() - started,
        )


class ChunkFailureRegistry:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self._records: list[dict[str, Any]] = []

    def record(
        self,
        *,
        chunk_index: int,
        invocation: ChunkInvocation,
        result: ChunkResult,
        missing_artifact: bool = False,
    ) -> dict[str, Any]:
        record = {
            "chunk_index": chunk_index,
            "snapshot_id": invocation.snapshot_id,
            "as_of": invocation.as_of.isoformat(),
            "pool_mode": invocation.pool_mode,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "missing_artifact": missing_artifact,
            "error": result.error,
            "observed_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
        }
        self._records.append(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            )
        return record

    @property
    def failure_n(self) -> int:
        return len(self._records)


def aggregate_chunk_rows(
    rows_per_chunk: Sequence[Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Merge chunks deterministically regardless of completion order."""

    merged = [dict(row) for rows in rows_per_chunk for row in rows]
    merged.sort(key=lambda row: (str(row["code"]), row["trade_date"]))
    return merged


def chunk_output_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(b"[")
    for index, row in enumerate(rows):
        if index:
            digest.update(b", ")
        text = json.dumps(
            {"code": row["code"], **row},
            sort_keys=True,
            ensure_ascii=False,
        )
        digest.update(text.encode("utf-8"))
    digest.update(b"]")
    return digest.hexdigest()
