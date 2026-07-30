from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
import yaml

from limit_pullback.config import load_strategy_config
from limit_pullback.models.enums import (
    DataQuality,
    EntryRoomState,
    EventFlag,
    ReviewGroup,
    ScoreProfile,
    SetupStage,
    PatternType,
)
from limit_pullback.models.signal import S1Snapshot
from limit_pullback.models.strategy import PriceCluster
from limit_pullback.strategy import engine as engine_module
from limit_pullback.strategy.engine import (
    _entry_room,
    evaluate_strategy,
    make_setup_id,
)
from limit_pullback.strategy.patterns import select_primary_pattern
from limit_pullback.strategy.structure import (
    select_resistance_levels as real_select_resistance_levels,
)
from tests.synthetic_data import (
    TZ_SHANGHAI,
    append_b2_confirm_bar,
    append_b2_ready_bar,
    append_invalid_bar,
    append_open_space_pullback,
    append_pullback_bars,
    append_s2_bar,
    append_support_threat_bar,
    base_setup_bars,
    business_dates,
    full_limit_pool,
    make_bar,
)


GENERATED_AT = datetime(2024, 1, 1, 16, 0, tzinfo=TZ_SHANGHAI)


@pytest.fixture
def config(project_root):
    return load_strategy_config(project_root / "config" / "strategy.yaml")


@pytest.fixture
def golden(project_root):
    with (
        project_root / "tests" / "fixtures" / "golden_expectations.yaml"
    ).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def assert_golden(signal, expectation):
    assert signal.setup_stage.value == expectation["setup_stage"]
    assert sorted(flag.value for flag in signal.event_flags) == sorted(
        expectation["event_flags"]
    )
    if "matched_patterns" in expectation:
        assert sorted(
            pattern.value for pattern in signal.matched_patterns
        ) == sorted(
            expectation["matched_patterns"]
        )
    if "primary_pattern" in expectation:
        assert signal.primary_pattern.value == expectation["primary_pattern"]
    assert signal.review_group.value == expectation["review_group"]


def build_progression(config):
    bars = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(bars)
    b1 = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    append_b2_ready_bar(bars)
    ready = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=b1,
    )
    append_b2_confirm_bar(bars)
    confirmed = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=ready,
    )
    return bars, pool, b1, ready, confirmed


def evaluate_setup_timeline(bars, config):
    pool = full_limit_pool(bars)
    previous = None
    timeline = []
    for index in range(130, len(bars)):
        signal = evaluate_strategy(
            bars=bars[: index + 1],
            as_of=bars[index].trade_date,
            config=config,
            generated_at=GENERATED_AT,
            limit_pool=pool,
            previous_signal=previous,
        )
        timeline.append(signal)
        previous = signal
    return tuple(timeline)


def resistance_selector_with_target(target):
    def select(*args, **kwargs):
        immediate, _, audit, expected = real_select_resistance_levels(
            *args,
            **kwargs,
        )
        return immediate, target, audit, expected

    return select


def pressure_target(low: str, high: str) -> PriceCluster:
    low_value = Decimal(low)
    high_value = Decimal(high)
    return PriceCluster(
        low=low_value,
        high=high_value,
        center=(low_value + high_value) / Decimal("2"),
        sources=("TEST_LEGAL_PRESSURE",),
    )


def test_golden_b1_b2_progression_and_frozen_snapshots(config, golden):
    bars, _, b1, ready, confirmed = build_progression(config)

    assert_golden(b1, golden["b1_ready"])
    assert_golden(ready, golden["b2_ready"])
    assert_golden(confirmed, golden["b2_confirmed"])
    assert ready.b2_trigger is not None
    assert ready.b2_trigger.frozen_as_of < confirmed.trade_date
    assert ready.b2_trigger.eligible_from <= confirmed.trade_date
    assert confirmed.b2_trigger == ready.b2_trigger
    assert b1.anchor == ready.anchor == confirmed.anchor
    assert b1.support == ready.support == confirmed.support
    assert b1.target_s1 == ready.target_s1 == confirmed.target_s1
    assert (
        b1.initial_invalid_price
        == ready.initial_invalid_price
        == confirmed.initial_invalid_price
    )
    assert b1.setup_id == ready.setup_id == confirmed.setup_id
    assert confirmed.trade_date == bars[-1].trade_date
    assert EventFlag.S1_BREAKOUT not in confirmed.event_flags
    assert b1.is_entry_candidate
    assert ready.is_entry_candidate
    assert confirmed.is_entry_candidate
    assert "near_s1_event" not in b1.score.risks
    assert "near_s1_event" not in ready.score.risks


