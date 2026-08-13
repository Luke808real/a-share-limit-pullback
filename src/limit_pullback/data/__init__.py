"""REF-R3 data boundary package.

The data layer owns the canonical reading surface. For the strangler phase the
legacy screen path delegates to this package; behavior is byte-identical.

Known temporary edge (recorded for R4/R5): `data/canonical.py` keeps the lazy
`screen.engine.pool_quality` import inside the pool provider to preserve exact
behavior; pool-quality policy moves out of the engine in REF-R4/R6.
"""

from limit_pullback.data.canonical import (
    FIXED_FETCHED_AT,
    CanonicalDailyBarProvider,
    CanonicalLimitUpPoolProvider,
    CanonicalMarketData,
    canonical_universe_codes,
    iter_canonical_code_bars,
    load_canonical_market,
    load_canonical_metadata,
)
from limit_pullback.data.ports import CanonicalDataPort
from limit_pullback.data.snapshot import SnapshotDataAdapter
from limit_pullback.data.universe import Phase2d0Universe

__all__ = [
    "FIXED_FETCHED_AT",
    "CanonicalDailyBarProvider",
    "CanonicalDataPort",
    "CanonicalLimitUpPoolProvider",
    "CanonicalMarketData",
    "Phase2d0Universe",
    "SnapshotDataAdapter",
    "canonical_universe_codes",
    "iter_canonical_code_bars",
    "load_canonical_market",
    "load_canonical_metadata",
]
