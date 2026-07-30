"""Two fixed provider responsibilities used by the stage-2A adapters."""

from __future__ import annotations

from typing import Protocol

from limit_pullback.models.market import (
    DailyBarsRequest,
    DailyBarsResult,
    LimitUpPoolRequest,
    LimitUpPoolResult,
)


class ProviderError(RuntimeError):
    """An explicit upstream/provider failure; never triggers a silent fallback."""


class DailyBarProvider(Protocol):
    provider_name: str
    provider_version: str

    def fetch_daily_bars(self, request: DailyBarsRequest) -> DailyBarsResult:
        ...


class LimitUpPoolProvider(Protocol):
    provider_name: str
    provider_version: str

    def fetch_limit_up_pool(
        self,
        request: LimitUpPoolRequest,
    ) -> LimitUpPoolResult:
        ...