def test_same_day_trigger_cannot_confirm_b2(config):
    bars = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(bars)
    b1 = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    append_b2_confirm_bar(bars)
    signal = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=b1,
    )

    assert signal.setup_stage is SetupStage.B2_READY
    assert signal.b2_trigger is not None
    assert signal.b2_trigger.frozen_as_of == signal.trade_date
    assert signal.b2_trigger.eligible_from > signal.trade_date


def test_intraday_b2_break_without_close_hold_stays_ready(config):
    bars, pool, _, ready, _ = build_progression(config)
    bars.pop()
    raised_trigger = ready.b2_trigger.model_copy(
        update={"trigger_price": Decimal("11.30")}
    )
    ready = ready.model_copy(update={"b2_trigger": raised_trigger})
    append_b2_confirm_bar(bars)
    signal = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=ready,
    )

    assert signal.setup_stage is SetupStage.B2_READY
    assert signal.b2_trigger.trigger_price == Decimal("11.30")
    assert signal.score.risks["b2_quality"] == "盘中突破B2触发价但收盘未站稳"


def test_close_hold_of_frozen_b2_trigger_confirms(config):
    _, _, _, ready, confirmed = build_progression(config)

    assert confirmed.b2_trigger == ready.b2_trigger
    assert confirmed.setup_stage is SetupStage.B2_CONFIRMED
    assert confirmed.event_flags == frozenset()


def test_golden_s2_event(config, golden):
    bars, pool, _, _, confirmed = build_progression(config)
    append_s2_bar(bars)
    exhausted = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=confirmed,
    )

    assert_golden(exhausted, golden["s2_exhausted"])
    assert EventFlag.S2_EXHAUSTED in exhausted.event_flags
    assert not exhausted.is_entry_candidate


def test_golden_invalid_preserves_initial_invalid_price(config, golden):
    base = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(base)
    b1 = evaluate_strategy(
        bars=base,
        as_of=base[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    tightened = b1.model_copy(
        update={
            "invalid_price": b1.initial_invalid_price + Decimal("0.05"),
            "invalid_price_snapshot": b1.invalid_price_snapshot.model_copy(
                update={
                    "invalid_price": (
                        b1.initial_invalid_price + Decimal("0.05")
                    )
                }
            ),
        }
    )
    append_invalid_bar(base)
    invalid = evaluate_strategy(
        bars=base,
        as_of=base[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=tightened,
    )

    assert_golden(invalid, golden["invalid"])
    assert invalid.initial_invalid_price == b1.initial_invalid_price
    assert invalid.invalid_price == tightened.invalid_price
    assert invalid.invalid_price >= invalid.initial_invalid_price
    assert invalid.b2_trigger is None
    assert invalid.invalidation_reasons
    assert EventFlag.NEAR_S1 not in invalid.event_flags
    assert EventFlag.S1_BREAKOUT not in invalid.event_flags
    assert EventFlag.SUPPORT_WARNING not in invalid.event_flags
    assert invalid.score.normalized_score >= Decimal("60")
    assert not invalid.is_entry_candidate


def test_golden_open_space_has_no_synthetic_target(config, golden):
    bars = append_open_space_pullback(
        base_setup_bars(include_left_pressure=False)
    )
    signal = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=full_limit_pool(bars),
    )

    assert_golden(signal, golden["open_space"])
    assert signal.review_group is ReviewGroup.OPEN_SPACE
    assert signal.target_s1 is None
    assert signal.risk_reward_ratio is None
    assert signal.entry_room_state is EntryRoomState.OPEN_SPACE
    assert signal.entry_headroom_pct is None
    assert signal.is_entry_candidate


def test_b1_date_is_identical_with_or_without_target_s1(config, monkeypatch):
    bars = append_pullback_bars(base_setup_bars())
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(None),
    )
    without_target = evaluate_setup_timeline(bars, config)
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(pressure_target("13.00", "13.10")),
    )
    with_target = evaluate_setup_timeline(bars, config)

    without_b1 = next(
        signal
        for signal in without_target
        if signal.setup_stage is SetupStage.B1_READY
    )
    with_b1 = next(
        signal
        for signal in with_target
        if signal.setup_stage is SetupStage.B1_READY
    )

    assert without_b1.trade_date == with_b1.trade_date
    assert without_b1.target_s1 is None
    assert with_b1.target_s1 is not None


