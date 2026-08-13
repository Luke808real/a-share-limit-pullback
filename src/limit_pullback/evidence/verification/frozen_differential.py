"""Frozen-reference differential verifier (P1).

The full-market run artifact embeds the complete ordered row set and hashes it
twice: a per-chunk row-spool hash (`chunk_runtimes[*].child_rows_spool_hash`)
and the total ordered output hash. Because the rows ARE the emitted state and
signal records, byte-identical per-chunk hashes plus an identical total hash
mean `state diff = 0`, `signal diff = 0`, and `artifact semantic diff = 0`
between two runs over the same frozen snapshot.

The 4+ GB run JSON is never fully materialized: only the bounded summary head,
the chunk-runtime block, and the tail summary are read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HEAD_BYTES = 300_000
TAIL_BYTES = 16_384


def _balanced_json_block(text: str, key: str) -> Any:
    start = text.find(f'"{key}":')
    if start < 0:
        return None
    bracket = text.find("[", start)
    brace = text.find("{", start)
    candidates = [position for position in (bracket, brace) if position >= 0]
    if not candidates:
        return None
    cursor = min(candidates)
    opening = text[cursor]
    closing = "]" if opening == "[" else "}"
    depth = 0
    in_string = False
    escaped = False
    for index in range(cursor, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return json.loads(text[cursor : index + 1])
    return None


def _bounded_tail(path: Path) -> str:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - TAIL_BYTES))
        return handle.read().decode("utf-8", errors="replace")


def read_run_summary(path: Path) -> dict[str, Any]:
    """Extract the bounded summary of one run artifact without loading rows."""

    with path.open("rb") as handle:
        head = handle.read(HEAD_BYTES).decode("utf-8", errors="replace")
    tail = _bounded_tail(path)
    output_hash = re.search(
        r'"output_hash"\s*:\s*"([0-9a-f]{64})"',
        head + tail,
    )
    rows_count = re.search(r'"rows_count"\s*:\s*(\d+)', head + tail)
    universe_size = re.search(r'"universe_size"\s*:\s*(\d+)', head + tail)
    status_counts = _balanced_json_block(tail, "status_counts")
    chunks = _balanced_json_block(head, "chunk_runtimes")
    if chunks is None:
        chunks = _balanced_json_block(tail, "chunk_runtimes")
    return {
        "output_hash": output_hash.group(1) if output_hash else None,
        "rows_count": int(rows_count.group(1)) if rows_count else None,
        "universe_size": int(universe_size.group(1)) if universe_size else None,
        "status_counts": status_counts,
        "chunk_runtimes": chunks,
    }


def verify_against_reference(
    artifact_path: Path,
    reference: dict[str, Any],
) -> dict[str, Any]:
    """Compare one artifact summary against a frozen reference summary."""

    summary = read_run_summary(artifact_path)
    problems: list[str] = []
    for key in ("output_hash", "rows_count", "universe_size"):
        if summary[key] != reference.get(key):
            problems.append(
                f"{key} mismatch: {summary[key]} != {reference.get(key)}"
            )
    if summary["status_counts"] != reference.get("status_counts"):
        problems.append("status_counts mismatch")
    reference_chunks = reference.get("chunk_runtimes")
    current_chunks = summary["chunk_runtimes"]
    if reference_chunks and current_chunks:
        if len(reference_chunks) != len(current_chunks):
            problems.append("chunk count mismatch")
        else:
            for index, (reference_chunk, current_chunk) in enumerate(
                zip(reference_chunks, current_chunks, strict=True)
            ):
                for field in ("child_output_hash", "child_rows_spool_hash"):
                    if reference_chunk.get(field) != current_chunk.get(field):
                        problems.append(
                            f"chunk {index} {field} mismatch"
                        )
    return {
        "passed": not problems,
        "problems": problems,
        "summary": summary,
    }


__all__ = ["read_run_summary", "verify_against_reference"]
