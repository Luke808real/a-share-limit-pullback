"""Pure end-of-day strategy evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import (
    DataQuality,
    EventFlag,
    ReviewGroup,
    ScoreProfile,
    SetupStage,
)
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.signal import (
    B2TriggerSnapshot,
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
from limit_pullback.strategy.math import calculate_indicators
from limit_pullback.strategy.patterns import evaluate_patterns
from limit_pullback.strategy.scoring import build_score
from limit_pullback.strategy.structure import (
    cluster_price_candidates,
    detect_anchor,
    generate_resistance_candidates,
    generate_support_candidates,
    select_resistance_cluster,
    select_support_cluster,
)


ZERO = Decimal("0")
ONE = Decimal("1")
ACTIONABLE = frozenset(
    {SetupStage.B1_READY, SetupStage.B2_READY, SetupStage.B2_CONFIRMED}
)


def make_setup_id(
    code: str,
    anchor_date: date,
    anchor_price: Decimal,
    price_tick: Decimal = Decimal("0.01"),
) -> str:
    ticks = (anchor_price / price_tick).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return f"{code}:{anchor_date:%Y%m%d}:{ticks}"


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, ZERO) / Decimal(len(values))


def _conditions(results: dict[str, bool | None]) -> ConditionScore:
    return ConditionScore(
        matched=tuple(sorted(
            name for name, result in results.items() if result is True
        )),
        failed=tuple(sorted(
            name for name, result in results.items() if result is False
        )),
        unavailable=tuple(sorted(
            name for name, result in results.items() if result is None
        )),
    )


def _as_cluster(snapshot: SupportSnapshot) -> PriceCluster:
    return PriceCluster(
        low=snapshot.support_low,
        high=snapshot.support_high,
        center=snapshot.support_center,
        sources=snapshot.sources,
    )


def _as_s1_cluster(snapshot: S1Snapshot) -> PriceCluster:
    return PriceCluster(
        low=snapshot.s1_low,
        high=snapshot.s1_high,
        center=(snapshot.s1_low + snapshot.s1_high) / Decimal("2"),
        sources=snapshot.sources,
    )


def _quantize_price(value: Decimal, config: StrategyConfig) -> Decimal:
    return value.quantize(config.anchor.price_tick, rounding=ROUND_HALF_UP)


def _risk_reward(
    current_close: Decimal,
    invalid_price: Decimal,
    s1: PriceCluster | None,
) -> Decimal | None:
    if s1 is None:
        return None
    if s1.low <= current_close:
        return None
    potential_loss = current_close - invalid_price
    if potential_loss <= ZERO:
        return None
    return (s1.low - current_close) / potential_loss


def _evaluate_b1(
    *,
    ordered: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    current: DailyBar,
    anchor: AnchorEvaluation,
    support: PriceCluster | None,
    invalid_price: Decimal | None,
    s1: PriceCluster | None,
    config: StrategyConfig,
) -> ConditionScore:
    anchor_index = next(
        index
        for index, bar in enumerate(ordered)
        if bar.trade_date == anchor.snapshot.anchor_date
    )
    current_index = len(ordered) - 1
    days_after = current_index - anchor_index
    anchor_bar = ordered[anchor_index]
    post_anchor = tuple(ordered[anchor_index + 1 :])
    current_indicator = indicators[-1]

    support_touch = (
        current.low <= support.high and current.high >= support.low
        if support is not None
        else None
    )
    support_hold = (
        current.close >= support.low if support is not None else None
    )
    recent_days = config.b1.recent_volume_days
    if len(post_anchor) >= recent_days and len(post_anchor) >= 2:
        recent_average = _mean(tuple(
            bar.volume for bar in post_anchor[-recent_days:]
        ))
        post_anchor_max = max(bar.volume for bar in post_anchor)
        recent_volume_contraction = (
            recent_average
            <= post_anchor_max * config.b1.recent_volume_to_post_anchor_max
        )
    else:
        recent_volume_contraction = None
    no_long_bearish = not (
        current_indicator.kline.is_long_bearish
        and current.volume >= anchor_bar.volume
    )
    reversal = (
        current_indicator.kline.is_doji
        or current_indicator.kline.has_long_lower_shadow
        or (
            current_indicator.kline.is_bullish
            and current_indicator.kline.is_small_body
        )
        or (
            current_indicator.kline.is_bearish
            and current_indicator.kline.is_small_body
            and current.volume < anchor_bar.volume
        )
    )
    risk_reward = (
        _risk_reward(current.close, invalid_price, s1)
        if invalid_price is not None
        else None
    )
    return _conditions(
        {
            "anchor_day_window": (
                config.b1.days_after_anchor_min
                <= days_after
                <= config.b1.days_after_anchor_max
            ),
            "optimal_day_window": (
                config.b1.optimal_days_min
                <= days_after
                <= config.b1.optimal_days_max
            ),
            "anchor_price_band": (
                config.b1.close_to_anchor_min
                <= current.close / anchor.snapshot.anchor_price
                <= config.b1.close_to_anchor_max
            ),
            "support_touch": support_touch,
            "support_hold": support_hold,
            "anchor_volume_contraction": (
                current.volume
                <= anchor_bar.volume * config.b1.volume_to_anchor_max
            ),
            "recent_volume_contraction": recent_volume_contraction,
            "no_volume_long_bearish": no_long_bearish,
            "reversal_kline": reversal,
            "risk_reward": (
                risk_reward >= config.b1.minimum_risk_reward
                if risk_reward is not None
                else None
            ),
        }
    )


def _evaluate_b2_confirmation(
    *,
    ordered: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    current: DailyBar,
    anchor: AnchorEvaluation,
    trigger: B2TriggerSnapshot,
    invalid_price: Decimal | None,
    s1: PriceCluster | None,
    config: StrategyConfig,
) -> ConditionScore:
    anchor_index = next(
        index
        for index, bar in enumerate(ordered)
        if bar.trade_date == anchor.snapshot.anchor_date
    )
    current_indicator = indicators[-1]
    pullback_bars = tuple(ordered[anchor_index + 1 : -1])
    average_pullback_volume = (
        _mean(tuple(bar.volume for bar in pullback_bars))
        if pullback_bars
        else None
    )
    volume_ratio = (
        current.volume / average_pullback_volume
        if average_pullback_volume is not None and average_pullback_volume > ZERO
        else None
    )
    ma_values = tuple(
        value
        for window in (5, 10)
        if (value := current_indicator.raw_equivalent_mas.get(window)) is not None
    )
    risk_reward = (
        _risk_reward(current.close, invalid_price, s1)
        if invalid_price is not None
        else None
    )
    moderate_body = (
        current_indicator.kline.is_bullish
        and not current_indicator.kline.is_doji
        and current_indicator.kline.body_share
        < config.indicators.kline.long_body_share_min
    )
    return _conditions(
        {
            "frozen_trigger_breakout": current.high >= trigger.trigger_price,
            "daily_return_range": (
                config.b2.daily_return_min
                <= current.close / current.preclose - ONE
                <= config.b2.daily_return_max
            ),
            "moderate_bullish_body": moderate_body,
            "upper_close_location": (
                current_indicator.kline.close_location
                >= config.b2.close_location_min
            ),
            "stands_above_ma5_or_ma10": (
                current.close >= min(ma_values) if ma_values else None
            ),
            "volume_expansion_range": (
                config.b2.volume_expansion_min
                <= volume_ratio
                <= config.b2.volume_expansion_max
                if volume_ratio is not None
                else None
            ),
            "not_explosive_long_bar": (
                (
                    volume_ratio <= config.b2.volume_expansion_max
                    and current_indicator.kline.body_share
                    < config.indicators.kline.long_body_share_min
                )
                if volume_ratio is not None
                else None
            ),
            "reasonable_s1_space": (
                risk_reward >= config.b1.minimum_risk_reward
                if risk_reward is not None
                else None
            ),
        }
    )


def _evaluate_invalid(
    *,
    ordered: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    current: DailyBar,
    anchor: AnchorEvaluation,
    support: PriceCluster | None,
    support_snapshot: SupportSnapshot | None,
    invalid_price: Decimal | None,
    config: StrategyConfig,
) -> bool:
    if invalid_price is not None and current.close <= invalid_price:
        return True
    if support is None:
        return False
    support_break = (
        current.close
        < support.low * (ONE - config.invalidation.support_break_buffer)
    )
    ma10 = indicators[-1].raw_equivalent_mas.get(10)
    anchor_and_ma10_break = (
        ma10 is not None
        and current.close < anchor.snapshot.anchor_price
        and current.close < ma10
    )
    previous = tuple(ordered[:-1])
    previous_volumes = tuple(bar.volume for bar in previous[-5:])
    volume_reference = _mean(previous_volumes) if previous_volumes else None
    b1_low_break = (
        support_snapshot is not None
        and support_snapshot.reference_low is not None
        and current.close < support_snapshot.reference_low
        and volume_reference is not None
        and current.volume
        >= volume_reference * config.invalidation.volume_expansion_min
    )
    distribution_days = config.invalidation.consecutive_distribution_days
    if len(ordered) >= distribution_days + 5:
        tail = tuple(ordered[-distribution_days:])
        reference = tuple(ordered[-distribution_days - 5 : -distribution_days])
        consecutive_down = all(
            bar.close < bar.preclose and bar.close < bar.open for bar in tail
        )
        distribution = (
            consecutive_down
            and _mean(tuple(bar.volume for bar in tail))
            >= _mean(tuple(bar.volume for bar in reference))
            * config.invalidation.volume_expansion_min
        )
    else:
        distribution = False
    failed_recovery = (
        len(ordered) >= 2
        and ordered[-2].close
        < support.low * (ONE - config.invalidation.support_break_buffer)
        and current.close < support.low
    )
    return any(
        (
            support_break,
            anchor_and_ma10_break,
            b1_low_break,
            distribution,
            failed_recovery,
        )
    )


def _event_flags(
    *,
    ordered: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    current: DailyBar,
    support: PriceCluster | None,
    invalid_price: Decimal | None,
    s1: PriceCluster | None,
    config: StrategyConfig,
) -> frozenset[EventFlag]:
    flags: set[EventFlag] = set()
    if support is not None:
        near_support = (
            current.low
            <= support.high * (ONE + config.events.support_warning_distance)
        )
        not_invalid = invalid_price is None or current.close > invalid_price
        if near_support and not_invalid:
            flags.add(EventFlag.SUPPORT_WARNING)
    if s1 is None:
        return frozenset(flags)

    if (
        current.high
        >= s1.low * (ONE - config.events.near_s1_distance)
    ):
        flags.add(EventFlag.NEAR_S1)
    if (
        current.close
        >= s1.high * (ONE + config.events.s1_breakout_close_buffer)
    ):
        flags.add(EventFlag.S1_BREAKOUT)

    previous_volumes = tuple(bar.volume for bar in ordered[:-1][-5:])
    average_volume = _mean(previous_volumes) if previous_volumes else None
    kline = indicators[-1].kline
    s2_conditions = _conditions(
        {
            "touch_s1": current.high >= s1.low,
            "close_off_high": (
                (current.high - current.close) / current.high
                >= config.events.s2.close_off_high_min
            ),
            "upper_shadow": (
                kline.upper_shadow_share
                >= config.events.s2.upper_shadow_share_min
            ),
            "volume_expansion": (
                current.volume
                >= average_volume * config.events.s2.volume_to_ma5_min
                if average_volume is not None
                else None
            ),
            "failed_to_hold_s1": current.close < s1.high,
        }
    )
    if (
        "touch_s1" in s2_conditions.matched
        and s2_conditions.match_ratio
        >= config.events.s2.minimum_condition_ratio
    ):
        flags.add(EventFlag.S2_EXHAUSTED)
    return frozenset(flags)


def evaluate_strategy(
    *,
    bars: Sequence[DailyBar],
    as_of: date,
    config: StrategyConfig,
    generated_at: datetime,
    limit_pool: Sequence[LimitUpRecord] = (),
    previous_signal: StrategySignal | None = None,
) -> StrategySignal:
    """Evaluate one code as of one close, using only supplied data at or before T."""

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
    indicators = calculate_indicators(ordered, config.indicators, as_of)
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
    resistance_candidates = generate_resistance_candidates(
        ordered, anchor, as_of, config
    )
    resistance_clusters = cluster_price_candidates(
        resistance_candidates, config.resistance.cluster_distance
    )
    computed_s1 = select_resistance_cluster(
        resistance_clusters, current.close
    )

    frozen_support = (
        previous_same.support if previous_same is not None else None
    )
    active_support = (
        _as_cluster(frozen_support)
        if frozen_support is not None
        else computed_support
    )
    previous_was_actionable = (
        previous_same is not None
        and previous_same.setup_stage in ACTIONABLE | {SetupStage.INVALID}
    )
    if previous_was_actionable:
        frozen_s1 = previous_same.s1
        active_s1 = _as_s1_cluster(frozen_s1) if frozen_s1 is not None else None
    else:
        frozen_s1 = None
        active_s1 = computed_s1

    proposed_invalid = (
        _quantize_price(
            active_support.low * (ONE - config.support.invalid_buffer),
            config,
        )
        if active_support is not None
        else None
    )
    initial_invalid = (
        previous_same.initial_invalid_price
        if previous_same is not None
        and previous_same.initial_invalid_price is not None
        else proposed_invalid
    )
    current_invalid = (
        max(previous_same.invalid_price, initial_invalid)
        if previous_same is not None
        and previous_same.invalid_price is not None
        and initial_invalid is not None
        else initial_invalid
    )

    patterns = evaluate_patterns(
        ordered, indicators, anchor, active_support, as_of, config
    )
    b1_conditions = _evaluate_b1(
        ordered=ordered,
        indicators=indicators,
        current=current,
        anchor=anchor,
        support=active_support,
        invalid_price=current_invalid,
        s1=active_s1,
        config=config,
    )
    b1_ready = (
        active_support is not None
        and current_invalid is not None
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
            invalid_price=current_invalid,
            s1=active_s1,
            config=config,
        )
        b2_confirmed = (
            "frozen_trigger_breakout" in b2_conditions.matched
            and b2_conditions.match_ratio >= config.b2.minimum_condition_ratio
        )

    invalid = (
        previous_same is not None
        and previous_same.setup_stage is SetupStage.INVALID
    ) or _evaluate_invalid(
        ordered=ordered,
        indicators=indicators,
        current=current,
        anchor=anchor,
        support=active_support,
        support_snapshot=frozen_support,
        invalid_price=current_invalid,
        config=config,
    )

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
        platform = tuple(ordered[-config.b2.platform_lookback_days :])
        trigger_price = _quantize_price(
            max(bar.high for bar in platform)
            * (ONE + config.b2.trigger_buffer),
            config,
        )
        trigger = B2TriggerSnapshot(
            trigger_price=trigger_price,
            frozen_as_of=as_of,
            eligible_from=as_of + timedelta(days=1),
            sources=("PULLBACK_PLATFORM_HIGH",),
        )
        stage = SetupStage.B2_READY
    elif b1_ready:
        stage = SetupStage.B1_READY
    else:
        stage = SetupStage.WATCH_PULLBACK

    should_freeze_structure = stage in ACTIONABLE | {SetupStage.INVALID}
    if should_freeze_structure and frozen_support is None and active_support is not None:
        frozen_support = SupportSnapshot(
            support_low=active_support.low,
            support_high=active_support.high,
            support_center=active_support.center,
            sources=active_support.sources,
            frozen_as_of=as_of,
            reference_low=current.low,
        )
    if should_freeze_structure and not previous_was_actionable:
        frozen_s1 = (
            S1Snapshot(
                s1_low=active_s1.low,
                s1_high=active_s1.high,
                sources=active_s1.sources,
                frozen_as_of=as_of,
            )
            if active_s1 is not None
            else None
        )

    if invalid:
        if frozen_support is None and active_support is not None:
            frozen_support = SupportSnapshot(
                support_low=active_support.low,
                support_high=active_support.high,
                support_center=active_support.center,
                sources=active_support.sources,
                frozen_as_of=as_of,
                reference_low=current.low,
            )
        if not previous_was_actionable and frozen_s1 is None and active_s1 is not None:
            frozen_s1 = S1Snapshot(
                s1_low=active_s1.low,
                s1_high=active_s1.high,
                sources=active_s1.sources,
                frozen_as_of=as_of,
            )

    event_s1 = _as_s1_cluster(frozen_s1) if frozen_s1 is not None else active_s1
    flags = _event_flags(
        ordered=ordered,
        indicators=indicators,
        current=current,
        support=active_support,
        invalid_price=current_invalid,
        s1=event_s1,
        config=config,
    )

    score = build_score(
        config=config,
        profile=anchor.profile,
        bars=ordered,
        indicators=indicators,
        current=current,
        anchor=anchor,
        support=active_support,
        patterns=patterns,
        b1_conditions=b1_conditions,
        b2_conditions=b2_conditions,
        setup_stage=stage,
        limit_pool=usable_pool,
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

    signal_s1 = frozen_s1 if stage in ACTIONABLE | {SetupStage.INVALID} else None
    signal_support = (
        frozen_support if stage in ACTIONABLE | {SetupStage.INVALID} else None
    )
    signal_initial_invalid = (
        initial_invalid if signal_support is not None else None
    )
    signal_invalid = (
        current_invalid if signal_support is not None else None
    )
    if stage in ACTIONABLE and signal_s1 is None:
        review_group = ReviewGroup.OPEN_SPACE
        risk_reward = None
    else:
        review_group = ReviewGroup.STANDARD
        risk_reward = (
            _risk_reward(
                current.close,
                signal_invalid,
                _as_s1_cluster(signal_s1),
            )
            if signal_invalid is not None and signal_s1 is not None
            else None
        )

    return StrategySignal(
        strategy_version=config.strategy_version,
        setup_id=setup_id,
        trade_date=as_of,
        code=current.code,
        generated_at=generated_at,
        setup_stage=stage,
        patterns=patterns.patterns,
        event_flags=flags,
        review_group=review_group,
        data_quality=data_quality,
        quality_flags=tuple(sorted(base_flags)),
        score=score,
        anchor=anchor_snapshot,
        support=signal_support,
        initial_invalid_price=signal_initial_invalid,
        invalid_price=signal_invalid,
        b2_trigger=trigger,
        s1=signal_s1,
        risk_reward_ratio=risk_reward,
    )