def test_replacing_legal_target_s1_does_not_change_setup_timeline(
    config,
    monkeypatch,
):
    bars = append_pullback_bars(base_setup_bars())
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(pressure_target("11.14", "11.16")),
    )
    near_target = evaluate_setup_timeline(bars, config)
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(pressure_target("13.00", "13.10")),
    )
    far_target = evaluate_setup_timeline(bars, config)

    assert tuple(
        (signal.trade_date, signal.setup_stage) for signal in near_target
    ) == tuple(
        (signal.trade_date, signal.setup_stage) for signal in far_target
    )


def test_null_to_high_risk_reward_cannot_promote_watch_early(
    config,
    monkeypatch,
):
    bars = append_pullback_bars(base_setup_bars())
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(None),
    )
    null_risk = evaluate_setup_timeline(bars, config)
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(pressure_target("13.00", "13.10")),
    )
    high_risk = evaluate_setup_timeline(bars, config)
    null_b1 = next(
        signal for signal in null_risk
        if signal.setup_stage is SetupStage.B1_READY
    )
    high_b1 = next(
        signal for signal in high_risk
        if signal.setup_stage is SetupStage.B1_READY
    )

    assert null_b1.risk_reward_ratio is None
    assert (
        high_b1.risk_reward_ratio
        >= config.entry_room.minimum_risk_reward
    )
    assert tuple(
        signal.setup_stage
        for signal in null_risk
        if signal.trade_date < null_b1.trade_date
    ) == tuple(
        signal.setup_stage
        for signal in high_risk
        if signal.trade_date < high_b1.trade_date
    )
    assert null_b1.trade_date == high_b1.trade_date


def test_poor_risk_reward_does_not_downgrade_structural_b1(
    config,
    monkeypatch,
):
    bars = append_pullback_bars(base_setup_bars())
    strict_entry_config = config.model_copy(
        update={
            "entry_room": config.entry_room.model_copy(
                update={"minimum_risk_reward": Decimal("5.00")}
            )
        }
    )
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(pressure_target("13.00", "13.10")),
    )
    high_risk = next(
        signal
        for signal in evaluate_setup_timeline(bars, strict_entry_config)
        if signal.setup_stage is SetupStage.B1_READY
    )
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(pressure_target("11.14", "11.16")),
    )
    poor_risk = next(
        signal
        for signal in evaluate_setup_timeline(bars, strict_entry_config)
        if signal.setup_stage is SetupStage.B1_READY
    )

    assert high_risk.setup_stage is SetupStage.B1_READY
    assert poor_risk.setup_stage is SetupStage.B1_READY
    assert (
        poor_risk.risk_reward_ratio
        < strict_entry_config.entry_room.minimum_risk_reward
    )
    assert poor_risk.trade_date == high_risk.trade_date


def test_open_space_remains_structural_b1_ready(config, monkeypatch):
    bars = append_pullback_bars(base_setup_bars())
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(None),
    )
    signal = next(
        signal
        for signal in evaluate_setup_timeline(bars, config)
        if signal.setup_stage is SetupStage.B1_READY
    )

    assert signal.setup_stage is SetupStage.B1_READY
    assert signal.review_group is ReviewGroup.OPEN_SPACE
    assert signal.target_s1 is None
    assert signal.risk_reward_ratio is None
    assert signal.entry_room_state is EntryRoomState.OPEN_SPACE


