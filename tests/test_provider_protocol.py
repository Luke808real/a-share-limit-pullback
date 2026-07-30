from inspect import getmembers, isfunction
from typing import get_type_hints

from limit_pullback.models.market import (
    DailyBarsRequest,
    DailyBarsResult,
    LimitUpPoolRequest,
    LimitUpPoolResult,
)
from limit_pullback.providers.base import Provider


def test_provider_protocol_freezes_exactly_two_public_methods():
    methods = {
        name
        for name, member in getmembers(Provider, isfunction)
        if not name.startswith("_")
    }
    assert methods == {"fetch_daily_bars", "fetch_limit_up_pool"}


def test_provider_annotations_use_project_models():
    daily_annotations = get_type_hints(Provider.fetch_daily_bars)
    pool_annotations = get_type_hints(Provider.fetch_limit_up_pool)

    assert daily_annotations["request"] is DailyBarsRequest
    assert daily_annotations["return"] is DailyBarsResult
    assert pool_annotations["request"] is LimitUpPoolRequest
    assert pool_annotations["return"] is LimitUpPoolResult
