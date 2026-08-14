"""Offline tests for the persistent indicator cache (rebuild fast path)."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from decimal import Decimal

from limit_pullback.models.market import DailyBar
from limit_pullback.screen.indicator_cache import (
    load_cached_indicators,
    store_cached_indicators,
)
from tests.synthetic_data import base_setup_bars, business_dates, make_bar


def _bars(n: int) -> list[DailyBar]:
    bars = base_setup_bars()
    while len(bars) < n:
        day = business_dates(bars[-1].trade_date, 1)[0]
        bars.append(
            make_bar(
                day,
                open_price="11.00",
                high="11.20",
                low="10.90",
                close="11.05",
                preclose=str(bars[-1].close),
                volume="300",
            )
        )
    return bars[:n]


def _indicators(bars, config):
    from limit_pullback.strategy.math import calculate_indicators

    return calculate_indicators(bars, config)


def test_round_trip_is_exact(project_root, tmp_path):
    from limit_pullback.config import load_strategy_config

    config = load_strategy_config(project_root / "config" / "strategy.yaml").indicators
    indicators = _indicators(_bars(130), config)
    store_cached_indicators(tmp_path, "600000", indicators)
    loaded = load_cached_indicators(tmp_path, "600000")
    assert loaded is not None
    assert loaded == indicators
    for a, b in zip(loaded, indicators, strict=True):
        assert a == b
        assert a.continuous_mas == b.continuous_mas
        assert a.raw_equivalent_mas == b.raw_equivalent_mas
        assert a.position_120 == b.position_120


def test_missing_and_corrupt_are_misses(tmp_path):
    assert load_cached_indicators(tmp_path, "000001") is None
    (tmp_path / "000001.json").write_text("not json", encoding="utf-8")
    assert load_cached_indicators(tmp_path, "000001") is None
    (tmp_path / "000001.json").write_text("[]", encoding="utf-8")
    assert load_cached_indicators(tmp_path, "000001") is None
    (tmp_path / "000001.json").write_text(
        json.dumps([{"trade_date": "2024-01-01", "code": "000001"}]),
        encoding="utf-8",
    )
    assert load_cached_indicators(tmp_path, "000001") is None


def test_screen_code_cache_hit_skips_recompute(project_root, tmp_path, monkeypatch):
    from limit_pullback.config import load_strategy_config
    from limit_pullback.screen import engine as engine_mod
    from limit_pullback.strategy.engine import evaluate_strategy

    calls = {"n": 0}
    real = engine_mod.calculate_indicators

    def counting(bars, config, as_of=None):
        calls["n"] += 1
        return real(bars, config, as_of)

    monkeypatch.setattr(engine_mod, "calculate_indicators", counting)
    bars = _bars(130)
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    pool_records = ()
    generated_at = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)

    first = engine_mod.screen_code(
        code="600000",
        bars=bars,
        pool_records=pool_records,
        config=config,
        start_date=None,
        as_of=bars[-1].trade_date,
        generated_at=generated_at,
        indicator_cache=tmp_path,
    )
    assert calls["n"] == 1
    second = engine_mod.screen_code(
        code="600000",
        bars=bars,
        pool_records=pool_records,
        config=config,
        start_date=None,
        as_of=bars[-1].trade_date,
        generated_at=generated_at,
        indicator_cache=tmp_path,
    )
    assert calls["n"] == 1  # cache hit, no recompute
    assert first == second
