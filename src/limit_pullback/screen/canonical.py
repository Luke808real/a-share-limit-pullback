"""Compatibility shim for the canonical readers moved to the data layer.

REF-R3: the implementation moved verbatim to
`limit_pullback.data.canonical`; this module re-exports the same objects so
existing callers keep working unchanged.
"""

from limit_pullback.data.canonical import (
    FIXED_FETCHED_AT,
    CanonicalDailyBarProvider,
    CanonicalLimitUpPoolProvider,
    CanonicalMarketData,
    _as_time,
    _canonical_daily_row_stream,
    _canonical_row_content,
    _daily_bar_from_row,
    _load_daily_bars_stream,
    canonical_universe_codes,
    iter_canonical_code_bars,
    load_canonical_market,
    load_canonical_metadata,
)

__all__ = [
    "FIXED_FETCHED_AT",
    "CanonicalDailyBarProvider",
    "CanonicalLimitUpPoolProvider",
    "CanonicalMarketData",
    "_as_time",
    "_canonical_daily_row_stream",
    "_canonical_row_content",
    "_daily_bar_from_row",
    "_load_daily_bars_stream",
    "canonical_universe_codes",
    "iter_canonical_code_bars",
    "load_canonical_market",
    "load_canonical_metadata",
]
