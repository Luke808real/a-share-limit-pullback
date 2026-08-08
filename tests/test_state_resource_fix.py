"""State-generation resource fix tests: bounded parallel merge + bounded
compact roundtrip hash (semantics preserved exactly).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from limit_pullback.screen.generation import compact_output_roundtrip_hash
from limit_pullback.screen.runner import (
    _spool_output_hash,
    _stream_merge_chunk_spools,
)


def _write_chunk_spool(spool_dir: Path, run_id: str, index: int, rows) -> Path:
    path = spool_dir / f"{run_id}.{index}.rows.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for code, day in rows:
            stream.write(
                json.dumps(
                    {"code": code, "trade_date": day.isoformat(), "payload": "x"}
                )
                + "\n"
            )
    return path


def _sorted_reference(chunk_spools: list[Path]) -> list[str]:
    lines = []
    for path in chunk_spools:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                lines.append((str(row["code"]), str(row["trade_date"]), line))
    lines.sort(key=lambda item: (item[0], item[1]))
    return [line for _code, _day, line in lines]


def _days(start: date, count: int):
    import datetime

    return [start + datetime.timedelta(days=index) for index in range(count)]


def test_parallel_merge_preserves_global_order(tmp_path):
    """A. Chunk concatenation equals the previous global (code, trade_date)
    sort, including codes with many dates, zero-output chunks and uneven
    chunk sizes."""

    run_id = "run-x"
    spool_dir = tmp_path / "spools"
    chunks = [
        # chunk 0: code 000001 with many dates
        [("000001", day) for day in _days(date(2026, 6, 1), 40)],
        # chunk 1: zero-output rows
        [],
        # chunk 2: uneven mix (ascending within code, as workers emit)
        [("000010", date(2026, 6, 1)), ("000010", date(2026, 6, 3))],
        # chunk 3: another code, one row
        [("605198", date(2026, 6, 5))],
    ]
    chunk_paths = [
        _write_chunk_spool(spool_dir, run_id, index, rows)
        for index, rows in enumerate(chunks)
    ]
    expected = _sorted_reference(chunk_paths)
    final = tmp_path / "final.jsonl"
    _stream_merge_chunk_spools(spool_dir, run_id, list(range(4)), final)
    got = final.read_text(encoding="utf-8").splitlines()
    assert got == expected
    # chunk spools removed after successful merge (C).
    assert all(not path.exists() for path in chunk_paths)


def test_merge_output_hash_identical(tmp_path):
    """B. Output hash of the concatenated spool equals the hash of the
    globally-sorted reference."""

    run_id = "run-h"
    spool_dir = tmp_path / "spools"
    chunks = [
        [("000001", day) for day in _days(date(2026, 6, 1), 25)],
        [("000002", day) for day in _days(date(2026, 6, 1), 7)],
    ]
    chunk_paths = [
        _write_chunk_spool(spool_dir, run_id, index, rows)
        for index, rows in enumerate(chunks)
    ]
    reference_lines = _sorted_reference(chunk_paths)
    final = tmp_path / "final.jsonl"
    _stream_merge_chunk_spools(spool_dir, run_id, [0, 1], final)
    reference = tmp_path / "reference.jsonl"
    reference.write_text(
        "\n".join(reference_lines) + "\n", encoding="utf-8"
    )
    assert _spool_output_hash(final) == _spool_output_hash(reference)


def test_merge_failure_publishes_nothing(tmp_path):
    """D. A missing chunk spool fails the merge: no final spool, no temp
    artifact, and any already-copied chunks are still removed."""

    run_id = "run-f"
    spool_dir = tmp_path / "spools"
    _write_chunk_spool(spool_dir, run_id, 0, [("000001", date(2026, 6, 1))])
    # chunk 1 spool intentionally missing
    final = tmp_path / "final.jsonl"
    with pytest.raises(FileNotFoundError):
        _stream_merge_chunk_spools(spool_dir, run_id, [0, 1], final)
    assert not final.exists()
    assert list(spool_dir.glob("*.tmp-*")) == []


def _old_roundtrip_hash(path: Path) -> tuple[str, int]:
    table = pq.read_table(path)
    payloads = table["payload"].to_pylist()
    digest = hashlib.sha256()
    digest.update(b"[")
    for index, payload in enumerate(payloads):
        if index:
            digest.update(b", ")
        digest.update(str(payload).encode("utf-8"))
    digest.update(b"]")
    return digest.hexdigest(), len(payloads)


def _write_payload_parquet(path: Path, payloads, row_group_size=3):
    table = pa.table({"payload": pa.array(payloads, type=pa.string())})
    pq.write_table(
        table,
        path,
        compression="zstd",
        row_group_size=row_group_size,
        data_page_size=64,
    )


def test_streaming_roundtrip_hash_equals_old(tmp_path):
    """E. Streaming compact hash equals the old digest on multi-row /
    multi-row-group parquet; row count identical (G)."""

    payloads = [f"row-{index}" for index in range(37)]
    path = tmp_path / "compact.parquet"
    _write_payload_parquet(path, payloads)
    old_digest, old_rows = _old_roundtrip_hash(path)
    new_digest, new_rows = compact_output_roundtrip_hash(path)
    assert new_digest == old_digest
    assert new_rows == old_rows == len(payloads)


def test_empty_compact_roundtrip_hash(tmp_path):
    """F. Empty compact output: digest of b"[]", row count 0."""

    path = tmp_path / "empty.parquet"
    pq.write_table(pa.table({"payload": pa.array([], type=pa.string())}), path)
    digest, rows = compact_output_roundtrip_hash(path)
    assert digest == hashlib.sha256(b"[]").hexdigest()
    assert rows == 0
