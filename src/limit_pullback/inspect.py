"""Stateless, single-stock, in-memory real-data orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone

from limit_pullback.instruments import parse_instrument_code
from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import DataQuality, EvaluationMode
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
QUALITY_ORDER = {
    DataQuality.OK: 0,
    DataQuality.PARTIAL: 1,
    DataQuality.DEGRADED: 2,
    DataQuality.UNUSABLE: 3,
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _missing_fields(flags: Sequence[str]) -> tuple[str, ...]:
    fields: set[str] = set()
    for flag in flags:
        if flag.startswith(("MISSING_DAILY_FIELD:", "MISSING_LIMIT_FIELD:")):
            fields.add(flag.rsplit(":", 1)[-1])
        elif flag.startswith("MALFORMED_DAILY_ROW:"):
            parts = flag.split(":", 3)
            if len(parts) != 4:
                continue
            fields.update(
                field
                for field in parts[3].split(",")
                if (
                    field
                    and field not in {"invalid_date", "missing_date"}
                    and field.replace("_", "").isalnum()
                    and not field[0].isdigit()
                )
            )
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
    source_qualities: Sequence[DataQuality],
    *,
    source_flags: Sequence[str] = (),
    insufficient_history: bool = False,
) -> StrategySignal:
    merged = _worst_quality(signal.data_quality, *source_qualities)
    flags = {*signal.quality_flags, *source_flags}
    if insufficient_history:
        merged = DataQuality.UNUSABLE
        flags.add("INSUFFICIENT_TRADING_HISTORY")
    updates: dict[str, object] = {}
    if merged is not signal.data_quality:
        updates["data_quality"] = merged
    frozen_flags = tuple(sorted(flags))
    if frozen_flags != signal.quality_flags:
        updates["quality_flags"] = frozen_flags
    if merged is DataQuality.UNUSABLE and signal.entry_quality_score is not None:
        updates["entry_quality_score"] = signal.entry_quality_score * 0
    if not updates:
        return signal
    return signal.model_copy(update=updates)


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
    """Fetch one code and evaluate one close without previous setup state."""

    code = parse_instrument_code(code).normalized_code
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
    bars = tuple(sorted(
        (
            bar
            for bar in daily_result.bars
            if bar.code == code and start_date <= bar.trade_date <= as_of
        ),
        key=lambda item: item.trade_date,
    ))
    if not bars or bars[-1].trade_date != as_of:
        raise ValueError(
            f"daily source has no trading observation for {code} on {as_of}"
        )
    insufficient_history = (
        len(bars) < config.universe.minimum_listing_trade_days
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
        signal = _merge_signal_quality(
            preliminary,
            (daily_result.quality,),
            source_flags=daily_result.quality_flags,
            insufficient_history=insufficient_history,
        )
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
            (daily_result.quality, pool_result.quality),
            source_flags=(
                *daily_result.quality_flags,
                *pool_result.quality_flags,
            ),
            insufficient_history=insufficient_history,
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
        evaluation_mode=EvaluationMode.STATELESS_INSPECT,
        code=code,
        as_of=as_of,
        days=days,
        generated_at=generated_at,
        daily_data=daily_report,
        limit_up_pool_data=pool_report,
        signal=signal,
    )
