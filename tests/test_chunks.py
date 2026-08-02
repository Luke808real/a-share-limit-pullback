from __future__ import annotations

import json
import threading
import time
from datetime import date
from pathlib import Path

from limit_pullback.screen.chunks import _chunked_run_id, chunk_codes, run_chunked_screen
from limit_pullback.screen.runner import _digest, _git_head, run_screen
from tests.test_screen import _build_warehouse


def _screen_defaults() -> dict:
    return {
        "as_of": date(2026, 7, 31),
        "snapshot_id": "snap-2026-07-31-b5f84004de8a",
        "start": date(2024, 1, 1),
        "commit": "c" * 40,
        "config_hash": "d" * 64,
        "pool_mode": "formal",
    }


def test_chunk_codes_deterministic_and_disjoint():
    universe = tuple(f"{i:06d}" for i in range(500))
    chunks = chunk_codes(universe, 200)
    assert [len(c) for c in chunks] == [200, 200, 100]
    assert sorted(sum(chunks, [])) == list(universe)


def test_chunk_codes_size_does_not_change_membership():
    universe = tuple(f"{i:06d}" for i in range(1000))
    for size in (200, 250):
        chunks = chunk_codes(universe, size)
        assert sorted(sum(chunks, [])) == list(universe)


def test_chunked_run_id_matches_single_process_rule():
    base = _screen_defaults()
    expected = (
        f"screen-rebuild-{base['as_of'].isoformat()}-{base['snapshot_id'][:12]}-"
        f"{_digest(base['start'], (), base['commit'], base['config_hash'], base['pool_mode'])[:12]}"
    )
    # codes=None (full market) must use the empty request, exactly like run_screen.
    assert _chunked_run_id(codes=None, **base) == expected


def test_chunked_run_id_normalizes_explicit_codes_like_runner():
    base = _screen_defaults()
    codes = ["000002", "1", "000001"]
    expected = (
        f"screen-rebuild-{base['as_of'].isoformat()}-{base['snapshot_id'][:12]}-"
        f"{_digest(base['start'], ('000001', '000002'), base['commit'], base['config_hash'], base['pool_mode'])[:12]}"
    )
    assert _chunked_run_id(codes=codes, **base) == expected
    # Re-running the same logical request is stable (no chunk detail in identity).
    assert _chunked_run_id(codes=codes, **base) == _chunked_run_id(codes=codes, **base)


def test_parent_sampler_thread_stops_on_event():
    from limit_pullback.screen.chunks import _parent_peak_sampler

    peak: dict[str, int] = {"value": 0}
    stop = threading.Event()
    thread = threading.Thread(target=_parent_peak_sampler, args=(peak, stop), daemon=True)
    thread.start()
    time.sleep(0.3)
    stop.set()
    thread.join(timeout=1.0)
    assert not thread.is_alive()


def test_chunked_run_matches_single_process_run_and_child_commit(tmp_path):
    config_path = Path(__file__).resolve().parents[1] / "config" / "strategy.yaml"
    layout, dates, snapshot_id = _build_warehouse(tmp_path)
    single = run_screen(
        layout=layout,
        as_of=dates[-1],
        snapshot_id=snapshot_id,
        start=dates[0],
        rebuild=True,
        config_path=config_path,
    )
    chunked = run_chunked_screen(
        layout=layout,
        as_of=dates[-1],
        snapshot_id=snapshot_id,
        start=dates[0],
        config_path=config_path,
    )
    assert chunked["run_id"] == single.run_id
    assert chunked["output_hash"] == single.output_hash
    assert chunked["rows_count"] == single.rows_count
    manifest = json.loads(Path(chunked["output_path"]).read_text(encoding="utf-8"))
    expected_commit = _git_head()
    assert manifest["strategy_commit"] == expected_commit
    state_files = list((layout.root / "screen" / "states").glob("*.json"))
    assert state_files, "chunk child must write per-code screen state"
    for state_file in state_files:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["strategy_commit"] == expected_commit
