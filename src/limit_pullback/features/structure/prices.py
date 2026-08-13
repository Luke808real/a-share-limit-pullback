"""Policy-free price geometry: proximity and deterministic clustering.

REF-R4.2 verbatim extraction from `strategy/structure.py`. All thresholds are
caller-provided values; no strategy config is read here.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from limit_pullback.models.strategy import PriceCluster, PriceLevelCandidate

ONE = Decimal("1")


def at_price(value: Decimal, target: Decimal, tolerance: Decimal) -> bool:
    """Whether ``value`` is within ``tolerance`` of ``target``."""

    return abs(value - target) <= tolerance


def cluster_price_candidates(
    candidates: Sequence[PriceLevelCandidate],
    distance: Decimal,
) -> tuple[PriceCluster, ...]:
    """Complete-link-style clustering, deterministic for every input order."""

    ordered = tuple(sorted(candidates, key=lambda item: (item.value, item.source)))
    if not ordered:
        return ()
    groups: list[list[PriceLevelCandidate]] = []
    current: list[PriceLevelCandidate] = []
    cluster_low: Decimal | None = None
    for candidate in ordered:
        if not current:
            current = [candidate]
            cluster_low = candidate.value
            continue
        assert cluster_low is not None
        if candidate.value / cluster_low - ONE <= distance:
            current.append(candidate)
        else:
            groups.append(current)
            current = [candidate]
            cluster_low = candidate.value
    groups.append(current)

    clusters = []
    for group in groups:
        values = tuple(item.value for item in group)
        low = min(values)
        high = max(values)
        arithmetic_mean = sum(values, Decimal("0")) / Decimal(len(values))
        center = min(max(arithmetic_mean, low), high)
        clusters.append(
            PriceCluster(
                low=low,
                high=high,
                center=center,
                sources=tuple(sorted({item.source for item in group})),
            )
        )
    return tuple(clusters)


__all__ = ["at_price", "cluster_price_candidates"]
