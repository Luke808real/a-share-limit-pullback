"""Cold strategy rebuild compute profile v0.1 (research-only)."""

from __future__ import annotations

import cProfile
import hashlib
import io
import json
import os
import pstats
import resource
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

from limit_pullback.screen.runner import _digest, _git_head, run_screen
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.parquet import sha256_file


ROOT = Path("/Users/luke808/AI/V flash")
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
HARD_LIMIT = 1_800_000_000
SAMPLE = [
    "000001",
    "000610",
    "000890",
    "001365",
    "002152",
    "002327",
    "002513",
    "002690",
    "002881",
    "600025",
    "600250",
    "600495",
    "600703",
    "600906",
    "601512",
    "603061",
    "603273",
    "603596",
    "603900",
    "605599",
]
PHASES = [
    "A_canonical_load",
    "B_market_normalization",
    "C_state_initialization",
    "D_prefix_provenance_hashing",
    "E_strategy_evaluation",
    "F_indicator_rolling",
    "G_candidate_setup_construction",
    "H_state_serialization_persist",
    "I_run_artifact_generation",
    "J_other",
]


def rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if os.uname().sysname == "Darwin" else value * 1024


def _current_rss_bytes(pid: int) -> int | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        value = result.stdout.strip()
        return int(value) * 1024 if value else None
    except Exception:
        return None


def _watchdog() -> None:
    pid = os.getpid()
    while True:
        rss = _current_rss_bytes(pid)
        if rss is not None and rss > HARD_LIMIT:
            print(json.dumps({"abort": "RSS_BUDGET_ABORTED", "rss_bytes": rss}))
            os._exit(99)
        time.sleep(0.5)


def _wrap(module, name: str, phase: str, timings: dict, counters: dict) -> None:
    original = getattr(module, name)
    timings.setdefault(phase, 0.0)

    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            timings[phase] += time.perf_counter() - started

    wrapper.__name__ = f"wrapped_{name}"
    setattr(module, name, wrapper)


def main() -> None:
    watchdog = threading.Thread(target=_watchdog, daemon=True)
    watchdog.start()
    import limit_pullback.screen.canonical as canonical_mod
    import limit_pullback.screen.engine as engine_mod
    import limit_pullback.screen.runner as runner_mod
    import limit_pullback.screen.state as state_mod
    import limit_pullback.strategy.engine as strategy_engine
    import limit_pullback.strategy.math as math_mod
    import limit_pullback.warehouse.parquet as parquet_mod

    timings: dict[str, float] = {phase: 0.0 for phase in PHASES}
    counters: dict[str, int] = {"evaluate_strategy_calls": 0}
    original_evaluate = strategy_engine.evaluate_strategy

    def evaluate_wrapper(*args, **kwargs):
        counters["evaluate_strategy_calls"] += 1
        return original_evaluate(*args, **kwargs)

    strategy_engine.evaluate_strategy = evaluate_wrapper
    if hasattr(engine_mod, "evaluate_strategy"):
        engine_mod.evaluate_strategy = evaluate_wrapper

    _wrap(runner_mod, "load_canonical_market", "A_canonical_load", timings, counters)
    _wrap(canonical_mod, "load_canonical_market", "A_canonical_load", timings, counters)
    _wrap(runner_mod, "screen_code", "E_strategy_evaluation", timings, counters)
    _wrap(math_mod, "calculate_indicators", "F_indicator_rolling", timings, counters)
    _wrap(strategy_engine, "calculate_indicators", "F_indicator_rolling", timings, counters)
    _wrap(state_mod, "load_state", "C_state_initialization", timings, counters)
    _wrap(state_mod, "save_state", "H_state_serialization_persist", timings, counters)
    _wrap(runner_mod, "_bars_prefix_hash", "D_prefix_provenance_hashing", timings, counters)
    _wrap(runner_mod, "write_json_atomic", "I_run_artifact_generation", timings, counters)
    _wrap(parquet_mod, "write_json_atomic", "I_run_artifact_generation", timings, counters)

    config_hash = sha256_file(ROOT / "config/strategy.yaml")
    commit = _git_head()
    run_id = (
        f"screen-rebuild-2026-07-31-{SNAPSHOT_ID[:12]}-"
        f"{_digest(date(2024, 1, 1), tuple(SAMPLE), commit, config_hash, 'formal')[:12]}"
    )
    (ROOT / "data/screen/runs" / f"{run_id}.json").unlink(missing_ok=True)

    profiler = cProfile.Profile()
    started = time.perf_counter()
    layout = WarehouseLayout(ROOT / "data")
    profiler.enable()
    result = run_screen(
        layout=layout,
        as_of=date(2026, 7, 31),
        snapshot_id=SNAPSHOT_ID,
        codes=SAMPLE,
        rebuild=True,
        start=date(2024, 1, 1),
    )
    profiler.disable()
    total = time.perf_counter() - started

    timings["J_other"] = max(
        0.0,
        total - sum(timings.values()),
    )
    out = ROOT / "data/tmp/cold-rebuild-profile"
    out.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative").print_stats(30)
    cumulative = stream.getvalue()
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("tottime").print_stats(30)
    self_time = stream.getvalue()
    (out / "top30_cumulative.txt").write_text(cumulative, encoding="utf-8")
    (out / "top30_self.txt").write_text(self_time, encoding="utf-8")
    payload = {
        "sample_hash": hashlib.sha256(
            json.dumps(SAMPLE, sort_keys=True).encode()
        ).hexdigest(),
        "codes": SAMPLE,
        "total_seconds": round(total, 3),
        "peak_rss_bytes": rss_bytes(),
        "output_hash": result.output_hash,
        "phases": {
            phase: {
                "seconds": round(timings[phase], 3),
                "percent": round(timings[phase] / total * 100, 1) if total else 0,
            }
            for phase in PHASES
        },
        "counters": counters,
        "per_code": round(total / len(SAMPLE), 3),
        "per_bar": round(total / result.rows_count, 4) if result.rows_count else None,
    }
    (out / "profile.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
