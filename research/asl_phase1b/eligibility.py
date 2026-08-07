"""Main-board non-ST strategy eligibility — Phase-1B shadow path (READ-ONLY).

Frozen universe contract (no redesign): SH/SZ MAINBOARD NORMAL A-SHARES ONLY.

ELIGIBILITY IS A MASK, NOT A HISTORY-DELETION RULE.

Correct strategy model:

    all real ASL bars
            |
            v
    screen_code / indicator history   (complete, unmodified market history)
            |
            v
    eligibility mask on evaluation date
            |
            v
    only eligible dates may produce user-facing candidates

ST bars are NEVER deleted from the price series: moving averages, volume
averages, preclose continuity, trading-day distances and support/resistance
history must see the real market.  The production strategy already rejects
``is_st=True`` bars as limit-up anchors; this module only gates user-facing
output.

ST status policy (fail closed):

    is_st == True                        -> EXCLUDED_ST
    trusted explicit non-ST status       -> may be ELIGIBLE
    ST status unknown / unproven         -> EXCLUDED_STATUS_UNKNOWN

An absent status row is NEVER treated as non-ST ("we prefer missing a
candidate over accidentally trading an ST stock").

Data source: ASL curated instruments (exchange / asset_type / list_date /
delist_date) for main-board membership and listing state; ASL PIT
trading-status facts for ST / suspension / same-day non-ST.  No legacy stock
names, no extra providers, no Parquet edits.

Exclusion reasons:

* EXCLUDED_NON_MAINBOARD  — not SH/SZ main-board A-share (ChiNext / STAR /
  BSE / ETF / CDR / other)
* EXCLUDED_NOT_LISTED     — before list_date or on/after delist_date
* EXCLUDED_ST             — trusted PIT is_st=True on that date
* EXCLUDED_SUSPENDED      — PIT trade_status=False / no bar that date
* EXCLUDED_STATUS_UNKNOWN — no trusted ST status evidence for that date
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

#: Frozen SH/SZ main-board A-share prefix contract (QA cross-check and the
#: operational board definition — ASL has no explicit "main board" column;
#: STAR=68x, ChiNext=30x, BSE=92x/43x/83x/87x, ETF=51x/52x/56x/58x/15x/16x,
#: CDR=689x are all outside this contract).
FROZEN_MAINBOARD_PREFIXES = (
    "000", "001", "002", "003",
    "600", "601", "603", "605",
)


def load_instruments(asl_root: Path) -> dict[str, dict[str, Any]]:
    """{code: instrument} from ASL curated instruments (source of truth)."""

    path = Path(asl_root) / "curated" / "instruments" / "part-merged.parquet"
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for row in pq.read_table(path).to_pylist():
        symbol = str(row.get("symbol") or "")
        if "." not in symbol:
            continue
        out[symbol.split(".")[0].zfill(6)] = {
            "symbol": symbol,
            "exchange": str(row.get("exchange") or "").upper(),
            "asset_type": str(row.get("asset_type") or ""),
            "list_date": row.get("list_date"),
            "delist_date": row.get("delist_date"),
        }
    return out


def is_mainboard_instrument(
    instrument: Mapping[str, Any] | None,
) -> bool:
    """SH/SZ exchange, stock asset type, and the frozen main-board prefixes."""

    if instrument is None:
        return False
    if instrument["exchange"] not in ("SH", "SZ"):
        return False
    if instrument["asset_type"] != "stock":
        return False
    code = instrument["symbol"].split(".")[0].zfill(6)
    return code.startswith(FROZEN_MAINBOARD_PREFIXES)


def eligibility_for_date(
    code: str,
    day: date,
    instrument: Mapping[str, Any] | None,
    row: Mapping[str, Any] | None,
) -> str:
    """``ELIGIBLE`` or ``EXCLUDED_<reason>`` for one code-date (the mask).

    Precedence: NON_MAINBOARD > NOT_LISTED > ST > SUSPENDED > STATUS_UNKNOWN.
    ``ELIGIBLE`` requires a TRUSTED explicit non-ST fact (``is_st is False``,
    which the adapter only emits from a trusted same-day status row);
    ``is_st is None`` (unproven) is ``EXCLUDED_STATUS_UNKNOWN`` and never
    guessed normal.  A missing row (no bar that date) is suspended.

    This function NEVER shortens the strategy history — it only decides
    whether that evaluation date may produce a user-facing candidate.
    """

    if not is_mainboard_instrument(instrument):
        return "EXCLUDED_NON_MAINBOARD"
    list_date = instrument.get("list_date")
    delist_date = instrument.get("delist_date")
    if (list_date is not None and day < list_date) or (
        delist_date is not None and day >= delist_date
    ):
        return "EXCLUDED_NOT_LISTED"
    if row is None:
        return "EXCLUDED_SUSPENDED"
    if row.get("is_st") is True:
        return "EXCLUDED_ST"
    if row.get("trade_status") is False:
        return "EXCLUDED_SUSPENDED"
    if row.get("is_st") is False:
        # Trusted explicit non-ST status (adapter emits is_st=False only
        # from a trusted same-day status row).
        return "ELIGIBLE"
    return "EXCLUDED_STATUS_UNKNOWN"


def is_asof_strategy_eligible(
    code: str,
    as_of: date,
    instrument: Mapping[str, Any] | None,
    asof_row: Mapping[str, Any] | None,
) -> str:
    """AS_OF screen gate: run the AS_OF eligibility check FIRST.

    If the AS_OF date is excluded, no candidate is returned for the code; if
    it is eligible, the strategy still runs on the COMPLETE historical bar
    series (never on a shortened series).
    """

    return eligibility_for_date(code, as_of, instrument, asof_row)


def classify_rows_evidence(
    rows: Sequence[Mapping[str, Any]],
    instruments: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per-date eligibility classification for EVIDENCE ONLY.

    This must NOT be used to build a shortened strategy history.  It exists
    to report why individual code-dates are ineligible (exclusion audit).
    Returns ``(eligible_dates, exclusions)`` with ``{code, date, reason}``.
    """

    eligible: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for row in rows:
        code = str(row["code"])
        reason = eligibility_for_date(
            code,
            row["trade_date"],
            instruments.get(code),
            row,
        )
        entry = {
            "code": code,
            "date": row["trade_date"].isoformat(),
            "reason": reason,
        }
        if reason == "ELIGIBLE":
            eligible.append(entry)
        else:
            exclusions.append(entry)
    return eligible, exclusions


def mask_timeline_dates(
    items: Sequence[Any],
    instruments: Mapping[str, Mapping[str, Any]],
    rows_by_date: Mapping[date, Mapping[str, Any]],
    code: str,
) -> list[Any]:
    """Mask strategy timeline items to eligibility-eligible dates ONLY.

    The strategy already ran on the complete history; this filters the
    user-facing output so excluded evaluation dates never surface as
    candidates (B1/B2/T0 output).
    """

    masked: list[Any] = []
    for item in items:
        reason = eligibility_for_date(
            code,
            item.trade_date,
            instruments.get(code),
            rows_by_date.get(item.trade_date),
        )
        if reason == "ELIGIBLE":
            masked.append(item)
    return masked
