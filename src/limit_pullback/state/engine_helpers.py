"""State transition helpers (verbatim REF-R5 move from strategy/engine.py).

These functions evaluate frozen state conditions: setup identity, B1/B2
conditions, trigger freezing, invalid reasons, event flags, entry room, and
risk/reward. They are byte-identical to the code base `1cb5fb7a` helpers.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import (
    DataQuality,
    EntryRoomState,
    EventFlag,
    SetupStage,
)
from limit_pullback.models.market import DailyBar
from limit_pullback.models.signal import (
    B2TriggerSnapshot,
    InvalidPriceSnapshot,
    S1Snapshot,
    SupportSnapshot,
)
from limit_pullback.models.strategy import (
    AnchorEvaluation,
    ConditionScore,
    IndicatorPoint,
    PriceCluster,
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
        }
    )


def _evaluate_b2_confirmation(
    *,
    ordered: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    current: DailyBar,
    anchor: AnchorEvaluation,
    trigger: B2TriggerSnapshot,
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
        }
    )


def _entry_quality_score(
    *,
    setup_quality_score: Decimal,
    stage: SetupStage,
    data_quality: DataQuality,
    event_flags: frozenset[EventFlag],
    entry_headroom_pct: Decimal | None,
    entry_room_state: EntryRoomState | None,
    risk_reward_ratio: Decimal | None,
    config: StrategyConfig,
) -> Decimal | None:
    """Derive entry value without feeding it back into setup lifecycle state."""

    if stage not in ACTIONABLE:
        return None
    if (
        data_quality is DataQuality.UNUSABLE
        or entry_room_state is EntryRoomState.NONE
        or EventFlag.S1_BREAKOUT in event_flags
        or EventFlag.S2_EXHAUSTED in event_flags
    ):
        return ZERO.quantize(config.scoring.normalized_score_quantum)

    factor = ONE
    if (
        entry_room_state is EntryRoomState.THIN
        and entry_headroom_pct is not None
    ):
        factor = min(
            factor,
            max(
                ZERO,
                entry_headroom_pct / config.entry_room.thin_headroom_max,
            ),
        )
    if risk_reward_ratio is not None:
        factor = min(
            factor,
            risk_reward_ratio / config.entry_room.minimum_risk_reward,
            ONE,
        )
    return (setup_quality_score * factor).quantize(
        config.scoring.normalized_score_quantum,
        rounding=ROUND_HALF_UP,
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


__all__ = [
    "ACTIONABLE",
    "ONE",
    "ZERO",
    "_as_cluster",
    "_as_s1_cluster",
    "_conditions",
    "_entry_quality_score",
    "_entry_room",
    "_evaluate_b1",
    "_evaluate_b2_confirmation",
    "_evaluate_event_flags",
    "_evaluate_invalid_reasons",
    "_expected_b2_trigger",
    "_mean",
    "_platform_b2_trigger",
    "_quantize_price",
    "_risk_reward",
    "make_setup_id",
]
