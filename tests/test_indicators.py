from __future__ import annotations

from datetime import date

import pytest

from limit_pullback.strategy.indicators import IndicatorPrefixView


def _points(count: int):
    return tuple(
        type("P", (), {"trade_date": date(2026, 1, 1), "index": index})()
        for index in range(count)
    )


def test_prefix_view_never_exposes_future():
    points = _points(120)
    view = IndicatorPrefixView(points, 100)
    assert len(view) == 100
    assert view[-1].index == 99
    assert view[0].index == 0
    assert [item.index for item in view] == list(range(100))
    assert [item.index for item in view[:]] == list(range(100))
    assert [item.index for item in view[90:200]] == list(range(90, 100))
    assert [item.index for item in view[-20:]] == list(range(80, 100))
    with pytest.raises(IndexError):
        _ = view[100]
    with pytest.raises(IndexError):
        _ = view[-101]


def test_prefix_view_rejects_bad_end():
    points = _points(10)
    with pytest.raises(ValueError):
        IndicatorPrefixView(points, 11)
    with pytest.raises(ValueError):
        IndicatorPrefixView(points, -1)
