from __future__ import annotations

from datetime import datetime, timezone

import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.inspect import inspect_stock
from limit_pullback.models.enums import (
    DataQuality,
    EvaluationMode,
    ScoreProfile,
)
from limit_pullback.models.market import DailyBarsResult, LimitUpPoolResult
from tests.synthetic_data import (
    append_pullback_bars,
    base_setup_bars,
    full_limit_pool,
)


NOW = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)


class FakeDailyProvider:
    def __init__(
        self,
        bars,
        quality=DataQuality.OK,
        flags=(),
    ):
        self.bars = bars
        self.quality = quality
        self.flags = flags
        self.request = None

    def fetch_daily_bars(self, request):
        self.request = request
        return DailyBarsResult(
            bars=self.bars,
            quality=self.quality,
            quality_flags=self.flags,
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


def _supported_bars(code="002606"):
    bars = append_pullback_bars(base_setup_bars())
    return tuple(bar.model_copy(update={"code": code}) for bar in bars)


def _supported_pool(bars, code="002606"):
    records = full_limit_pool(list(bars))
    return tuple(
        record.model_copy(update={"code": code})
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
    assert output.evaluation_mode is EvaluationMode.STATELESS_INSPECT
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


def test_inspect_accepts_arbitrary_supported_main_board_code(project_root):
    bars = _supported_bars("603318")
    daily = FakeDailyProvider(bars)
    limit = FakePoolProvider(_supported_pool(bars, "603318"))

    output = inspect_stock(
        code="603318",
        as_of=bars[-1].trade_date,
        days=400,
        config=load_strategy_config(project_root / "config" / "strategy.yaml"),
        daily_provider=daily,
        limit_pool_provider=limit,
        clock=lambda: NOW,
    )

    assert output.code == "603318"
    assert daily.request.codes == ("603318",)
    assert limit.request.codes == ("603318",)


def test_inspect_rejects_unsupported_board_before_provider(project_root):
    class ProviderMustNotRun:
        def fetch_daily_bars(self, request):
            raise AssertionError("provider must not be called")

    with pytest.raises(ValueError, match="UNSUPPORTED_MARKET_BOARD:300001"):
        inspect_stock(
            code="300001",
            as_of=NOW.date(),
            days=400,
            config=load_strategy_config(
                project_root / "config" / "strategy.yaml"
            ),
            daily_provider=ProviderMustNotRun(),
            limit_pool_provider=FakePoolProvider(()),
            clock=lambda: NOW,
        )


def test_valid_code_without_provider_data_is_a_business_error(project_root):
    with pytest.raises(
        ValueError,
        match="daily source has no trading observation for 603318",
    ):
        inspect_stock(
            code="603318",
            as_of=NOW.date(),
            days=400,
            config=load_strategy_config(
                project_root / "config" / "strategy.yaml"
            ),
            daily_provider=FakeDailyProvider(()),
            limit_pool_provider=FakePoolProvider(()),
            clock=lambda: NOW,
        )


def test_short_history_is_unusable_without_changing_structure_rules(project_root):
    bars = _supported_bars("603318")[:119]
    output = inspect_stock(
        code="603318",
        as_of=bars[-1].trade_date,
        days=400,
        config=load_strategy_config(project_root / "config" / "strategy.yaml"),
        daily_provider=FakeDailyProvider(bars),
        limit_pool_provider=FakePoolProvider(()),
        clock=lambda: NOW,
    )

    assert output.daily_data.record_count == 119
    assert output.signal.data_quality is DataQuality.UNUSABLE
    assert "INSUFFICIENT_TRADING_HISTORY" in output.signal.quality_flags
    assert output.signal.is_entry_candidate is False


def test_malformed_daily_fields_are_aggregated_without_code_or_date(project_root):
    bars = _supported_bars()
    flag = f"MALFORMED_DAILY_ROW:002606:{bars[-2].trade_date}:open,amount"
    output = inspect_stock(
        code="002606",
        as_of=bars[-1].trade_date,
        days=400,
        config=load_strategy_config(project_root / "config" / "strategy.yaml"),
        daily_provider=FakeDailyProvider(
            bars,
            quality=DataQuality.DEGRADED,
            flags=(flag,),
        ),
        limit_pool_provider=FakePoolProvider(_supported_pool(bars)),
        clock=lambda: NOW,
    )

    assert output.daily_data.missing_fields == ("amount", "open")
    assert "002606" not in output.daily_data.missing_fields
    assert str(bars[-2].trade_date) not in output.daily_data.missing_fields
    assert flag in output.signal.quality_flags
