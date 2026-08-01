from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.models.enums import EntryRoomState, EventFlag, SetupStage
from limit_pullback.strategy.engine import evaluate_strategy
from limit_pullback.screen.models import ScreenState
from limit_pullback.screen.runner import _pool_prefix_hash
from limit_pullback.trade_plan import (
    _pool_prefix_hash_from_rows,
    _state_provenance_valid,
    build_trade_plan,
)
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


def _watch_signal(config, *, close: str = "10.74", low: str = "10.69"):
    bars = append_pullback_bars(base_setup_bars())
    current = bars[-1]
    safe_low = Decimal(low)
    safe_open = max(Decimal("10.86"), safe_low + Decimal("0.05"))
    safe_high = max(Decimal("10.90"), Decimal(close) + Decimal("0.04"), safe_open)
    bars[-1] = make_bar(
        current.trade_date,
        open_price=str(safe_open),
        high=str(safe_high),
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


def test_b1_prep_does_not_require_b1_ready(config):
    bars, pool, signal = _watch_signal(config)

    plan = _plan(signal=signal, bars=bars, pool=pool, config=config)

    assert signal.setup_stage is SetupStage.WATCH_PULLBACK
    assert plan.execution_label.value == "B1_PREP"
    assert plan.setup_stage is SetupStage.WATCH_PULLBACK


def test_b1_ready_preferred_entry_is_inside_buy_zone(config):
    bars, pool, signal = _watch_signal(config, close="10.86", low="10.78")
    b1 = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )

    plan = _plan(signal=b1, bars=bars, pool=pool, config=config)

    assert plan.execution_label.value == "B1_READY"
    assert plan.buy_zone_low <= plan.preferred_entry <= plan.buy_zone_high
    assert "PRICE_ABOVE_BUY_ZONE" in plan.cancel_conditions
    assert not plan.is_actionable


def test_b1_prep_far_from_support_is_watch_only(config):
    bars, pool, signal = _watch_signal(
        config,
        close="11.60",
        low="11.40",
    )

    plan = _plan(signal=signal, bars=bars, pool=pool, config=config)

    assert plan.execution_label.value == "WATCH_ONLY"
    assert not plan.is_actionable
    assert "PRICE_NOT_NEAR_SUPPORT" in plan.cancel_conditions


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


def test_b1_prep_rejected_by_s2_exhausted(config):
    bars, pool, signal = _watch_signal(config)
    exhausted = signal.model_copy(
        update={"event_flags": frozenset({EventFlag.S2_EXHAUSTED})}
    )

    plan = _plan(signal=exhausted, bars=bars, pool=pool, config=config)

    assert plan.execution_label.value == "WATCH_ONLY"
    assert not plan.is_actionable
    assert "S2_EXHAUSTED" in plan.cancel_conditions


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


def test_extreme_rr_does_not_change_setup_or_entry_scores(config):
    bars, pool, signal = _watch_signal(config)
    b1 = evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
    )
    plan = _plan(signal=b1, bars=bars, pool=pool, config=config)

    assert plan.setup_quality_score == b1.setup_quality_score
    assert plan.entry_quality_score == b1.entry_quality_score
    assert plan.rr is not None
    assert plan.preferred_entry <= plan.buy_zone_high


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


def test_screen_state_provenance_rejects_cross_code_and_mixed_date(config):
    bars, pool, signal = _watch_signal(config)
    trade_date = signal.trade_date
    state = ScreenState(
        code=signal.code,
        last_processed_date=trade_date,
        signal_json=signal.model_dump_json(exclude_computed_fields=True),
        setup_id=signal.setup_id,
        snapshot_id="snap-test",
        bars_prefix_hash="bars",
        limit_pool_prefix_hash="pool",
        strategy_commit="commit-test",
        config_hash="config-test",
        reconciliation_policy_version="policy-test",
        processed_at=datetime.now(timezone.utc),
    )
    common = dict(
        state=state,
        signal=signal,
        snapshot_id="snap-test",
        as_of=trade_date,
        reconciliation_policy_version="policy-test",
        config_hash="config-test",
        current_commit="commit-test",
    )
    assert _state_provenance_valid(code=signal.code, **common)
    assert not _state_provenance_valid(code="603918", **common)
    assert not _state_provenance_valid(
        code=signal.code,
        **{**common, "as_of": trade_date + timedelta(days=1)},
    )
    assert not _state_provenance_valid(
        code=signal.code,
        **{**common, "config_hash": "other-config"},
    )


def test_streamed_pool_prefix_hash_matches_screen_hash(config):
    bars, pool, _ = _watch_signal(config)
    record = pool[0]
    row = {
        "code": record.code,
        "trade_date": record.trade_date,
        "name": record.name,
        "limit_price": record.limit_price,
        "reconciliation_status": "CONFIRMED",
    }
    expected = _pool_prefix_hash(
        [record],
        {(record.code, record.trade_date): "CONFIRMED"},
        record.trade_date,
    )
    assert _pool_prefix_hash_from_rows([row], record.trade_date) == expected
