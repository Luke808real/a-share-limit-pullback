"""DAILY_PIPELINE_FAST_PATH_V01 operational entrypoint.

Commands:
    ops daily YYYY-MM-DD
    ops verify-full YYYY-MM-DD
    ops replay CODE --from YYYY-MM-DD --to YYYY-MM-DD
    ops status --json

DAILY never runs a second full rebuild; it builds once, verifies the same
candidate, and atomically promotes it.  VERIFY runs the full correctness
workload for release/manual audits.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from datetime import timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from limit_pullback.config import load_strategy_config
from limit_pullback.coverage import (
    DATA_MISSING_UNEXPLAINED,
    classify_daily_coverage,
)
from limit_pullback.derived_limit_event import (
    build_derived_limit_events,
    derived_event_content_hash,
)
from limit_pullback.models.market import DailyBarsRequest
from limit_pullback.providers.baostock_daily import BaoStockDailyBarProvider
from limit_pullback.runtime import RuntimeConfig, load_runtime_config
from limit_pullback.screen.canonical import iter_canonical_code_bars
from limit_pullback.screen.generation import build_state_generation
from limit_pullback.screen.runner import run_screen
from limit_pullback.universe import (
    PHASE2D0_UNIVERSE_CONTRACT_VERSION,
    phase2d0_universe_from_snapshot,
)
from limit_pullback.warehouse.daily_catchup import fetch_daily_delta
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.promotion import promote_snapshot
from limit_pullback.warehouse.snapshot import (
    resolve_formal_screen_ready_snapshot,
)
from limit_pullback.warehouse.staging import run_adr008_staging

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data"
STRATEGY_CONFIG = ROOT / "config" / "strategy.yaml"
SENTINEL_CODES = ("603980", "002112", "000001", "605198")


def _layout() -> WarehouseLayout:
    return WarehouseLayout(DATA_ROOT)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _verified_no_trade_from_previous(
    layout: WarehouseLayout,
    snapshot,
    sessions: tuple[date, ...],
    universe_members: Sequence[str],
) -> tuple[tuple[str, date], ...]:
    """Reuse previous verified coverage: no CONFIRMED bar => verified no-trade."""

    import duckdb

    daily_rel = next(
        key
        for key in snapshot.canonical_file_hashes
        if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
    )
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='1GB'")
    traded = {
        (str(row[0]), row[1])
        for row in con.execute(
            """
            SELECT DISTINCT code, trade_date
            FROM read_parquet(?)
            WHERE reconciliation_status = 'CONFIRMED'
              AND trade_date IN (SELECT unnest(?::DATE[]))
            """,
            [
                str(layout.root / daily_rel),
                [session.isoformat() for session in sessions],
            ],
        ).fetchall()
    }
    return tuple(
        (code, session)
        for session in sessions
        for code in universe_members
        if (code, session) not in traded
    )


def _verify_no_trade_with_baostock(
    layout: WarehouseLayout,
    session: date,
    universe_members: Sequence[str],
    staged_rows: Sequence[dict[str, Any]],
) -> tuple[tuple[str, date], ...]:
    audit = classify_daily_coverage(
        contract_version=PHASE2D0_UNIVERSE_CONTRACT_VERSION,
        as_of=session,
        universe_members=universe_members,
        staged_rows=staged_rows,
    )
    if audit.unexplained_n == 0:
        return ()
    provider = BaoStockDailyBarProvider()
    verified: list[tuple[str, date]] = []
    for code, _day in audit.unexplained_missing:
        result = provider.fetch_daily_bars(
            DailyBarsRequest(
                codes=(code,),
                start_date=session,
                end_date=session,
            )
        )
        skipped = any(
            flag.startswith(
                f"NON_TRADING_BAR_SKIPPED:{code}:{session.isoformat()}"
            )
            for flag in result.quality_flags
        )
        if skipped and not result.bars:
            verified.append((code, session))
        else:
            raise ValueError(
                "DATA_MISSING_UNEXPLAINED:"
                f"{code}:{session.isoformat()}"
            )
    return tuple(verified)


def _calendar_sessions(
    layout: WarehouseLayout,
    snapshot,
    previous_as_of: date,
    as_of: date,
) -> tuple[date, ...]:
    import duckdb

    daily_rel = next(
        key
        for key in snapshot.canonical_file_hashes
        if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
    )
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET memory_limit='1GB'")
    rows = con.execute(
        """
        SELECT DISTINCT trade_date
        FROM read_parquet(?)
        WHERE reconciliation_status = 'CONFIRMED'
          AND trade_date > CAST(? AS DATE)
          AND trade_date <= CAST(? AS DATE)
        ORDER BY trade_date
        """,
        [
            str(layout.root / daily_rel),
            previous_as_of.isoformat(),
            as_of.isoformat(),
        ],
    ).fetchall()
    return tuple(row[0] for row in rows)


def _previous_trading_session(
    layout: WarehouseLayout,
    snapshot,
    as_of: date,
) -> date:
    """Max CONFIRMED trading session strictly before as_of in the snapshot."""

    import duckdb

    daily_rel = next(
        key
        for key in snapshot.canonical_file_hashes
        if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
    )
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET memory_limit='1GB'")
    rows = con.execute(
        """
        SELECT max(trade_date)
        FROM read_parquet(?)
        WHERE reconciliation_status = 'CONFIRMED'
          AND trade_date < CAST(? AS DATE)
        """,
        [str(layout.root / daily_rel), as_of.isoformat()],
    ).fetchall()
    value = rows[0][0] if rows else None
    if value is None:
        raise ValueError(
            "PREDECESSOR_EXPECTED_AS_OF_MISSING:"
            f"no confirmed session before {as_of.isoformat()}"
        )
    return value


def _predecessor_candidate_valid(
    gen: dict[str, Any],
    layout: WarehouseLayout,
    *,
    expected_universe_hash: str,
    expected_universe_n: int,
) -> tuple[bool, str]:
    if gen.get("status") != "ACTIVE":
        return False, "STATUS_NOT_ACTIVE"
    if gen.get("universe_hash") != expected_universe_hash:
        return False, "UNIVERSE_HASH_MISMATCH"
    root = layout.root / "screen" / "generations" / gen["generation_id"]
    verification_path = root / "verification.json"
    if not verification_path.exists():
        return False, "VERIFICATION_MISSING"
    try:
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "VERIFICATION_UNREADABLE"
    if verification.get("passed") is not True:
        return False, "VERIFICATION_NOT_PASSED"
    if verification.get("state_n") != expected_universe_n:
        return False, "STATE_COUNT_MISMATCH"
    if verification.get("state_coverage_through_as_of_n") != (
        expected_universe_n
    ):
        return False, "COVERAGE_INCOMPLETE"
    return True, ""


def resolve_predecessor(
    candidates: Sequence[dict[str, Any]],
    *,
    expected_as_of: date,
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    """Fail-closed predecessor resolution over eligible candidates.

    Returns (method, selected, eligible).  Method is UNIQUE, AMBIGUOUS or NONE.
    Ambiguity is never resolved by created_at or any ordering heuristic.
    """

    eligible = [
        dict(candidate)
        for candidate in candidates
        if candidate.get("status") == "ACTIVE"
        and candidate.get("as_of") == expected_as_of
    ]
    if len(eligible) == 1:
        return "UNIQUE", eligible[0], eligible
    if len(eligible) == 0:
        return "NONE", None, eligible
    return "AMBIGUOUS", None, eligible


def _resolve_verify_predecessor(
    layout: WarehouseLayout,
    metadata,
    snapshot,
    *,
    as_of: date,
    universe_hash: str,
    universe_n: int,
    explicit: str | None = None,
) -> dict[str, Any]:
    expected_as_of = _previous_trading_session(layout, snapshot, as_of)
    rows = metadata._connection.execute(
        """
        SELECT generation_id, status, snapshot_id, as_of, universe_hash,
               strategy_code_commit, strategy_config_hash, created_at
        FROM state_generations
        """
    ).fetchall()
    columns = [
        "generation_id",
        "status",
        "snapshot_id",
        "as_of",
        "universe_hash",
        "strategy_commit",
        "strategy_config_hash",
        "created_at",
    ]
    all_candidates = [
        dict(zip(columns, row, strict=True)) for row in rows
    ]

    def _valid(gen: dict[str, Any]) -> tuple[bool, str]:
        return _predecessor_candidate_valid(
            gen,
            layout,
            expected_universe_hash=universe_hash,
            expected_universe_n=universe_n,
        )

    if explicit is not None:
        matches = [
            gen for gen in all_candidates if gen["generation_id"] == explicit
        ]
        if not matches:
            raise ValueError(
                "PREDECESSOR_RESOLUTION=EXPLICIT_NOT_FOUND:"
                f"{explicit}"
            )
        candidate = matches[0]
        if candidate["as_of"] != expected_as_of:
            raise ValueError(
                "PREDECESSOR_RESOLUTION=EXPLICIT_WRONG_AS_OF:"
                f"expected={expected_as_of.isoformat()} "
                f"actual={candidate['as_of'].isoformat()}"
            )
        ok, reason = _valid(candidate)
        if not ok:
            raise ValueError(
                "PREDECESSOR_RESOLUTION=EXPLICIT_INVALID:"
                f"{explicit}:{reason}"
            )
        return {
            "requested_verify_date": as_of.isoformat(),
            "predecessor_expected_as_of": expected_as_of.isoformat(),
            "predecessor_resolution_method": "EXPLICIT",
            "predecessor_generation_id": candidate["generation_id"],
            "predecessor_status": candidate["status"],
            "predecessor_snapshot_id": candidate["snapshot_id"],
            "predecessor_universe_hash": candidate["universe_hash"],
            "predecessor_strategy_commit": candidate["strategy_commit"],
            "candidates": [
                {
                    "generation_id": gen["generation_id"],
                    "status": gen["status"],
                    "as_of": gen["as_of"].isoformat(),
                    "snapshot_id": gen["snapshot_id"],
                    "universe_hash": gen["universe_hash"],
                    "strategy_commit": gen["strategy_commit"],
                    "created_at": (
                        gen["created_at"].isoformat()
                        if gen["created_at"] is not None
                        else None
                    ),
                }
                for gen in all_candidates
                if gen["as_of"] == expected_as_of
            ],
        }

    eligible: list[dict[str, Any]] = []
    for gen in all_candidates:
        if gen["as_of"] != expected_as_of:
            continue
        ok, _reason = _valid(gen)
        if ok:
            eligible.append(gen)
    method, selected, _ = resolve_predecessor(
        eligible,
        expected_as_of=expected_as_of,
    )
    if method == "NONE":
        raise ValueError(
            "PREDECESSOR_RESOLUTION=NONE:"
            f"no eligible ACTIVE generation with as_of={expected_as_of.isoformat()}"
        )
    if method == "AMBIGUOUS":
        raise ValueError(
            "PREDECESSOR_RESOLUTION=AMBIGUOUS:"
            "multiple eligible candidates; pass --from-generation. candidates="
            + json.dumps(
                [
                    {
                        "generation_id": gen["generation_id"],
                        "status": gen["status"],
                        "as_of": gen["as_of"].isoformat(),
                        "snapshot_id": gen["snapshot_id"],
                        "universe_hash": gen["universe_hash"],
                        "strategy_commit": gen["strategy_commit"],
                        "created_at": (
                            gen["created_at"].isoformat()
                            if gen["created_at"] is not None
                            else None
                        ),
                    }
                    for gen in eligible
                ],
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    assert selected is not None
    return {
        "requested_verify_date": as_of.isoformat(),
        "predecessor_expected_as_of": expected_as_of.isoformat(),
        "predecessor_resolution_method": "UNIQUE",
        "predecessor_generation_id": selected["generation_id"],
        "predecessor_status": selected["status"],
        "predecessor_snapshot_id": selected["snapshot_id"],
        "predecessor_universe_hash": selected["universe_hash"],
        "predecessor_strategy_commit": selected["strategy_commit"],
        "candidates": [
            {
                "generation_id": gen["generation_id"],
                "status": gen["status"],
                "as_of": gen["as_of"].isoformat(),
                "snapshot_id": gen["snapshot_id"],
                "universe_hash": gen["universe_hash"],
                "strategy_commit": gen["strategy_commit"],
                "created_at": (
                    gen["created_at"].isoformat()
                    if gen["created_at"] is not None
                    else None
                ),
            }
            for gen in eligible
        ],
    }


def _sentinel_check(
    layout: WarehouseLayout,
    snapshot,
    generation_root: Path,
    as_of: date,
    config_path: Path,
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for code in SENTINEL_CODES:
        tmp = DATA_ROOT / "tmp" / "ops-sentinel" / f"{as_of.isoformat()}-{code}"
        result = run_screen(
            layout=layout,
            as_of=as_of,
            snapshot_id=snapshot.snapshot_id,
            start=date(2024, 1, 1),
            rebuild=True,
            codes=[code],
            config_path=config_path,
            strategy_commit="ops-sentinel",
            manifest_path_override=tmp / "manifest.json",
            states_root=tmp / "states",
            compact_output_path=tmp / "screen-output.parquet",
        )
        sentinel_state_path = tmp / "states" / f"{code}.json"
        fast_state_path = generation_root / "states" / f"{code}.json"
        if not sentinel_state_path.exists() or not fast_state_path.exists():
            reports.append(
                {
                    "code": code,
                    "match": False,
                    "reason": "STATE_MISSING",
                }
            )
            continue
        from limit_pullback.screen.models import ScreenState

        sentinel_state = ScreenState.model_validate_json(
            sentinel_state_path.read_text(encoding="utf-8")
        )
        fast_state = ScreenState.model_validate_json(
            fast_state_path.read_text(encoding="utf-8")
        )
        from limit_pullback.models.signal import StrategySignal

        sentinel_signal = StrategySignal.model_validate_json(
            sentinel_state.signal_json
        )
        fast_signal = StrategySignal.model_validate_json(fast_state.signal_json)
        match = (
            sentinel_signal.setup_id == fast_signal.setup_id
            and sentinel_signal.setup_stage == fast_signal.setup_stage
            and sentinel_state.last_processed_date
            == fast_state.last_processed_date
            and sentinel_state.limit_pool_prefix_hash
            == fast_state.limit_pool_prefix_hash
            and (
                sentinel_signal.anchor is None
                or fast_signal.anchor is None
                or (
                    sentinel_signal.anchor.anchor_date
                    == fast_signal.anchor.anchor_date
                    and sentinel_signal.anchor.anchor_price
                    == fast_signal.anchor.anchor_price
                )
            )
        )
        reports.append(
            {
                "code": code,
                "match": match,
                "fast_setup": fast_signal.setup_id,
                "fast_stage": fast_signal.setup_stage.value,
                "replay_setup": sentinel_signal.setup_id,
                "replay_stage": sentinel_signal.setup_stage.value,
                "fast_last_processed": fast_state.last_processed_date.isoformat(),
                "replay_last_processed": sentinel_state.last_processed_date.isoformat(),
            }
        )
    return reports


def cmd_daily(args: argparse.Namespace) -> int:
    session = args.date
    layout = _layout()
    runtime = load_runtime_config()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        prev_snapshot = resolve_formal_screen_ready_snapshot(md)
        prev_state_pointer = md.get_formal_state_pointer()
        if prev_state_pointer is None:
            raise ValueError("no ACTIVE state generation to advance from")
        prev_generation = md.state_generation_by_id(prev_state_pointer)
    prev_gen_root = (
        layout.root / "screen" / "generations" / prev_state_pointer
    )
    universe = phase2d0_universe_from_snapshot(layout, prev_snapshot)
    cache_root = (
        layout.root / "tmp" / f"canonical-catchup-{session:%Y-%m-%d}"
    )
    cache_root.mkdir(parents=True, exist_ok=True)
    run_id = f"adr008-staging-{session:%Y%m%d}-tdx-tencent-v1"

    started = time.time()
    provider = fetch_daily_delta(
        layout,
        base_snapshot_id=prev_snapshot.snapshot_id,
        session=session,
        runtime=runtime,
        run_id=f"CATCHUP_{session:%Y%m%d}_TDX_TENCENT",
        cache_root=cache_root,
    )
    staging = run_adr008_staging(
        layout,
        run_id=run_id,
        seed_snapshot_id=prev_snapshot.snapshot_id,
        sessions=[session],
        tdx_raw_rows=pq.read_table(provider.raw_tdx_path).to_pylist(),
        tencent_raw_rows=pq.read_table(provider.raw_tencent_path).to_pylist(),
        tdx_artifact_path=provider.raw_tdx_path,
        tencent_artifact_path=provider.raw_tencent_path,
    )
    if not staging.publish_eligible or staging.unclassified_failure_n:
        raise ValueError("STAGING_NOT_ELIGIBLE")
    staged_rows = pq.read_table(staging.candidate_path).to_pylist()
    current_verified = _verify_no_trade_with_baostock(
        layout,
        session,
        universe.members,
        staged_rows,
    )
    verified = current_verified
    config = load_strategy_config(STRATEGY_CONFIG)
    events = build_derived_limit_events(
        [
            {
                "code": row["code"],
                "trade_date": row["trade_date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "preclose": row["preclose"],
                "source_daily_hash": row.get("selected_source_hash") or "",
            }
            for row in staged_rows
            if row.get("close") is not None
            and row.get("preclose") is not None
            and row["code"] in set(universe.members)
        ],
        source_id=run_id,
        config=config,
        universe_members=set(universe.members),
    )
    promotion = promote_snapshot(
        layout,
        base_snapshot_id=prev_snapshot.snapshot_id,
        staged_rows=staged_rows,
        prb_staging_hash=staging.staging_canonical_hash,
        prb_staging_manifest_path=staging.manifest_path,
        universe=universe,
        derived_events=events,
        derived_event_hash=derived_event_content_hash(events),
        config=config,
        raw_tdx_path=provider.raw_tdx_path,
        raw_tencent_path=provider.raw_tencent_path,
        sessions=[session],
        as_of=session,
        verified_no_trade=current_verified,
    )
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        new_snapshot = md.snapshot_by_id(promotion.snapshot_id)
    calendar = _calendar_sessions(
        layout,
        new_snapshot,
        prev_snapshot.as_of - timedelta(days=30),
        session,
    )
    prior_sessions = tuple(day for day in calendar if day < session)
    prior_verified = _verified_no_trade_from_previous(
        layout,
        prev_snapshot,
        prior_sessions,
        universe.members,
    )
    verified = tuple(sorted(set(prior_verified + current_verified)))
    fast_stats: dict[str, Any] = {}
    build_root = layout.root / "tmp" / "pr-e" / f"daily-{session:%Y%m%d}"
    generation = build_state_generation(
        layout,
        snapshot_id=promotion.snapshot_id,
        universe=universe,
        config_path=STRATEGY_CONFIG,
        as_of=session,
        start=None,
        rebuild=False,
        build_root=build_root,
        dry_run=False,
        seed_states_root=prev_gen_root / "states",
        verified_no_trade=verified,
        session_calendar=calendar,
        fast_path=True,
        window_calendar_days=runtime.daily_window_calendar_days,
        previous_commit=prev_generation.get("strategy_code_commit"),
        fast_stats=fast_stats,
        workers=runtime.screen_process_workers,
    )
    sentinels = _sentinel_check(
        layout,
        new_snapshot,
        generation.generation_root,
        session,
        STRATEGY_CONFIG,
    )
    summary = {
        "date": session.isoformat(),
        "provider": {
            "total_codes": provider.provider_total_codes,
            "cached_codes": provider.provider_cached_codes,
            "requested_codes": provider.provider_requested_codes,
            "retry_codes": provider.provider_retry_codes,
            "wall_time": provider.provider_wall_time,
        },
        "staging": {
            "confirmed_n": staging.confirmed_n,
            "provisional_n": staging.provisional_n,
            "incomplete_n": staging.incomplete_n,
            "conflicted_n": staging.conflicted_n,
            "preclose_continuity_mismatch_n": (
                staging.preclose_continuity_mismatch_n
            ),
            "staging_hash": staging.staging_canonical_hash,
        },
        "snapshot": {
            "id": promotion.snapshot_id,
            "status": promotion.status,
            "pointer_before": promotion.formal_pointer_before,
            "pointer_after": promotion.formal_pointer_after,
        },
        "generation": {
            "id": generation.generation_id,
            "status": generation.status,
            "state_n": generation.state_n,
            "semantic_root": generation.state_semantic_root_hash,
            "pointer_before": generation.pointer_before,
            "pointer_after": generation.pointer_after,
        },
        "predecessor_resolution": {
            "method": "FORMAL_STATE_POINTER",
            "generation_id": prev_state_pointer,
            "requires_followup": False,
        },
        "fast_path_stats": fast_stats,
        "sentinel_checks": sentinels,
        "total_wall_seconds": round(time.time() - started, 2),
    }
    summary_path = cache_root / "daily-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_verify_full(args: argparse.Namespace) -> int:
    as_of = args.date
    layout = _layout()
    runtime = load_runtime_config()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = md.snapshot_by_id(args.snapshot_id) if args.snapshot_id else None
        if snapshot is None:
            snapshot = resolve_formal_screen_ready_snapshot(md)
        universe = phase2d0_universe_from_snapshot(layout, snapshot)
        predecessor_report = _resolve_verify_predecessor(
            layout,
            md,
            snapshot,
            as_of=as_of,
            universe_hash=universe.member_hash,
            universe_n=universe.member_n,
            explicit=args.from_generation,
        )
    report_dir = layout.root / "tmp" / "ops-verify"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"predecessor-{as_of:%Y%m%d}.json"
    report_path.write_text(
        json.dumps(predecessor_report, ensure_ascii=False, indent=2)
    )
    print(
        "PREDECESSOR_REPORT",
        json.dumps(predecessor_report, ensure_ascii=False, indent=2),
        flush=True,
    )
    if args.resolve_only:
        return 0
    calendar = _calendar_sessions(
        layout,
        snapshot,
        snapshot.as_of - timedelta(days=30),
        as_of,
    )
    verified = _verified_no_trade_from_previous(
        layout, snapshot, calendar, universe.members
    )
    full_root = layout.root / "tmp" / "ops-verify" / f"full-{as_of:%Y%m%d}"
    inc_root = layout.root / "tmp" / "ops-verify" / f"inc-{as_of:%Y%m%d}"
    repeat_root = layout.root / "tmp" / "ops-verify" / f"repeat-{as_of:%Y%m%d}"
    prev_gen_root = (
        layout.root
        / "screen"
        / "generations"
        / predecessor_report["predecessor_generation_id"]
    )
    verify_commit = predecessor_report["predecessor_strategy_commit"]
    full = build_state_generation(
        layout,
        snapshot_id=snapshot.snapshot_id,
        universe=universe,
        config_path=STRATEGY_CONFIG,
        as_of=as_of,
        start=date(2024, 1, 1),
        rebuild=True,
        build_root=full_root,
        dry_run=True,
        strategy_commit=verify_commit,
        verified_no_trade=verified,
        session_calendar=calendar,
        workers=runtime.screen_process_workers,
    )
    if prev_gen_root is not None:
        inc = build_state_generation(
            layout,
            snapshot_id=snapshot.snapshot_id,
            universe=universe,
            config_path=STRATEGY_CONFIG,
            as_of=as_of,
            start=None,
            rebuild=False,
            build_root=inc_root,
            dry_run=True,
            strategy_commit=verify_commit,
            seed_states_root=prev_gen_root / "states",
            verified_no_trade=verified,
            session_calendar=calendar,
            fast_path=True,
            window_calendar_days=runtime.daily_window_calendar_days,
            previous_commit=verify_commit,
            workers=runtime.screen_process_workers,
        )
        inc_semantic = inc.state_semantic_root_hash
    else:
        inc_semantic = None
    repeat = build_state_generation(
        layout,
        snapshot_id=snapshot.snapshot_id,
        universe=universe,
        config_path=STRATEGY_CONFIG,
        as_of=as_of,
        start=date(2024, 1, 1),
        rebuild=True,
        build_root=repeat_root,
        dry_run=True,
        strategy_commit=verify_commit,
        verified_no_trade=verified,
        session_calendar=calendar,
        workers=runtime.screen_process_workers,
    )
    parity = {
        "full_semantic": full.state_semantic_root_hash,
        "incremental_fast_semantic": inc_semantic,
        "repeat_semantic": repeat.state_semantic_root_hash,
        "full_inc_equal": (
            full.state_semantic_root_hash == inc_semantic
            if inc_semantic
            else None
        ),
        "full_repeat_equal": (
            full.state_semantic_root_hash == repeat.state_semantic_root_hash
        ),
        "state_n": full.state_n,
    }
    print(json.dumps(parity, ensure_ascii=False, indent=2))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = (
            md.snapshot_by_id(args.snapshot_id)
            if args.snapshot_id
            else resolve_formal_screen_ready_snapshot(md)
        )
    bars = next(
        (
            bars
            for code, bars in iter_canonical_code_bars(
                layout,
                snapshot,
                codes=[args.code],
                as_of=args.to,
            )
            if code == args.code
        ),
        (),
    )
    output = [
        {
            "trade_date": bar.trade_date.isoformat(),
            "open": str(bar.open),
            "high": str(bar.high),
            "low": str(bar.low),
            "close": str(bar.close),
            "volume": str(bar.volume),
            "amount": str(bar.amount),
        }
        for bar in bars
        if args.from_date <= bar.trade_date <= args.to
    ]
    print(
        json.dumps(
            {
                "code": args.code,
                "snapshot_id": snapshot.snapshot_id,
                "bars_read": len(bars),
                "rows": output,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        pointer = md.get_formal_pointer()
        state_pointer = md.get_formal_state_pointer()
        snapshots = md._connection.execute(
            "SELECT snapshot_id, status, as_of FROM dataset_snapshots ORDER BY as_of"
        ).fetchall()
        generations = md._connection.execute(
            "SELECT generation_id, status, snapshot_id FROM state_generations ORDER BY generation_id"
        ).fetchall()
    payload = {
        "formal_snapshot_pointer": pointer,
        "formal_state_pointer": state_pointer,
        "snapshots": [
            {
                "snapshot_id": row[0],
                "status": row[1],
                "as_of": row[2].isoformat(),
            }
            for row in snapshots
        ],
        "state_generations": [
            {
                "generation_id": row[0],
                "status": row[1],
                "snapshot_id": row[2],
            }
            for row in generations
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _plan_json_codes(plan_json: Path) -> tuple[str, ...]:
    """Union of codes across plan/top/ambush/formed pools of a TradePlanOutput dump."""
    import os

    try:
        payload = json.loads(plan_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"PLAN_JSON_UNREADABLE:{plan_json}:{exc}") from exc
    codes: set[str] = set()
    for key in ("plans", "top_candidates", "ambush_watch_pool", "formed_b_point_pool"):
        for entry in payload.get(key) or []:
            code = entry.get("code") if isinstance(entry, dict) else None
            if isinstance(code, str) and code.isdigit() and len(code) == 6:
                codes.add(code)
    if not codes:
        raise ValueError("PLAN_JSON_NO_CODES:no 6-digit codes found")
    return tuple(sorted(codes))


def cmd_news_brief(args: argparse.Namespace) -> int:
    """Observation-layer news brief for a set of codes (ASL lake read-only)."""
    import os

    from limit_pullback.news_brief import build_news_brief, render_markdown

    codes: tuple[str, ...] = ()
    if args.plan_json:
        codes = _plan_json_codes(Path(args.plan_json))
    if args.codes:
        explicit = tuple(c.strip() for c in args.codes.split(",") if c.strip())
        codes = tuple(sorted(set(codes) | set(explicit)))
    if not codes:
        raise ValueError("NEWS_BRIEF_NO_CODES:pass --codes or --plan-json")
    db_path = Path(
        args.asl_db
        or os.environ.get("ASL_DB_PATH")
        or "/Users/luke808/AI/asl-shared/duckdb/ashare-lake.duckdb"
    )
    brief = build_news_brief(
        db_path=db_path,
        as_of=args.as_of,
        codes=codes,
        window_days=args.window_days,
    )
    print(brief.model_dump_json(indent=2))
    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "brief.json").write_text(
            brief.model_dump_json(indent=2) + chr(10), encoding="utf-8"
        )
        (out_dir / "brief.md").write_text(render_markdown(brief), encoding="utf-8")
    return 0


def _fmt(value) -> str:
    if value is None:
        return "-"
    text = str(value)
    if hasattr(value, "value"):
        return str(value.value)
    return text


def _render_watchlist_md(plan, brief, session: date) -> str:
    lines: list[str] = []
    lines.append(f"# 每日人工盯盘清单 — {session.isoformat()}")
    lines.append("")
    lines.append("> 机器生成，仅供人工决策；最终交易决定在系统外独立做出。")
    lines.append("")
    lines.append(f"- 快照: {plan.snapshot_id}")
    lines.append(f"- 计划日: {plan.plan_date.isoformat()}")
    lines.append(
        f"- 观察日: {plan.for_trade_date.isoformat() if plan.for_trade_date else 'null'}"
    )
    lines.append(
        f"- 可执行: {plan.actionable_count} / B1_PREP: {plan.b1_prep_count} / "
        f"B1_READY: {plan.b1_ready_count} / B2_READY: {plan.b2_ready_count} / "
        f"B2_CONFIRMED: {plan.b2_confirmed_count}"
    )
    if brief is not None:
        hits = {sn.code: len(sn.items) for sn in brief.symbol_news}
        lines.append(
            f"- 消息面命中: {sum(1 for n in hits.values() if n)} / {len(hits)} 只"
        )
    else:
        hits = {}
    if not plan.plans:
        lines.append("")
        lines.append("## NO_TRADE_DAY（无候选，不为交易强制选股）")
    if plan.top_candidates:
        lines.append("")
        lines.append("## 重点候选")
        lines.append("")
        lines.append(
            "| code | stage | label | buy_zone | preferred | trigger | invalid | 消息面 |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for p in plan.top_candidates:
            buy_zone = (
                f"{_fmt(p.buy_zone_low)}..{_fmt(p.buy_zone_high)}"
                if p.buy_zone_low is not None
                else "-"
            )
            lines.append(
                f"| {p.code} | {_fmt(p.setup_stage)} | {_fmt(p.execution_label)} | "
                f"{buy_zone} | {_fmt(p.preferred_entry)} | {_fmt(p.trigger_price)} | "
                f"{_fmt(p.invalid_price)} | {hits.get(p.code, 0)} |"
            )
    lines.append("")
    lines.append("## 消息面观察")
    lines.append("")
    if brief is not None:
        lines.append(f"- content_hash: {brief.content_hash}")
        lines.append(f"- 详情: 随附 brief.md（OBSERVATION 层）")
    else:
        lines.append("- 无候选标的，跳过消息面 brief。")
    return chr(10).join(lines) + chr(10)


def cmd_daily_run(args: argparse.Namespace) -> int:
    """Fail-closed daily orchestration:
    daily -> trade-plan -> news-brief -> fast-radar -> watchlist -> reconcile."""
    import os
    import time as _time

    from limit_pullback.news_brief import build_news_brief, render_markdown

    layout = _layout()
    session = args.date
    run_dir = layout.root / "tmp" / f"daily-run-{session:%Y%m%d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = []
    completed: list[str] = []

    def _finish_step(name: str, t0: float, ok: bool, detail: Any = None) -> None:
        steps.append(
            {
                "name": name,
                "wall_seconds": round(_time.time() - t0, 2),
                "ok": ok,
                "detail": detail,
            }
        )
        if ok:
            completed.append(name)

    def _fail(name: str, t0: float, exc: Exception) -> int:
        _finish_step(name, t0, False, repr(exc))
        (run_dir / "timing.json").write_text(
            json.dumps(
                {
                    "date": session.isoformat(),
                    "steps": steps,
                    "completed": completed,
                    "status": "FAILED",
                },
                ensure_ascii=False,
                indent=2,
            )
            + chr(10),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "error": {
                        "type": "DAILY_RUN_FAILED",
                        "step": name,
                        "message": repr(exc),
                        "completed": completed,
                    }
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    # 1. daily pipeline (fail-closed inside cmd_daily)
    name = "daily"
    t0 = _time.time()
    try:
        from types import SimpleNamespace

        rc = cmd_daily(SimpleNamespace(date=session))
        if rc != 0:
            raise ValueError(f"cmd_daily returned rc={rc}")
    except Exception as exc:
        return _fail(name, t0, exc)
    cache_root = layout.root / "tmp" / f"canonical-catchup-{session:%Y-%m-%d}"
    summary_path = cache_root / "daily-summary.json"
    if not summary_path.exists():
        return _fail(name, t0, ValueError("DAILY_SUMMARY_MISSING"))
    daily_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    snapshot_status = daily_summary.get("snapshot", {}).get("status")
    generation_status = daily_summary.get("generation", {}).get("status")
    sentinels = daily_summary.get("sentinel_checks") or []
    if snapshot_status != "SCREEN_READY":
        return _fail(name, t0, ValueError(f"SNAPSHOT_STATUS={snapshot_status}"))
    if generation_status != "ACTIVE":
        return _fail(name, t0, ValueError(f"GENERATION_STATUS={generation_status}"))
    if any(s.get("match") is not True for s in sentinels):
        return _fail(name, t0, ValueError("SENTINEL_CHECK_FAILED"))
    snapshot_id = daily_summary["snapshot"]["id"]
    _finish_step(
        name,
        t0,
        True,
        {"snapshot_id": snapshot_id, "generation_id": daily_summary["generation"]["id"]},
    )

    # 2. trade-plan
    name = "trade-plan"
    t0 = _time.time()
    try:
        from limit_pullback.config import load_strategy_config, load_trade_plan_config
        from limit_pullback.trade_plan import build_trade_plan_output
        from limit_pullback.warehouse.parquet import sha256_file

        plan = build_trade_plan_output(
            layout=layout,
            as_of=session,
            snapshot_id=snapshot_id,
            config=load_strategy_config(STRATEGY_CONFIG),
            config_hash=sha256_file(STRATEGY_CONFIG),
            trade_plan_config=load_trade_plan_config(
                ROOT / "config" / "trade_plan.yaml"
            ),
            execution_config_hash=sha256_file(ROOT / "config" / "trade_plan.yaml"),
        )
    except Exception as exc:
        return _fail(name, t0, exc)
    (run_dir / "plan.json").write_text(
        plan.model_dump_json(indent=2) + chr(10), encoding="utf-8"
    )
    _finish_step(
        name,
        t0,
        True,
        {
            "actionable": plan.actionable_count,
            "b1_prep": plan.b1_prep_count,
            "plans": len(plan.plans),
        },
    )

    # 3. news-brief (observation layer; explicit N/A when data is missing)
    name = "news-brief"
    t0 = _time.time()
    codes = tuple(sorted({p.code for p in plan.plans}))
    brief = None
    if not codes:
        _finish_step(name, t0, True, "no candidates; brief skipped")
    else:
        try:
            db_path = Path(
                os.environ.get("ASL_DB_PATH")
                or "/Users/luke808/AI/asl-shared/duckdb/ashare-lake.duckdb"
            )
            brief = build_news_brief(
                db_path=db_path,
                as_of=session,
                codes=codes,
                window_days=getattr(args, "window_days", 3) or 3,
            )
        except Exception as exc:
            return _fail(name, t0, exc)
        (run_dir / "brief.json").write_text(
            brief.model_dump_json(indent=2) + chr(10), encoding="utf-8"
        )
        (run_dir / "brief.md").write_text(render_markdown(brief), encoding="utf-8")
        _finish_step(name, t0, True, {"matched": brief.symbols_matched})

    # 4. fast-radar (observation layer: whole-market asl fast radar)
    name = "fast-radar"
    t0 = _time.time()
    radar_md = ""
    try:
        from limit_pullback.fast_radar import (
            render_radar_markdown,
            run_fast_radar,
        )

        radar = run_fast_radar(as_of=session, top=args.radar_top or 30)
        (run_dir / "fast-radar.json").write_text(
            json.dumps(radar, ensure_ascii=False, indent=2) + chr(10),
            encoding="utf-8",
        )
        radar_md = render_radar_markdown(radar)
        (run_dir / "fast-radar.md").write_text(radar_md, encoding="utf-8")
        _finish_step(
            name, t0, True, {"screen_n": radar.get("screen_n"), "limitup_n": radar.get("limitup_n")}
        )
    except Exception as exc:
        return _fail(name, t0, exc)

    # 5. watchlist markdown
    name = "watchlist"
    t0 = _time.time()
    try:
        watch_md = _render_watchlist_md(plan, brief, session)
        if radar_md:
            watch_md += chr(10) + radar_md
        (run_dir / "watchlist.md").write_text(watch_md, encoding="utf-8")
        review_dir = ROOT / "research" / "daily-review"
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / f"{session.isoformat()}-HUMAN-WATCH.md").write_text(
            watch_md, encoding="utf-8"
        )
    except Exception as exc:
        return _fail(name, t0, exc)
    _finish_step(name, t0, True)

    # 6. pointer consistency recheck (reconciliation receipt)
    name = "reconcile"
    t0 = _time.time()
    try:
        with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
            pointer = md.get_formal_pointer()
            state_pointer = md.get_formal_state_pointer()
        snapshot_pointer_id = pointer[0] if isinstance(pointer, (list, tuple)) else pointer
        if snapshot_pointer_id != snapshot_id:
            return _fail(name, t0, ValueError(f"SNAPSHOT_POINTER_MISMATCH:{pointer}"))
        if state_pointer != daily_summary["generation"]["id"]:
            return _fail(
                name, t0, ValueError(f"STATE_POINTER_MISMATCH:{state_pointer}")
            )
    except Exception as exc:
        return _fail(name, t0, exc)
    _finish_step(name, t0, True, {"snapshot": pointer, "state": state_pointer})

    (run_dir / "timing.json").write_text(
        json.dumps(
            {
                "date": session.isoformat(),
                "steps": steps,
                "completed": completed,
                "status": "OK",
            },
            ensure_ascii=False,
            indent=2,
        )
        + chr(10),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "date": session.isoformat(),
                "status": "OK",
                "steps": steps,
                "outputs": {
                    "run_dir": str(run_dir),
                    "watchlist": str(review_dir / f"{session.isoformat()}-HUMAN-WATCH.md"),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ops")
    sub = parser.add_subparsers(dest="command", required=True)

    daily = sub.add_parser("daily")
    daily.add_argument("date", type=_date)
    daily.set_defaults(func=cmd_daily)

    daily_run = sub.add_parser("daily-run")
    daily_run.add_argument("date", type=_date)
    daily_run.add_argument("--window-days", type=int, default=3)
    daily_run.add_argument("--radar-top", type=int, default=30)
    daily_run.set_defaults(func=cmd_daily_run)

    verify = sub.add_parser("verify-full")
    verify.add_argument("date", type=_date)
    verify.add_argument("--snapshot-id")
    verify.add_argument("--from-generation")
    verify.add_argument("--resolve-only", action="store_true")
    verify.set_defaults(func=cmd_verify_full)

    replay = sub.add_parser("replay")
    replay.add_argument("code")
    replay.add_argument("--from", dest="from_date", type=_date, required=True)
    replay.add_argument("--to", dest="to", type=_date, required=True)
    replay.add_argument("--snapshot-id")
    replay.set_defaults(func=cmd_replay)

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    news_brief = sub.add_parser("news-brief")
    news_brief.add_argument("--as-of", type=_date, required=True)
    news_brief.add_argument("--codes", help="comma-separated 6-digit codes")
    news_brief.add_argument("--plan-json", help="TradePlanOutput JSON dump")
    news_brief.add_argument("--asl-db")
    news_brief.add_argument("--window-days", type=int, default=3)
    news_brief.add_argument("--out-dir", help="also write brief.json + brief.md")
    news_brief.set_defaults(func=cmd_news_brief)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
