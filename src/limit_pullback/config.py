"""Load and validate the strategy YAML without side effects."""

from __future__ import annotations

from pathlib import Path

import yaml

from limit_pullback.models.config import StrategyConfig


def load_strategy_config(path: str | Path) -> StrategyConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError("strategy configuration must be a YAML mapping")
    return StrategyConfig.model_validate(payload)
