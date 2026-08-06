"""PR-C characterization audits: anchor parity and derived-event coverage.

All loops stream one code at a time from the canonical snapshot; the full
multi-million-row daily file is never materialized.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from limit_pullback.config import load_strategy_config
from limit_pullback.derived_limit_event import (
    DerivedLimitUpEvent,
    build_derived_limit_events,
    compose_enrichment,
    events_to_limit_up_records,
)
from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.screen.canonical import iter_canonical_code_bars
from limit_pullback.strategy.structure import detect_anchor
from limit_pullback.warehouse.layout import WarehouseLayout


def _anchor_key(anchor) -> tuple | None:
    if anchor is None:
        return None
    return (
        anchor.snapshot.anchor_date.isoformat(),
        str(anchor.snapshot.anchor_price),
        anchor.profile.value,
        anchor.is_first_board,
        anchor.recent_limit_count,
        anchor.recent_limits_non_consecutive,
        anchor.seal_before_cutoff,
    )


def build_snapshot_derived_pool(
    layout: WarehouseLayout,
    snapshot,
    *,
    config: StrategyConfig,
    legacy_pool: Sequence[LimitUpRecord],
    source_id: str,
) -> tuple[list[DerivedLimitUpEvent], list[LimitUpRecord]]:
    """Stream the snapshot and build derived events composed with enrichment."""

    events: list[DerivedLimitUpEvent] = []
    for code, bars in iter_canonical_code_bars(
        layout,
        snapshot,
        as_of=snapshot.as_of,
    ):
        code_events = build_derived_limit_events(
            [
                {
                    "code": bar.code,
                    "trade_date": bar.trade_date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "preclose": bar.preclose,
                    "source_daily_hash": "",
                }
                for bar in bars
            ],
            source_id=source_id,
            config=config,
        )
        enrichment_rows = [
            {
                "code": record.code,
                "trade_date": record.trade_date,
                "first_seal_time": record.first_seal_time,
                "last_seal_time": record.last_seal_time,
                "open_count": record.open_count,
                "consecutive_count": record.consecutive_count,
                "industry": record.industry,
            }
            for record in legacy_pool
        ]
        code_events = compose_enrichment(code_events, enrichment_rows)
        events.extend(code_events)
    events.sort(key=lambda event: (event.code, event.trade_date))
    return events, events_to_limit_up_records(events)


def _daily_bar_from_row(row: Mapping[str, Any]) -> DailyBar:
    return DailyBar(
        trade_date=row["trade_date"],
        code=str(row["code"]),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        preclose=Decimal(str(row["preclose"])),
        volume=Decimal(str(row["volume"])),
        amount=Decimal(str(row["amount"])),
        turnover_rate=(
            Decimal(str(row["turnover_rate"]))
            if row.get("turnover_rate") is not None
            else None
        ),
        pct_change=(
            Decimal(str(row["pct_change"]))
            if row.get("pct_change") is not None
            else None
        ),
        trade_status=bool(row.get("trade_status", True)),
        is_st=(
            bool(row["is_st"]) if row.get("is_st") is not None else None
        ),
        source="STAGED_ADR008",
        fetched_at=datetime(2026, 8, 5, 23, 59, 59, tzinfo=timezone.utc),
    )


def load_legacy_pool_records(
    layout: WarehouseLayout,
    snapshot,
) -> list[LimitUpRecord]:
    """Load the immutable legacy canonical pool as LimitUpRecords."""

    import pyarrow.parquet as pq

    pool_rel = next(
        (
            key
            for key in snapshot.canonical_file_hashes
            if key.endswith(
                "/limit_up_pool/" + snapshot.snapshot_id + ".parquet"
            )
        ),
        None,
    )
    if pool_rel is None:
        return []
    records: list[LimitUpRecord] = []
    for row in pq.read_table(layout.root / pool_rel).to_pylist():
        records.append(
            LimitUpRecord(
                trade_date=row["trade_date"],
                code=str(row["code"]),
                name=str(row["name"]),
                limit_price=Decimal(str(row["limit_price"])),
                first_seal_time=_as_time(row.get("first_seal_time")),
                last_seal_time=_as_time(row.get("last_seal_time")),
                open_count=(
                    int(row["open_count"])
                    if row.get("open_count") is not None
                    else None
                ),
                consecutive_count=(
                    int(row["consecutive_count"])
                    if row.get("consecutive_count") is not None
                    else None
                ),
                turnover_rate=(
                    Decimal(str(row["turnover_rate"]))
                    if row.get("turnover_rate") is not None
                    else None
                ),
                float_market_cap=(
                    Decimal(str(row["float_market_cap"]))
                    if row.get("float_market_cap") is not None
                    else None
                ),
                total_market_cap=(
                    Decimal(str(row["total_market_cap"]))
                    if row.get("total_market_cap") is not None
                    else None
                ),
                industry=row.get("industry"),
                source="CANONICAL_POOL",
                fetched_at=datetime(
                    2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc
                ),
            )
        )
    records.sort(key=lambda record: (record.code, record.trade_date))
    return records


def _as_time(value: Any) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value)[:8])
    except ValueError:
        return None


def anchor_regression_0731(
    layout: WarehouseLayout,
    snapshot,
    *,
    config: StrategyConfig,
    legacy_pool: Sequence[LimitUpRecord],
    new_pool: Sequence[LimitUpRecord] | None = None,
) -> dict[str, Any]:
    """Compare detect_anchor output at 2026-07-31: legacy pool vs derived pool."""

    as_of = snapshot.as_of
    old_by_code: dict[str, LimitUpRecord] = {
        (record.code, record.trade_date): record
        for record in legacy_pool
        if record.trade_date <= as_of
    }
    if new_pool is None:
        _, new_pool = build_snapshot_derived_pool(
            layout,
            snapshot,
            config=config,
            legacy_pool=legacy_pool,
            source_id=snapshot.snapshot_id,
        )
    new_by_key: dict[tuple[str, date], LimitUpRecord] = {
        (record.code, record.trade_date): record
        for record in new_pool
        if record.trade_date <= as_of
    }
    old_counts = Counter()
    new_counts = Counter()
    diff_n = 0
    first_diffs: list[dict[str, Any]] = []
    for code, bars in iter_canonical_code_bars(
        layout,
        snapshot,
        as_of=as_of,
    ):
        old_pool = [old_by_code[(code, bar.trade_date)] for bar in bars if (code, bar.trade_date) in old_by_code]
        new_pool_code = [new_by_key[(code, bar.trade_date)] for bar in bars if (code, bar.trade_date) in new_by_key]
        old_anchor = detect_anchor(bars, as_of, config, limit_pool=old_pool)
        new_anchor = detect_anchor(bars, as_of, config, limit_pool=new_pool_code)
        old_counts[old_anchor.profile.value if old_anchor else "NONE"] += 1
        new_counts[new_anchor.profile.value if new_anchor else "NONE"] += 1
        if _anchor_key(old_anchor) != _anchor_key(new_anchor):
            diff_n += 1
            if len(first_diffs) < 5:
                first_diffs.append(
                    {
                        "code": code,
                        "old": _anchor_key(old_anchor),
                        "new": _anchor_key(new_anchor),
                    }
                )
    return {
        "old_full_n": old_counts.get("FULL", 0),
        "old_price_only_n": old_counts.get("PRICE_ONLY", 0),
        "old_none_n": old_counts.get("NONE", 0),
        "new_full_n": new_counts.get("FULL", 0),
        "new_price_only_n": new_counts.get("PRICE_ONLY", 0),
        "new_none_n": new_counts.get("NONE", 0),
        "anchor_regression_diff_n": diff_n,
        "first_diffs": first_diffs,
    }


def derived_session_audit(
    layout: WarehouseLayout,
    seed_snapshot,
    *,
    staged_rows: Sequence[Mapping[str, Any]],
    config: StrategyConfig,
    universe_members: Sequence[str],
    sessions: Sequence[date],
    staging_run_id: str,
    legacy_pool: Sequence[LimitUpRecord] = (),
) -> dict[str, Any]:
    """Derived limit-event + anchor-eligibility audit for staged sessions."""

    member_set = set(universe_members)
    staged_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in staged_rows:
        if row.get("close") is None or str(row["code"]) not in member_set:
            continue
        staged_by_code.setdefault(str(row["code"]), []).append(dict(row))

    legacy_by_key: dict[tuple[str, date], LimitUpRecord] = {
        (record.code, record.trade_date): record
        for record in legacy_pool
    }
    per_date: dict[date, dict[str, int]] = {
        session: {
            "limit_close_n": 0,
            "one_word_n": 0,
            "t_word_n": 0,
            "price_only_anchor_eligible_n": 0,
            "full_enrichment_available_n": 0,
            "derived_event_n": 0,
        }
        for session in sessions
    }
    session_set = set(sessions)
    events: list[DerivedLimitUpEvent] = []
    for code, bars in iter_canonical_code_bars(
        layout,
        seed_snapshot,
        as_of=seed_snapshot.as_of,
    ):
        staged = staged_by_code.get(code, ())
        if not staged:
            continue
        merged = list(bars) + [
            _daily_bar_from_row(row)
            for row in sorted(staged, key=lambda row: row["trade_date"])
            if row["trade_date"] > seed_snapshot.as_of
        ]
        merged.sort(key=lambda bar: bar.trade_date)
        code_events = build_derived_limit_events(
            [
                {
                    "code": bar.code,
                    "trade_date": bar.trade_date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "preclose": bar.preclose,
                    "source_daily_hash": (
                        next(
                            (
                                row["selected_source_hash"]
                                for row in staged
                                if row["trade_date"] == bar.trade_date
                            ),
                            "",
                        )
                        if bar.trade_date > seed_snapshot.as_of
                        else ""
                    ),
                }
                for bar in merged
            ],
            source_id=staging_run_id,
            config=config,
            universe_members=member_set,
        )
        code_events = compose_enrichment(
            code_events,
            [
                {
                    **record.__dict__,
                    "code": record.code,
                    "trade_date": record.trade_date,
                }
                for record in legacy_pool
                if record.trade_date <= seed_snapshot.as_of
            ],
        )
        events.extend(
            event
            for event in code_events
            if event.trade_date in session_set
        )
        records = events_to_limit_up_records(code_events)
        for session in sessions:
            session_events = [
                event
                for event in code_events
                if event.trade_date == session
            ]
            stats = per_date[session]
            stats["limit_close_n"] += len(session_events)
            stats["one_word_n"] += sum(
                1 for event in session_events if event.is_one_word
            )
            stats["t_word_n"] += sum(
                1 for event in session_events if event.is_t_word
            )
            stats["full_enrichment_available_n"] += sum(
                1
                for event in session_events
                if event.enrichment_profile == "FULL"
            )
            anchor = detect_anchor(
                merged,
                session,
                config,
                limit_pool=[
                    record
                    for record in records
                    if record.trade_date <= session
                ],
            )
            if anchor is not None and anchor.profile.value == "PRICE_ONLY":
                stats["price_only_anchor_eligible_n"] += 1
            stats["derived_event_n"] += len(session_events)
    return {
        "per_date": {
            session.isoformat(): stats
            for session, stats in sorted(per_date.items())
        },
        "events": events,
        "derived_event_n": len(events),
    }
