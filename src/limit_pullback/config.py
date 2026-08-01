"""Load and validate the strategy YAML without side effects."""

from __future__ import annotations

from pathlib import Path

import yaml

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.trade_plan import TradePlanConfig
from limit_pullback.models.outcome import OutcomeStudyConfig


def load_strategy_config(path: str | Path) -> StrategyConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError("strategy configuration must be a YAML mapping")
    return StrategyConfig.model_validate(payload)


def load_trade_plan_config(path: str | Path) -> TradePlanConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError("trade-plan configuration must be a YAML mapping")
    return TradePlanConfig.model_validate(payload)


def load_outcome_study_config(path: str | Path) -> OutcomeStudyConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError("outcome-study configuration must be a YAML mapping")
    return OutcomeStudyConfig.from_payload(payload)
