"""Fresh child process for one deterministic screen chunk (research/perf path)."""

from __future__ import annotations

import json
import hashlib
import os
import resource
import sys
import time
from datetime import date
from pathlib import Path

from limit_pullback.screen.runner import run_screen
from limit_pullback.warehouse.layout import WarehouseLayout


def main() -> None:
    data_root = Path(sys.argv[1])
    snapshot_id = sys.argv[2]
    as_of = date.fromisoformat(sys.argv[3])
    start = date.fromisoformat(sys.argv[4]) if sys.argv[4] != "None" else None
    config_path = Path(sys.argv[5])
    chunk_index = int(sys.argv[6])
    codes = json.loads(Path(sys.argv[7]).read_text(encoding="utf-8"))
    manifest_path = Path(sys.argv[8])
    started = time.perf_counter()
    result = run_screen(
        layout=WarehouseLayout(data_root),
        as_of=as_of,
        snapshot_id=snapshot_id,
        start=start,
        rebuild=True,
        codes=codes,
        config_path=config_path,
        manifest_path_override=manifest_path,
    )
    elapsed = time.perf_counter() - started
    rows_spool = manifest_path.with_name(manifest_path.stem + ".rows.jsonl")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with rows_spool.open("w", encoding="utf-8") as stream:
        hash_obj = hashlib.sha256()
        first_row = True
        for row in manifest.get("rows", []):
            row_text = json.dumps(row, sort_keys=True, ensure_ascii=False)
            stream.write(row_text + "\n")
            if first_row:
                hash_obj.update(b"[")
                first_row = False
            else:
                hash_obj.update(b", ")
            hash_obj.update(row_text.encode("utf-8"))
        hash_obj.update(b"]")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if os.uname().sysname != "Darwin":
        rss *= 1024
    print(
        json.dumps(
            {
                "chunk_index": chunk_index,
                "codes": len(codes),
                "rows_count": result.rows_count,
                "output_hash": result.output_hash,
                "seconds": round(elapsed, 3),
                "peak_rss_bytes": rss,
                "manifest_path": str(manifest_path),
                "rows_spool_path": str(rows_spool),
                "rows_spool_hash": hash_obj.hexdigest(),
                "status_counts": manifest.get("status_counts", {}),
                "new_anchor_count": manifest.get("new_anchor_count", 0),
                "active_setup_count": manifest.get("active_setup_count", 0),
                "entry_candidate_count": manifest.get("entry_candidate_count", 0),
                "quality_rejection_count": manifest.get("quality_rejection_count", 0),
            }
        )
    )


if __name__ == "__main__":
    main()
