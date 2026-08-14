"""DAILY_PIPELINE_FAST_PATH_V01 unit + real-data equivalence tests."""

from __future__ import annotations

import hashlib
import shutil
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.ops import (
    _resolve_verify_predecessor,
    build_parser,
    resolve_predecessor,
)
from limit_pullback.runtime import load_runtime_config
from limit_pullback.screen.fast_path import FastPathStats, run_screen_fast
from limit_pullback.screen.runner import run_screen
from limit_pullback.universe import Phase2d0Universe
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata


def _member_hash(members):
    payload = "|".join(sorted(members))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _layout() -> WarehouseLayout:
    root = Path(__file__).resolve().parents[1] / "data"
    if not (root / "warehouse.duckdb").exists():
        pytest.skip("real data root not present")
    return WarehouseLayout(root)


def test_ops_daily_accepts_arbitrary_date():
    parser = build_parser()
    args = parser.parse_args(["daily", "2026-08-07"])
    assert args.date == date(2026, 8, 7)
    args = parser.parse_args(["daily", "2026-08-08"])
    assert args.date == date(2026, 8, 8)


def test_runtime_defaults_are_fixed():
    cfg = load_runtime_config()
    assert cfg.tencent_workers == 16
    assert cfg.canonical_reader_threads == 4
    assert cfg.daily_window_calendar_days == 400


def _candidate(gen_id, as_of, status="ACTIVE"):
    return {
        "generation_id": gen_id,
        "status": status,
        "snapshot_id": "snap-test",
        "as_of": as_of,
        "universe_hash": "u",
        "strategy_commit": "c",
        "strategy_config_hash": "cfg",
        "created_at": None,
    }


def test_predecessor_resolution_unique_single_candidate():
    candidates = [_candidate("gen-1", date(2026, 8, 5))]
    method, selected, eligible = resolve_predecessor(
        candidates,
        expected_as_of=date(2026, 8, 5),
    )
    assert method == "UNIQUE"
    assert selected["generation_id"] == "gen-1"
    assert len(eligible) == 1


def test_predecessor_resolution_ambiguous_same_as_of():
    candidates = [
        _candidate("gen-old", date(2026, 8, 5)),
        _candidate("gen-intermediate", date(2026, 8, 5)),
        _candidate("gen-correct", date(2026, 8, 5)),
    ]
    method, selected, eligible = resolve_predecessor(
        candidates,
        expected_as_of=date(2026, 8, 5),
    )
    assert method == "AMBIGUOUS"
    assert selected is None
    assert {c["generation_id"] for c in eligible} == {
        "gen-old",
        "gen-intermediate",
        "gen-correct",
    }


def test_predecessor_resolution_none():
    method, selected, eligible = resolve_predecessor(
        [_candidate("gen-other", date(2026, 8, 4))],
        expected_as_of=date(2026, 8, 5),
    )
    assert method == "NONE"
    assert selected is None
    assert eligible == []


def test_ops_verify_parser_supports_predecessor_flags():
    parser = build_parser()
    args = parser.parse_args(
        [
            "verify-full",
            "2026-08-06",
            "--from-generation",
            "stategen-2026-08-05-9ff1f6c6c107",
            "--resolve-only",
        ]
    )
    assert args.from_generation == "stategen-2026-08-05-9ff1f6c6c107"
    assert args.resolve_only is True


