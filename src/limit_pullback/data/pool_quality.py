"""Pool reconciliation status -> data quality classification (P5).

Verbatim move of `screen.engine.pool_quality`. This maps anchor pool
reconciliation status to data quality (formal mode refuses PROVISIONAL pool
records as OK anchor data; debug mode allows them with a warning flag), which
is data-quality semantics, not ranking policy.
"""

from __future__ import annotations

from limit_pullback.models.enums import DataQuality

POOL_STATUS_CONFIRMED = "CONFIRMED"
POOL_STATUS_SINGLE_SOURCE = "CONFIRMED_SINGLE_SOURCE"
POOL_STATUS_PROVISIONAL = "PROVISIONAL"


def pool_quality(
    status: str | None,
    *,
    pool_mode: str,
) -> tuple[DataQuality, str | None]:
    """Quality propagation for anchor pool records.

    Formal mode refuses PROVISIONAL pool records as OK anchor data;
    debug mode allows them with an explicit warning flag and lower quality.
    """

    if status in (POOL_STATUS_CONFIRMED, POOL_STATUS_SINGLE_SOURCE):
        return DataQuality.OK, None
    if status == POOL_STATUS_PROVISIONAL:
        if pool_mode == "debug":
            return DataQuality.DEGRADED, "LIMIT_POOL_PROVISIONAL_WARNING"
        return DataQuality.UNUSABLE, "LIMIT_POOL_PROVISIONAL"
    return DataQuality.OK, None


__all__ = ["pool_quality"]
