"""PR-E unit tests: state generation lifecycle, verify, storage, chunk contract."""

from __future__ import annotations

import json
import hashlib
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.screen.chunk_contract import (
    ChunkInvocation,
    ChunkFailureRegistry,
    ChunkResult,
    aggregate_chunk_rows,
    build_chunk_command,
    chunk_output_hash,
    run_chunk,
)
from limit_pullback.screen.generation import (
    ACTIVE,
    STAGED,
    StateGenerationError,
    StatePointerError,
    build_state_generation,
    compact_output_roundtrip_hash,
    state_semantic_root_hash,
)
from limit_pullback.screen.runner import ScreenFailpointError
from limit_pullback.trade_plan import StrategySemanticReviewPendingError
from limit_pullback.universe import (
    Phase2d0Universe,
    phase2d0_universe_from_snapshot,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from tests.test_screen import _build_warehouse


@pytest.fixture
def gen_env(tmp_path):
    layout, dates, sid = _build_warehouse(tmp_path)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(sid)
    config = load_strategy_config(
        Path(__file__).resolve().parents[1] / "config" / "strategy.yaml"
    )
    members = tuple(sorted(("603318", "002640")))
    universe = Phase2d0Universe(
        contract_version="PHASE2D0_UNIVERSE_V1",
        strategy_version="phase-2d0",
        exchange_allowlist=("SH", "SZ"),
        board_allowlist=("MAIN",),
        as_of=dates[-1],
        members=members,
        member_hash=hashlib.sha256(
            "|".join(members).encode("utf-8")
        ).hexdigest(),
    )
    return layout, snapshot, universe, config, dates


def _state_pointer(layout):
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        return metadata.get_formal_state_pointer()


def _generation_status(layout, generation_id):
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        generation = metadata.state_generation_by_id(generation_id)
    return generation["status"] if generation else None


def _build(layout, snapshot, universe, config, dates, *, as_of=None, start=None,
           rebuild=True, failpoint=None, dry_run=False, build_root=None):
    build_root = build_root or (
        layout.root / "tmp" / "pr-e" / "test"
    )
    return build_state_generation(
        layout,
        snapshot_id=snapshot.snapshot_id,
        universe=universe,
        config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "strategy.yaml",
        as_of=as_of or dates[-1],
        start=start or dates[0],
        rebuild=rebuild,
        build_root=build_root,
        failpoint=failpoint,
        dry_run=dry_run,
    )


def test_state_generation_staged_not_visible(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    result = _build(
        layout, snapshot, universe, config, dates, dry_run=True
    )
    assert result.status == STAGED
    assert _generation_status(layout, result.generation_id) is None
    assert _state_pointer(layout) is None


def test_state_generation_verified_not_active_until_pointer_commit(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    with pytest.raises(ScreenFailpointError):
        _build(
            layout,
            snapshot,
            universe,
            config,
            dates,
            failpoint="before_pointer_update",
        )
    assert _state_pointer(layout) is None


def test_only_active_generation_formally_resolves(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    result = _build(layout, snapshot, universe, config, dates)
    assert _state_pointer(layout) == result.generation_id
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        generation = metadata.state_generation_by_id(result.generation_id)
    assert generation["status"] == ACTIVE


def test_state_pointer_no_latest_fallback(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    from limit_pullback.trade_plan import build_trade_plan_output

    with pytest.raises(StatePointerError) as exc_info:
        build_trade_plan_output(
            layout=layout,
            as_of=dates[-1],
            snapshot_id=snapshot.snapshot_id,
            config=config,
            config_hash="x" * 64,
        )
    assert exc_info.value.code == "FORMAL_STATE_POINTER_MISSING"


def test_generation_snapshot_binding_required(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.set_formal_pointer(
            snapshot_id="snap-other",
            validation_report_hash="x",
        )
    with pytest.raises(StatePointerError) as exc_info:
        _build(layout, snapshot, universe, config, dates)
    assert exc_info.value.code == "STATE_SNAPSHOT_POINTER_MISMATCH"


def test_generation_universe_binding_required(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    bad_universe = Phase2d0Universe(
        contract_version=universe.contract_version,
        strategy_version=universe.strategy_version,
        exchange_allowlist=universe.exchange_allowlist,
        board_allowlist=universe.board_allowlist,
        as_of=universe.as_of,
        members=tuple(sorted(set(universe.members) | {"999999"})),
        member_hash="",
    )
    with pytest.raises(StateGenerationError):
        _build(layout, snapshot, bad_universe, config, dates)


def test_partial_generation_cannot_promote(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    with pytest.raises(ScreenFailpointError):
        _build(
            layout,
            snapshot,
            universe,
            config,
            dates,
            failpoint="mid_state_write",
        )
    assert _state_pointer(layout) is None


def test_verification_failure_pointer_unchanged(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    bad_universe = Phase2d0Universe(
        contract_version=universe.contract_version,
        strategy_version=universe.strategy_version,
        exchange_allowlist=universe.exchange_allowlist,
        board_allowlist=universe.board_allowlist,
        as_of=universe.as_of,
        members=tuple(sorted(set(universe.members) | {"999999"})),
        member_hash="tampered",
    )
    with pytest.raises(StateGenerationError):
        _build(layout, snapshot, bad_universe, config, dates)
    assert _state_pointer(layout) is None


def test_active_generation_immutable(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    first = _build(layout, snapshot, universe, config, dates)
    root = first.generation_root
    states = sorted((root / "states").glob("[0-9]*.json"))
    assert len(states) == len(universe.members)
    before = state_semantic_root_hash(root / "states")
    second = _build(
        layout,
        snapshot,
        universe,
        config,
        dates,
        build_root=layout.root / "tmp" / "pr-e" / "test2",
    )
    assert second.idempotent is True
    assert second.generation_id == first.generation_id
    assert state_semantic_root_hash(root / "states") == before


def test_repromotion_idempotent(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    first = _build(layout, snapshot, universe, config, dates)
    second = _build(
        layout,
        snapshot,
        universe,
        config,
        dates,
        build_root=layout.root / "tmp" / "pr-e" / "test3",
    )
    assert second.idempotent is True
    assert second.generation_id == first.generation_id
    assert _state_pointer(layout) == first.generation_id


def test_state_code_set_equals_phase2d0_universe(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    result = _build(layout, snapshot, universe, config, dates, dry_run=True)
    codes = sorted(
        path.stem
        for path in (result.generation_root / "states").glob("[0-9]*.json")
    )
    assert codes == list(universe.members)


def test_no_chinext_state(gen_env):
    assert all(not code.startswith(("300", "301")) for code in gen_env[2].members)


def test_no_star_state(gen_env):
    assert all(not code.startswith(("688", "689")) for code in gen_env[2].members)


def test_all_states_bind_new_snapshot(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    result = _build(layout, snapshot, universe, config, dates, dry_run=True)
    states = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (result.generation_root / "states").glob("[0-9]*.json")
    ]
    assert all(state["snapshot_id"] == snapshot.snapshot_id for state in states)


def test_all_states_last_processed_as_of(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    as_of = dates[-1]
    result = _build(
        layout, snapshot, universe, config, dates, as_of=as_of
    )
    states = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (result.generation_root / "states").glob("[0-9]*.json")
    ]
    assert all(state["last_processed_date"] == as_of.isoformat() for state in states)


def test_full_rebuild_equals_incremental_rebuild(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    mid = dates[40]
    end = dates[-1]
    full = _build(
        layout,
        snapshot,
        universe,
        config,
        dates,
        as_of=end,
        start=dates[0],
        rebuild=True,
        dry_run=True,
        build_root=layout.root / "tmp" / "pr-e" / "full",
    )
    checkpoint = _build(
        layout,
        snapshot,
        universe,
        config,
        dates,
        as_of=mid,
        start=dates[0],
        rebuild=True,
        dry_run=True,
        build_root=layout.root / "tmp" / "pr-e" / "checkpoint",
    )
    incremental_root = layout.root / "tmp" / "pr-e" / "incremental"
    build_state_generation(
        layout,
        snapshot_id=snapshot.snapshot_id,
        universe=universe,
        config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "strategy.yaml",
        as_of=end,
        start=None,
        rebuild=False,
        build_root=incremental_root,
        dry_run=True,
        seed_states_root=checkpoint.generation_root / "states",
    )
    incremental_hash = state_semantic_root_hash(
        incremental_root / "states"
    )
    assert incremental_hash[0] == full.state_semantic_root_hash
    assert incremental_hash[1] == full.state_n
    full_table = pq.read_table(
        layout.root / "tmp" / "pr-e" / "full" / "screen-output.parquet"
    )
    full_payloads = {
        payload
        for day, payload in zip(
            full_table["trade_date"].to_pylist(),
            full_table["payload"].to_pylist(),
            strict=True,
        )
        if day > mid
    }
    inc_payloads = set(
        pq.read_table(
            incremental_root / "screen-output.parquet"
        )["payload"].to_pylist()
    )
    assert full_payloads == inc_payloads


def test_run_manifest_does_not_embed_rows(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    result = _build(layout, snapshot, universe, config, dates, dry_run=True)
    manifest = json.loads(
        (result.generation_root / "manifest.json").read_text(encoding="utf-8")
    )
    assert "rows" not in manifest
    assert manifest.get("compact_output_row_n", 0) > 0


def test_compact_output_roundtrip_hash(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    result = _build(layout, snapshot, universe, config, dates, dry_run=True)
    manifest = json.loads(
        (result.generation_root / "manifest.json").read_text(encoding="utf-8")
    )
    roundtrip, _ = compact_output_roundtrip_hash(
        result.generation_root / "screen-output.parquet"
    )
    assert roundtrip == manifest["output_hash"]
    assert result.compact_roundtrip_hash_match is True


def test_compact_output_row_count(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    result = _build(layout, snapshot, universe, config, dates, dry_run=True)
    table = pq.read_table(result.generation_root / "screen-output.parquet")
    assert table.num_rows == result.compact_output_row_n
    assert table.num_rows > 0


def test_generation_artifacts_content_addressed(gen_env):
    layout, snapshot, universe, config, dates = gen_env
    first = _build(
        layout,
        snapshot,
        universe,
        config,
        dates,
        dry_run=True,
        build_root=layout.root / "tmp" / "pr-e" / "ca1",
    )
    second = _build(
        layout,
        snapshot,
        universe,
        config,
        dates,
        dry_run=True,
        build_root=layout.root / "tmp" / "pr-e" / "ca2",
    )
    assert first.generation_id == second.generation_id
    assert first.generation_id.startswith(
        f"stategen-{dates[-1].isoformat()}-"
    )


def _chunk_invocation(tmp_path, *, pool_mode="formal") -> ChunkInvocation:
    layout = WarehouseLayout(tmp_path / "data")
    layout.ensure_dirs()
    codes_path = tmp_path / "codes.json"
    manifest_path = tmp_path / "manifest.json"
    codes_path.write_text(json.dumps(["603318"]), encoding="utf-8")
    return ChunkInvocation(
        data_root=layout.root,
        snapshot_id="snap-x",
        as_of=date(2026, 8, 5),
        start=None,
        codes=("603318",),
        config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "strategy.yaml",
        strategy_commit="c" * 40,
        chunk_index=0,
        codes_path=codes_path,
        manifest_path=manifest_path,
        pool_mode=pool_mode,
    )


def test_chunk_invocation_propagates_pool_mode(tmp_path):
    invocation = _chunk_invocation(tmp_path, pool_mode="debug")
    argv, _ = build_chunk_command(invocation)
    assert argv[-1] == "debug"
    assert argv[4] == invocation.snapshot_id
    assert argv[1] == "-m"


def test_chunk_invocation_uses_supported_python_environment(tmp_path):
    import sys

    invocation = _chunk_invocation(tmp_path)
    argv, env = build_chunk_command(invocation)
    assert argv[0] == sys.executable
    assert env["PYTHONPATH"].endswith("src")
    assert "src/src" not in env["PYTHONPATH"]


def test_chunk_timeout_fails_generation(tmp_path):
    invocation = _chunk_invocation(tmp_path)
    result = run_chunk(invocation, timeout_seconds=0)
    assert result.timed_out is True
    assert result.ok is False
    registry = ChunkFailureRegistry(path=tmp_path / "failures.jsonl")
    registry.record(
        chunk_index=0,
        invocation=invocation,
        result=result,
    )
    assert registry.failure_n == 1


def test_chunk_nonzero_exit_fails_generation(tmp_path):
    invocation = _chunk_invocation(tmp_path)
    result = run_chunk(invocation, timeout_seconds=30)
    assert result.ok is False
    assert result.exit_code != 0


def test_chunk_missing_artifact_fails_generation(tmp_path):
    invocation = _chunk_invocation(tmp_path)
    result = ChunkResult(
        chunk_index=0,
        exit_code=0,
        timed_out=False,
        error=None,
        elapsed_seconds=0.1,
    )
    registry = ChunkFailureRegistry(path=tmp_path / "failures.jsonl")
    registry.record(
        chunk_index=0,
        invocation=invocation,
        result=result,
        missing_artifact=not invocation.manifest_path.exists(),
    )
    assert registry.failure_n == 1


def test_chunk_order_does_not_change_root_hash():
    chunks = [
        [
            {"code": "000002", "trade_date": "2026-08-05", "x": 1},
            {"code": "000001", "trade_date": "2026-08-05", "x": 2},
        ],
        [{"code": "000003", "trade_date": "2026-08-05", "x": 3}],
    ]
    a = chunk_output_hash(aggregate_chunk_rows(chunks))
    b = chunk_output_hash(aggregate_chunk_rows(list(reversed(chunks))))
    assert a == b


FAULT_POINTS = (
    "after_first_state_batch",
    "mid_state_write",
    "after_all_states",
    "after_compact_output",
    "after_manifest",
    "during_verify",
    "after_verify_before_metadata",
    "during_metadata_transaction",
    "before_pointer_update",
)


@pytest.mark.parametrize("failpoint", FAULT_POINTS)
def test_fault_injection_pointer_unchanged(gen_env, failpoint):
    layout, snapshot, universe, config, dates = gen_env
    with pytest.raises(ScreenFailpointError):
        _build(
            layout,
            snapshot,
            universe,
            config,
            dates,
            failpoint=failpoint,
        )
    assert _state_pointer(layout) is None
