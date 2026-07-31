"""Market-wide screen runner with incremental/rebuild modes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from limit_pullback.config import load_strategy_config
from limit_pullback.models.replay import ReplayTimelineItem
from limit_pullback.models.signal import StrategySignal
from limit_pullback.screen.canonical import CanonicalMarketData, load_canonical_market
from limit_pullback.screen.engine import derive_status, screen_code
from limit_pullback.screen.models import ScreenRunResult
from limit_pullback.screen.state import load_state, save_state, state_path
from limit_pullback.screen.verify import (
    verify_rebuild_incremental,
    verify_single_stock_replay,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.parquet import sha256_file, write_json_atomic


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _digest(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _generated_at(as_of: date) -> datetime:
    return datetime.combine(as_of, time(23, 59, 59), tzinfo=timezone.utc)


def _bars_prefix_hash(bars, up_to: date) -> str:
    prefix = [
        (
            bar.trade_date.isoformat(),
            str(bar.open),
            str(bar.high),
            str(bar.low),
            str(bar.close),
            str(bar.preclose),
            str(bar.volume),
            str(bar.amount),
            str(bar.turnover_rate) if bar.turnover_rate is not None else None,
            str(bar.pct_change) if bar.pct_change is not None else None,
            bar.trade_status,
            bar.is_st,
        )
        for bar in bars
        if bar.trade_date <= up_to
    ]
    return _digest(json.dumps(prefix, sort_keys=True))


def _pool_prefix_hash(
    pool_records,
    pool_status: dict[tuple[str, date], str],
    up_to: date,
) -> str:
    prefix = [
        (
            record.code,
            record.trade_date.isoformat(),
            pool_status.get((record.code, record.trade_date), "PROVISIONAL"),
            str(record.limit_price),
            record.name,
        )
        for record in pool_records
        if record.trade_date <= up_to
    ]
    return _digest(json.dumps(prefix, sort_keys=True))


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "strategy.yaml"


def _status_counts(rows: list[tuple[str, list[ReplayTimelineItem]]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, code_rows in rows:
        statuses, _ = derive_status(code_rows)
        for status in statuses:
            counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _active_setups(rows: list[tuple[str, list[ReplayTimelineItem]]]) -> int:
    from limit_pullback.models.enums import SetupStage

    active = 0
    for _, code_rows in rows:
        if not code_rows:
            continue
        last = code_rows[-1]
        if last.setup_stage in {
            SetupStage.LIMIT_ANCHOR,
            SetupStage.WATCH_PULLBACK,
            SetupStage.B1_READY,
            SetupStage.B2_READY,
            SetupStage.B2_CONFIRMED,
        }:
            active += 1
    return active


def run_screen(
    *,
    layout: WarehouseLayout,
    as_of: date,
    snapshot_id: str | None = None,
    start: date | None = None,
    rebuild: bool = False,
    codes: Sequence[str] | None = None,
    config_path: str | Path | None = None,
    lookback_calendar_days: int = 400,
    verify_replay: bool = False,
    pool_debug: bool = False,
    clock: Callable[[], datetime] = _now_utc,
    strategy_commit: str | None = None,
) -> ScreenRunResult:
    """Run the offline screen over one canonical snapshot."""

    if rebuild and start is None:
        raise ValueError("--rebuild requires --start")
    if start is not None and start > as_of:
        raise ValueError("start cannot be after as_of")
    config_path = Path(config_path or _default_config_path())
    config = load_strategy_config(config_path)
    config_hash = sha256_file(config_path)
    commit = strategy_commit or _git_head()

    market = load_canonical_market(
        layout,
        snapshot_id=snapshot_id,
        as_of=None if snapshot_id else as_of,
    )
    if market.snapshot.as_of < as_of:
        raise ValueError(
            f"SNAPSHOT_AS_OF_BEFORE_REQUESTED: {market.snapshot.as_of} < {as_of}"
        )
    pool_mode = "debug" if pool_debug else "formal"
    resolved_snapshot_id = market.snapshot.snapshot_id
    requested = tuple(sorted({code.zfill(6) for code in (codes or ())}))
    universe = tuple(
        code for code in market.universe if not requested or code in requested
    )
    if not universe:
        raise ValueError("NO_CONFIRMED_DATA: snapshot has no CONFIRMED daily bars")

    kind = "rebuild" if rebuild else "incremental"
    run_id = (
        f"screen-{kind}-{as_of.isoformat()}-"
        f"{resolved_snapshot_id[:12]}-"
        f"{_digest(start, requested, commit, config_hash, pool_mode)[:12]}"
    )
    output_path = layout.root / "screen" / "runs" / f"{run_id}.json"
    cached_exists = output_path.exists()
    states_root = layout.root / "screen" / "states"
    states_root.mkdir(parents=True, exist_ok=True)
    layout.root.joinpath("screen", "runs").mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        cached = json.loads(output_path.read_text(encoding="utf-8"))
        if verify_replay and cached.get("verify_replay_matched") is not True:
            # A cached run must not claim verification it never performed.
            # Fall through and recompute (same run_id overwrites atomically).
            pass
        else:
            return ScreenRunResult(
                run_id=run_id,
                kind=kind,
                as_of=as_of,
                start=start,
                snapshot_id=resolved_snapshot_id,
                strategy_commit=commit,
                config_hash=config_hash,
                output_hash=cached.get("output_hash", ""),
                universe_size=len(universe),
                codes=universe,
                rows_count=int(cached.get("rows_count", 0)),
                status_counts=cached.get("status_counts", {}),
                new_anchor_count=int(cached.get("new_anchor_count", 0)),
                active_setup_count=int(cached.get("active_setup_count", 0)),
                entry_candidate_count=int(cached.get("entry_candidate_count", 0)),
                quality_rejection_count=int(cached.get("quality_rejection_count", 0)),
                verify_replay=verify_replay,
                verify_replay_matched=cached.get("verify_replay_matched"),
                pool_mode=pool_mode,
                reused=True,
                output_path=str(output_path),
                state_path=str(states_root),
            )

    generated_at = _generated_at(as_of)
    per_code_rows: list[tuple[str, list[ReplayTimelineItem]]] = []
    processed_at = clock()
    verified = True
    notes: list[str] = []
    if pool_mode == "debug":
        notes.append("LIMIT_POOL_DEBUG_MODE:PROVISIONAL_POOL_ALLOWED")
    elif any(status == "PROVISIONAL" for status in market.pool_status.values()):
        notes.append("LIMIT_POOL_PROVISIONAL_BLOCKED_FORMAL")
    if cached_exists and verify_replay:
        notes.append("CACHE_REVERIFY")
    for code in universe:
        bars = market.bars_by_code.get(code, ())
        if not bars:
            continue
        state = None if rebuild else load_state(state_path(layout.root, code))
        previous_signal: StrategySignal | None = None
        last_processed: date | None = None
        if state is not None:
            stale = (
                state.strategy_commit != commit
                or state.config_hash != config_hash
                or state.reconciliation_policy_version
                != market.snapshot.reconciliation_policy_version
                or state.bars_prefix_hash
                != _bars_prefix_hash(bars, state.last_processed_date)
                or state.limit_pool_prefix_hash
                != _pool_prefix_hash(
                    market.pool_records,
                    market.pool_status,
                    state.last_processed_date,
                )
            )
            if stale:
                state = None
                notes.append(f"STATE_INVALIDATED:{code}")
            else:
                previous_signal = StrategySignal.model_validate_json(
                    state.signal_json
                )
                last_processed = state.last_processed_date
        rows, final_signal = screen_code(
            code=code,
            bars=bars,
            pool_records=market.pool_records,
            config=config,
            start_date=start if rebuild else None,
            as_of=as_of,
            generated_at=generated_at,
            previous_signal=previous_signal,
            last_processed=last_processed,
            pool_status=market.pool_status,
            pool_mode=pool_mode,
        )
        if final_signal is not None:
            save_state(
                state_path(layout.root, code),
                code=code,
                last_processed_date=min(final_signal.trade_date, as_of),
                signal=final_signal,
                snapshot_id=resolved_snapshot_id,
                bars_prefix_hash=_bars_prefix_hash(
                    bars, min(final_signal.trade_date, as_of)
                ),
                limit_pool_prefix_hash=_pool_prefix_hash(
                    market.pool_records,
                    market.pool_status,
                    min(final_signal.trade_date, as_of),
                ),
                strategy_commit=commit,
                config_hash=config_hash,
                reconciliation_policy_version=(
                    market.snapshot.reconciliation_policy_version
                ),
                processed_at=processed_at,
            )
        per_code_rows.append((code, list(rows)))
        if verify_replay:
            mismatches = verify_rebuild_incremental(
                code=code,
                bars=bars,
                pool_records=market.pool_records,
                config=config,
                start=start or min((bar.trade_date for bar in bars), default=as_of),
                as_of=as_of,
                generated_at=generated_at,
                incremental_rows=rows,
                pool_status=market.pool_status,
                pool_mode=pool_mode,
            )
            if mismatches:
                verified = False
                raise ValueError(
                    f"rebuild/incremental mismatch for {code}: {mismatches[0]}"
                )
            replay_mismatches = verify_single_stock_replay(
                market=market,
                code=code,
                config=config,
                start=start or min((bar.trade_date for bar in bars), default=as_of),
                as_of=as_of,
                lookback_calendar_days=lookback_calendar_days,
                generated_at=generated_at,
                screen_rows=rows,
                pool_mode=pool_mode,
            )
            if replay_mismatches:
                verified = False
                raise ValueError(
                    f"screen/replay mismatch for {code}: {replay_mismatches[0]}"
                )

    row_payload = [
        {"code": code, **item.model_dump(mode="json")}
        for code, code_rows in per_code_rows
        for item in code_rows
    ]
    row_payload.sort(key=lambda item: (item["code"], item["trade_date"]))
    output_hash = _digest(json.dumps(row_payload, sort_keys=True, ensure_ascii=False))
    counts = _status_counts(per_code_rows)
    new_anchors = sum(
        derive_status(code_rows)[1] for _, code_rows in per_code_rows
    )
    active = _active_setups(per_code_rows)
    entry_candidates = sum(
        1
        for _, code_rows in per_code_rows
        for row in code_rows
        if row.is_entry_candidate
    )
    quality_rejections = sum(
        1
        for _, code_rows in per_code_rows
        for row in code_rows
        if (
            row.data_quality.value == "UNUSABLE"
            or "INSUFFICIENT_TRADING_HISTORY" in row.quality_flags
        )
    )
    manifest = {
        "run_id": run_id,
        "kind": kind,
        "as_of": as_of.isoformat(),
        "start": start.isoformat() if start else None,
        "snapshot_id": resolved_snapshot_id,
        "strategy_commit": commit,
        "config_hash": config_hash,
        "dataset_snapshot_id": resolved_snapshot_id,
        "output_hash": output_hash,
        "rows_count": len(row_payload),
        "created_at": processed_at.isoformat(),
        "status_counts": counts,
        "new_anchor_count": new_anchors,
        "active_setup_count": active,
        "entry_candidate_count": entry_candidates,
        "quality_rejection_count": quality_rejections,
        "verify_replay_matched": verified if verify_replay else None,
        "pool_mode": pool_mode,
        "notes": notes,
        "universe_size": len(universe),
        "codes": universe,
        "rows": row_payload,
    }
    write_json_atomic(manifest, output_path)
    return ScreenRunResult(
        run_id=run_id,
        kind=kind,
        as_of=as_of,
        start=start,
        snapshot_id=resolved_snapshot_id,
        strategy_commit=commit,
        config_hash=config_hash,
        output_hash=output_hash,
        universe_size=len(universe),
        codes=universe,
        rows_count=len(row_payload),
        status_counts=counts,
        new_anchor_count=new_anchors,
        active_setup_count=active,
        entry_candidate_count=entry_candidates,
        quality_rejection_count=quality_rejections,
        verify_replay=verify_replay,
        verify_replay_matched=verified if verify_replay else None,
        pool_mode=pool_mode,
        reused=False,
        output_path=str(output_path),
        state_path=str(states_root),
        notes=tuple(notes),
    )
