"""R3B.1 contiguous-tail bucket ordering regression tests."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3b_factor_structure_v01 as r3b  # noqa: E402


def test_sparse_interior_bucket_no_noncontiguous_tail():
    """First sparse value starts the tail; no isolated sparse bucket before it."""
    counts = {1: 100, 2: 80, 3: 10, 4: 5, 5: 200}
    order, labels = r3b.contiguous_time_buckets(counts, min_n=30)
    assert order == ["1", "2", "TAIL>=3"]
    assert labels == {1: "1", 2: "2", 3: "TAIL>=3", 4: "TAIL>=3", 5: "TAIL>=3"}


def test_contiguous_tail_start_correct():
    counts = {1: 100, 2: 10, 3: 5}
    order, labels = r3b.contiguous_time_buckets(counts, min_n=30)
    assert order == ["1", "TAIL>=2"]
    assert labels[2] == "TAIL>=2" and labels[3] == "TAIL>=2"


def test_sparse_first_value_tail_from_min():
    counts = {1: 5, 2: 100, 3: 90}
    order, labels = r3b.contiguous_time_buckets(counts, min_n=30)
    assert order == ["TAIL>=1"]
    assert labels == {1: "TAIL>=1", 2: "TAIL>=1", 3: "TAIL>=1"}


def test_no_tail_when_all_dense():
    counts = {1: 100, 2: 80, 3: 60}
    order, labels = r3b.contiguous_time_buckets(counts, min_n=30)
    assert order == ["1", "2", "3"]
    assert "TAIL" not in "".join(order)


def test_shape_input_strictly_increasing_then_single_tail():
    """Order must be strictly increasing naturals followed by at most one TAIL."""
    for counts in [
        {1: 100, 2: 80, 3: 10, 4: 5, 5: 200},
        {1: 100, 2: 10},
        {1: 5},
        {1: 100, 2: 90, 3: 80, 4: 70, 5: 60, 6: 50, 7: 40, 8: 20, 9: 10},
    ]:
        order, labels = r3b.contiguous_time_buckets(counts, min_n=30)
        tails = [o for o in order if o.startswith("TAIL")]
        assert len(tails) <= 1
        if tails:
            assert order[-1] == tails[0]
        numeric = [int(o) for o in order if not o.startswith("TAIL")]
        assert numeric == sorted(numeric)
        assert len(numeric) == len(set(numeric))
        assert len(labels) == len(counts)  # every raw value preserved in label map
