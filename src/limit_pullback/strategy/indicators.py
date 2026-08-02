"""Zero-copy prefix view over precomputed IndicatorPoint series."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any


class IndicatorPrefixView(Sequence):
    """Read-only prefix of an IndicatorPoint tuple; never exposes future points.

    Integer and negative indexing are O(1). Slices and iteration are clamped
    to ``end`` so callers can never observe points beyond the current prefix.
    """

    __slots__ = ("_points", "_end")

    def __init__(self, points: Sequence[Any], end: int) -> None:
        if end < 0 or end > len(points):
            raise ValueError("end must be within [0, len(points)]")
        self._points = points
        self._end = end

    def __len__(self) -> int:
        return self._end

    def _resolve(self, index: int) -> int:
        if index < 0:
            index += self._end
        if index < 0 or index >= self._end:
            raise IndexError(index)
        return index

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(self._end)
            return tuple(
                self._points[position]
                for position in range(start, stop, step)
            )
        return self._points[self._resolve(index)]

    def __iter__(self):
        return itertools.islice(self._points, 0, self._end)