def test_no_entry_room_keeps_b2_ready_but_disqualifies_entry(config):
    bars = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(bars)
    b1 = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    append_b2_ready_bar(bars)
    ready = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=b1,
    )
    raised_trigger = ready.b2_trigger.model_copy(
        update={
            "trigger_price": ready.target_s1.s1_low + Decimal("0.50"),
        }
    )
    append_b2_confirm_bar(bars)
    signal = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=ready.model_copy(
            update={"b2_trigger": raised_trigger}
        ),
    )

    assert signal.setup_stage is SetupStage.B2_READY
    assert signal.entry_room_state is EntryRoomState.NONE
    assert not signal.is_entry_candidate
    assert signal.entry_quality_score == Decimal("0.00")


def test_s1_breakout_changes_event_not_setup_stage(config):
    bars = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(bars)
    b1 = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    trade_date = business_dates(bars[-1].trade_date, 2)[1]
    bars.append(
        make_bar(
            trade_date,
            open_price="11.20",
            high="11.55",
            low="11.15",
            close="11.50",
            preclose="10.98",
            volume="500",
        )
    )
    lower_s1 = b1.target_s1.model_copy(
        update={
            "s1_low": Decimal("11.40"),
            "s1_high": Decimal("11.45"),
        }
    )
    breakout = evaluate_strategy(
        bars=bars,
        as_of=trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=b1.model_copy(update={"target_s1": lower_s1}),
    )
    higher_s1 = b1.target_s1.model_copy(
        update={
            "s1_low": Decimal("13.00"),
            "s1_high": Decimal("13.10"),
        }
    )
    no_breakout = evaluate_strategy(
        bars=bars,
        as_of=trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=b1.model_copy(update={"target_s1": higher_s1}),
    )

    assert breakout.setup_stage is SetupStage.B2_READY
    assert no_breakout.setup_stage is SetupStage.B2_READY
    assert EventFlag.S1_BREAKOUT in breakout.event_flags
    assert EventFlag.S1_BREAKOUT not in no_breakout.event_flags
    assert not breakout.is_entry_candidate


def test_future_pressure_change_does_not_change_historical_setup_timeline(
    config,
):
    bars = append_pullback_bars(base_setup_bars())
    cutoff = bars[-1].trade_date
    baseline = evaluate_setup_timeline(bars, config)
    extended = list(bars)
    append_b2_ready_bar(extended)
    extended[-1] = extended[-1].model_copy(
        update={"high": Decimal("99.99")}
    )
    repeated = evaluate_setup_timeline(extended, config)

    assert tuple(
        (
            signal.trade_date,
            signal.setup_id,
            signal.setup_stage,
            signal.setup_quality_score,
        )
        for signal in baseline
    ) == tuple(
        (
            signal.trade_date,
            signal.setup_id,
            signal.setup_stage,
            signal.setup_quality_score,
        )
        for signal in repeated
        if signal.trade_date <= cutoff
    )


def test_setup_quality_score_is_stable_when_s1_changes(
    config,
    monkeypatch,
):
    bars = append_pullback_bars(base_setup_bars())
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(pressure_target("11.14", "11.16")),
    )
    near_target = next(
        signal
        for signal in evaluate_setup_timeline(bars, config)
        if signal.setup_stage is SetupStage.B1_READY
    )
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(pressure_target("13.00", "13.10")),
    )
    far_target = next(
        signal
        for signal in evaluate_setup_timeline(bars, config)
        if signal.setup_stage is SetupStage.B1_READY
    )

    assert near_target.setup_stage is far_target.setup_stage
    assert near_target.setup_quality_score == far_target.setup_quality_score
    assert near_target.score.component_scores == far_target.score.component_scores


