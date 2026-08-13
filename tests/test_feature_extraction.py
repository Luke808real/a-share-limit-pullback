"""REF-R4 feature extraction tests: verbatim move identity and layer boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from limit_pullback.features.common import (
    IndicatorPrefixView,
    SequencePrefixView,
    build_continuous_prices,
    calculate_kline_ratios,
)
from limit_pullback.strategy import indicators as strategy_indicators
from limit_pullback.strategy import math as strategy_math
from limit_pullback.strategy import structure as strategy_structure
from limit_pullback.strategy.indicators_calc import calculate_indicators
from limit_pullback.strategy.kline_policy import (
    calculate_kline_metrics,
    classify_kline_flags,
)
from limit_pullback.features.structure.prices import (
    at_price,
    cluster_price_candidates,
)

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


def test_kline_ratios_are_policy_free_and_flags_are_policy():
    from limit_pullback.models.config import StrategyConfig
    from limit_pullback.config import load_strategy_config

    from tests.synthetic_data import base_setup_bars

    config: StrategyConfig = load_strategy_config(
        ROOT / "config" / "strategy.yaml"
    )
    bar = base_setup_bars()[-1]
    ratios = calculate_kline_ratios(bar)
    # Pure facts: no config involved.
    assert hasattr(ratios, "body_share")
    assert not hasattr(ratios, "is_doji")
    metrics = classify_kline_flags(ratios, config.indicators)
    assert calculate_kline_metrics(bar, config.indicators) == metrics
    assert metrics.is_bullish == ratios.is_bullish
    assert metrics.is_doji == (
        ratios.body_share <= config.indicators.kline.doji_body_share_max
    )


def test_structure_geometry_shims_reexport_feature_objects():
    assert strategy_structure._at_price is at_price
    assert strategy_structure.cluster_price_candidates is cluster_price_candidates


def test_cluster_price_candidates_deterministic():
    from decimal import Decimal

    from limit_pullback.models.strategy import PriceLevelCandidate

    candidates = tuple(
        PriceLevelCandidate(source=source, value=Decimal(value))
        for source, value in (
            ("ANCHOR_PRICE", "10.00"),
            ("MA5", "10.01"),
            ("PLATFORM_HIGH_20", "11.50"),
        )
    )
    clusters = cluster_price_candidates(candidates, Decimal("0.02"))
    assert len(clusters) == 2
    assert clusters[0].sources == ("ANCHOR_PRICE", "MA5")
    assert clusters[1].sources == ("PLATFORM_HIGH_20",)
    assert clusters == cluster_price_candidates(
        tuple(reversed(candidates)),
        Decimal("0.02"),
    )
