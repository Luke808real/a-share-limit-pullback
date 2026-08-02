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


class SequencePrefixView(Sequence):
    """Zero-copy bounded view over an ordered sequence.

    Slices return another bounded view instead of copying a tuple. Integer and
    negative indexing are O(1). Iteration only visits ``start..end``.
    """

    __slots__ = ("_values", "_start", "_end")

    def __init__(self, values: Sequence[Any], start: int = 0, end: int | None = None):
        if start < 0:
            raise ValueError("start must be >= 0")
        end = len(values) if end is None else end
        if end < start or end > len(values):
            raise ValueError("end must be within [start, len(values)]")
        self._values = values
        self._start = start
        self._end = end

    def __len__(self) -> int:
        return self._end - self._start

    def _resolve(self, index: int) -> int:
        if index < 0:
            index += self._end - self._start
        if index < 0 or index >= self._end - self._start:
            raise IndexError(index)
        return self._start + index

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(self._end - self._start)
            if step != 1:
                return tuple(self._values[self._start + start + i] for i in range(0, stop - start, step))
            return SequencePrefixView(self._values, self._start + start, self._start + stop)
        return self._values[self._resolve(index)]

    def __iter__(self):
        return (self._values[index] for index in range(self._start, self._end))