def test_real_predecessor_20260805_ambiguity_and_explicit():
    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = md.snapshot_by_id("snap-2026-08-06-e798f88ff67b")
    assert snapshot is not None
    from limit_pullback.universe import phase2d0_universe_from_snapshot

    real_universe = phase2d0_universe_from_snapshot(layout, snapshot)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        try:
            _resolve_verify_predecessor(
                layout,
                md,
                snapshot,
                as_of=date(2026, 8, 6),
                universe_hash=real_universe.member_hash,
                universe_n=real_universe.member_n,
            )
        except ValueError as exc:
            assert "PREDECESSOR_RESOLUTION=AMBIGUOUS" in str(exc)
        else:
            raise AssertionError("expected AMBIGUOUS fail-closed")

        report = _resolve_verify_predecessor(
            layout,
            md,
            snapshot,
            as_of=date(2026, 8, 6),
            universe_hash=real_universe.member_hash,
            universe_n=real_universe.member_n,
            explicit="stategen-2026-08-05-9ff1f6c6c107",
        )
    assert (
        report["predecessor_generation_id"]
        == "stategen-2026-08-05-9ff1f6c6c107"
    )
    assert report["predecessor_resolution_method"] == "EXPLICIT"
    assert report["predecessor_expected_as_of"] == "2026-08-05"
    assert len(report["candidates"]) >= 3


def test_real_predecessor_explicit_wrong_date_fails_closed():
    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = md.snapshot_by_id("snap-2026-08-06-e798f88ff67b")
    assert snapshot is not None
    from limit_pullback.universe import phase2d0_universe_from_snapshot

    universe = phase2d0_universe_from_snapshot(layout, snapshot)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        with pytest.raises(ValueError) as exc_info:
            _resolve_verify_predecessor(
                layout,
                md,
                snapshot,
                as_of=date(2026, 8, 6),
                universe_hash=universe.member_hash,
                universe_n=universe.member_n,
                explicit="stategen-2026-08-06-a846075a5ac7",
            )
    assert "EXPLICIT_WRONG_AS_OF" in str(exc_info.value)


def test_real_predecessor_explicit_nonexistent_fails_closed():
    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = md.snapshot_by_id("snap-2026-08-06-e798f88ff67b")
    assert snapshot is not None
    from limit_pullback.universe import phase2d0_universe_from_snapshot

    universe = phase2d0_universe_from_snapshot(layout, snapshot)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        with pytest.raises(ValueError) as exc_info:
            _resolve_verify_predecessor(
                layout,
                md,
                snapshot,
                as_of=date(2026, 8, 6),
                universe_hash=universe.member_hash,
                universe_n=universe.member_n,
                explicit="stategen-does-not-exist",
            )
    assert "EXPLICIT_NOT_FOUND" in str(exc_info.value)


