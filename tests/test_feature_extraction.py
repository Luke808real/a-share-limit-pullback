"""REF-R4 feature extraction tests: verbatim move identity and layer boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from limit_pullback.features.common import (
    IndicatorPrefixView,
    SequencePrefixView,
    build_continuous_prices,
    calculate_indicators,
    calculate_kline_metrics,
)
from limit_pullback.strategy import indicators as strategy_indicators
from limit_pullback.strategy import math as strategy_math

ROOT = Path(__file__).resolve().parents[1]


def test_strategy_shims_reexport_feature_objects():
    assert strategy_math.build_continuous_prices is build_continuous_prices
    assert strategy_math.calculate_indicators is calculate_indicators
    assert strategy_math.calculate_kline_metrics is calculate_kline_metrics
    assert strategy_indicators.IndicatorPrefixView is IndicatorPrefixView
    assert strategy_indicators.SequencePrefixView is SequencePrefixView


def test_features_layer_import_boundary():
    """Features import only models, domain, stdlib; never strategy/warehouse/screen."""

    forbidden = (
        "limit_pullback.strategy",
        "limit_pullback.warehouse",
        "limit_pullback.screen",
        "limit_pullback.selection",
        "limit_pullback.runtime",
        "limit_pullback.providers",
    )
    offenders: list[str] = []
    for path in sorted(
        (ROOT / "src" / "limit_pullback" / "features").rglob("*.py")
    ):
        names: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        hits = {
            name
            for name in names
            if name.startswith("limit_pullback")
            and any(
                name == root or name.startswith(root + ".")
                for root in forbidden
            )
        }
        if hits:
            offenders.append(f"{path.relative_to(ROOT)}: {sorted(hits)}")
    assert not offenders, f"features layer boundary violations: {offenders}"


def test_continuous_prices_prefix_invariance():
    from tests.synthetic_data import base_setup_bars

    bars = base_setup_bars()
    shorter = bars[:8]
    full = build_continuous_prices(bars)
    prefix = build_continuous_prices(shorter)
    assert full[: len(prefix)] == prefix
