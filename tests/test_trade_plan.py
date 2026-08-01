from __future__ import annotations

from datetime import timedelta

import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.models.enums import EntryRoomState, SetupStage
from limit_pullback.strategy.engine import evaluate_strategy
from limit_pullback.trade_plan import build_trade_plan
from tests.synthetic_data import (
    append_b2_ready_bar,
    append_pullback_bars,
    base_setup_bars,
    full_limit_pool,
    make_bar,
)
from tests.test_strategy_engine import GENERATED_AT


@pytest.fixture
def config(project_root):
    return load_strategy_config(project_root / "config" / "strategy.yaml")


def _watch_signal(config, *, close: str = "10.86", low: str = "10.78"):
    bars = append_pullback_bars(base_setup_bars())
    current = bars[-1]
    bars[-1] = make_bar(
        current.trade_date,
        open_price="10.86",
        high="10.90",
        low=low,
        close=close,
        preclose="10.96",
        volume="300",
    )
    pool = full_limit_pool(bars)
    signal = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    watch = signal.model_copy(
        update={
            "setup_stage": SetupStage.WATCH_PULLBACK,
            "support": None,
            "invalid_price_snapshot": None,
            "initial_invalid_price": None,
            "invalid_price": None,
            "b2_trigger": None,
            "expected_b2_trigger_price": None,
            "resistance_candidates": (),
            "immediate_resistance": None,
            "target_s1": None,
            "entry_reference_price": None,
            "entry_headroom_pct": None,
            "entry_room_state": None,
            "entry_room_reasons": (),
            "risk_reward_ratio": None,
            "entry_quality_score": None,
            "event_flags": frozenset(),
            "event_reasons": {},
            "invalidation_reasons": (),
        }
    )
    return bars, pool, watch


def _plan(*, signal, bars, pool, config, plan_date=None):
    effective_plan_date = plan_date or bars[-1].trade_date
    return build_trade_plan(
        signal=signal,
        bars=bars,
        limit_pool=pool,
        config=config,
        plan_date=effective_plan_date,
        for_trade_date=effective_plan_date + timedelta(days=1),
        snapshot_id="snap-test",
        strategy_commit="commit-test",
        config_hash="config-test",
    )


def test_b1_prep_positive(config):
    bars, pool, signal = _watch_signal(config)

    plan = _plan(signal=signal, bars=bars, pool=pool, config=config)

    assert plan.execution_label.value == "B1_PREP"
    assert plan.is_actionable
    assert plan.buy_zone_low is not None
    assert plan.preferred_entry is not None
    assert plan.invalid_price is not None
    assert plan.s1_price is None
    assert plan.cancel_conditions == ()


def test_b1_prep_rejected_by_invalid_setup(config):
    bars, pool, signal = _watch_signal(config)
    invalid = signal.model_copy(update={"setup_stage": SetupStage.INVALID})

    plan = _plan(signal=invalid, bars=bars, pool=pool, config=config)

    assert plan.execution_label.value == "WATCH_ONLY"
    assert not plan.is_actionable
    assert "INVALID_SETUP" in plan.cancel_conditions


def test_b1_prep_rejected_by_entry_room_none(config):
    bars, pool, signal = _watch_signal(config)
    b1 = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    b1 = b1.model_copy(update={"entry_room_state": EntryRoomState.NONE})

    plan = _plan(signal=b1, bars=bars, pool=pool, config=config)

    assert plan.execution_label.value == "B1_READY"
    assert not plan.is_actionable
    assert "ENTRY_ROOM_NONE" in plan.cancel_conditions


def test_b1_prep_rejected_by_volume_damage(config):
    bars, pool, signal = _watch_signal(config)
    current = bars[-1]
    bars[-1] = make_bar(
        current.trade_date,
        open_price="11.00",
        high="11.05",
        low="10.50",
        close="10.55",
        preclose="10.96",
        volume="2000",
    )

    plan = _plan(signal=signal, bars=bars, pool=pool, config=config)

    assert plan.execution_label.value == "WATCH_ONLY"
    assert not plan.is_actionable
    assert "BEARISH_VOLUME_DAMAGE" in plan.cancel_conditions


def test_plan_does_not_read_t_plus_one_data(config):
    bars, pool, signal = _watch_signal(config)
    baseline = _plan(signal=signal, bars=bars, pool=pool, config=config)
    future_date = bars[-1].trade_date + timedelta(days=1)
    future = make_bar(
        future_date,
        open_price="1.00",
        high="50.00",
        low="0.50",
        close="40.00",
        preclose="1.00",
        volume="9999999",
    )

    changed = _plan(
        signal=signal,
        bars=[*bars, future],
        pool=pool,
        config=config,
        plan_date=bars[-1].trade_date,
    )

    assert changed == baseline


def test_b2_ready_can_exist_without_actionable_plan(config):
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
    ready = ready.model_copy(update={"entry_room_state": EntryRoomState.NONE})

    plan = _plan(signal=ready, bars=bars, pool=pool, config=config)

    assert ready.setup_stage is SetupStage.B2_READY
    assert plan.execution_label.value == "B2_READY"
    assert not plan.is_actionable
    assert plan.trigger_price == ready.b2_trigger.trigger_price


def test_603918_b2_ready_semantics_do_not_imply_confirmation(config):
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
    ready = ready.model_copy(update={"code": "603918"})

    plan = _plan(signal=ready, bars=bars, pool=pool, config=config)

    assert plan.setup_stage is SetupStage.B2_READY
    assert plan.execution_label.value == "B2_READY"
    assert plan.trigger_price is not None
    assert plan.preferred_entry == plan.trigger_price


def test_same_inputs_are_deterministic(config):
    bars, pool, signal = _watch_signal(config)

    first = _plan(signal=signal, bars=bars, pool=pool, config=config)
    second = _plan(signal=signal, bars=bars, pool=pool, config=config)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
