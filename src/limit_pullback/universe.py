"""PHASE2D0 universe contract and coverage semantics.

Architect decision (PR-C resume): the historical production screen universe
for ``phase-2d0`` is exactly SH/SZ MAIN-BOARD codes that have CONFIRMED
canonical rows.  Declared config gates (``exclude_st``,
``minimum_listing_trade_days``, ``require_active_trade``) were NOT enforced at
universe membership by the historical production path and are explicitly
deferred as semantic debt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from limit_pullback.instruments import (
    InstrumentCodeError,
    parse_instrument_code,
)
from limit_pullback.warehouse.layout import WarehouseLayout

PHASE2D0_UNIVERSE_CONTRACT_VERSION = "PHASE2D0_UNIVERSE_V1"
PHASE2D0_STRATEGY_VERSION = "phase-2d0"

DECLARED_BUT_NOT_ENFORCED_FILTERS = (
    "exclude_st",
    "minimum_listing_trade_days",
    "require_active_trade",
)


@dataclass(frozen=True)
class Phase2d0Universe:
    contract_version: str
    strategy_version: str
    exchange_allowlist: tuple[str, ...]
    board_allowlist: tuple[str, ...]
    as_of: date
    members: tuple[str, ...]
    member_hash: str
    legacy_behavior_compatibility: bool = True

    @property
    def member_n(self) -> int:
        return len(self.members)


def _member_hash(members: Sequence[str]) -> str:
    payload = "|".join(sorted(members))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_phase2d0_main_board(code: str) -> bool:
    """SH/SZ MAIN-BOARD membership predicate (prefix contract as typed metadata)."""

    try:
        parse_instrument_code(code)
    except InstrumentCodeError:
        return False
    return True


def phase2d0_universe_members(codes: Sequence[str]) -> tuple[str, ...]:
    """Filter codes to the PHASE2D0_UNIVERSE_V1 membership set.

    Membership is exchange/board only (SH/SZ MAIN).  Declared config filters
    are intentionally NOT applied; see DECLARED_BUT_NOT_ENFORCED_FILTERS.
    """

    return tuple(
        sorted(
            {
                str(code).zfill(6)
                for code in codes
                if is_phase2d0_main_board(str(code).zfill(6))
            }
        )
    )


def phase2d0_universe_from_snapshot(
    layout: WarehouseLayout,
    snapshot,
    *,
    as_of: date | None = None,
) -> Phase2d0Universe:
    """Build the PHASE2D0 universe from a snapshot's CONFIRMED daily rows."""

    frontier = as_of or snapshot.as_of
    daily_rel = next(
        (
            key
            for key in snapshot.canonical_file_hashes
            if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
        ),
        None,
    )
    if daily_rel is None:
        raise ValueError("snapshot has no daily bars")
    table = pq.read_table(
        layout.root / daily_rel,
        columns=["code", "trade_date", "reconciliation_status"],
    )
    mask = pc.equal(
        table["reconciliation_status"],
        pa.scalar("CONFIRMED"),
    )
    mask = pc.and_(
        mask,
        pc.less_equal(table["trade_date"], pa.scalar(frontier)),
    )
    codes = sorted(
        {str(code) for code in table.filter(mask)["code"].to_pylist()}
    )
    members = phase2d0_universe_members(codes)
    return Phase2d0Universe(
        contract_version=PHASE2D0_UNIVERSE_CONTRACT_VERSION,
        strategy_version=PHASE2D0_STRATEGY_VERSION,
        exchange_allowlist=("SH", "SZ"),
        board_allowlist=("MAIN",),
        as_of=frontier,
        members=members,
        member_hash=_member_hash(members),
    )


def declared_config_universe_members(
    *,
    members: Sequence[str],
    rows_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    as_of: date,
    minimum_listing_trade_days: int = 120,
) -> tuple[str, ...]:
    """AUDIT-ONLY universe applying the declared-but-not-enforced config gates.

    Never used for screen membership.  Exists only for semantic impact
    analysis (LEGACY_VS_DECLARED_DIFF_N).
    """

    kept: list[str] = []
    for code in sorted(set(members)):
        rows = rows_by_code.get(code, ())
        if not rows:
            continue
        latest = max(rows, key=lambda row: row["trade_date"])
        if latest.get("is_st") is True:
            continue
        sessions = {row["trade_date"] for row in rows}
        if len(sessions) < minimum_listing_trade_days:
            continue
        if latest["trade_date"] != as_of:
            continue
        kept.append(code)
    return tuple(sorted(kept))


