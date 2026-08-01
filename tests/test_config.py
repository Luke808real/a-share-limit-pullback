from decimal import Decimal

import pytest
from pydantic import ValidationError

from limit_pullback.config import load_strategy_config, load_trade_plan_config
from limit_pullback.models.enums import ScoreProfile
from limit_pullback.warehouse.parquet import sha256_file


def test_strategy_yaml_loads_with_decimal_values(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")

    assert config.strategy_version == "0.1.0"
    assert config.support.cluster_distance == Decimal("0.02")
    assert config.entry_room.minimum_risk_reward == Decimal("1.50")
    assert config.scoring.normalized_score_quantum == Decimal("0.01")
    assert set(config.scoring.profiles) == set(ScoreProfile)


def test_config_rejects_unknown_fields(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    payload = config.model_dump(mode="python")
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        type(config).model_validate(payload)


def test_config_rejects_python_float(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    payload = config.model_dump(mode="python")
    payload["support"]["cluster_distance"] = 0.02

    with pytest.raises(TypeError, match="float is forbidden"):
        type(config).model_validate(payload)


def test_support_above_close_tolerance_must_remain_small(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    payload = config.model_dump(mode="python")
    payload["support"]["max_above_reference_close"] = Decimal("0.006")

    with pytest.raises(ValidationError, match="less than or equal to 0.005"):
        type(config).model_validate(payload)


def test_trade_plan_thresholds_are_separate_from_frozen_strategy_config(project_root):
    strategy_path = project_root / "config" / "strategy.yaml"
    trade_plan_path = project_root / "config" / "trade_plan.yaml"

    assert sha256_file(strategy_path) == (
        "47a0ea2b41952f06f43d1fe3a5e066993bade6ecec45c81103022008c7eae6bf"
    )
    config = load_trade_plan_config(trade_plan_path)
    assert config.prep_support_distance_max == Decimal("0.04")
    assert config.prep_volume_to_anchor_max == Decimal("1.00")
    assert config.prep_volume_to_post_anchor_max == Decimal("0.90")

    payload = config.model_dump(mode="python")
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        type(config).model_validate(payload)


def test_trade_plan_config_rejects_python_float(project_root):
    config = load_trade_plan_config(project_root / "config" / "trade_plan.yaml")
    payload = config.model_dump(mode="python")
    payload["prep_support_distance_max"] = 0.04

    with pytest.raises(TypeError, match="float is forbidden"):
        type(config).model_validate(payload)
