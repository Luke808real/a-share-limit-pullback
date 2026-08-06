"""Daily coverage status model for the formal strategy universe.

Universe membership is orthogonal to per-session bar availability.  A member
code may be CONFIRMED_TRADED_BAR, VERIFIED_NO_TRADE, or
DATA_MISSING_UNEXPLAINED for a given session; only the last blocks formal
universe data readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

CONFIRMED_TRADED_BAR = "CONFIRMED_TRADED_BAR"
VERIFIED_NO_TRADE = "VERIFIED_NO_TRADE"
DATA_MISSING_UNEXPLAINED = "DATA_MISSING_UNEXPLAINED"


@dataclass(frozen=True)
class DailyCoverageAudit:
    contract_version: str
    as_of: date
    universe_members: tuple[str, ...]
    traded: tuple[tuple[str, date], ...]
    verified_no_trade: tuple[tuple[str, date], ...]
    unexplained_missing: tuple[tuple[str, date], ...]

    @property
    def traded_n(self) -> int:
        return len(self.traded)

    @property
    def verified_no_trade_n(self) -> int:
        return len(self.verified_no_trade)

    @property
    def unexplained_n(self) -> int:
        return len(self.unexplained_missing)

    @property
    def ready(self) -> bool:
        return self.unexplained_n == 0


def classify_daily_coverage(
    *,
    contract_version: str,
    as_of: date,
    universe_members: Sequence[str],
    staged_rows: Sequence[Mapping],
    verified_no_trade: Sequence[tuple[str, date]] = (),
) -> DailyCoverageAudit:
    """Classify every (member, as_of) into the three coverage states."""

    row_keys = {
        (str(row["code"]), row["trade_date"])
        for row in staged_rows
        if row.get("trade_date") == as_of and row.get("close") is not None
    }
    verified = set(verified_no_trade)
    traded: list[tuple[str, date]] = []
    no_trade: list[tuple[str, date]] = []
    unexplained: list[tuple[str, date]] = []
    for code in sorted(set(universe_members)):
        key = (code, as_of)
        if key in row_keys:
            traded.append(key)
        elif key in verified:
            no_trade.append(key)
        else:
            unexplained.append(key)
    return DailyCoverageAudit(
        contract_version=contract_version,
        as_of=as_of,
        universe_members=tuple(sorted(set(universe_members))),
        traded=tuple(sorted(traded)),
        verified_no_trade=tuple(sorted(no_trade)),
        unexplained_missing=tuple(sorted(unexplained)),
    )
