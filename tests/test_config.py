from decimal import Decimal

import pytest
from pydantic import ValidationError

from limit_pullback.config import load_strategy_config
from limit_pullback.models.enums import ScoreProfile


def test_strategy_yaml_loads_with_decimal_values(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")

    assert config.strategy_version == "0.1.0"
    assert config.support.cluster_distance == Decimal("0.02")
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
