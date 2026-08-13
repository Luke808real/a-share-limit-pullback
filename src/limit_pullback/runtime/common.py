"""Shared per-day evaluation seam for Replay and Daily (REF-R7).

Both orchestration modes evaluate one code one day at a time with identical
inputs: the day prefix, the day pool prefix, the previous signal, and the
precomputed indicator series with an end index. This function is the single
call surface they share; it delegates to the one state engine.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.signal import StrategySignal
from limit_pullback.models.strategy import IndicatorPoint
from limit_pullback.state.engine import evaluate_strategy


def evaluate_day(
    *,
    bars: Sequence[DailyBar],
    as_of: date,
    config: StrategyConfig,
    generated_at: datetime,
    limit_pool: Sequence[LimitUpRecord],
    previous_signal: StrategySignal | None,
    full_indicators: Sequence[IndicatorPoint] | None,
    indicator_end_index: int | None,
) -> StrategySignal:
    """Evaluate one code for one close using the shared state engine."""

    return evaluate_strategy(
        bars=bars,
        as_of=as_of,
        config=config,
        generated_at=generated_at,
        limit_pool=limit_pool,
        previous_signal=previous_signal,
        precomputed_indicators=full_indicators,
        indicator_end_index=indicator_end_index,
    )


__all__ = ["evaluate_day"]
