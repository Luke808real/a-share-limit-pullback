"""Screen verification: rebuild==incremental and market==single replay."""

from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.replay import ReplayTimelineItem
from limit_pullback.replay import replay_stock
from limit_pullback.screen.canonical import CanonicalMarketData
from limit_pullback.screen.engine import screen_code


def compare_rows(
    *,
    code: str,
    left: Sequence[ReplayTimelineItem],
    right: Sequence[ReplayTimelineItem],
) -> list[str]:
    left_by_key = {
        item.trade_date: {"code": code, **item.model_dump(mode="json")}
        for item in left
    }
    right_by_key = {
        item.trade_date: {"code": code, **item.model_dump(mode="json")}
        for item in right
    }
    mismatches: list[str] = []
    for key in sorted(set(left_by_key) | set(right_by_key)):
        if left_by_key.get(key) != right_by_key.get(key):
            mismatches.append(f"{code} {key}: row mismatch")
            if len(mismatches) >= 10:
                break
    return mismatches


def verify_rebuild_incremental(
    *,
    code: str,
    bars,
    pool_records,
    config: StrategyConfig,
    start: date,
    as_of: date,
    generated_at: datetime,
    incremental_rows: Sequence[ReplayTimelineItem],
) -> list[str]:
    rebuild_rows, _ = screen_code(
        code=code,
        bars=bars,
        pool_records=pool_records,
        config=config,
        start_date=start,
        as_of=as_of,
        generated_at=generated_at,
    )
    covered = {
        item.trade_date for item in incremental_rows
    }
    overlap = [
        item for item in rebuild_rows if item.trade_date in covered
    ]
    return compare_rows(
        code=code,
        left=overlap,
        right=incremental_rows,
    )


def verify_single_stock_replay(
    *,
    market: CanonicalMarketData,
    code: str,
    config: StrategyConfig,
    start: date,
    as_of: date,
    lookback_calendar_days: int,
    generated_at: datetime,
    screen_rows: Sequence[ReplayTimelineItem],
) -> list[str]:
    bars = market.bars_by_code.get(code, ())
    if not bars:
        return []
    span_days = (as_of - min(bar.trade_date for bar in bars)).days + 10
    effective_lookback = max(lookback_calendar_days, span_days)
    output = replay_stock(
        code=code,
        start=start,
        as_of=as_of,
        lookback_calendar_days=effective_lookback,
        config=config,
        daily_provider=market.daily_provider(),
        limit_pool_provider=market.pool_provider(),
        clock=lambda: generated_at,
    )
    replay_rows = output.timeline
    covered = {item.trade_date for item in screen_rows}
    overlap = [
        item for item in replay_rows if item.trade_date in covered
    ]
    return compare_rows(
        code=code,
        left=overlap,
        right=screen_rows,
    )
