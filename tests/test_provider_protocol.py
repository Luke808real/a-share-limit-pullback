from inspect import getmembers, isfunction
from typing import get_type_hints

from limit_pullback.models.market import (
    DailyBarsRequest,
    DailyBarsResult,
    LimitUpPoolRequest,
    LimitUpPoolResult,
)
from limit_pullback.providers.base import DailyBarProvider, LimitUpPoolProvider


def test_provider_protocols_each_freeze_one_public_method():
    daily_methods = {
        name
        for name, member in getmembers(DailyBarProvider, isfunction)
        if not name.startswith("_")
    }
    pool_methods = {
        name
        for name, member in getmembers(LimitUpPoolProvider, isfunction)
        if not name.startswith("_")
    }
    assert daily_methods == {"fetch_daily_bars"}
    assert pool_methods == {"fetch_limit_up_pool"}


def test_provider_annotations_use_project_models():
    daily_annotations = get_type_hints(DailyBarProvider.fetch_daily_bars)
    pool_annotations = get_type_hints(LimitUpPoolProvider.fetch_limit_up_pool)

    assert daily_annotations["request"] is DailyBarsRequest
    assert daily_annotations["return"] is DailyBarsResult
    assert pool_annotations["request"] is LimitUpPoolRequest
    assert pool_annotations["return"] is LimitUpPoolResult
