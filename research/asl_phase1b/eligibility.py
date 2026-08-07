"""Main-board non-ST strategy eligibility — Phase-1B shadow path (READ-ONLY).

Frozen universe contract (no redesign): SH/SZ MAINBOARD NORMAL A-SHARES ONLY.

Eligibility is decided BEFORE strategy evaluation (``screen_code``).  A
code-date outside the universe is excluded from evaluation; normal periods of
the same stock remain evaluable.  ST is an EXCLUSION FLAG only: a trusted
PIT ``is_st=True`` (ASL Baostock historical ST or same-day status) excludes
the code-date; ``is_st=None`` (unknown) NEVER excludes.

Data source: ASL curated instruments (exchange / asset_type / list_date /
delist_date) for main-board membership and listing state; ASL PIT
trading-status facts for ST and suspension.  No legacy stock names, no extra
providers, no Parquet edits.

Exclusion reasons:

* EXCLUDED_NON_MAINBOARD — not SH/SZ main-board A-share (ChiNext / STAR /
  BSE / ETF / CDR / other)
* EXCLUDED_NOT_LISTED   — before list_date or on/after delist_date
* EXCLUDED_ST           — trusted PIT is_st=True on that date
* EXCLUDED_SUSPENDED    — PIT trade_status=False on that date (suspended /
  non-trading session)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

#: Frozen SH/SZ main-board A-share prefix contract (QA cross-check and the
#: operational board definition — ASL has no explicit "main board" column;
#: STAR=68x, ChiNext=30x, BSE=92x/43x/83x/87x, ETF=51x/52x/56x/58x/15x/16x
#: are all outside this contract).
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


def is_strategy_eligible(
    code: str,
    day: date,
    instrument: Mapping[str, Any] | None,
    row: Mapping[str, Any],
) -> str:
    """``ELIGIBLE`` or ``EXCLUDED_<reason>`` for one code-date.

    Precedence: NON_MAINBOARD > NOT_LISTED > ST > SUSPENDED.  ST is an
    exclusion flag only — ``is_st is True`` excludes, ``is_st=None`` never
    does.  Suspension excludes via the PIT ``trade_status`` flag; a session
    with no bar at all is simply absent from the bar series.
    """

    if not is_mainboard_instrument(instrument):
        return "EXCLUDED_NON_MAINBOARD"
    list_date = instrument.get("list_date")
    delist_date = instrument.get("delist_date")
    if (list_date is not None and day < list_date) or (
        delist_date is not None and day >= delist_date
    ):
        return "EXCLUDED_NOT_LISTED"
    if row.get("is_st") is True:
        return "EXCLUDED_ST"
    if row.get("trade_status") is False:
        return "EXCLUDED_SUSPENDED"
    return "ELIGIBLE"


def filter_eligible_rows(
    rows: Sequence[Mapping[str, Any]],
    instruments: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split adapter rows into (eligible, exclusions) BEFORE strategy input.

    Exclusions carry ``{code, date, reason}`` for evidence; eligible rows are
    passed unchanged to ``screen_code``.
    """

    eligible: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for row in rows:
        code = str(row["code"])
        reason = is_strategy_eligible(
            code,
            row["trade_date"],
            instruments.get(code),
            row,
        )
        if reason == "ELIGIBLE":
            eligible.append(row)
        else:
            exclusions.append(
                {
                    "code": code,
                    "date": row["trade_date"].isoformat(),
                    "reason": reason,
                }
            )
    return eligible, exclusions
