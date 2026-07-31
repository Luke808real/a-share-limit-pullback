"""Shared provider-quality merge and timeline conversion.

Public internal helpers used by both the single-stock replay driver and the
market-wide screen so that quality propagation stays byte-identical without
either module depending on the other's private functions.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from limit_pullback.models.enums import DataQuality
from limit_pullback.models.replay import ReplayTimelineItem
from limit_pullback.models.signal import StrategySignal

QUALITY_ORDER = {
    DataQuality.OK: 0,
    DataQuality.PARTIAL: 1,
    DataQuality.DEGRADED: 2,
    DataQuality.UNUSABLE: 3,
}


def missing_fields(flags: Sequence[str]) -> tuple[str, ...]:
    fields: set[str] = set()
    for flag in flags:
        if flag.startswith(("MISSING_DAILY_FIELD:", "MISSING_LIMIT_FIELD:")):
            fields.add(flag.rsplit(":", 1)[-1])
        elif flag.startswith("MALFORMED_DAILY_ROW:"):
            parts = flag.split(":", 3)
            if len(parts) != 4:
                continue
            fields.update(
                field
                for field in parts[3].split(",")
                if (
                    field
                    and field not in {"invalid_date", "missing_date"}
                    and field.replace("_", "").isalnum()
                    and not field[0].isdigit()
                )
            )
    return tuple(sorted(fields))


def worst_quality(values: Sequence[DataQuality]) -> DataQuality:
    return max(values, key=QUALITY_ORDER.__getitem__)


def merge_signal_quality(
    signal: StrategySignal,
    source_qualities: Sequence[DataQuality],
    *,
    source_flags: Sequence[str] = (),
    insufficient_history: bool = False,
) -> StrategySignal:
    merged = worst_quality((signal.data_quality, *source_qualities))
    flags = {*signal.quality_flags, *source_flags}
    if insufficient_history:
        merged = DataQuality.UNUSABLE
        flags.add("INSUFFICIENT_TRADING_HISTORY")
    updates: dict[str, object] = {}
    if merged is not signal.data_quality:
        updates["data_quality"] = merged
    frozen_flags = tuple(sorted(flags))
    if frozen_flags != signal.quality_flags:
        updates["quality_flags"] = frozen_flags
    if merged is DataQuality.UNUSABLE and signal.entry_quality_score is not None:
        updates["entry_quality_score"] = signal.entry_quality_score * 0
    if not updates:
        return signal
    return signal.model_copy(update=updates)


def quality_flag_date(flag: str) -> date | None:
    if not flag.startswith((
        "DUPLICATE_DAILY_ROW_DEDUPED:",
        "MALFORMED_DAILY_ROW:",
        "MISSING_DAILY_FIELD:",
        "NON_TRADING_BAR_SKIPPED:",
    )):
        return None
    parts = flag.split(":")
    if len(parts) < 3:
        return None
    try:
        return date.fromisoformat(parts[2])
    except ValueError:
        return None


def daily_prefix_quality(
    overall: DataQuality,
    flags: Sequence[str],
) -> DataQuality:
    if overall is DataQuality.UNUSABLE:
        return DataQuality.UNUSABLE
    if any(flag.startswith("MALFORMED_DAILY_ROW:") for flag in flags):
        return DataQuality.DEGRADED
    if flags:
        return DataQuality.PARTIAL
    return DataQuality.OK


def timeline_item(signal: StrategySignal) -> ReplayTimelineItem:
    return ReplayTimelineItem(
        trade_date=signal.trade_date,
        setup_id=signal.setup_id,
        setup_stage=signal.setup_stage,
        event_flags=tuple(sorted(signal.event_flags, key=lambda item: item.value)),
        event_reasons=signal.event_reasons,
        matched_patterns=tuple(
            sorted(signal.matched_patterns, key=lambda item: item.value)
        ),
        primary_pattern=signal.primary_pattern,
        pattern_scores=signal.pattern_scores,
        pattern_conditions=signal.pattern_conditions,
        primary_pattern_reason=signal.primary_pattern_reason,
        b1_conditions=signal.b1_conditions,
        b2_conditions=signal.b2_conditions,
        score_profile=signal.score.profile,
        normalized_score=signal.score.normalized_score,
        setup_quality_score=signal.setup_quality_score,
        entry_quality_score=signal.entry_quality_score,
        is_entry_candidate=signal.is_entry_candidate,
        anchor_snapshot=signal.anchor,
        support_snapshot=signal.support,
        invalid_price_snapshot=signal.invalid_price_snapshot,
        b2_trigger_snapshot=signal.b2_trigger,
        expected_b2_trigger_price=signal.expected_b2_trigger_price,
        resistance_candidates=signal.resistance_candidates,
        immediate_resistance=signal.immediate_resistance,
        target_s1=signal.target_s1,
        entry_reference_price=signal.entry_reference_price,
        entry_headroom_pct=signal.entry_headroom_pct,
        entry_room_state=signal.entry_room_state,
        entry_room_reasons=signal.entry_room_reasons,
        risk_reward_ratio=signal.risk_reward_ratio,
        review_group=signal.review_group,
        initial_invalid_price=signal.initial_invalid_price,
        invalid_price=signal.invalid_price,
        reasons=signal.score.reasons,
        risks=signal.score.risks,
        invalidation_reasons=signal.invalidation_reasons,
        data_quality=signal.data_quality,
        quality_flags=signal.quality_flags,
    )