def test_entry_fields_may_change_when_s1_changes(config, monkeypatch):
    bars = append_pullback_bars(base_setup_bars())
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(pressure_target("11.14", "11.16")),
    )
    near_target = next(
        signal
        for signal in evaluate_setup_timeline(bars, config)
        if signal.setup_stage is SetupStage.B1_READY
    )
    monkeypatch.setattr(
        engine_module,
        "select_resistance_levels",
        resistance_selector_with_target(pressure_target("13.00", "13.10")),
    )
    far_target = next(
        signal
        for signal in evaluate_setup_timeline(bars, config)
        if signal.setup_stage is SetupStage.B1_READY
    )

    assert near_target.setup_stage is SetupStage.B1_READY
    assert far_target.setup_stage is SetupStage.B1_READY
    assert near_target.target_s1 != far_target.target_s1
    assert near_target.entry_headroom_pct != far_target.entry_headroom_pct
    assert near_target.risk_reward_ratio != far_target.risk_reward_ratio
    assert near_target.entry_quality_score != far_target.entry_quality_score


def test_target_s1_at_entry_reference_has_no_entry_room(config):
    target = S1Snapshot(
        s1_low=Decimal("12.00"),
        s1_high=Decimal("12.10"),
        sources=("LEFT_TARGET_HIGH",),
        frozen_as_of=date(2024, 1, 5),
        eligible_from=date(2024, 1, 6),
    )

    reference, headroom, state, reasons = _entry_room(
        stage=SetupStage.B1_READY,
        current_close=Decimal("12.00"),
        trigger=None,
        target_s1=target,
        config=config,
    )

    assert reference == Decimal("12.00")
    assert headroom == Decimal("0")
    assert state is EntryRoomState.NONE
    assert "TARGET_S1_AT_OR_BELOW_ENTRY_REFERENCE" in reasons


def test_entry_room_uses_decimal_arithmetic(config):
    target = S1Snapshot(
        s1_low=Decimal("12.00"),
        s1_high=Decimal("12.10"),
        sources=("LEFT_TARGET_HIGH",),
        frozen_as_of=date(2024, 1, 5),
        eligible_from=date(2024, 1, 6),
    )

    reference, headroom, state, _ = _entry_room(
        stage=SetupStage.B1_READY,
        current_close=Decimal("10.00"),
        trigger=None,
        target_s1=target,
        config=config,
    )

    assert isinstance(reference, Decimal)
    assert isinstance(headroom, Decimal)
    assert headroom == Decimal("0.20")
    assert state is EntryRoomState.SUFFICIENT


def test_b2_trigger_above_frozen_target_becomes_no_room(config):
    bars = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(bars)
    b1 = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    append_b2_ready_bar(bars)
    ready = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=b1,
    )
    raised_trigger = ready.b2_trigger.model_copy(
        update={
            "trigger_price": ready.target_s1.s1_low + Decimal("0.50"),
        }
    )
    raised_ready = ready.model_copy(update={"b2_trigger": raised_trigger})
    append_b2_confirm_bar(bars)

    signal = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=raised_ready,
    )

    assert signal.target_s1 == ready.target_s1
    assert signal.entry_reference_price == raised_trigger.trigger_price
    assert signal.entry_room_state is EntryRoomState.NONE
    assert not signal.is_entry_candidate


def test_healthy_pullback_has_no_support_warning(config):
    bars = append_pullback_bars(base_setup_bars())
    signal = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=full_limit_pool(bars),
    )

    assert signal.setup_stage is SetupStage.B1_READY
    assert EventFlag.SUPPORT_WARNING not in signal.event_flags
    assert EventFlag.SUPPORT_WARNING not in signal.event_reasons


def test_support_threat_emits_warning(config):
    bars = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(bars)
    b1 = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    append_support_threat_bar(bars)
    warning = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=b1,
    )

    assert warning.setup_stage is not SetupStage.INVALID
    assert EventFlag.SUPPORT_WARNING in warning.event_flags


def test_dual_pattern_match_has_one_primary_pattern(config):
    bars = append_pullback_bars(base_setup_bars())
    signal = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=full_limit_pool(bars),
    )

    assert len(signal.matched_patterns) == 2
    assert signal.primary_pattern in signal.matched_patterns
    assert signal.primary_pattern.value == "BEARISH_PULLBACK"
    assert set(signal.pattern_scores) == signal.matched_patterns


def test_equal_pattern_scores_use_frozen_priority():
    scores = {
        PatternType.AIR_REFUEL: Decimal("80.00"),
        PatternType.BEARISH_PULLBACK: Decimal("80.00"),
    }

    assert select_primary_pattern(set(scores), scores) is PatternType.BEARISH_PULLBACK


