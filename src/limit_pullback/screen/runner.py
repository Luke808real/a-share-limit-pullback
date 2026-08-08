"""Market-wide screen runner with incremental/rebuild modes."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from limit_pullback.config import load_strategy_config
from limit_pullback.models.enums import SetupStage
from limit_pullback.models.replay import ReplayTimelineItem
from limit_pullback.models.signal import StrategySignal
from limit_pullback.screen.canonical import (
    CanonicalMarketData,
    canonical_universe_codes,
    iter_canonical_code_bars,
    load_canonical_metadata,
)
from limit_pullback.screen.engine import derive_status, screen_code
from limit_pullback.screen.models import ScreenRunResult
from limit_pullback.screen.state import load_state, save_state
from limit_pullback.screen.verify import (
    verify_rebuild_incremental,
    verify_single_stock_replay,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import sha256_file, write_json_atomic
from limit_pullback.warehouse.snapshot import (
    require_state_snapshot_usable,
    snapshot_status_map,
)


def _stream_merge_chunk_spools(
    spool_dir: Path,
    run_id: str,
    indexes: Sequence[int],
    spool_path: Path,
) -> None:
    """Stream-concatenate chunk spools in chunk-index order into ONE final
    spool, atomically (temp file + fsync + os.replace; cleanup on failure).

    Ordering contract: requested/universe codes are a sorted-unique tuple and
    chunks are contiguous slices of it, so chunk-index concatenation
    reproduces the global (code, trade_date) order WITHOUT materializing
    every row in Python or performing a global sort.
    """

    spool_dir.mkdir(parents=True, exist_ok=True)
    temporary = spool_path.with_name(f".{spool_path.name}.tmp-{uuid4().hex}")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            for index in indexes:
                chunk_spool = spool_dir / f"{run_id}.{index}.rows.jsonl"
                with chunk_spool.open("r", encoding="utf-8") as chunk:
                    for line in chunk:
                        line = line.strip()
                        if not line:
                            continue
                        stream.write(line + "\n")
                chunk_spool.unlink(missing_ok=True)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, spool_path)
        with spool_path.open("rb") as handle:
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class ScreenFailpointError(RuntimeError):
    """Raised at requested screen state-write failpoints (fault injection)."""


_SCREEN_FAILPOINT_STATE = {"saves": 0}


def _raise_screen_failpoint(failpoint: str | None, path: Path | None) -> None:
    if failpoint is None:
        return
    if failpoint == "after_all_states" and path is None:
        raise ScreenFailpointError(failpoint)
    if path is None:
        return
    _SCREEN_FAILPOINT_STATE["saves"] += 1
    saves = _SCREEN_FAILPOINT_STATE["saves"]
    if failpoint == "after_first_state_batch" and saves == 1:
        raise ScreenFailpointError(failpoint)
    if failpoint == "mid_state_write" and saves == 2:
        raise ScreenFailpointError(failpoint)


def _write_compact_output(
    *,
    metadata: dict[str, Any],
    spool_path: Path,
    compact_output_path: Path,
    output_path: Path,
) -> None:
    """Write a columnar rows payload plus a small JSON manifest (no row embedding)."""

    import pyarrow as pa
    import pyarrow.parquet as pq
    from datetime import date as _date

    schema = pa.schema(
        [
            pa.field("code", pa.string()),
            pa.field("trade_date", pa.date32()),
            pa.field("payload", pa.string()),
        ]
    )
    compact_output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(
        compact_output_path,
        schema,
        compression="zstd",
    )
    batch_rows: list[dict[str, Any]] = []
    hash_obj = hashlib.sha256()
    first = True
    count = 0
    with spool_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            payload = json.dumps(row, sort_keys=True, ensure_ascii=False)
            batch_rows.append(
                {
                    "code": str(row["code"]),
                    "trade_date": _date.fromisoformat(
                        str(row["trade_date"])[:10]
                    ),
                    "payload": payload,
                }
            )
            if first:
                hash_obj.update(b"[")
                first = False
            else:
                hash_obj.update(b", ")
            hash_obj.update(payload.encode("utf-8"))
            count += 1
            if len(batch_rows) >= 50000:
                writer.write_table(
                    pa.Table.from_pylist(batch_rows, schema=schema)
                )
                batch_rows = []
    if batch_rows:
        writer.write_table(pa.Table.from_pylist(batch_rows, schema=schema))
    writer.close()
    hash_obj.update(b"]")
    meta = dict(metadata)
    meta.pop("rows", None)
    meta["compact_output_path"] = compact_output_path.name
    meta["compact_output_row_n"] = count
    meta["compact_roundtrip_hash"] = hash_obj.hexdigest()
    meta["compact_roundtrip_hash_match"] = (
        hash_obj.hexdigest() == metadata.get("output_hash")
    )
    write_json_atomic(meta, output_path)


def _spool_output_hash(spool_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"[")
    first = True
    with spool_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            if first:
                first = False
            else:
                digest.update(b", ")
            digest.update(line.encode("utf-8"))
    digest.update(b"]")
    return digest.hexdigest()


_SCREEN_WORKER_STATE: tuple[dict[str, Any], tuple, dict] | None = None


def _init_screen_worker(
    ctx: dict[str, Any],
    pool_records: tuple,
    pool_status: dict,
) -> None:
    global _SCREEN_WORKER_STATE
    _SCREEN_WORKER_STATE = (ctx, pool_records, pool_status)
    os.environ["LIMIT_PULLBACK_CANONICAL_READER_MEMORY_LIMIT"] = "512MB"


def _screen_chunk_worker(
    codes: tuple[str, ...],
    chunk_spool: str,
) -> dict[str, Any]:
    """Run the exact per-code screen loop for one code chunk in a child."""

    ctx, pool_records, pool_status = _SCREEN_WORKER_STATE
    layout = WarehouseLayout(ctx["layout_root"])
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(ctx["snapshot_id"])
    if snapshot is None:
        raise ValueError(f"unknown snapshot: {ctx['snapshot_id']}")
    config = load_strategy_config(ctx["config_path"])
    as_of = ctx["as_of"]
    start = ctx["start"]
    rebuild = ctx["rebuild"]
    commit = ctx["commit"]
    config_hash = ctx["config_hash"]
    generated_at = ctx["generated_at"]
    processed_at = ctx["processed_at"]
    states_root = Path(ctx["states_root"])
    pool_mode = ctx["pool_mode"]
    status_by_snapshot = None if rebuild else snapshot_status_map(layout)
    chunk_spool_path = Path(chunk_spool)
    chunk_spool_path.parent.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    status_counts: dict[str, int] = {}
    new_anchors = 0
    active = 0
    entry_candidates = 0
    quality_rejections = 0
    rows_count = 0
    with chunk_spool_path.open("w", encoding="utf-8") as spool_file:
        for code, bars in iter_canonical_code_bars(
            layout,
            snapshot,
            codes=codes,
            as_of=as_of,
        ):
            state = (
                None
                if rebuild
                else load_state(states_root / f"{code}.json")
            )
            if state is not None:
                require_state_snapshot_usable(
                    status_by_snapshot or {},
                    snapshot_id=state.snapshot_id,
                    as_of=state.last_processed_date,
                )
            previous_signal: StrategySignal | None = None
            last_processed: date | None = None
            if state is not None:
                stale = (
                    state.strategy_commit != commit
                    or state.config_hash != config_hash
                    or state.reconciliation_policy_version
                    != snapshot.reconciliation_policy_version
                    or state.last_processed_date > as_of
                    or state.bars_prefix_hash
                    != _bars_prefix_hash(bars, state.last_processed_date)
                    or state.limit_pool_prefix_hash
                    != _pool_prefix_hash(
                        pool_records,
                        pool_status,
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
                    if (
                        previous_signal.trade_date != state.last_processed_date
                        or previous_signal.trade_date > as_of
                    ):
                        state = None
                        previous_signal = None
                        notes.append(f"STATE_INVALIDATED:{code}")
                    else:
                        last_processed = state.last_processed_date
            rows, final_signal = screen_code(
                code=code,
                bars=bars,
                pool_records=pool_records,
                config=config,
                start_date=start if rebuild else None,
                as_of=as_of,
                generated_at=generated_at,
                previous_signal=previous_signal,
                last_processed=last_processed,
                pool_status=pool_status,
                pool_mode=pool_mode,
            )
            if final_signal is not None:
                save_state(
                    states_root / f"{code}.json",
                    code=code,
                    last_processed_date=min(final_signal.trade_date, as_of),
                    signal=final_signal,
                    snapshot_id=ctx["resolved_snapshot_id"],
                    bars_prefix_hash=_bars_prefix_hash(
                        bars, min(final_signal.trade_date, as_of)
                    ),
                    limit_pool_prefix_hash=_pool_prefix_hash(
                        pool_records,
                        pool_status,
                        min(final_signal.trade_date, as_of),
                    ),
                    strategy_commit=commit,
                    config_hash=config_hash,
                    reconciliation_policy_version=(
                        snapshot.reconciliation_policy_version
                    ),
                    processed_at=processed_at,
                )
            statuses, new_anchor = derive_status(rows)
            for status in statuses:
                status_counts[status] = status_counts.get(status, 0) + 1
            new_anchors += new_anchor
            active += _active_setup_from_code_rows(rows)
            entry_candidates += sum(
                1 for row in rows if row.is_entry_candidate
            )
            quality_rejections += sum(
                1
                for row in rows
                if (
                    row.data_quality.value == "UNUSABLE"
                    or "INSUFFICIENT_TRADING_HISTORY" in row.quality_flags
                )
            )
            for item in rows:
                row_dict = {"code": code, **item.model_dump(mode="json")}
                spool_file.write(
                    json.dumps(row_dict, sort_keys=True, ensure_ascii=False)
                    + "\n"
                )
                rows_count += 1
    return {
        "status_counts": status_counts,
        "new_anchors": new_anchors,
        "active": active,
        "entry_candidates": entry_candidates,
        "quality_rejections": quality_rejections,
        "notes": notes,
        "rows_count": rows_count,
    }


def _run_screen_parallel(
    *,
    layout: WarehouseLayout,
    snapshot,
    requested: tuple[str, ...],
    as_of: date,
    start: date | None,
    rebuild: bool,
    config_path: Path,
    config_hash: str,
    commit: str,
    pool_records,
    pool_status,
    states_root: Path,
    spool_path: Path,
    run_id: str,
    generated_at: datetime,
    processed_at: datetime,
    pool_mode: str,
    resolved_snapshot_id: str,
    workers: int = 4,
) -> tuple[
    tuple[str, ...],
    int,
    str,
    dict[str, int],
    int,
    int,
    int,
    int,
    list[str],
]:
    codes = tuple(requested) if requested else canonical_universe_codes(
        layout,
        snapshot,
    )
    if not codes:
        raise ValueError("NO_CONFIRMED_DATA: snapshot has no CONFIRMED daily bars")
    # Ordering invariant for bounded chunk-spool concatenation: codes must be
    # sorted ascending and unique (requested is normalized to sorted(set(...))
    # by run_screen; canonical_universe_codes is ORDER BY code).  Chunks are
    # contiguous slices of this tuple.
    if codes != tuple(sorted(set(codes))):
        raise ValueError(
            "SCREEN_CODES_NOT_SORTED_UNIQUE: screen codes must be sorted "
            "ascending and unique"
        )
    worker_count = max(1, min(workers, len(codes), os.cpu_count() or 1))
    chunk_size = (len(codes) + worker_count - 1) // worker_count
    chunks = [
        codes[index : index + chunk_size]
        for index in range(0, len(codes), chunk_size)
    ]
    spool_dir = spool_path.parent
    spool_dir.mkdir(parents=True, exist_ok=True)
    ctx = {
        "layout_root": str(layout.root),
        "snapshot_id": snapshot.snapshot_id,
        "as_of": as_of,
        "start": start,
        "rebuild": rebuild,
        "config_path": str(config_path),
        "commit": commit,
        "config_hash": config_hash,
        "generated_at": generated_at,
        "processed_at": processed_at,
        "states_root": str(states_root),
        "pool_mode": pool_mode,
        "resolved_snapshot_id": resolved_snapshot_id,
    }
    with ProcessPoolExecutor(
        max_workers=worker_count,
        initializer=_init_screen_worker,
        initargs=(ctx, tuple(pool_records), dict(pool_status)),
    ) as executor:
        futures = {
            executor.submit(
                _screen_chunk_worker,
                chunk,
                str(spool_dir / f"{run_id}.{index}.rows.jsonl"),
            ): index
            for index, chunk in enumerate(chunks)
        }
        results = [
            (index, future.result())
            for future, index in futures.items()
        ]
    results.sort(key=lambda item: item[0])

    # Bounded streaming merge: no all-row Python list, no global sort.
    # Chunk-index concatenation is equivalent to the previous global
    # (code, trade_date) sort by the ordering invariant above.
    _stream_merge_chunk_spools(
        spool_dir,
        run_id,
        [index for index, _result in results],
        spool_path,
    )
    output_hash = _spool_output_hash(spool_path)

    status_counts: dict[str, int] = {}
    new_anchors = 0
    active = 0
    entry_candidates = 0
    quality_rejections = 0
    rows_count = 0
    notes: list[str] = []
    for _index, result in results:
        for status, count in result["status_counts"].items():
            status_counts[status] = status_counts.get(status, 0) + count
        new_anchors += result["new_anchors"]
        active += result["active"]
        entry_candidates += result["entry_candidates"]
        quality_rejections += result["quality_rejections"]
        rows_count += result["rows_count"]
        notes.extend(result["notes"])
    notes.sort()
    return (
        codes,
        rows_count,
        output_hash,
        status_counts,
        new_anchors,
        active,
        entry_candidates,
        quality_rejections,
        notes,
    )


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


def _active_setup_from_code_rows(rows: Sequence[ReplayTimelineItem]) -> int:
    if not rows:
        return 0
    last = rows[-1]
    if last.setup_stage in {
        SetupStage.LIMIT_ANCHOR,
        SetupStage.WATCH_PULLBACK,
        SetupStage.B1_READY,
        SetupStage.B2_READY,
        SetupStage.B2_CONFIRMED,
    }:
        return 1
    return 0


def _write_streaming_manifest(
    *,
    metadata_with_rows: dict[str, Any],
    spool_path: Path,
    output_path: Path,
) -> None:
    import os

    meta = dict(metadata_with_rows)
    meta.setdefault("rows", None)
    temporary = output_path.with_name(f".{output_path.name}.tmp-stream")
    with temporary.open("w", encoding="utf-8") as stream:
        keys = sorted(meta)
        stream.write("{\n")
        with spool_path.open("r", encoding="utf-8") as spool:
            first_row = True
            for key_index, key in enumerate(keys):
                stream.write(f"  {json.dumps(key)}: ")
                if key == "rows":
                    stream.write("[\n")
                    for line in spool:
                        line = line.strip()
                        if not line:
                            continue
                        if not first_row:
                            stream.write(",\n")
                        stream.write("    " + line)
                        first_row = False
                    stream.write("\n  ]")
                else:
                    stream.write(json.dumps(meta[key], ensure_ascii=False))
                if key_index < len(keys) - 1:
                    stream.write(",\n")
                else:
                    stream.write("\n")
        stream.write("}\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output_path)


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
    manifest_path_override: Path | None = None,
    states_root: Path | None = None,
    compact_output_path: Path | None = None,
    failpoint: str | None = None,
) -> ScreenRunResult:
    """Run the offline screen over one canonical snapshot."""

    _SCREEN_FAILPOINT_STATE["saves"] = 0
    if rebuild and start is None:
        raise ValueError("--rebuild requires --start")
    if start is not None and start > as_of:
        raise ValueError("start cannot be after as_of")
    config_path = Path(config_path or _default_config_path())
    config = load_strategy_config(config_path)
    config_hash = sha256_file(config_path)
    commit = strategy_commit or _git_head()
    requested = tuple(sorted({code.zfill(6) for code in (codes or ())}))

    snapshot, pool_records, pool_status = load_canonical_metadata(
        layout,
        snapshot_id=snapshot_id,
        as_of=None if snapshot_id else as_of,
    )
    if snapshot.as_of < as_of:
        raise ValueError(
            f"SNAPSHOT_AS_OF_BEFORE_REQUESTED: {snapshot.as_of} < {as_of}"
        )
    pool_mode = "debug" if pool_debug else "formal"
    resolved_snapshot_id = snapshot.snapshot_id
    status_by_snapshot = None if rebuild else snapshot_status_map(layout)

    kind = "rebuild" if rebuild else "incremental"
    run_id = (
        f"screen-{kind}-{as_of.isoformat()}-"
        f"{resolved_snapshot_id[:12]}-"
        f"{_digest(start, requested, commit, config_hash, pool_mode)[:12]}"
    )
    output_path = (
        manifest_path_override
        or layout.root / "screen" / "runs" / f"{run_id}.json"
    )
    cached_exists = output_path.exists()
    states_root = states_root or (layout.root / "screen" / "states")
    states_root.mkdir(parents=True, exist_ok=True)
    layout.root.joinpath("screen", "runs").mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and manifest_path_override is None:
        cached = json.loads(output_path.read_text(encoding="utf-8"))
        cached_codes = tuple(cached.get("codes", ()))
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
                universe_size=len(cached_codes),
                codes=cached_codes,
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
    processed_at = clock()
    verified = True
    notes: list[str] = []
    if pool_mode == "debug":
        notes.append("LIMIT_POOL_DEBUG_MODE:PROVISIONAL_POOL_ALLOWED")
    elif any(status == "PROVISIONAL" for status in pool_status.values()):
        notes.append("LIMIT_POOL_PROVISIONAL_BLOCKED_FORMAL")
    if cached_exists and verify_replay:
        notes.append("CACHE_REVERIFY")
    spool_dir = layout.root / "screen" / "runs" / ".tmp"
    spool_dir.mkdir(parents=True, exist_ok=True)
    spool_path = spool_dir / f"{run_id}.rows.jsonl"
    status_counts: dict[str, int] = {}
    new_anchors = 0
    active = 0
    entry_candidates = 0
    quality_rejections = 0
    rows_count = 0
    hash_obj = hashlib.sha256()
    first_row = True
    spool_file = None
    universe: list[str] = []
    parallel = (
        not verify_replay
        and failpoint is None
        and (os.cpu_count() or 1) >= 2
    )
    if parallel:
        (
            universe_tuple,
            rows_count,
            output_hash,
            status_counts,
            new_anchors,
            active,
            entry_candidates,
            quality_rejections,
            parallel_notes,
        ) = _run_screen_parallel(
            layout=layout,
            snapshot=snapshot,
            requested=requested,
            as_of=as_of,
            start=start,
            rebuild=rebuild,
            config_path=config_path,
            config_hash=config_hash,
            commit=commit,
            pool_records=pool_records,
            pool_status=pool_status,
            states_root=states_root,
            spool_path=spool_path,
            run_id=run_id,
            generated_at=generated_at,
            processed_at=processed_at,
            pool_mode=pool_mode,
            resolved_snapshot_id=resolved_snapshot_id,
        )
        notes.extend(parallel_notes)
        counts = dict(sorted(status_counts.items()))
        if not universe_tuple:
            raise ValueError(
                "NO_CONFIRMED_DATA: snapshot has no CONFIRMED daily bars"
            )
    else:
        try:
            spool_file = spool_path.open("w", encoding="utf-8")
            for code, bars in iter_canonical_code_bars(
                layout,
                snapshot,
                codes=requested or None,
                as_of=as_of,
            ):
                universe.append(code)
                state = (
                    None
                    if rebuild
                    else load_state(states_root / f"{code}.json")
                )
                if state is not None:
                    require_state_snapshot_usable(
                        status_by_snapshot or {},
                        snapshot_id=state.snapshot_id,
                        as_of=state.last_processed_date,
                    )
                previous_signal: StrategySignal | None = None
                last_processed: date | None = None
                if state is not None:
                    stale = (
                        state.strategy_commit != commit
                        or state.config_hash != config_hash
                        or state.reconciliation_policy_version
                        != snapshot.reconciliation_policy_version
                        or state.last_processed_date > as_of
                        or state.bars_prefix_hash
                        != _bars_prefix_hash(
                            bars, state.last_processed_date
                        )
                        or state.limit_pool_prefix_hash
                        != _pool_prefix_hash(
                            pool_records,
                            pool_status,
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
                        if (
                            previous_signal.trade_date
                            != state.last_processed_date
                            or previous_signal.trade_date > as_of
                        ):
                            state = None
                            previous_signal = None
                            notes.append(f"STATE_INVALIDATED:{code}")
                        else:
                            last_processed = state.last_processed_date
                rows, final_signal = screen_code(
                    code=code,
                    bars=bars,
                    pool_records=pool_records,
                    config=config,
                    start_date=start if rebuild else None,
                    as_of=as_of,
                    generated_at=generated_at,
                    previous_signal=previous_signal,
                    last_processed=last_processed,
                    pool_status=pool_status,
                    pool_mode=pool_mode,
                )
                if final_signal is not None:
                    save_state(
                        states_root / f"{code}.json",
                        code=code,
                        last_processed_date=min(
                            final_signal.trade_date, as_of
                        ),
                        signal=final_signal,
                        snapshot_id=resolved_snapshot_id,
                        bars_prefix_hash=_bars_prefix_hash(
                            bars, min(final_signal.trade_date, as_of)
                        ),
                        limit_pool_prefix_hash=_pool_prefix_hash(
                            pool_records,
                            pool_status,
                            min(final_signal.trade_date, as_of),
                        ),
                        strategy_commit=commit,
                        config_hash=config_hash,
                        reconciliation_policy_version=(
                            snapshot.reconciliation_policy_version
                        ),
                        processed_at=processed_at,
                    )
                    _raise_screen_failpoint(
                        failpoint, states_root / f"{code}.json"
                    )
                if verify_replay:
                    mismatches = verify_rebuild_incremental(
                        code=code,
                        bars=bars,
                        pool_records=pool_records,
                        config=config,
                        start=start
                        or min(
                            (bar.trade_date for bar in bars),
                            default=as_of,
                        ),
                        as_of=as_of,
                        generated_at=generated_at,
                        incremental_rows=rows,
                        pool_status=pool_status,
                        pool_mode=pool_mode,
                    )
                    if mismatches:
                        verified = False
                        raise ValueError(
                            f"rebuild/incremental mismatch for {code}: "
                            f"{mismatches[0]}"
                        )
                    replay_mismatches = verify_single_stock_replay(
                        market=CanonicalMarketData(
                            snapshot=snapshot,
                            bars_by_code={code: bars},
                            pool_records=pool_records,
                            pool_status=pool_status,
                        ),
                        code=code,
                        config=config,
                        start=start
                        or min(
                            (bar.trade_date for bar in bars),
                            default=as_of,
                        ),
                        as_of=as_of,
                        lookback_calendar_days=lookback_calendar_days,
                        generated_at=generated_at,
                        screen_rows=rows,
                        pool_mode=pool_mode,
                    )
                    if replay_mismatches:
                        verified = False
                        raise ValueError(
                            f"screen/replay mismatch for {code}: "
                            f"{replay_mismatches[0]}"
                        )

                statuses, new_anchor = derive_status(rows)
                for status in statuses:
                    status_counts[status] = (
                        status_counts.get(status, 0) + 1
                    )
                new_anchors += new_anchor
                active += _active_setup_from_code_rows(rows)
                entry_candidates += sum(
                    1 for row in rows if row.is_entry_candidate
                )
                quality_rejections += sum(
                    1
                    for row in rows
                    if (
                        row.data_quality.value == "UNUSABLE"
                        or "INSUFFICIENT_TRADING_HISTORY"
                        in row.quality_flags
                    )
                )
                for item in rows:
                    row_dict = {"code": code, **item.model_dump(mode="json")}
                    row_text = json.dumps(
                        row_dict, sort_keys=True, ensure_ascii=False
                    )
                    spool_file.write(row_text + "\n")
                    if first_row:
                        hash_obj.update(b"[")
                        first_row = False
                    else:
                        hash_obj.update(b", ")
                    hash_obj.update(row_text.encode("utf-8"))
                    rows_count += 1
        except Exception:
            spool_path.unlink(missing_ok=True)
            raise
        finally:
            if spool_file is not None:
                spool_file.close()
        hash_obj.update(b"]")
        output_hash = hash_obj.hexdigest()
        _raise_screen_failpoint(failpoint, None)
        counts = dict(sorted(status_counts.items()))
        if not universe:
            raise ValueError(
                "NO_CONFIRMED_DATA: snapshot has no CONFIRMED daily bars"
            )
        universe_tuple = tuple(universe)
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
        "rows_count": rows_count,
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
        "codes": universe_tuple,
    }
    if compact_output_path is not None:
        _write_compact_output(
            metadata=manifest,
            spool_path=spool_path,
            compact_output_path=Path(compact_output_path),
            output_path=output_path,
        )
    else:
        _write_streaming_manifest(
            metadata_with_rows=manifest,
            spool_path=spool_path,
            output_path=output_path,
        )
    spool_path.unlink(missing_ok=True)
    return ScreenRunResult(
        run_id=run_id,
        kind=kind,
        as_of=as_of,
        start=start,
        snapshot_id=resolved_snapshot_id,
        strategy_commit=commit,
        config_hash=config_hash,
        output_hash=output_hash,
        universe_size=len(universe_tuple),
        codes=universe_tuple,
        rows_count=rows_count,
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
