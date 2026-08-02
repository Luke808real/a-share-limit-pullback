"""Process-isolated sequential chunk execution for cold rebuild (perf path)."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from limit_pullback.screen.canonical import (
    canonical_universe_codes,
    load_canonical_metadata,
)
from limit_pullback.screen.runner import _digest, _git_head
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.parquet import sha256_file


CHUNK_SIZE = 200


def _chunked_run_id(
    *,
    as_of: date,
    snapshot_id: str,
    start: date | None,
    commit: str,
    config_hash: str,
    pool_mode: str,
    codes: Sequence[str] | None,
) -> str:
    """Logical run identity; chunk size / chunk count must not enter here."""

    requested = tuple(sorted({code.zfill(6) for code in (codes or ())}))
    return (
        f"screen-rebuild-{as_of.isoformat()}-{snapshot_id[:12]}-"
        f"{_digest(start, requested, commit, config_hash, pool_mode)[:12]}"
    )


def chunk_codes(universe, chunk_size: int):
    return [
        list(universe[index : index + chunk_size])
        for index in range(0, len(universe), chunk_size)
    ]


def rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if os.uname().sysname == "Darwin" else value * 1024


def _parent_peak_sampler(peak: dict[str, int], stop: threading.Event) -> None:
    pid = os.getpid()
    while not stop.is_set():
        try:
            out = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(pid)],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            ).stdout.strip()
            if out:
                peak["value"] = max(peak["value"], int(out) * 1024)
        except Exception:
            pass
        time.sleep(0.2)


def _parent_rss() -> int:
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        ).stdout.strip()
        return int(out) * 1024 if out else 0
    except Exception:
        return 0


def run_chunked_screen(
    *,
    layout: WarehouseLayout,
    as_of: date,
    snapshot_id: str | None = None,
    start: date,
    config_path: Path,
    chunk_size: int = CHUNK_SIZE,
    pool_mode: str = "formal",
    codes: Sequence[str] | None = None,
) -> dict[str, Any]:
    snapshot, _, _ = load_canonical_metadata(
        layout,
        snapshot_id=snapshot_id,
        as_of=None if snapshot_id else as_of,
    )
    resolved_snapshot_id = snapshot.snapshot_id
    universe = (
        tuple(sorted(codes))
        if codes is not None
        else canonical_universe_codes(layout, snapshot)
    )
    if not universe:
        raise ValueError("NO_CONFIRMED_DATA: snapshot has no CONFIRMED daily bars")
    chunks = chunk_codes(universe, chunk_size)
    config_hash = sha256_file(config_path)
    commit = _git_head()
    run_id = _chunked_run_id(
        as_of=as_of,
        snapshot_id=resolved_snapshot_id,
        start=start,
        commit=commit,
        config_hash=config_hash,
        pool_mode=pool_mode,
        codes=codes,
    )
    temp_root = layout.root / "tmp" / "screen-chunks" / run_id
    temp_root.mkdir(parents=True, exist_ok=True)
    spool_path = temp_root / "merged.rows.jsonl"
    status_counts: dict[str, int] = {}
    new_anchors = 0
    active = 0
    entry_candidates = 0
    quality_rejections = 0
    rows_count = 0
    max_child_rss = 0
    chunk_runtimes = []
    hash_obj = hashlib.sha256()
    first_row = True
    parent_peak: dict[str, int] = {"value": 0}
    sampler_stop = threading.Event()
    sampler = threading.Thread(
        target=_parent_peak_sampler,
        args=(parent_peak, sampler_stop),
        daemon=True,
    )
    sampler.start()
    try:
        with spool_path.open("w", encoding="utf-8") as spool:
            for index, codes in enumerate(chunks):
                codes_path = temp_root / f"codes-{index:03d}.json"
                manifest_path = temp_root / f"manifest-{index:03d}.json"
                codes_path.write_text(json.dumps(codes), encoding="utf-8")
                started = time.perf_counter()
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "limit_pullback.screen.chunk_child",
                        str(layout.root),
                        resolved_snapshot_id,
                        as_of.isoformat(),
                        start.isoformat(),
                        str(config_path),
                        str(commit),
                        str(index),
                        str(codes_path),
                        str(manifest_path),
                    ],
                    capture_output=True,
                    text=True,
                    env={
                        **os.environ,
                        "PYTHONPATH": str(
                            Path(__file__).resolve().parents[2] / "src"
                        ),
                    },
                    check=False,
                )
                elapsed = time.perf_counter() - started
                if proc.returncode != 0 or not manifest_path.exists():
                    raise RuntimeError(
                        f"chunk {index} failed: {proc.stderr[-1000:]}"
                    )
                child = json.loads(proc.stdout.strip().splitlines()[-1])
                max_child_rss = max(max_child_rss, int(child.get("peak_rss_bytes") or 0))
                chunk_runtimes.append(
                    {
                        "chunk": index,
                        "codes": len(codes),
                        "seconds": round(elapsed, 3),
                        "parent_rss_after": _parent_rss(),
                        "child_output_hash": child.get("output_hash"),
                        "child_rows_spool_hash": child.get("rows_spool_hash"),
                    }
                )
                rows_spool = Path(child["rows_spool_path"])
                if not rows_spool.exists():
                    raise RuntimeError(f"chunk {index} rows spool missing")
                for key, value in (child.get("status_counts") or {}).items():
                    status_counts[key] = status_counts.get(key, 0) + value
                new_anchors += int(child.get("new_anchor_count") or 0)
                active += int(child.get("active_setup_count") or 0)
                entry_candidates += int(child.get("entry_candidate_count") or 0)
                quality_rejections += int(child.get("quality_rejection_count") or 0)
                with rows_spool.open("r", encoding="utf-8") as rows_stream:
                    for line in rows_stream:
                        line = line.strip()
                        if not line:
                            continue
                        row = json.loads(line)
                        row_text = json.dumps(row, sort_keys=True, ensure_ascii=False)
                        spool.write(row_text + "\n")
                        if first_row:
                            hash_obj.update(b"[")
                            first_row = False
                        else:
                            hash_obj.update(b", ")
                        hash_obj.update(row_text.encode("utf-8"))
                        rows_count += 1
        hash_obj.update(b"]")
        output_hash = hash_obj.hexdigest()
        manifest_meta = {
            "run_id": run_id,
            "kind": "rebuild",
            "as_of": as_of.isoformat(),
            "start": start.isoformat(),
            "snapshot_id": resolved_snapshot_id,
            "strategy_commit": commit,
            "config_hash": config_hash,
            "dataset_snapshot_id": resolved_snapshot_id,
            "output_hash": output_hash,
            "rows_count": rows_count,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status_counts": dict(sorted(status_counts.items())),
            "new_anchor_count": new_anchors,
            "active_setup_count": active,
            "entry_candidate_count": entry_candidates,
            "quality_rejection_count": quality_rejections,
            "verify_replay_matched": None,
            "pool_mode": pool_mode,
            "notes": [
                f"CHUNKED_MODE:CHUNK_SIZE={chunk_size}",
                f"CHUNK_COUNT={len(chunks)}",
            ],
            "universe_size": len(universe),
            "codes": universe,
        }
        final_path = layout.root / "screen" / "runs" / f"{run_id}.json"
        from limit_pullback.screen.runner import _write_streaming_manifest

        _write_streaming_manifest(
            metadata_with_rows=manifest_meta,
            spool_path=spool_path,
            output_path=final_path,
        )
        return {
            "run_id": run_id,
            "output_path": str(final_path),
            "output_hash": output_hash,
            "rows_count": rows_count,
            "universe_size": len(universe),
            "chunk_count": len(chunks),
            "chunk_size": chunk_size,
            "chunk_runtimes": chunk_runtimes,
            "parent_peak_rss_bytes": parent_peak["value"],
            "max_child_peak_rss_bytes": max_child_rss,
        }
    finally:
        import shutil

        sampler_stop.set()
        sampler.join(timeout=1)
        shutil.rmtree(temp_root, ignore_errors=True)
