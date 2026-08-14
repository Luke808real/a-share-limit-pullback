"""Persistent indicator cache for full rebuilds.

calculate_indicators is a pure function of (canonical bars, indicators
config). A strategy-version change re-runs the screen over the SAME snapshot
bars, so the per-code indicator series is identical every time. Caching the
computed IndicatorPoint values makes strategy-only rebuilds skip the dominant
compute cost while staying bit-identical by construction (values are stored,
never recomputed). Any read failure is a cache MISS: the cache is an
optimization, never a correctness dependency.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from limit_pullback.models.strategy import IndicatorPoint
from limit_pullback.warehouse.layout import WarehouseLayout

# Bump whenever the indicator computation or its serialization changes;
# old-version dirs are simply never consulted again.
INDICATOR_CACHE_VERSION = "v1"


def indicator_cache_dir(
    layout: WarehouseLayout,
    snapshot_id: str,
    config_hash: str,
) -> Path:
    return (
        layout.root
        / "screen"
        / "indicator_cache"
        / snapshot_id
        / INDICATOR_CACHE_VERSION
        / config_hash[:16]
    )


def load_cached_indicators(
    cache_dir: Path,
    code: str,
) -> tuple[IndicatorPoint, ...] | None:
    path = cache_dir / f"{code}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        points = tuple(IndicatorPoint.model_validate(item) for item in payload)
    except Exception:
        return None
    if not points:
        return None
    return points


def store_cached_indicators(
    cache_dir: Path,
    code: str,
    indicators: tuple[IndicatorPoint, ...],
) -> None:
    payload = [point.model_dump(mode="json") for point in indicators]
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{code}.json"
    tmp = cache_dir / f"{code}.json.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
