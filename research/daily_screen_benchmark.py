"""Controlled daily-screen fast-path benchmark (research-only)."""

from __future__ import annotations

import json
import os
import resource
import sys
import time
from datetime import date
from pathlib import Path

from limit_pullback.screen.canonical import load_canonical_market
from limit_pullback.screen.runner import _digest, _git_head, run_screen
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.parquet import sha256_file


ROOT = Path("/Users/luke808/AI/V flash")
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
HARD_LIMIT = 1_800_000_000


def rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if os.uname().sysname == "Darwin" else value * 1024


def final_state_hash(output_path: str) -> str:
    import hashlib

    payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
    rows = payload.get("rows", [])
    by_code: dict[str, dict] = {}
    for row in rows:
        code = row.get("code")
        by_code[code] = row
    normalized = []
    for code in sorted(by_code):
        row = by_code[code]
        normalized.append(
            {
                key: row.get(key)
                for key in (
                    "code",
                    "trade_date",
                    "setup_stage",
                    "execution_label",
                    "anchor_date",
                    "anchor_price",
                    "support_low",
                    "support_high",
                    "support_center",
                    "invalid_price",
                    "setup_quality_score",
                    "entry_quality_score",
                    "entry_room_state",
                    "is_entry_candidate",
                    "preferred_entry",
                    "trigger_price",
                    "s1_price",
                )
            }
        )
    encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def persisted_state_hash(codes: list[str]) -> str:
    import hashlib

    normalized = []
    for code in sorted(codes):
        path = ROOT / "data/screen/states" / f"{code}.json"
        if not path.exists():
            normalized.append({"code": code, "missing": True})
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("processed_at", None)
        normalized.append({key: data.get(key) for key in sorted(data)})
    encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sample_codes(size: int) -> list[str]:
    state_dir = ROOT / "data/screen/states"
    all_codes = sorted(
        path.stem
        for path in state_dir.glob("[0-9][0-9][0-9][0-9][0-9][0-9].json")
    )
    if size >= len(all_codes):
        return all_codes
    step = (len(all_codes) - 1) / (size - 1)
    return [all_codes[round(index * step)] for index in range(size)]


def run_stage(
    *,
    label: str,
    layout: WarehouseLayout,
    codes: list[str],
    as_of: date,
    rebuild: bool,
    start: date | None = None,
) -> dict[str, object]:
    config_hash = sha256_file(ROOT / "config/strategy.yaml")
    commit = _git_head()
    kind = "rebuild" if rebuild else "incremental"
    run_id = (
        f"screen-{kind}-{as_of.isoformat()}-"
        f"{SNAPSHOT_ID[:12]}-"
        f"{_digest(start, tuple(sorted(codes)), commit, config_hash, 'formal')[:12]}"
    )
    cached_path = ROOT / "data/screen/runs" / f"{run_id}.json"
    cached_path.unlink(missing_ok=True)
    started = time.perf_counter()
    result = run_screen(
        layout=layout,
        as_of=as_of,
        snapshot_id=SNAPSHOT_ID,
        codes=codes,
        rebuild=rebuild,
        start=start,
    )
    elapsed = time.perf_counter() - started
    state_hash = persisted_state_hash(codes)
    return {
        "label": label,
        "codes": len(codes),
        "seconds": round(elapsed, 3),
        "peak_rss_bytes": rss_bytes(),
        "output_hash": result.output_hash,
        "final_state_hash": final_state_hash(result.output_path),
        "persisted_state_hash": state_hash,
        "rows_count": result.rows_count,
        "reused": result.reused,
    }


def main() -> None:
    layout = WarehouseLayout(ROOT / "data")
    results: dict[str, object] = {
        "stages": [],
        "loader": {},
        "equivalence": {},
    }
    sizes = [int(value) for value in sys.argv[1:]] or [20, 200, 500]
    for size in sizes:
        codes = sample_codes(size)
        stats: dict[str, object] = {}
        loader_started = time.perf_counter()
        market = load_canonical_market(
            layout,
            snapshot_id=SNAPSHOT_ID,
            codes=codes,
            stats=stats,
        )
        loader_seconds = time.perf_counter() - loader_started
        results["loader"][str(size)] = {
            **stats,
            "codes": len(codes),
            "load_seconds": round(loader_seconds, 3),
            "load_peak_rss_bytes": rss_bytes(),
            "universe_returned": len(market.bars_by_code),
        }
        if rss_bytes() > HARD_LIMIT:
            results["stop_reason"] = f"RSS_BUDGET_ABORTED after loader {size}"
            break
        if size == 20:
            ref_state = run_stage(
                label="rebuild_to_0730",
                layout=layout,
                codes=codes,
                as_of=date(2026, 7, 30),
                rebuild=True,
                start=date(2024, 1, 1),
            )
            fast = run_stage(
                label="incremental_0731",
                layout=layout,
                codes=codes,
                as_of=date(2026, 7, 31),
                rebuild=False,
            )
            ref_full = run_stage(
                label="rebuild_0731",
                layout=layout,
                codes=codes,
                as_of=date(2026, 7, 31),
                rebuild=True,
                start=date(2024, 1, 1),
            )
            results["stages"].extend([ref_state, fast, ref_full])
            results["equivalence"]["20"] = {
                "reference_hash": ref_full["output_hash"],
                "fast_path_hash": fast["output_hash"],
                "reference_final_state_hash": ref_full["final_state_hash"],
                "fast_path_final_state_hash": fast["final_state_hash"],
                "reference_persisted_state_hash": ref_full["persisted_state_hash"],
                "fast_path_persisted_state_hash": fast["persisted_state_hash"],
                "equal": ref_full["persisted_state_hash"] == fast["persisted_state_hash"],
            }
        else:
            fast = run_stage(
                label=f"incremental_{size}",
                layout=layout,
                codes=codes,
                as_of=date(2026, 7, 31),
                rebuild=False,
            )
            ref_full = run_stage(
                label=f"rebuild_{size}",
                layout=layout,
                codes=codes,
                as_of=date(2026, 7, 31),
                rebuild=True,
                start=date(2024, 1, 1),
            )
            results["stages"].extend([fast, ref_full])
            results["equivalence"][str(size)] = {
                "reference_hash": ref_full["output_hash"],
                "fast_path_hash": fast["output_hash"],
                "reference_final_state_hash": ref_full["final_state_hash"],
                "fast_path_final_state_hash": fast["final_state_hash"],
                "reference_persisted_state_hash": ref_full["persisted_state_hash"],
                "fast_path_persisted_state_hash": fast["persisted_state_hash"],
                "equal": ref_full["persisted_state_hash"] == fast["persisted_state_hash"],
            }
        if rss_bytes() > HARD_LIMIT:
            results["stop_reason"] = f"RSS_BUDGET_ABORTED after {size}"
            break
    results["final_peak_rss_bytes"] = rss_bytes()
    out = ROOT / "data/outcome-study/daily-screen-benchmark"
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
