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

STATE_COVERED_THROUGH_AS_OF = "STATE_COVERED_THROUGH_AS_OF"
STATE_MISSING_CONFIRMED_BAR_PROCESSING = (
    "STATE_MISSING_CONFIRMED_BAR_PROCESSING"
)
STATE_DATA_MISSING_UNEXPLAINED = "STATE_DATA_MISSING_UNEXPLAINED"
STATE_INVALID_COVERAGE_EVIDENCE = "STATE_INVALID_COVERAGE_EVIDENCE"


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
        if row.get("trade_date") == as_of
        and row.get("close") is not None
        and str(row.get("reconciliation_status")) == "CONFIRMED"
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


def state_is_covered_through(
    *,
    last_processed_date: date,
    as_of: date,
    session_calendar: Sequence[date],
    confirmed_traded_sessions: Sequence[tuple[str, date]],
    verified_no_trade_sessions: Sequence[tuple[str, date]],
    code: str,
) -> tuple[str, date, tuple[str, ...]]:
    """Session-by-session coverage proof for one state.

    Every trading session in ``(last_processed_date, as_of]`` must be either a
    CONFIRMED_TRADED_BAR (which must therefore have been processed) or a
    VERIFIED_NO_TRADE.  A confirmed bar after ``last_processed_date`` is a
    hard processing failure; an unexplained session is a coverage failure.
    """

    if last_processed_date > as_of:
        return (
            STATE_INVALID_COVERAGE_EVIDENCE,
            last_processed_date,
            ("LAST_PROCESSED_AFTER_AS_OF",),
        )
    confirmed = {
        (str(entry[0]), entry[1])
        for entry in confirmed_traded_sessions
        if entry[1] <= as_of
    }
    verified = {
        (str(entry[0]), entry[1])
        for entry in verified_no_trade_sessions
        if entry[1] <= as_of
    }
    sessions_after = sorted(
        session
        for session in set(session_calendar)
        if last_processed_date < session <= as_of
    )
    missing_processing = sorted(
        session
        for session in sessions_after
        if (code, session) in confirmed
    )
    unexplained = sorted(
        session
        for session in sessions_after
        if (code, session) not in confirmed
        and (code, session) not in verified
    )
    if missing_processing:
        return (
            STATE_MISSING_CONFIRMED_BAR_PROCESSING,
            last_processed_date,
            tuple(
                f"CONFIRMED_BAR_UNPROCESSED:{session.isoformat()}"
                for session in missing_processing
            ),
        )
    if unexplained:
        return (
            STATE_DATA_MISSING_UNEXPLAINED,
            last_processed_date,
            tuple(
                f"UNEXPLAINED_SESSION:{session.isoformat()}"
                for session in unexplained
            ),
        )
    return STATE_COVERED_THROUGH_AS_OF, as_of, ()
