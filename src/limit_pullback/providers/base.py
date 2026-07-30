"""Minimal provider boundary; no implementation is included in stage 1."""

from __future__ import annotations

from typing import Protocol

from limit_pullback.models.market import (
    DailyBarsRequest,
    DailyBarsResult,
    LimitUpPoolRequest,
    LimitUpPoolResult,
)


class Provider(Protocol):
    def fetch_daily_bars(self, request: DailyBarsRequest) -> DailyBarsResult:
        ...

    def fetch_limit_up_pool(
        self,
        request: LimitUpPoolRequest,
    ) -> LimitUpPoolResult:
        ...
