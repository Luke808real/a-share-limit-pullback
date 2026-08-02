from __future__ import annotations

from limit_pullback.screen.chunks import chunk_codes


def test_chunk_codes_deterministic_and_disjoint():
    universe = tuple(f"{i:06d}" for i in range(500))
    chunks = chunk_codes(universe, 200)
    assert [len(c) for c in chunks] == [200, 200, 100]
    assert sorted(sum(chunks, [])) == list(universe)


def test_chunk_codes_size_does_not_change_membership():
    universe = tuple(f"{i:06d}" for i in range(1000))
    for size in (200, 250):
        chunks = chunk_codes(universe, size)
        assert sorted(sum(chunks, [])) == list(universe)
