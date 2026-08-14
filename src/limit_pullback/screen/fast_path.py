"""True incremental daily screen advance (bounded window, no full replay).

For each code:

    previous ACTIVE state + new canonical bars -> evaluate new bar only

History is read as a bounded window sized by the longest frozen indicator /
structure lookback (config.runtime daily_window_calendar_days), not the code's
full canonical history.  ``bars_prefix_hash_v2`` is an appendable chain hash,
so a new state does not require rescanning all bars just to re-hash.

When the required context is unavailable (missing/corrupt state, anchor older
than the window, incompatible version), only that code falls back to a full
history read; the rest of the universe stays on the fast path.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from limit_pullback.config import load_strategy_config
from limit_pullback.models.config import StrategyConfig
from limit_pullback.screen.canonical import (
    FIXED_FETCHED_AT,
    _canonical_daily_row_stream,
    _daily_bar_from_row,
    iter_canonical_code_bars,
    load_canonical_metadata,
)
from limit_pullback.screen.engine import (
    derive_status,
    screen_code,
)
from limit_pullback.screen.runner import (
    _active_setup_from_code_rows,
    _bars_prefix_hash,
    _bars_prefix_hash_chain,
    _extend_bars_prefix_hash_chain,
    _generated_at,
    _pool_prefix_hash,
    _spool_output_hash,
    _write_compact_output,
)
from limit_pullback.screen.state import load_state, save_state
from limit_pullback.universe import Phase2d0Universe
from limit_pullback.warehouse.layout import WarehouseLayout


@dataclass
class FastPathStats:
    fast_path_n: int = 0
    targeted_fallback_n: int = 0
    full_fallback_n: int = 0
    fallback_reasons: dict[str, int] = field(default_factory=dict)
    rows_scanned: int = 0
    rows_materialized: int = 0


def _digest(*parts: object) -> str:
    import hashlib

    return hashlib.sha256(
        "|".join(str(part) for part in parts).encode("utf-8")
    ).hexdigest()


def _bulk_window_bars(
    layout: WarehouseLayout,
    snapshot,
    *,
    codes: Sequence[str],
    since: date,
    as_of: date,
) -> dict[str, tuple]:
    """Load the bounded window for every code in ONE ordered stream query.

    Replaces the previous per-code ``canonical_code_bars_window`` calls
    (~2 DuckDB connections + queries per code per run) with a single
    memory-bounded ordered scan.  Per-code windows are sliced in memory, so
    the emitted bars are byte-identical to the per-code queries.
    """

    bars_by_code: dict[str, list] = {}
    for row in _canonical_daily_row_stream(
        layout,
        snapshot,
        codes=codes,
        as_of=as_of,
        since=since,
    ):
        bars_by_code.setdefault(str(row["code"]), []).append(
            _daily_bar_from_row(row, fetched_at=FIXED_FETCHED_AT)
        )
    return {
        code: tuple(sorted(bars, key=lambda bar: bar.trade_date))
        for code, bars in bars_by_code.items()
    }


def run_screen_fast(
    *,
    layout: WarehouseLayout,
    snapshot,
    universe: Phase2d0Universe,
    as_of: date,
    config_path: Path,
    config: StrategyConfig,
    commit: str,
    config_hash: str,
    states_root: Path,
    spool_path: Path,
    manifest_path: Path,
    compact_output_path: Path,
    generated_at: datetime,
    processed_at: datetime,
    pool_mode: str,
    window_calendar_days: int,
    verified_no_trade: Sequence[tuple[str, date]] = (),
    previous_commit: str | None = None,
    stats: FastPathStats | None = None,
    window_bars_by_code: dict[str, tuple] | None = None,
    full_bars_loader: Callable[[str], tuple] | None = None,
    pool_override: tuple | None = None,
    pool_status_override: Mapping[tuple[str, date], str] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Advance every universe code from its previous state; returns manifest.

    ``window_bars_by_code`` / ``full_bars_loader`` / ``pool_override`` /
    ``pool_status_override`` let callers substitute an external bar/pool
    source (e.g. the ASL lake) while keeping the exact same state machine and
    output contract.  When they are None the canonical snapshot is read via
    one bulk window query plus rare per-code full-history fallbacks.
    """

    stats = stats or FastPathStats()
    if pool_override is not None:
        pool_records = pool_override
        pool_status = dict(pool_status_override or {})
    else:
        _snapshot, pool_records, pool_status = load_canonical_metadata(
            layout,
            snapshot_id=snapshot.snapshot_id,
        )
    verified = set(verified_no_trade)
    if window_bars_by_code is None:
        window_bars_by_code = _bulk_window_bars(
            layout,
            snapshot,
            codes=universe.members,
            since=as_of - timedelta(days=window_calendar_days + 10),
            as_of=as_of,
        )

    def _full_bars_for(code: str) -> tuple:
        if full_bars_loader is not None:
            return full_bars_loader(code)
        return _full_bars(layout, snapshot, code, as_of)

    spool_dir = spool_path.parent
    spool_dir.mkdir(parents=True, exist_ok=True)
    spool_file = spool_path.open("w", encoding="utf-8")
    status_counts: Counter[str] = Counter()
    new_anchors = 0
    active = 0
    entry_candidates = 0
    quality_rejections = 0
    rows_count = 0
    notes: list[str] = []
    codes_done: list[str] = []

    try:
        for index, code in enumerate(universe.members):
            codes_done.append(code)
            if progress_cb is not None and (index + 1) % 250 == 0:
                progress_cb(index + 1, len(universe.members))
            state = load_state(states_root / f"{code}.json")
            full_bars: tuple | None = None
            fallback_reason: str | None = None

            if state is None:
                stats.full_fallback_n += 1
                stats.fallback_reasons["PREVIOUS_STATE_MISSING"] = (
                    stats.fallback_reasons.get("PREVIOUS_STATE_MISSING", 0) + 1
                )
                fallback_reason = "PREVIOUS_STATE_MISSING"
                full_bars = _full_bars_for(code)
                rows, final_signal = screen_code(
                    code=code,
                    bars=full_bars,
                    pool_records=pool_records,
                    config=config,
                    start_date=None,
                    as_of=as_of,
                    generated_at=generated_at,
                    previous_signal=None,
                    last_processed=None,
                    pool_status=pool_status,
                    pool_mode=pool_mode,
                )
                notes.append(f"FULL_FALLBACK:{code}:{fallback_reason}")
            else:
                previous_signal = _signal_from_state(state)
                last_processed = state.last_processed_date
                if (
                    previous_commit is not None
                    and state.strategy_commit != previous_commit
                ) or state.config_hash != config_hash:
                    stats.full_fallback_n += 1
                    stats.fallback_reasons["STATE_VERSION_MISMATCH"] = (
                        stats.fallback_reasons.get(
                            "STATE_VERSION_MISMATCH", 0
                        )
                        + 1
                    )
                    fallback_reason = "STATE_VERSION_MISMATCH"
                    full_bars = _full_bars_for(code)
                    rows, final_signal = screen_code(
                        code=code,
                        bars=full_bars,
                        pool_records=pool_records,
                        config=config,
                        start_date=None,
                        as_of=as_of,
                        generated_at=generated_at,
                        previous_signal=None,
                        last_processed=None,
                        pool_status=pool_status,
                        pool_mode=pool_mode,
                    )
                    notes.append(f"FULL_FALLBACK:{code}:{fallback_reason}")
                elif state.bars_prefix_hash_v2 is None:
                    stats.targeted_fallback_n += 1
                    stats.fallback_reasons["MISSING_PREFIX_HASH_V2"] = (
                        stats.fallback_reasons.get(
                            "MISSING_PREFIX_HASH_V2", 0
                        )
                        + 1
                    )
                    fallback_reason = "MISSING_PREFIX_HASH_V2"
                    full_bars = _full_bars_for(code)
                    rows, final_signal = screen_code(
                        code=code,
                        bars=full_bars,
                        pool_records=pool_records,
                        config=config,
                        start_date=None,
                        as_of=as_of,
                        generated_at=generated_at,
                        previous_signal=previous_signal,
                        last_processed=last_processed,
                        pool_status=pool_status,
                        pool_mode=pool_mode,
                    )
                    notes.append(
                        f"TARGETED_FALLBACK:{code}:{fallback_reason}"
                    )
                else:
                    code_bars = window_bars_by_code.get(code, ())
                    new_bars = tuple(
                        bar
                        for bar in code_bars
                        if bar.trade_date > last_processed
                    )
                    stats.rows_scanned += len(new_bars)
                    stats.rows_materialized += len(new_bars)
                    if not new_bars:
                        if (code, as_of) not in verified:
                            raise ValueError(
                                "DATA_MISSING_UNEXPLAINED:"
                                f"{code}:{as_of.isoformat()}"
                            )
                        rows = ()
                        final_signal = previous_signal
                        window_bars = ()
                        notes.append(f"NO_TRADE_COVERED:{code}")
                    else:
                        window_start = last_processed - timedelta(
                            days=window_calendar_days
                        )
                        anchor_date = (
                            previous_signal.anchor.anchor_date
                            if previous_signal.anchor is not None
                            else None
                        )
                        if (
                            anchor_date is not None
                            and anchor_date <= window_start
                        ):
                            stats.targeted_fallback_n += 1
                            stats.fallback_reasons["ANCHOR_BEFORE_WINDOW"] = (
                                stats.fallback_reasons.get(
                                    "ANCHOR_BEFORE_WINDOW", 0
                                )
                                + 1
                            )
                            fallback_reason = "ANCHOR_BEFORE_WINDOW"
                            full_bars = _full_bars(
                                layout, snapshot, code, as_of
                            )
                            rows, final_signal = screen_code(
                                code=code,
                                bars=full_bars,
                                pool_records=pool_records,
                                config=config,
                                start_date=None,
                                as_of=as_of,
                                generated_at=generated_at,
                                previous_signal=previous_signal,
                                last_processed=last_processed,
                                pool_status=pool_status,
                                pool_mode=pool_mode,
                            )
                            notes.append(
                                f"TARGETED_FALLBACK:{code}:{fallback_reason}"
                            )
                        else:
                            window_bars = tuple(
                                bar
                                for bar in code_bars
                                if bar.trade_date > window_start
                            )
                            stats.rows_scanned += len(window_bars)
                            stats.rows_materialized += len(window_bars)
                            rows, final_signal = screen_code(
                                code=code,
                                bars=window_bars,
                                pool_records=pool_records,
                                config=config,
                                start_date=None,
                                as_of=as_of,
                                generated_at=generated_at,
                                previous_signal=previous_signal,
                                last_processed=last_processed,
                                pool_status=pool_status,
                                pool_mode=pool_mode,
                            )
                            stats.fast_path_n += 1

            if final_signal is None:
                raise ValueError(f"NO_FINAL_SIGNAL:{code}")
            up_to = min(final_signal.trade_date, as_of)
            if full_bars is not None:
                v1 = _bars_prefix_hash(full_bars, up_to)
                v2 = _bars_prefix_hash_chain(full_bars, up_to)
                stats.rows_scanned += len(full_bars)
                stats.rows_materialized += len(full_bars)
            else:
                v2 = state.bars_prefix_hash_v2
                assert v2 is not None
                new_for_hash = tuple(
                    bar
                    for bar in window_bars
                    if bar.trade_date > state.last_processed_date
                )
                for bar in new_for_hash:
                    v2 = _extend_bars_prefix_hash_chain(v2, bar)
                v1 = v2
            save_state(
                states_root / f"{code}.json",
                code=code,
                last_processed_date=up_to,
                signal=final_signal,
                snapshot_id=snapshot.snapshot_id,
                bars_prefix_hash=v1,
                bars_prefix_hash_v2=v2,
                limit_pool_prefix_hash=_pool_prefix_hash(
                    pool_records,
                    pool_status,
                    up_to,
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
                status_counts[status] += 1
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
                spool_file.write(
                    json.dumps(
                        row_dict,
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                rows_count += 1
    finally:
        spool_file.close()

    output_hash = _spool_output_hash(spool_path)
    manifest = {
        "run_id": _digest(
            "screen-incremental-fast",
            as_of.isoformat(),
            snapshot.snapshot_id[:12],
            commit,
            config_hash,
            pool_mode,
        )[:12],
        "kind": "incremental-fast",
        "as_of": as_of.isoformat(),
        "start": None,
        "snapshot_id": snapshot.snapshot_id,
        "strategy_commit": commit,
        "config_hash": config_hash,
        "dataset_snapshot_id": snapshot.snapshot_id,
        "output_hash": output_hash,
        "rows_count": rows_count,
        "created_at": processed_at.isoformat(),
        "status_counts": dict(sorted(status_counts.items())),
        "new_anchor_count": new_anchors,
        "active_setup_count": active,
        "entry_candidate_count": entry_candidates,
        "quality_rejection_count": quality_rejections,
        "verify_replay_matched": None,
        "pool_mode": pool_mode,
        "notes": sorted(set(notes)),
        "universe_size": len(codes_done),
        "codes": tuple(codes_done),
    }
    _write_compact_output(
        metadata=manifest,
        spool_path=spool_path,
        compact_output_path=compact_output_path,
        output_path=manifest_path,
    )
    spool_path.unlink(missing_ok=True)
    return manifest


def _full_bars(layout, snapshot, code: str, as_of: date) -> tuple:
    for yielded_code, bars in iter_canonical_code_bars(
        layout,
        snapshot,
        codes=[code],
        as_of=as_of,
    ):
        if yielded_code == code:
            return bars
    return ()


def _signal_from_state(state):
    from limit_pullback.models.signal import StrategySignal

    return StrategySignal.model_validate_json(state.signal_json)
