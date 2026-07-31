from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal

from limit_pullback.config import load_strategy_config
from limit_pullback.models.enums import ScoreProfile
from limit_pullback.models.strategy import PriceCluster, PriceLevelCandidate
from limit_pullback.strategy.structure import (
    cluster_price_candidates,
    detect_anchor,
    is_one_word_limit,
    is_t_word_limit,
    select_resistance_levels,
    select_support_cluster,
)
from tests.synthetic_data import (
    base_setup_bars,
    business_dates,
    full_limit_pool,
    make_bar,
)


def test_one_word_and_t_word_detection(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    trade_date = business_dates(base_setup_bars()[-1].trade_date + timedelta(days=1), 1)[0]
    one_word = make_bar(
        trade_date,
        open_price="11.00",
        high="11.00",
        low="11.00",
        close="11.00",
        preclose="10.00",
        volume="1000",
    )
    t_word = make_bar(
        trade_date,
        open_price="11.00",
        high="11.00",
        low="10.50",
        close="11.00",
        preclose="10.00",
        volume="1000",
    )

    assert is_one_word_limit(one_word, config)
    assert not is_t_word_limit(one_word, config)
    assert is_t_word_limit(t_word, config)
    assert not is_one_word_limit(t_word, config)


def test_full_and_price_only_anchor_profiles(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    bars = base_setup_bars()
    full = detect_anchor(
        bars,
        bars[-1].trade_date,
        config,
        full_limit_pool(bars),
    )
    price_only = detect_anchor(bars, bars[-1].trade_date, config)

    assert full is not None and full.profile is ScoreProfile.FULL
    assert price_only is not None and price_only.profile is ScoreProfile.PRICE_ONLY
    assert price_only.seal_before_cutoff is None


def test_consecutive_limit_and_late_seal_are_excluded(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    bars = base_setup_bars()
    second_date = business_dates(bars[-1].trade_date + timedelta(days=1), 1)[0]
    bars.append(
        make_bar(
            second_date,
            open_price="11.00",
            high="12.10",
            low="10.95",
            close="12.10",
            preclose="11.00",
            volume="1200",
        )
    )
    assert detect_anchor(bars, second_date, config) is None

    original = base_setup_bars()
    late_pool = list(full_limit_pool(original))
    late_pool[0] = late_pool[0].model_copy(
        update={"first_seal_time": time(14, 31)}
    )
    assert detect_anchor(
        original,
        original[-1].trade_date,
        config,
        late_pool,
    ) is None


def test_price_clustering_is_input_order_independent(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    candidates = (
        PriceLevelCandidate(source="MA10", value=Decimal("10.10")),
        PriceLevelCandidate(source="ANCHOR", value=Decimal("10.00")),
        PriceLevelCandidate(source="MA20", value=Decimal("10.19")),
        PriceLevelCandidate(source="LEFT_HIGH", value=Decimal("12.00")),
    )
    forward = cluster_price_candidates(
        candidates,
        config.support.cluster_distance,
    )
    reverse = cluster_price_candidates(
        tuple(reversed(candidates)),
        config.support.cluster_distance,
    )

    assert forward == reverse
    assert forward[0].low == Decimal("10.00")
    assert forward[0].high == Decimal("10.19")
    assert forward[0].sources == ("ANCHOR", "MA10", "MA20")


def test_cluster_center_clamps_decimal_context_rounding():
    value = Decimal("7.907800000000000000000000012")
    candidates = (
        PriceLevelCandidate(source="SUPPORT_LOW_REFERENCE", value=value),
        PriceLevelCandidate(source="SUPPORT_HIGH_REFERENCE", value=value),
    )

    cluster = cluster_price_candidates(
        candidates,
        Decimal("0.02"),
    )[0]

    assert cluster.low == value
    assert cluster.center == value
    assert cluster.high == value


def test_support_selection_rejects_level_materially_above_close(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    clusters = (
        PriceCluster(
            low=Decimal("16.90"),
            high=Decimal("17.04"),
            center=Decimal("16.97"),
            sources=("PLATFORM_HIGH_20",),
        ),
        PriceCluster(
            low=Decimal("16.40"),
            high=Decimal("16.50"),
            center=Decimal("16.45"),
            sources=("MA10",),
        ),
    )

    selected = select_support_cluster(
        clusters,
        current_close=Decimal("16.57"),
        config=config,
    )

    assert selected.center == Decimal("16.45")


def _resistance_selection(config):
    support = PriceCluster(
        low=Decimal("9.80"),
        high=Decimal("10.00"),
        center=Decimal("9.90"),
        sources=("MA10",),
    )
    candidates = (
        PriceLevelCandidate(
            source="SUPPORT_OVERLAP_HIGH",
            value=Decimal("9.90"),
        ),
        PriceLevelCandidate(
            source="ANCHOR_OVERLAP_HIGH",
            value=Decimal("11.00"),
        ),
        PriceLevelCandidate(
            source="EXPECTED_B2_PLATFORM",
            value=Decimal("10.50"),
        ),
        PriceLevelCandidate(
            source="LEFT_TARGET_HIGH",
            value=Decimal("12.00"),
        ),
    )
    return select_resistance_levels(
        candidates,
        anchor_price=Decimal("11.00"),
        support=support,
        reference_close=Decimal("10.20"),
        expected_b2_trigger=Decimal("10.51"),
        config=config,
    )


def test_anchor_price_cluster_cannot_be_selected_as_s1(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    _, target, audit, _ = _resistance_selection(config)
    anchor_candidate = next(
        item for item in audit if item.source == "ANCHOR_OVERLAP_HIGH"
    )

    assert anchor_candidate.excluded_reason == "ANCHOR_CLUSTER_OVERLAP"
    assert target is not None and target.low != Decimal("11.00")


def test_support_overlapping_resistance_cluster_is_excluded(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    _, _, audit, _ = _resistance_selection(config)
    support_candidate = next(
        item for item in audit if item.source == "SUPPORT_OVERLAP_HIGH"
    )

    assert support_candidate.excluded_reason == "SUPPORT_CLUSTER_OVERLAP"
    assert support_candidate.selected_reason is None


def test_immediate_resistance_and_target_s1_are_distinct(project_root):
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    immediate, target, audit, expected_trigger = _resistance_selection(config)

    assert immediate is not None and immediate.low == Decimal("10.50")
    assert target is not None and target.low == Decimal("12.00")
    assert target.low > expected_trigger
    assert any(
        item.selected_reason == "SELECTED_IMMEDIATE_RESISTANCE"
        for item in audit
    )
    assert any(
        item.selected_reason == "SELECTED_TARGET_S1"
        for item in audit
    )
