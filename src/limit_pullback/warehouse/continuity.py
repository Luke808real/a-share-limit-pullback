"""Sequential preclose construction for ADR-008 daily rows.

The canonical preclose contract is:

    preclose(code, session_t) == close(code, previous valid session for code)

This module owns that rule.  ``seed_previous_close`` is the last trusted close
per code from the seed canonical snapshot; each new session close then becomes
the predecessor for the next session.  No calendar-date-minus-one guessing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

OK = "OK"
MISSING_PREDECESSOR = "MISSING_PREDECESSOR"
PCT_QUANTUM = Decimal("0.0001")


def _pct_change(close: Decimal, preclose: Decimal) -> Decimal | None:
    if preclose <= 0:
        return None
    return (
        (close - preclose) / preclose * Decimal("100")
    ).quantize(PCT_QUANTUM, rounding=ROUND_HALF_UP)


def build_sequential_preclose(
    rows_by_code_session: Mapping[tuple[str, date], dict[str, Any]],
    *,
    seed_previous_close: Mapping[str, Decimal],
    ordered_sessions: Sequence[date],
) -> dict[tuple[str, date], dict[str, Any]]:
    """Attach preclose/pct_change to each staged row, session by session.

    For every code the seed close is the first new-session predecessor.  A row
    whose code has no trusted predecessor gets ``preclose=None`` and
    ``preclose_status=MISSING_PREDECESSOR``; it must never be confirmed.
    """

    ordered = tuple(sorted(set(ordered_sessions)))
    codes = sorted(
        set(seed_previous_close)
        | {key[0] for key in rows_by_code_session}
    )
    previous_close: dict[str, Decimal | None] = {
        code: Decimal(str(seed_previous_close[code]))
        for code in codes
        if code in seed_previous_close
    }
    result: dict[tuple[str, date], dict[str, Any]] = {}
    for code in codes:
        current = previous_close.get(code)
        for session in ordered:
            row = rows_by_code_session.get((code, session))
            if row is None:
                continue
            close = Decimal(str(row["close"]))
            if current is None:
                row["preclose"] = None
                row["preclose_status"] = MISSING_PREDECESSOR
                row["pct_change"] = None
            else:
                row["preclose"] = current
                row["preclose_status"] = OK
                row["pct_change"] = _pct_change(close, current)
            result[(code, session)] = row
            if close > 0:
                current = close
    return result


def previous_close_index(
    rows_by_code_session: Mapping[tuple[str, date], dict[str, Any]],
    *,
    seed_previous_close: Mapping[str, Decimal],
    ordered_sessions: Sequence[date],
) -> dict[tuple[str, date], Decimal]:
    """Build {(code, session): predecessor close} for the formal validator.

    This mirrors ``build_sequential_preclose`` exactly so the validator checks
    the same predecessor chain that constructed the rows.
    """

    ordered = tuple(sorted(set(ordered_sessions)))
    codes = sorted(
        set(seed_previous_close)
        | {key[0] for key in rows_by_code_session}
    )
    previous_close: dict[str, Decimal | None] = {
        code: Decimal(str(seed_previous_close[code]))
        for code in codes
        if code in seed_previous_close
    }
    index: dict[tuple[str, date], Decimal] = {}
    for code in codes:
        current = previous_close.get(code)
        for session in ordered:
            row = rows_by_code_session.get((code, session))
            if row is None:
                continue
            if current is not None:
                index[(code, session)] = current
            close = Decimal(str(row["close"]))
            if close > 0:
                current = close
    return index
