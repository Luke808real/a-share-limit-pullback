"""The single setup state engine (REF-R5 R5.2, seam-preserving).

`evaluate_strategy` orchestrates the frozen transition logic; helpers live in
`limit_pullback.state.engine_helpers`. `strategy/engine.py` is a compatibility
shim with module-level identity re-exports plus a lazy `evaluate_strategy`
(PEP 562), which keeps golden monkeypatch seams working and avoids the
strategy-package import cycle.

One test seam is late-bound: `select_resistance_levels` is looked up through
the `strategy.engine` shim at call time so existing golden tests that
monkeypatch that name keep passing without editing test files.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import (
    DataQuality,
    EntryRoomState,
    EventFlag,
    PatternType,
    ReviewGroup,
    ScoreProfile,
    SetupStage,
)
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.signal import (
    B2TriggerSnapshot,
    ConditionSnapshot,
    InvalidPriceSnapshot,
    ResistanceCandidateSnapshot,
    ResistanceSnapshot,
    S1Snapshot,
    StrategySignal,
    SupportSnapshot,
)
from limit_pullback.models.strategy import (
    AnchorEvaluation,
    ConditionScore,
    IndicatorPoint,
    PriceCluster,
)
from limit_pullback.state.engine_helpers import (
    _as_cluster,
    _as_s1_cluster,
    _conditions,
    _entry_quality_score,
    _entry_room,
    _evaluate_b1,
    _evaluate_b2_confirmation,
    _evaluate_event_flags,
    _evaluate_invalid_reasons,
    _expected_b2_trigger,
    _mean,
    _platform_b2_trigger,
    _quantize_price,
    _risk_reward,
    make_setup_id,
)
from limit_pullback.strategy.math import calculate_indicators
from limit_pullback.strategy.indicators import IndicatorPrefixView, SequencePrefixView
from limit_pullback.strategy.patterns import evaluate_patterns
from limit_pullback.selection.ranking import build_score
from limit_pullback.strategy.structure import (
    cluster_price_candidates,
    detect_anchor,
    generate_resistance_candidates,
    generate_support_candidates,
    select_support_cluster,
)


ZERO = Decimal("0")
ONE = Decimal("1")
ACTIONABLE = frozenset(
    {SetupStage.B1_READY, SetupStage.B2_READY, SetupStage.B2_CONFIRMED}
)


def _select_resistance_levels_seam(*args, **kwargs):
    """Late-bound call through the strategy.engine shim (golden test seam)."""

    import importlib

    module = importlib.import_module("limit_pullback.strategy.engine")
    return module.select_resistance_levels(*args, **kwargs)


def evaluate_strategy(
    *,
    bars: Sequence[DailyBar],
    as_of: date,
    config: StrategyConfig,
    generated_at: datetime,
    limit_pool: Sequence[LimitUpRecord] = (),
    previous_signal: StrategySignal | None = None,
    precomputed_indicators: Sequence[IndicatorPoint] | None = None,
    indicator_end_index: int | None = None,
) -> StrategySignal:
    """Evaluate one code as of one close, using only supplied data at or before T."""

    if isinstance(bars, SequencePrefixView):
        ordered = bars
    else:
        ordered = tuple(sorted(
            (bar for bar in bars if bar.trade_date <= as_of),
            key=lambda bar: bar.trade_date,
        ))
    if not ordered or ordered[-1].trade_date != as_of:
        raise ValueError("bars must contain an observation exactly on as_of")
    if len({bar.code for bar in ordered}) != 1:
        raise ValueError("evaluate_strategy requires exactly one stock code")
    if len({bar.trade_date for bar in ordered}) != len(ordered):
        raise ValueError("daily bars contain duplicate trade dates")
    current = ordered[-1]
    if previous_signal is not None:
        if previous_signal.code != current.code:
            raise ValueError("previous signal belongs to a different code")
        if previous_signal.strategy_version != config.strategy_version:
            raise ValueError("previous signal strategy_version does not match config")
        if previous_signal.trade_date >= as_of:
            raise ValueError("previous signal must precede as_of")

    usable_pool = tuple(
        record for record in limit_pool if record.trade_date <= as_of
    )
    if precomputed_indicators is None:
        indicators = calculate_indicators(ordered, config.indicators, as_of)
    else:
        if indicator_end_index is None:
            raise ValueError(
                "indicator_end_index is required when precomputed_indicators is provided"
            )
        indicators = IndicatorPrefixView(precomputed_indicators, indicator_end_index)
    anchor = detect_anchor(ordered, as_of, config, usable_pool)

    if anchor is None:
        setup_id = f"{current.code}:{as_of:%Y%m%d}:NORMAL"
        score = build_score(
            config=config,
            profile=ScoreProfile.PRICE_ONLY,
            bars=ordered,
            indicators=indicators,
            current=current,
            anchor=None,
            support=None,
            patterns=None,
            b1_conditions=None,
            b2_conditions=None,
            setup_stage=SetupStage.NORMAL,
            limit_pool=usable_pool,
        )
        quality_flags = tuple(sorted({
            "NO_VALID_ANCHOR",
            *score.quality_flags,
        }))
        return StrategySignal(
            strategy_version=config.strategy_version,
            setup_id=setup_id,
            trade_date=as_of,
            code=current.code,
            generated_at=generated_at,
            setup_stage=SetupStage.NORMAL,
            data_quality=DataQuality.UNUSABLE,
            quality_flags=quality_flags,
            score=score,
        )

    setup_id = make_setup_id(
        current.code,
        anchor.snapshot.anchor_date,
        anchor.snapshot.anchor_price,
        config.anchor.price_tick,
    )
    previous_same = (
        previous_signal
        if previous_signal is not None and previous_signal.setup_id == setup_id
        else None
    )
    anchor_snapshot = (
        previous_same.anchor
        if previous_same is not None and previous_same.anchor is not None
        else anchor.snapshot
    )

    support_candidates = generate_support_candidates(
        ordered, indicators, anchor, as_of, config
    )
    support_clusters = cluster_price_candidates(
        support_candidates, config.support.cluster_distance
    )
    computed_support = select_support_cluster(
        support_clusters, current.close, config
    )

    prior_support = (
        previous_same.support if previous_same is not None else None
    )
    prior_invalid_snapshot = (
        previous_same.invalid_price_snapshot
        if previous_same is not None
        else None
    )
    prior_immediate_resistance = (
        previous_same.immediate_resistance
        if previous_same is not None
        else None
    )
    prior_target_s1 = (
        previous_same.target_s1 if previous_same is not None else None
    )
    prior_resistance_candidates = (
        previous_same.resistance_candidates
        if previous_same is not None
        else ()
    )
    prior_expected_b2_trigger = (
        previous_same.expected_b2_trigger_price
        if previous_same is not None
        else None
    )
    eligible_support_snapshot = (
        prior_support
        if prior_support is not None and prior_support.eligible_from <= as_of
        else None
    )
    eligible_invalid_snapshot = (
        prior_invalid_snapshot
        if (
            prior_invalid_snapshot is not None
            and prior_invalid_snapshot.eligible_from <= as_of
        )
        else None
    )
    eligible_target_s1_snapshot = (
        prior_target_s1
        if (
            prior_target_s1 is not None
            and prior_target_s1.eligible_from <= as_of
        )
        else None
    )
    eligible_support = (
        _as_cluster(eligible_support_snapshot)
        if eligible_support_snapshot is not None
        else None
    )
    eligible_target_s1 = (
        _as_s1_cluster(eligible_target_s1_snapshot)
        if eligible_target_s1_snapshot is not None
        else None
    )
    setup_support = (
        eligible_support
        if prior_support is not None
        else computed_support
    )
    computed_expected_b2_trigger = _expected_b2_trigger(ordered, config)
    computed_immediate: PriceCluster | None = None
    computed_target_s1: PriceCluster | None = None
    computed_resistance_audit: tuple[ResistanceCandidateSnapshot, ...] = ()
    if prior_support is None and computed_support is not None:
        (
            computed_immediate,
            computed_target_s1,
            computed_resistance_audit,
            computed_expected_b2_trigger,
        ) = _select_resistance_levels_seam(
            generate_resistance_candidates(ordered, anchor, as_of, config),
            anchor_price=anchor.snapshot.anchor_price,
            support=computed_support,
            reference_close=current.close,
            expected_b2_trigger=computed_expected_b2_trigger,
            config=config,
        )
    setup_target_s1 = (
        eligible_target_s1
        if prior_target_s1 is not None
        else computed_target_s1
    )
    proposed_invalid = (
        _quantize_price(
            setup_support.low * (ONE - config.support.invalid_buffer),
            config,
        )
        if setup_support is not None
        else None
    )
    setup_invalid_price = (
        eligible_invalid_snapshot.invalid_price
        if eligible_invalid_snapshot is not None
        else proposed_invalid
    )

    patterns = evaluate_patterns(
        ordered, indicators, anchor, setup_support, as_of, config
    )
    b1_conditions = _evaluate_b1(
        ordered=ordered,
        indicators=indicators,
        current=current,
        anchor=anchor,
        support=setup_support,
        config=config,
    )
    b1_ready = (
        setup_support is not None
        and setup_invalid_price is not None
        and b1_conditions.available_count > 0
        and b1_conditions.match_ratio >= config.b1.minimum_condition_ratio
    )

    trigger = (
        previous_same.b2_trigger
        if previous_same is not None and previous_same.b2_trigger is not None
        else None
    )
    b2_conditions: ConditionScore | None = None
    b2_confirmed = False
    if trigger is not None and trigger.eligible_from <= as_of:
        b2_conditions = _evaluate_b2_confirmation(
            ordered=ordered,
            indicators=indicators,
            current=current,
            anchor=anchor,
            trigger=trigger,
            config=config,
        )
        mandatory_b2 = {
            "intraday_trigger_breakout",
            "close_holds_trigger",
        }
        other_matched = tuple(
            condition
            for condition in b2_conditions.matched
            if condition not in mandatory_b2
        )
        other_failed = tuple(
            condition
            for condition in b2_conditions.failed
            if condition not in mandatory_b2
        )
        other_available_count = len(other_matched) + len(other_failed)
        other_match_ratio = (
            Decimal(len(other_matched)) / Decimal(other_available_count)
            if other_available_count
            else ZERO
        )
        b2_confirmed = (
            mandatory_b2.issubset(b2_conditions.matched)
            and other_available_count > 0
            and other_match_ratio >= config.b2.minimum_condition_ratio
        )

    current_invalidation_reasons = (
        _evaluate_invalid_reasons(
            ordered=ordered,
            indicators=indicators,
            current=current,
            anchor=anchor,
            support=eligible_support,
            support_snapshot=eligible_support_snapshot,
            invalid_price=eligible_invalid_snapshot.invalid_price,
            config=config,
        )
        if (
            eligible_support is not None
            and eligible_invalid_snapshot is not None
        )
        else ()
    )
    if (
        previous_same is not None
        and previous_same.setup_stage is SetupStage.INVALID
    ):
        invalidation_reasons = tuple(sorted({
            *previous_same.invalidation_reasons,
            *current_invalidation_reasons,
        }))
    else:
        invalidation_reasons = current_invalidation_reasons
    invalid = bool(invalidation_reasons)

    stage: SetupStage
    if invalid:
        stage = SetupStage.INVALID
    elif current.trade_date == anchor.snapshot.anchor_date:
        stage = SetupStage.LIMIT_ANCHOR
    elif b2_confirmed:
        stage = SetupStage.B2_CONFIRMED
    elif trigger is not None:
        stage = SetupStage.B2_READY
    elif (
        previous_same is not None
        and previous_same.setup_stage is SetupStage.B1_READY
    ):
        trigger = B2TriggerSnapshot(
            trigger_price=_platform_b2_trigger(ordered, config),
            frozen_as_of=as_of,
            eligible_from=as_of + timedelta(days=1),
            sources=("PULLBACK_PLATFORM_HIGH",),
        )
        stage = SetupStage.B2_READY
    elif b1_ready:
        stage = SetupStage.B1_READY
    else:
        stage = SetupStage.WATCH_PULLBACK

    frozen_support = prior_support
    frozen_invalid_snapshot = prior_invalid_snapshot
    frozen_immediate_resistance = prior_immediate_resistance
    frozen_target_s1 = prior_target_s1
    frozen_resistance_candidates = prior_resistance_candidates
    frozen_expected_b2_trigger = prior_expected_b2_trigger
    if (
        stage is SetupStage.B1_READY
        and frozen_support is None
        and setup_support is not None
        and setup_invalid_price is not None
    ):
        eligible_from = as_of + timedelta(days=1)
        frozen_support = SupportSnapshot(
            support_low=setup_support.low,
            support_high=setup_support.high,
            support_center=setup_support.center,
            sources=setup_support.sources,
            frozen_as_of=as_of,
            eligible_from=eligible_from,
            reference_close=current.close,
            max_above_reference_close=(
                config.support.max_above_reference_close
            ),
            reference_low=current.low,
        )
        frozen_invalid_snapshot = InvalidPriceSnapshot(
            initial_invalid_price=setup_invalid_price,
            invalid_price=setup_invalid_price,
            frozen_as_of=as_of,
            eligible_from=eligible_from,
        )
        frozen_immediate_resistance = (
            ResistanceSnapshot(
                resistance_low=computed_immediate.low,
                resistance_high=computed_immediate.high,
                sources=computed_immediate.sources,
                frozen_as_of=as_of,
                eligible_from=eligible_from,
            )
            if computed_immediate is not None
            else None
        )
        frozen_target_s1 = (
            S1Snapshot(
                s1_low=computed_target_s1.low,
                s1_high=computed_target_s1.high,
                sources=computed_target_s1.sources,
                frozen_as_of=as_of,
                eligible_from=eligible_from,
            )
            if computed_target_s1 is not None
            else None
        )
        frozen_resistance_candidates = computed_resistance_audit
        frozen_expected_b2_trigger = computed_expected_b2_trigger

    flags, event_reasons = _evaluate_event_flags(
        ordered=ordered,
        indicators=indicators,
        current=current,
        support=eligible_support,
        invalid_price=(
            eligible_invalid_snapshot.invalid_price
            if eligible_invalid_snapshot is not None
            else None
        ),
        s1=eligible_target_s1,
        setup_stage=stage,
        config=config,
    )

    score = build_score(
        config=config,
        profile=anchor.profile,
        bars=ordered,
        indicators=indicators,
        current=current,
        anchor=anchor,
        support=setup_support,
        patterns=patterns,
        b1_conditions=b1_conditions,
        b2_conditions=b2_conditions,
        setup_stage=stage,
        limit_pool=usable_pool,
        event_flags=flags,
    )
    coverage = score.available_max_score / score.profile_max_score
    base_flags = set(score.quality_flags)
    if anchor.profile is ScoreProfile.PRICE_ONLY:
        base_flags.add(config.quality.inferred_anchor_flag)
        data_quality = DataQuality.PARTIAL
    else:
        data_quality = DataQuality.OK
    if coverage < config.quality.minimum_score_coverage:
        base_flags.add("LOW_SCORE_COVERAGE")
        data_quality = DataQuality.DEGRADED

    signal_immediate_resistance = (
        frozen_immediate_resistance
        if stage in ACTIONABLE | {SetupStage.INVALID}
        else None
    )
    signal_target_s1 = (
        frozen_target_s1
        if stage in ACTIONABLE | {SetupStage.INVALID}
        else None
    )
    signal_resistance_candidates = (
        frozen_resistance_candidates
        if stage in ACTIONABLE | {SetupStage.INVALID}
        else ()
    )
    signal_expected_b2_trigger = (
        frozen_expected_b2_trigger
        if stage in ACTIONABLE | {SetupStage.INVALID}
        else None
    )
    signal_support = (
        frozen_support if stage in ACTIONABLE | {SetupStage.INVALID} else None
    )
    signal_invalid_snapshot = (
        frozen_invalid_snapshot
        if stage in ACTIONABLE | {SetupStage.INVALID}
        else None
    )
    signal_initial_invalid = (
        signal_invalid_snapshot.initial_invalid_price
        if signal_invalid_snapshot is not None
        else None
    )
    signal_invalid = (
        signal_invalid_snapshot.invalid_price
        if signal_invalid_snapshot is not None
        else None
    )
    if stage in ACTIONABLE and signal_target_s1 is None:
        review_group = ReviewGroup.OPEN_SPACE
        risk_reward = None
    else:
        review_group = ReviewGroup.STANDARD
        risk_reward = (
            _risk_reward(
                current.close,
                signal_invalid,
                _as_s1_cluster(signal_target_s1),
            )
            if signal_invalid is not None and signal_target_s1 is not None
            else None
        )
    (
        entry_reference_price,
        entry_headroom_pct,
        entry_room_state,
        entry_room_reasons,
    ) = _entry_room(
        stage=stage,
        current_close=current.close,
        trigger=trigger,
        target_s1=signal_target_s1,
        config=config,
    )
    entry_room_risk = {
        EntryRoomState.THIN: "目标压力前剩余空间偏薄",
        EntryRoomState.NONE: "目标压力已无新建仓剩余空间",
        EntryRoomState.OPEN_SPACE: "缺少可靠target S1，需单独人工复核",
    }.get(entry_room_state)
    if entry_room_risk is not None:
        score = score.model_copy(
            update={
                "risks": {
                    **score.risks,
                    "entry_room": entry_room_risk,
                }
            }
        )
    entry_quality_score = _entry_quality_score(
        setup_quality_score=score.normalized_score,
        stage=stage,
        data_quality=data_quality,
        event_flags=flags,
        entry_headroom_pct=entry_headroom_pct,
        entry_room_state=entry_room_state,
        risk_reward_ratio=risk_reward,
        config=config,
    )

    return StrategySignal(
        strategy_version=config.strategy_version,
        setup_id=setup_id,
        trade_date=as_of,
        code=current.code,
        generated_at=generated_at,
        setup_stage=stage,
        matched_patterns=patterns.matched_patterns,
        primary_pattern=patterns.primary_pattern,
        pattern_scores=patterns.pattern_scores,
        pattern_conditions={
            PatternType.AIR_REFUEL: ConditionSnapshot(
                matched=patterns.air_refuel.matched,
                failed=patterns.air_refuel.failed,
                unavailable=patterns.air_refuel.unavailable,
            ),
            PatternType.BEARISH_PULLBACK: ConditionSnapshot(
                matched=patterns.bearish_pullback.matched,
                failed=patterns.bearish_pullback.failed,
                unavailable=patterns.bearish_pullback.unavailable,
            ),
        },
        primary_pattern_reason=patterns.primary_pattern_reason,
        b1_conditions=ConditionSnapshot(
            matched=b1_conditions.matched,
            failed=b1_conditions.failed,
            unavailable=b1_conditions.unavailable,
        ),
        b2_conditions=(
            ConditionSnapshot(
                matched=b2_conditions.matched,
                failed=b2_conditions.failed,
                unavailable=b2_conditions.unavailable,
            )
            if b2_conditions is not None
            else None
        ),
        event_flags=flags,
        event_reasons=event_reasons,
        review_group=review_group,
        data_quality=data_quality,
        quality_flags=tuple(sorted(base_flags)),
        score=score,
        anchor=anchor_snapshot,
        support=signal_support,
        invalid_price_snapshot=signal_invalid_snapshot,
        initial_invalid_price=signal_initial_invalid,
        invalid_price=signal_invalid,
        b2_trigger=trigger,
        expected_b2_trigger_price=signal_expected_b2_trigger,
        resistance_candidates=signal_resistance_candidates,
        immediate_resistance=signal_immediate_resistance,
        target_s1=signal_target_s1,
        entry_reference_price=entry_reference_price,
        entry_headroom_pct=entry_headroom_pct,
        entry_room_state=entry_room_state,
        entry_room_reasons=entry_room_reasons,
        risk_reward_ratio=risk_reward,
        entry_quality_score=entry_quality_score,
        invalidation_reasons=invalidation_reasons,
    )