def test_real_fast_path_matches_full_rebuild_for_sentinel_codes(tmp_path):
    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = md.snapshot_by_id("snap-2026-08-06-e798f88ff67b")
        prev = md.state_generation_by_id("stategen-2026-08-05-9ff1f6c6c107")
    assert snapshot is not None
    assert prev is not None
    as_of = date(2026, 8, 6)
    codes = ("002112", "603980")
    universe = Phase2d0Universe(
        contract_version="PHASE2D0_UNIVERSE_V1",
        strategy_version="phase-2d0",
        exchange_allowlist=("SH", "SZ"),
        board_allowlist=("MAIN",),
        as_of=as_of,
        members=codes,
        member_hash=_member_hash(codes),
    )
    config = load_strategy_config(
        Path(__file__).resolve().parents[1] / "config" / "strategy.yaml"
    )
    prev_states = (
        layout.root
        / "screen"
        / "generations"
        / "stategen-2026-08-05-9ff1f6c6c107"
        / "states"
    )

    # First fast pass: previous 08/05 states lack v2 -> targeted fallback.
    root1 = tmp_path / "fast1"
    states1 = root1 / "states"
    states1.mkdir(parents=True)
    for code in codes:
        shutil.copy2(prev_states / f"{code}.json", states1 / f"{code}.json")
    stats1 = FastPathStats()
    manifest1 = run_screen_fast(
        layout=layout,
        snapshot=snapshot,
        universe=universe,
        as_of=as_of,
        config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "strategy.yaml",
        config=config,
        commit=prev["strategy_code_commit"],
        config_hash=prev["strategy_config_hash"],
        states_root=states1,
        spool_path=root1 / "rows.jsonl",
        manifest_path=root1 / "manifest.json",
        compact_output_path=root1 / "screen-output.parquet",
        generated_at=datetime.combine(
            as_of, time(23, 59, 59), tzinfo=timezone.utc
        ),
        processed_at=datetime.now(timezone.utc),
        pool_mode="formal",
        window_calendar_days=400,
        previous_commit=prev["strategy_code_commit"],
        stats=stats1,
    )
    assert stats1.targeted_fallback_n == 2
    assert stats1.fast_path_n == 0

    # Build 08/05 states with v2 via a full runner (same snapshot, as_of 08/05).
    base_0805_root = tmp_path / "full-0805"
    run_screen(
        layout=layout,
        as_of=date(2026, 8, 5),
        snapshot_id=snapshot.snapshot_id,
        start=date(2024, 1, 1),
        rebuild=True,
        codes=list(codes),
        config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "strategy.yaml",
        strategy_commit=prev["strategy_code_commit"],
        manifest_path_override=base_0805_root / "manifest.json",
        states_root=base_0805_root / "states",
        compact_output_path=base_0805_root / "screen-output.parquet",
    )

    # Second fast pass from v2 states -> true fast path, no fallback.
    root2 = tmp_path / "fast2"
    states2 = root2 / "states"
    states2.mkdir(parents=True)
    for code in codes:
        shutil.copy2(
            base_0805_root / "states" / f"{code}.json",
            states2 / f"{code}.json",
        )
    stats2 = FastPathStats()
    manifest2 = run_screen_fast(
        layout=layout,
        snapshot=snapshot,
        universe=universe,
        as_of=as_of,
        config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "strategy.yaml",
        config=config,
        commit=prev["strategy_code_commit"],
        config_hash=prev["strategy_config_hash"],
        states_root=states2,
        spool_path=root2 / "rows.jsonl",
        manifest_path=root2 / "manifest.json",
        compact_output_path=root2 / "screen-output.parquet",
        generated_at=datetime.combine(
            as_of, time(23, 59, 59), tzinfo=timezone.utc
        ),
        processed_at=datetime.now(timezone.utc),
        pool_mode="formal",
        window_calendar_days=400,
        previous_commit=prev["strategy_code_commit"],
        stats=stats2,
    )
    assert stats2.targeted_fallback_n == 0
    assert stats2.full_fallback_n == 0
    assert stats2.fast_path_n == 2

    # Full single-code replay as reference.
    full_root = tmp_path / "full"
    run_screen(
        layout=layout,
        as_of=as_of,
        snapshot_id=snapshot.snapshot_id,
        start=date(2024, 1, 1),
        rebuild=True,
        codes=list(codes),
        config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "strategy.yaml",
        strategy_commit="ops-test",
        manifest_path_override=full_root / "manifest.json",
        states_root=full_root / "states",
        compact_output_path=full_root / "screen-output.parquet",
    )
    from limit_pullback.screen.models import ScreenState
    from limit_pullback.models.signal import StrategySignal

    for code in codes:
        fast_state = ScreenState.model_validate_json(
            (states2 / f"{code}.json").read_text(encoding="utf-8")
        )
        full_state = ScreenState.model_validate_json(
            (full_root / "states" / f"{code}.json").read_text(
                encoding="utf-8"
            )
        )
        fast_signal = StrategySignal.model_validate_json(
            fast_state.signal_json
        )
        full_signal = StrategySignal.model_validate_json(
            full_state.signal_json
        )
        assert fast_signal.setup_id == full_signal.setup_id
        assert fast_signal.setup_stage == full_signal.setup_stage
        assert fast_state.last_processed_date == full_state.last_processed_date
        assert fast_state.limit_pool_prefix_hash == (
            full_state.limit_pool_prefix_hash
        )
        assert fast_state.bars_prefix_hash_v2 is not None