def test_full_and_price_only_scoring_are_missing_aware(config):
    bars = append_pullback_bars(base_setup_bars())
    full = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=full_limit_pool(bars),
    )
    price_only = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
    )

    assert full.score.profile is ScoreProfile.FULL
    assert full.data_quality is DataQuality.OK
    assert price_only.score.profile is ScoreProfile.PRICE_ONLY
    assert price_only.data_quality is DataQuality.PARTIAL
    assert "seal_before_cutoff" not in price_only.score.component_scores
    assert "seal_before_cutoff" not in price_only.score.component_max_scores
    assert "seal_before_cutoff" not in price_only.score.risks
    assert "INFERRED_LIMIT_ANCHOR" in price_only.quality_flags


def test_signal_ignores_future_price_and_pool_data(config):
    bars = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(bars)
    as_of = bars[-1].trade_date
    original = evaluate_strategy(
        bars=bars,
        as_of=as_of,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    future = append_invalid_bar(list(bars))[-1]
    future_pool = pool[0].model_copy(
        update={
            "trade_date": future.trade_date,
            "consecutive_count": 9,
        }
    )
    repeated = evaluate_strategy(
        bars=(*bars, future),
        as_of=as_of,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=(*pool, future_pool),
    )

    assert repeated.model_dump_json() == original.model_dump_json()
    assert repeated.target_s1 == original.target_s1
    assert repeated.resistance_candidates == original.resistance_candidates
    assert repeated.entry_room_state == original.entry_room_state
    assert repeated.entry_headroom_pct == original.entry_headroom_pct


def test_s1_selection_uses_only_as_of_and_earlier_bars(config):
    bars = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(bars)
    as_of = bars[-1].trade_date
    original = evaluate_strategy(
        bars=bars,
        as_of=as_of,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    future_bars = list(bars)
    append_invalid_bar(future_bars)
    future_bars[-1] = future_bars[-1].model_copy(
        update={"high": Decimal("99.99")}
    )
    repeated = evaluate_strategy(
        bars=future_bars,
        as_of=as_of,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )

    assert repeated.immediate_resistance == original.immediate_resistance
    assert repeated.target_s1 == original.target_s1
    assert repeated.resistance_candidates == original.resistance_candidates


def test_setup_id_and_decimal_json_are_stable(config):
    bars = append_pullback_bars(base_setup_bars())
    signal = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=full_limit_pool(bars),
    )

    assert signal.setup_id == make_setup_id(
        signal.code,
        signal.anchor.anchor_date,
        signal.anchor.anchor_price,
        config.anchor.price_tick,
    )
    assert signal.setup_id == "600000:20230703:1100"
    payload = signal.model_dump_json()
    assert f'"anchor_price":"{signal.anchor.anchor_price}"' in payload
    assert (
        f'"normalized_score":"{signal.score.normalized_score}"'
        in payload
    )


def test_new_limit_anchor_creates_new_setup_id(config):
    bars = append_pullback_bars(base_setup_bars())
    old_signal = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=full_limit_pool(bars),
    )
    next_date = bars[-1].trade_date
    while True:
        next_date = next_date.fromordinal(next_date.toordinal() + 1)
        if next_date.weekday() < 5:
            break
    new_anchor = bars[-1].model_copy(
        update={
            "trade_date": next_date,
            "open": Decimal("10.95"),
            "high": Decimal("12.08"),
            "low": Decimal("10.90"),
            "close": Decimal("12.08"),
            "preclose": Decimal("10.98"),
            "volume": Decimal("1200"),
            "amount": Decimal("14496"),
        }
    )
    bars.append(new_anchor)
    new_signal = evaluate_strategy(
        bars=bars,
        as_of=next_date,
        config=config,
        generated_at=GENERATED_AT,
        previous_signal=old_signal,
    )

    assert new_signal.setup_stage is SetupStage.LIMIT_ANCHOR
    assert new_signal.setup_id != old_signal.setup_id
    assert new_signal.anchor.anchor_date == next_date