def declared_config_universe_from_snapshot(
    layout: WarehouseLayout,
    snapshot,
    *,
    as_of: date | None = None,
    minimum_listing_trade_days: int = 120,
) -> tuple[str, ...]:
    """AUDIT-ONLY declared-config universe via memory-bounded DuckDB scan."""

    import duckdb

    frontier = as_of or snapshot.as_of
    daily_rel = next(
        (
            key
            for key in snapshot.canonical_file_hashes
            if key.endswith("/daily_bars/" + snapshot.snapshot_id + ".parquet")
        ),
        None,
    )
    if daily_rel is None:
        return ()
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='2GB'")
    rows = con.execute(
        f"""
        SELECT code,
               count(DISTINCT trade_date) AS n_sessions,
               max(trade_date) AS last_date,
               arg_max(is_st, trade_date) AS latest_st
        FROM read_parquet('{layout.root / daily_rel}')
        WHERE reconciliation_status = 'CONFIRMED'
          AND trade_date <= DATE '{frontier.isoformat()}'
        GROUP BY code
        """
    ).fetchall()
    members = set(phase2d0_universe_members(row[0] for row in rows))
    kept: list[str] = []
    for code, n_sessions, last_date, latest_st in rows:
        code = str(code)
        if code not in members:
            continue
        if latest_st is True:
            continue
        if int(n_sessions) < minimum_listing_trade_days:
            continue
        if last_date != frontier:
            continue
        kept.append(code)
    return tuple(sorted(kept))


def _declared_audit_breakdown(
    baseline: set[str],
    rows_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    as_of: date,
) -> dict[str, int]:
    st = 0
    under120 = 0
    no_current_bar = 0
    for code in baseline:
        rows = rows_by_code.get(code, ())
        latest = max(rows, key=lambda row: row["trade_date"])
        if latest.get("is_st") is True:
            st += 1
        if len({row["trade_date"] for row in rows}) < 120:
            under120 += 1
        if latest["trade_date"] != as_of:
            no_current_bar += 1
    return {
        "LEGACY_ST_MEMBER_N": st,
        "LEGACY_UNDER120_MEMBER_N": under120,
        "LEGACY_NO_CURRENT_BAR_MEMBER_N": no_current_bar,
    }


def write_universe_manifest(
    *,
    universe: Phase2d0Universe,
    layout: WarehouseLayout,
    declared_member_n: int | None = None,
    legacy_vs_declared_diff_n: int | None = None,
    baseline_members: Sequence[str] | None = None,
    rows_by_code: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    audit_breakdown: Mapping[str, int] | None = None,
    path: Path | None = None,
) -> Path:
    """Write the staged PHASE2D0 universe manifest (audit, not promotion)."""

    baseline_set = set(baseline_members or universe.members)
    breakdown = {}
    if audit_breakdown is not None:
        breakdown = dict(audit_breakdown)
    elif rows_by_code is not None:
        breakdown = _declared_audit_breakdown(
            baseline_set,
            rows_by_code,
            universe.as_of,
        )
    target = path or (
        layout.root
        / "tmp"
        / "staging"
        / "pr-c"
        / "universe"
        / f"phase2d0-universe-{universe.as_of.isoformat()}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract_version": universe.contract_version,
        "strategy_version": universe.strategy_version,
        "as_of": universe.as_of.isoformat(),
        "exchange_allowlist": list(universe.exchange_allowlist),
        "board_allowlist": list(universe.board_allowlist),
        "member_identity_semantics": (
            "canonical CONFIRMED daily rows + SH/SZ MAIN board via "
            "limit_pullback.instruments.parse_instrument_code"
        ),
        "member_n": universe.member_n,
        "member_hash": universe.member_hash,
        "legacy_behavior_compatibility": universe.legacy_behavior_compatibility,
        "declared_config_filters_not_applied_to_membership": list(
            DECLARED_BUT_NOT_ENFORCED_FILTERS
        ),
        "reason": "PHASE2D0_HISTORICAL_BEHAVIOR_COMPATIBILITY",
        "declared_config_universe_n": declared_member_n,
        "legacy_vs_declared_diff_n": legacy_vs_declared_diff_n,
        "audit_breakdown": breakdown,
        "members": list(universe.members),
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target
