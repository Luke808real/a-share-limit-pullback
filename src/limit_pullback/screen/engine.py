"""Per-code daily setup advancement over canonical bars.

The loop mirrors the frozen ``replay`` driver exactly: the same
``evaluate_strategy`` calls with the same bar prefixes, limit-pool records
and previous signal, so market-wide output is field-identical to
single-stock replay on the same canonical snapshot.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import DataQuality
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.replay import ReplayTimelineItem
from limit_pullback.models.signal import StrategySignal
from limit_pullback.replay import _merge_signal_quality, _timeline_item
from limit_pullback.strategy.engine import evaluate_strategy
from limit_pullback.strategy.structure import is_limit_close


def screen_code(
    *,
    code: str,
    bars: Sequence[DailyBar],
    pool_records: Sequence[LimitUpRecord],
    config: StrategyConfig,
    start_date: date | None,
    as_of: date,
    generated_at: datetime,
    previous_signal: StrategySignal | None = None,
    last_processed: date | None = None,
) -> tuple[tuple[ReplayTimelineItem, ...], StrategySignal | None]:
    """Advance one code from the oldest bar (or last processed state) to as_of."""

    ordered = tuple(sorted(bars, key=lambda bar: bar.trade_date))
    if not ordered:
        return (), previous_signal
    if last_processed is not None and last_processed >= as_of:
        return (), previous_signal

    code_pool = tuple(
        sorted(
            (record for record in pool_records if record.code == code),
            key=lambda item: (item.trade_date, item.code),
        )
    )
    candidate_pool_dates = tuple(
        sorted(
            {
                bar.trade_date
                for bar in ordered
                if (
                    bar.trade_status
                    and bar.is_st is not True
                    and is_limit_close(bar, config)
                )
            }
        )
    )
    previous = previous_signal
    rows: list[ReplayTimelineItem] = []
    for index, current in enumerate(ordered):
        if current.trade_date > as_of:
            break
        if last_processed is not None and current.trade_date <= last_processed:
            continue
        bars_up_to_date = ordered[: index + 1]
        pool_up_to_date = tuple(
            record
            for record in code_pool
            if record.trade_date <= current.trade_date
        )
        signal = evaluate_strategy(
            bars=bars_up_to_date,
            as_of=current.trade_date,
            config=config,
            generated_at=generated_at,
            limit_pool=pool_up_to_date,
            previous_signal=previous,
        )
        signal = _merge_signal_quality(
            signal,
            (DataQuality.OK,),
            insufficient_history=(
                len(bars_up_to_date) < config.universe.minimum_listing_trade_days
            ),
        )
        if start_date is None or current.trade_date >= start_date:
            rows.append(_timeline_item(signal))
        previous = signal
    return tuple(rows), previous


def derive_status(
    rows: Sequence[ReplayTimelineItem],
) -> tuple[tuple[str, ...], int]:
    """Map replay rows to the user-facing screen status per row.

    Returns (statuses, new_anchor_count). ``NEW_ANCHOR`` is the first row of a
    new setup id; other rows keep their frozen ``setup_stage``.
    """

    statuses: list[str] = []
    new_anchors = 0
    previous_setup_id: str | None = None
    for row in rows:
        if (
            row.anchor_snapshot is not None
            and row.setup_id != previous_setup_id
        ):
            statuses.append("NEW_ANCHOR")
            new_anchors += 1
        else:
            statuses.append(row.setup_stage.value)
        previous_setup_id = row.setup_id
    return tuple(statuses), new_anchors
