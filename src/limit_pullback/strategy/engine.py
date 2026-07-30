"""Pure end-of-day strategy evaluation."""

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
from limit_pullback.strategy.math import calculate_indicators
from limit_pullback.strategy.patterns import evaluate_patterns
from limit_pullback.strategy.scoring import build_score
from limit_pullback.strategy.structure import (
    cluster_price_candidates,
    detect_anchor,
    generate_resistance_candidates,
    generate_support_candidates,
    select_resistance_levels,
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


def _expected_b2_trigger(
    ordered: Sequence[DailyBar],
    config: StrategyConfig,
) -> Decimal:
    return _quantize_price(
        ordered[-1].high * (ONE + config.b2.trigger_buffer),
        config,
    )


def _platform_b2_trigger(
    ordered: Sequence[DailyBar],
    config: StrategyConfig,
) -> Decimal:
    platform = tuple(ordered[-config.b2.platform_lookback_days :])
    return _quantize_price(
        max(bar.high for bar in platform) * (ONE + config.b2.trigger_buffer),
        config,
    )


def _entry_room(
    *,
    stage: SetupStage,
    current_close: Decimal,
    trigger: B2TriggerSnapshot | None,
    target_s1: S1Snapshot | None,
    config: StrategyConfig,
) -> tuple[
    Decimal | None,
    Decimal | None,
    EntryRoomState | None,
    tuple[str, ...],
]:
    if stage not in ACTIONABLE:
        return None, None, None, ()
    if stage is SetupStage.B2_READY:
        assert trigger is not None
        reference = max(current_close, trigger.trigger_price)
        reference_reason = "B2_READY_MAX_CLOSE_AND_TRIGGER"
    elif stage is SetupStage.B2_CONFIRMED:
        reference = current_close
        reference_reason = "B2_CONFIRMED_CLOSE"
    else:
        reference = current_close
        reference_reason = "B1_READY_CLOSE"

    if target_s1 is None:
        return (
            reference,
            None,
            EntryRoomState.OPEN_SPACE,
            (reference_reason, "NO_RELIABLE_TARGET_S1"),
        )
    headroom = (target_s1.s1_low - reference) / reference
    if headroom <= ZERO:
        state = EntryRoomState.NONE
        state_reason = "TARGET_S1_AT_OR_BELOW_ENTRY_REFERENCE"
    elif headroom < config.entry_room.thin_headroom_max:
        state = EntryRoomState.THIN
        state_reason = "TARGET_S1_HEADROOM_THIN"
    else:
        state = EntryRoomState.SUFFICIENT
        state_reason = "TARGET_S1_HEADROOM_SUFFICIENT"
    return reference, headroom, state, (reference_reason, state_reason)


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
            "intraday_trigger_breakout": current.high >= trigger.trigger_price,
            "close_holds_trigger": current.close >= trigger.trigger_price,
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


def _evaluate_invalid_reasons(
    *,
    ordered: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    current: DailyBar,
    anchor: AnchorEvaluation,
    support: PriceCluster | None,
    support_snapshot: SupportSnapshot | None,
    invalid_price: Decimal | None,
    config: StrategyConfig,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if invalid_price is not None and current.close <= invalid_price:
        reasons.append("HIT_INVALID_PRICE")
    if support is None:
        return tuple(reasons)
    if (
        current.close
        < support.low * (ONE - config.invalidation.support_break_buffer)
    ):
        reasons.append("SUPPORT_BREAK")
    ma10 = indicators[-1].raw_equivalent_mas.get(10)
    if (
        ma10 is not None
        and current.close < anchor.snapshot.anchor_price
        and current.close < ma10
    ):
        reasons.append("ANCHOR_AND_MA10_BREAK")
    previous = tuple(ordered[:-1])
    previous_volumes = tuple(bar.volume for bar in previous[-5:])
    volume_reference = _mean(previous_volumes) if previous_volumes else None
    if (
        support_snapshot is not None
        and support_snapshot.reference_low is not None
        and current.close < support_snapshot.reference_low
        and volume_reference is not None
        and current.volume
        >= volume_reference * config.invalidation.volume_expansion_min
    ):
        reasons.append("VOLUME_BREAK_B1_LOW")
    distribution_days = config.invalidation.consecutive_distribution_days
    if len(ordered) >= distribution_days + 5:
        tail = tuple(ordered[-distribution_days:])
        reference = tuple(ordered[-distribution_days - 5 : -distribution_days])
        consecutive_down = all(
            bar.close < bar.preclose and bar.close < bar.open for bar in tail
        )
        if (
            consecutive_down
            and _mean(tuple(bar.volume for bar in tail))
            >= _mean(tuple(bar.volume for bar in reference))
            * config.invalidation.volume_expansion_min
        ):
            reasons.append("CONSECUTIVE_VOLUME_DISTRIBUTION")
    if (
        len(ordered) >= 2
        and support_snapshot is not None
        and support_snapshot.eligible_from <= ordered[-2].trade_date
        and ordered[-2].close
        < support.low * (ONE - config.invalidation.support_break_buffer)
        and current.close < support.low
    ):
        reasons.append("FAILED_SUPPORT_RECOVERY")
    return tuple(sorted(set(reasons)))


def _evaluate_event_flags(
    *,
    ordered: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    current: DailyBar,
    support: PriceCluster | None,
    invalid_price: Decimal | None,
    s1: PriceCluster | None,
    setup_stage: SetupStage,
    config: StrategyConfig,
) -> tuple[frozenset[EventFlag], dict[EventFlag, tuple[str, ...]]]:
    flags: set[EventFlag] = set()
    reasons: dict[EventFlag, list[str]] = {}

    def add_reason(flag: EventFlag, reason: str) -> None:
        flags.add(flag)
        reasons.setdefault(flag, []).append(reason)

    if support is not None:
        warning_config = config.events.support_warning
        close_near_support_low = (
            current.close >= support.low
            and (
                current.close - support.low
            ) / support.low <= warning_config.close_to_support_low_max
        )
        close_near_invalid = (
            invalid_price is not None
            and current.close > invalid_price
            and (
                current.close - invalid_price
            ) / invalid_price <= warning_config.close_to_invalid_max
        )
        intraday_break_recovered = (
            current.low < support.low and current.close >= support.low
        )
        volume_window = tuple(
            bar.volume
            for bar in ordered[:-1][-warning_config.volume_lookback_days :]
        )
        abnormal_volume_near_support = (
            bool(volume_window)
            and current.low
            >= support.low * (ONE - warning_config.test_distance_max)
            and current.low
            <= support.low * (ONE + warning_config.test_distance_max)
            and current.volume
            >= _mean(volume_window) * warning_config.abnormal_volume_ratio_min
        )
        test_days = warning_config.consecutive_test_days
        recent_tests = tuple(ordered[-test_days:])
        consecutive_support_tests = (
            len(recent_tests) == test_days
            and all(
                support.low * (ONE - warning_config.test_distance_max)
                <= bar.low
                <= support.low * (ONE + warning_config.test_distance_max)
                for bar in recent_tests
            )
        )
        warning_reasons = (
            ("CLOSE_NEAR_SUPPORT_LOW", close_near_support_low),
            ("CLOSE_NEAR_INITIAL_INVALID_PRICE", close_near_invalid),
            ("INTRADAY_SUPPORT_BREAK_RECOVERED", intraday_break_recovered),
            ("ABNORMAL_VOLUME_NEAR_SUPPORT", abnormal_volume_near_support),
            ("CONSECUTIVE_SUPPORT_TESTS", consecutive_support_tests),
        )
        for reason, matched in warning_reasons:
            if matched:
                add_reason(EventFlag.SUPPORT_WARNING, reason)
    if s1 is not None:
        if (
            current.close
            >= s1.high * (ONE + config.events.s1_breakout_close_buffer)
        ):
            add_reason(
                EventFlag.S1_BREAKOUT,
                "CLOSE_ABOVE_S1_BREAKOUT_THRESHOLD",
            )
        elif (
            current.high
            >= s1.low * (ONE - config.events.near_s1_distance)
        ):
            add_reason(EventFlag.NEAR_S1, "HIGH_WITHIN_NEAR_S1_DISTANCE")

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
            for condition in s2_conditions.matched:
                add_reason(
                    EventFlag.S2_EXHAUSTED,
                    f"S2_MATCHED:{condition}",
                )

    if setup_stage is SetupStage.INVALID:
        flags = set(
            flag for flag in flags if flag is EventFlag.S2_EXHAUSTED
        )
        reasons = {
            flag: values for flag, values in reasons.items() if flag in flags
        }
    if EventFlag.S1_BREAKOUT in flags:
        flags.discard(EventFlag.NEAR_S1)
        reasons.pop(EventFlag.NEAR_S1, None)
    frozen_flags = frozenset(flags)
    return frozen_flags, {
        flag: tuple(sorted(set(reasons[flag])))
        for flag in sorted(frozen_flags, key=lambda item: item.value)
    }


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
        ) = select_resistance_levels(
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
        invalid_price=setup_invalid_price,
        s1=setup_target_s1,
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
            invalid_price=(
                eligible_invalid_snapshot.invalid_price
                if eligible_invalid_snapshot is not None
                else None
            ),
            s1=eligible_target_s1,
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
        invalidation_reasons=invalidation_reasons,
    )
