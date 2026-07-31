"""Single-stock, in-memory real-data orchestration for stage 2A."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import DataQuality
from limit_pullback.models.inspect import DataSourceReport, InspectOutput
from limit_pullback.models.market import (
    DailyBarsRequest,
    LimitUpPoolRequest,
)
from limit_pullback.models.signal import StrategySignal
from limit_pullback.providers.base import DailyBarProvider, LimitUpPoolProvider
from limit_pullback.strategy.engine import evaluate_strategy


DAILY_PROVIDER_NAME = "BAOSTOCK"
LIMIT_POOL_PROVIDER_NAME = "AKSHARE_STOCK_ZT_POOL_EM"
SUPPORTED_INSPECT_CODES = frozenset({"002606", "603123", "001382"})
QUALITY_ORDER = {
    DataQuality.OK: 0,
    DataQuality.PARTIAL: 1,
    DataQuality.DEGRADED: 2,
    DataQuality.UNUSABLE: 3,
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _missing_fields(flags: tuple[str, ...]) -> tuple[str, ...]:
    fields: set[str] = set()
    for flag in flags:
        if flag.startswith(("MISSING_DAILY_FIELD:", "MISSING_LIMIT_FIELD:")):
            fields.add(flag.rsplit(":", 1)[-1])
    return tuple(sorted(fields))


def _worst_quality(*values: DataQuality) -> DataQuality:
    return max(values, key=QUALITY_ORDER.__getitem__)


def _source_report(
    *,
    provider: str,
    requested_start: date,
    requested_end: date,
    fetched_at: datetime | None,
    quality: DataQuality,
    record_count: int,
    quality_flags: tuple[str, ...],
) -> DataSourceReport:
    return DataSourceReport(
        provider=provider,
        requested_start=requested_start,
        requested_end=requested_end,
        fetched_at=fetched_at,
        quality=quality,
        record_count=record_count,
        quality_flags=quality_flags,
        missing_fields=_missing_fields(quality_flags),
    )


def _merge_signal_quality(
    signal: StrategySignal,
    *source_qualities: DataQuality,
) -> StrategySignal:
    merged = _worst_quality(signal.data_quality, *source_qualities)
    if merged is signal.data_quality:
        return signal
    return signal.model_copy(update={"data_quality": merged})


def inspect_stock(
    *,
    code: str,
    as_of: date,
    days: int,
    config: StrategyConfig,
    daily_provider: DailyBarProvider,
    limit_pool_provider: LimitUpPoolProvider,
    clock: Callable[[], datetime] = _now_utc,
) -> InspectOutput:
    """Fetch one code, evaluate at one close and return JSON-ready models only."""

    if code not in SUPPORTED_INSPECT_CODES:
        raise ValueError(
            f"stage 2A inspect only supports {sorted(SUPPORTED_INSPECT_CODES)}"
        )
    if days < 1:
        raise ValueError("days must be at least 1")
    generated_at = clock()
    start_date = as_of - timedelta(days=days - 1)
    daily_result = daily_provider.fetch_daily_bars(
        DailyBarsRequest(
            codes=(code,),
            start_date=start_date,
            end_date=as_of,
        )
    )
    bars = tuple(
        bar
        for bar in daily_result.bars
        if bar.code == code and start_date <= bar.trade_date <= as_of
    )
    if not bars or bars[-1].trade_date != as_of:
        raise ValueError(
            f"daily source has no trading observation for {code} on {as_of}"
        )

    preliminary = evaluate_strategy(
        bars=bars,
        as_of=as_of,
        config=config,
        generated_at=generated_at,
    )
    if preliminary.anchor is None:
        pool_report = _source_report(
            provider=LIMIT_POOL_PROVIDER_NAME,
            requested_start=as_of,
            requested_end=as_of,
            fetched_at=None,
            quality=DataQuality.PARTIAL,
            record_count=0,
            quality_flags=("LIMIT_POOL_NOT_REQUESTED:NO_VALID_ANCHOR",),
        )
        signal = _merge_signal_quality(preliminary, daily_result.quality)
    else:
        anchor_date = preliminary.anchor.anchor_date
        pool_result = limit_pool_provider.fetch_limit_up_pool(
            LimitUpPoolRequest(
                trade_date=anchor_date,
                codes=(code,),
            )
        )
        signal = evaluate_strategy(
            bars=bars,
            as_of=as_of,
            config=config,
            generated_at=generated_at,
            limit_pool=pool_result.records,
        )
        signal = _merge_signal_quality(
            signal,
            daily_result.quality,
            pool_result.quality,
        )
        pool_report = _source_report(
            provider=LIMIT_POOL_PROVIDER_NAME,
            requested_start=anchor_date,
            requested_end=anchor_date,
            fetched_at=pool_result.fetched_at,
            quality=pool_result.quality,
            record_count=len(pool_result.records),
            quality_flags=pool_result.quality_flags,
        )

    daily_report = _source_report(
        provider=DAILY_PROVIDER_NAME,
        requested_start=start_date,
        requested_end=as_of,
        fetched_at=daily_result.fetched_at,
        quality=daily_result.quality,
        record_count=len(bars),
        quality_flags=daily_result.quality_flags,
    )
    return InspectOutput(
        code=code,
        as_of=as_of,
        days=days,
        generated_at=generated_at,
        daily_data=daily_report,
        limit_up_pool_data=pool_report,
        signal=signal,
    )
