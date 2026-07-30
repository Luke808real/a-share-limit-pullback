from __future__ import annotations

from datetime import datetime, timezone

from limit_pullback.config import load_strategy_config
from limit_pullback.inspect import inspect_stock
from limit_pullback.models.enums import DataQuality, ScoreProfile
from limit_pullback.models.market import DailyBarsResult, LimitUpPoolResult
from tests.synthetic_data import (
    append_pullback_bars,
    base_setup_bars,
    full_limit_pool,
)


NOW = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)


class FakeDailyProvider:
    def __init__(self, bars):
        self.bars = bars
        self.request = None

    def fetch_daily_bars(self, request):
        self.request = request
        return DailyBarsResult(
            bars=self.bars,
            quality=DataQuality.OK,
            fetched_at=NOW,
        )


class FakePoolProvider:
    def __init__(self, records, quality=DataQuality.OK, flags=()):
        self.records = records
        self.quality = quality
        self.flags = flags
        self.request = None

    def fetch_limit_up_pool(self, request):
        self.request = request
        return LimitUpPoolResult(
            trade_date=request.trade_date,
            records=self.records,
            quality=self.quality,
            quality_flags=self.flags,
            fetched_at=NOW,
        )


def _supported_bars():
    bars = append_pullback_bars(base_setup_bars())
    return tuple(bar.model_copy(update={"code": "002606"}) for bar in bars)


def _supported_pool(bars):
    records = full_limit_pool(list(bars))
    return tuple(
        record.model_copy(update={"code": "002606"})
        for record in records[:1]
    )


def test_inspect_runs_one_code_in_memory_and_keeps_provenance(project_root):
    bars = _supported_bars()
    pool = _supported_pool(bars)
    daily = FakeDailyProvider(bars)
    limit = FakePoolProvider(pool)

    output = inspect_stock(
        code="002606",
        as_of=bars[-1].trade_date,
        days=400,
        config=load_strategy_config(project_root / "config" / "strategy.yaml"),
        daily_provider=daily,
        limit_pool_provider=limit,
        clock=lambda: NOW,
    )

    assert daily.request.codes == ("002606",)
    assert limit.request.codes == ("002606",)
    assert limit.request.trade_date == output.signal.anchor.anchor_date
    assert output.daily_data.provider == "BAOSTOCK"
    assert output.daily_data.record_count == len(bars)
    assert output.limit_up_pool_data.provider == "AKSHARE_STOCK_ZT_POOL_EM"
    assert output.signal.score.profile is ScoreProfile.FULL
    assert '"provider":"BAOSTOCK"' in output.model_dump_json()


def test_inspect_missing_pool_data_uses_price_only_without_fabrication(project_root):
    bars = _supported_bars()
    daily = FakeDailyProvider(bars)
    limit = FakePoolProvider(
        (),
        quality=DataQuality.PARTIAL,
        flags=("LIMIT_POOL_UNAVAILABLE:RuntimeError:test",),
    )

    output = inspect_stock(
        code="002606",
        as_of=bars[-1].trade_date,
        days=400,
        config=load_strategy_config(project_root / "config" / "strategy.yaml"),
        daily_provider=daily,
        limit_pool_provider=limit,
        clock=lambda: NOW,
    )

    assert output.signal.score.profile is ScoreProfile.PRICE_ONLY
    assert output.signal.data_quality is DataQuality.PARTIAL
    assert output.limit_up_pool_data.record_count == 0
    assert output.limit_up_pool_data.quality_flags == (
        "LIMIT_POOL_UNAVAILABLE:RuntimeError:test",
    )
