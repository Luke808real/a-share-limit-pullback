from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
import yaml

from limit_pullback.config import load_strategy_config
from limit_pullback.models.enums import (
    DataQuality,
    EventFlag,
    ReviewGroup,
    ScoreProfile,
    SetupStage,
)
from limit_pullback.strategy.engine import evaluate_strategy, make_setup_id
from tests.synthetic_data import (
    TZ_SHANGHAI,
    append_b2_confirm_bar,
    append_b2_ready_bar,
    append_invalid_bar,
    append_open_space_pullback,
    append_pullback_bars,
    append_s2_bar,
    base_setup_bars,
    full_limit_pool,
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
    if "patterns" in expectation:
        assert sorted(pattern.value for pattern in signal.patterns) == sorted(
            expectation["patterns"]
        )
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
    assert b1.s1 == ready.s1 == confirmed.s1
    assert (
        b1.initial_invalid_price
        == ready.initial_invalid_price
        == confirmed.initial_invalid_price
    )
    assert b1.setup_id == ready.setup_id == confirmed.setup_id
    assert confirmed.trade_date == bars[-1].trade_date


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
        update={"invalid_price": b1.initial_invalid_price + Decimal("0.05")}
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
    assert signal.s1 is None
    assert signal.risk_reward_ratio is None


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

    assert repeated == original


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
