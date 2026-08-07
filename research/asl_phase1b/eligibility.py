"""Main-board non-ST strategy eligibility — Phase-1B shadow path (READ-ONLY).

Frozen universe contract (no redesign): SH/SZ MAINBOARD NORMAL A-SHARES ONLY.

ST IS A POSITIVE EXCLUSION SET, NOT A PER-ROW STATUS REQUIREMENT.

Baostock historical ST rows are positive ST exclusion facts; ordinary
non-ST dates generally have no status row, and that is NORMAL.  A missing
per-stock status row is never turned into an exclusion.

    ASL ST dataset / ST exclusion set
            |
            +-- code-date is trusted ST/*ST -> EXCLUDED_ST
            |
            +-- otherwise                   -> continue eligibility checks

Fail-closed applies at DATASET LEVEL: the screen for an evaluation date is
published only when the required eligibility universe is covered by a
COMPLETED trusted ST data operation.  Completeness is proven by the official
ASL ST-backfill completion evidence (the ``trading_status_st_backfill``
resume marker) — NEVER inferred from the number of ST rows, from a
non-empty trading_status dataset, or from a stock's absence from the ST set.
If coverage is incomplete the screen is NOT published
(``ST_DATA_NOT_READY``).

ELIGIBILITY IS A MASK, NOT A HISTORY-DELETION RULE.

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

ST bars are NEVER deleted from the price series; the production strategy
already rejects ``is_st=True`` bars as limit-up anchors.

One code-date eligibility (in order):

1. non-main-board -> EXCLUDED_NON_MAINBOARD
2. not listed / delisted -> EXCLUDED_NOT_LISTED
3. no trading bar / suspended -> EXCLUDED_SUSPENDED
4. trusted ST/*ST exclusion fact -> EXCLUDED_ST
5. otherwise -> ELIGIBLE

Data source: ASL curated instruments (exchange / asset_type / list_date /
delist_date) and ASL trading_status (trusted Baostock ST facts).  No legacy
stock names, no extra providers, no Parquet edits.
"""

from __future__ import annotations

import json
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


def official_st_completed_symbols(asl_root: Path) -> set[str]:
    """Official ASL ST-backfill completion evidence (resume marker).

    Reads ``<root>/meta/state/trading_status_st_backfill.json`` — the
    per-symbol completion registry written by the official ASL backfill path
    (``_mark_st_backfilled``) only after a symbol's trusted ST fetch + write
    succeeded.  Missing or malformed evidence returns an empty set (fail
    closed); no second coverage database is invented.
    """

    marker = Path(asl_root) / "meta" / "state" / "trading_status_st_backfill.json"
    if not marker.exists():
        return set()
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return set()
    completed = payload.get("completed")
    if not isinstance(completed, list):
        return set()
    return {str(symbol) for symbol in completed if isinstance(symbol, str)}


def _required_symbols(required_codes: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for code in required_codes:
        code = str(code).zfill(6)
        out.add(code + (".SH" if code.startswith("6") else ".SZ"))
    return out


def st_exclusion_ready(
    asl_root: Path,
    as_of: date,
    required_codes: Sequence[str],
) -> bool:
    """Dataset-level ST exclusion readiness over *required_codes*.

    READY only when the official ASL completion evidence proves a COMPLETED
    trusted ST operation for EVERY required code.  Row counts, a non-empty
    trading_status dataset, or a stock's absence from the ST set NEVER prove
    completeness — a day with zero ST names can still be READY when the
    official completion contract proves the fetch completed.

    *as_of* scopes the contract date; the official resume marker is the
    completion evidence.
    """

    completed = official_st_completed_symbols(asl_root)
    required = _required_symbols(required_codes)
    return required <= completed


def screen_gate(
    asl_root: Path,
    as_of: date,
    required_codes: Sequence[str],
) -> str:
    """``READY`` or ``ST_DATA_NOT_READY`` — the screen for *as_of* is
    published only when the required eligibility universe is covered by a
    completed trusted ST data operation."""

    return (
        "READY"
        if st_exclusion_ready(asl_root, as_of, required_codes)
        else "ST_DATA_NOT_READY"
    )


def eligibility_for_date(
    code: str,
    day: date,
    instrument: Mapping[str, Any] | None,
    row: Mapping[str, Any] | None,
) -> str:
    """``ELIGIBLE`` or ``EXCLUDED_<reason>`` for one code-date (the mask).

    In order: NON_MAINBOARD > NOT_LISTED > SUSPENDED > ST > ELIGIBLE.  ST is
    a positive exclusion set: a trusted ``is_st=True`` fact excludes; the
    absence of a per-stock status row never excludes (ordinary non-ST dates
    generally have no status row).  Dataset-level readiness is a separate
    gate (``screen_gate`` / ``st_exclusion_ready``).

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
    if row is None or row.get("trade_status") is False:
        return "EXCLUDED_SUSPENDED"
    if row.get("is_st") is True:
        return "EXCLUDED_ST"
    return "ELIGIBLE"


def required_st_codes_for_asof(
    instruments: Mapping[str, Mapping[str, Any]],
    bars_at_asof: Mapping[str, Any],
    as_of: date,
) -> list[str]:
    """Required ST coverage scope for *as_of* — the codes that actually reach
    the ST check (frozen eligibility order steps 1-3 passed).

    Codes eliminated before the ST check are NOT part of the required ST
    coverage scope:

    * step 1  non-main-board                          -> excluded
    * step 2  not listed / delisted on *as_of*        -> excluded
    * step 3  suspended / no valid trading AS_OF bar  -> excluded

    ``bars_at_asof`` maps code -> volume (or row dict with ``volume``); a
    missing entry or volume <= 0 means no valid trading bar.  Sorted for
    determinism.
    """

    out: list[str] = []
    for code, instrument in instruments.items():
        if not is_mainboard_instrument(instrument):
            continue
        list_date = instrument.get("list_date")
        delist_date = instrument.get("delist_date")
        if (list_date is not None and as_of < list_date) or (
            delist_date is not None and as_of >= delist_date
        ):
            continue
        bar = bars_at_asof.get(code)
        volume = bar.get("volume") if isinstance(bar, dict) else bar
        if bar is None or (volume or 0) <= 0:
            continue
        out.append(code)
    return out


def is_asof_strategy_eligible(
    code: str,
    as_of: date,
    instrument: Mapping[str, Any] | None,
    asof_row: Mapping[str, Any] | None,
) -> str:
    """AS_OF screen gate: run the AS_OF eligibility check FIRST.

    If the AS_OF date is excluded, no candidate is returned for the code; if
    it is eligible, the strategy still runs on the COMPLETE historical bar
    series (never on a shortened series).  Dataset-level ST readiness is
    checked separately via ``screen_gate`` before the screen is published.
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
