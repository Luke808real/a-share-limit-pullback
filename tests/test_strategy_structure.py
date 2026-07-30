from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal

from limit_pullback.config import load_strategy_config
from limit_pullback.models.enums import ScoreProfile
from limit_pullback.models.strategy import PriceLevelCandidate
from limit_pullback.strategy.structure import (
    cluster_price_candidates,
    detect_anchor,
    is_one_word_limit,
    is_t_word_limit,
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
