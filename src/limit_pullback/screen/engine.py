"""Per-code daily setup advancement over canonical bars.

The loop mirrors the frozen ``replay`` driver exactly: the same
``evaluate_strategy`` calls with the same bar prefixes, limit-pool records
and previous signal, so market-wide output is field-identical to
single-stock replay on the same canonical snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import DataQuality, SetupStage
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.replay import ReplayTimelineItem
from limit_pullback.models.signal import StrategySignal
from limit_pullback.quality import merge_signal_quality, timeline_item
from limit_pullback.strategy.engine import evaluate_strategy
from limit_pullback.strategy.indicators import SequencePrefixView
from limit_pullback.strategy.math import calculate_indicators

POOL_STATUS_CONFIRMED = "CONFIRMED"
POOL_STATUS_SINGLE_SOURCE = "CONFIRMED_SINGLE_SOURCE"
POOL_STATUS_PROVISIONAL = "PROVISIONAL"


def pool_quality(
    status: str | None,
    *,
    pool_mode: str,
) -> tuple[DataQuality, str | None]:
    """Quality propagation for anchor pool records.

    Formal mode refuses PROVISIONAL pool records as OK anchor data;
    debug mode allows them with an explicit warning flag and lower quality.
    """

    if status in (POOL_STATUS_CONFIRMED, POOL_STATUS_SINGLE_SOURCE):
        return DataQuality.OK, None
    if status == POOL_STATUS_PROVISIONAL:
        if pool_mode == "debug":
            return DataQuality.DEGRADED, "LIMIT_POOL_PROVISIONAL_WARNING"
        return DataQuality.UNUSABLE, "LIMIT_POOL_PROVISIONAL"
    return DataQuality.OK, None


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
    pool_status: Mapping[tuple[str, date], str] | None = None,
    pool_mode: str = "formal",
) -> tuple[tuple[ReplayTimelineItem, ...], StrategySignal | None]:
    """Advance one code from the oldest bar (or last processed state) to as_of."""

    ordered = tuple(sorted(bars, key=lambda bar: bar.trade_date))
    if not ordered:
        return (), previous_signal
    if last_processed is not None and last_processed >= as_of:
        return (), previous_signal
    full_indicators = calculate_indicators(ordered, config.indicators)

    code_pool = tuple(
        sorted(
            (record for record in pool_records if record.code == code),
            key=lambda item: (item.trade_date, item.code),
        )
    )
    previous = previous_signal
    rows: list[ReplayTimelineItem] = []
    for index, current in enumerate(ordered):
        if current.trade_date > as_of:
            break
        if last_processed is not None and current.trade_date <= last_processed:
            continue
        bars_up_to_date = SequencePrefixView(ordered, 0, index + 1)
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
            precomputed_indicators=full_indicators,
            indicator_end_index=index + 1,
        )
        signal = merge_signal_quality(
            signal,
            (DataQuality.OK,),
            insufficient_history=(
                len(bars_up_to_date) < config.universe.minimum_listing_trade_days
            ),
        )
        if signal.anchor is not None:
            status = (pool_status or {}).get(
                (code, signal.anchor.anchor_date)
            )
            quality, flag = pool_quality(status, pool_mode=pool_mode)
            if flag is not None:
                signal = merge_signal_quality(
                    signal,
                    (quality,),
                    source_flags=(flag,),
                )
        if start_date is None or current.trade_date >= start_date:
            rows.append(timeline_item(signal))
        previous = signal
    return tuple(rows), previous


def derive_status(
    rows: Sequence[ReplayTimelineItem],
) -> tuple[tuple[str, ...], int]:
    """Map replay rows to the user-facing screen status per row.

    ``NEW_ANCHOR`` only marks the exact trading day on which a new setup is
    created: the row is in ``LIMIT_ANCHOR`` stage and its anchor date equals
    the row's trade date. Continuing days of an existing setup never repeat
    ``NEW_ANCHOR``.
    """

    statuses: list[str] = []
    new_anchors = 0
    for row in rows:
        is_new_anchor = (
            row.setup_stage is SetupStage.LIMIT_ANCHOR
            and row.anchor_snapshot is not None
            and row.anchor_snapshot.anchor_date == row.trade_date
        )
        if is_new_anchor:
            statuses.append("NEW_ANCHOR")
            new_anchors += 1
        else:
            statuses.append(row.setup_stage.value)
    return tuple(statuses), new_anchors
