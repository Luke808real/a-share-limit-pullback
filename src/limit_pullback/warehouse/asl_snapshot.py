"""Phase 1C-Q1: build immutable V Flash candidate snapshots from ASL facts.

PRIMARY wiring (official query API):

    ASL
    → ashare_lake.query.load()/scan() (asl_query_adapter — official API only)
    → asl_rows_to_canonical_rows()    (thin mapping to the existing canonical
                                       daily schema — no new format)
    → create_snapshot()               (existing immutable snapshot writer)
    → candidate snapshot (status CURRENT)

The physical-parquet reader (``asl_adapter.load_asl_daily_slice``) is the
LEGACY_MIGRATION_FALLBACK: ``reader="physical"`` keeps it available for
migration audit, but the production default read boundary is the official
Query API.

Explicitly NOT routed through the legacy acquisition / staging /
reconciliation / repair chain.  Legacy provider code remains physically
present but is never called by this path.

``reconciliation_status="CONFIRMED"`` in rows written here means "accepted
canonical fact from authoritative ASL" — it does NOT mean "verified through
legacy multi-provider reconciliation".  No provider reconciliation is
fabricated.

``source_row_hash`` is the existing deterministic canonical row hash
(``validate.DAILY_HASH_FIELDS`` via ``parquet.row_hash``).

Snapshots built here are CANDIDATES (status ``CURRENT``).  They are never
promoted by this module: formal ``SCREEN_READY`` consumption remains blocked
until ST readiness and promotion review are complete.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Sequence

from limit_pullback.warehouse.asl_adapter import (
    CONTRACT_VERSION,
    TESTED_COMPAT_REVISION,
    AslDailyBarRow,
    FROZEN_UNIVERSE_PREFIXES,
    load_asl_daily_slice,
    resolve_asl_asof_scope,
)
from limit_pullback.warehouse.asl_query_adapter import (
    query_asof_scope,
    query_daily_facts,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import SnapshotRecord
from limit_pullback.warehouse.parquet import row_hash
from limit_pullback.warehouse.snapshot import create_snapshot
from limit_pullback.warehouse.validate import DAILY_HASH_FIELDS

#: Policy label for snapshots whose facts come from authoritative ASL.
#: Deliberately distinct from the legacy ``ADR-008-PRD`` label: no ADR-008
#: cross-provider reconciliation ran on this path.
ASL_RECONCILIATION_POLICY_VERSION = "ASL-AUTHORITATIVE-V1"

#: Bounded code chunk size for the query-backed build (internal; the
#: official query API remains responsible for physical reads).
ASL_SNAPSHOT_CODE_CHUNK_SIZE = 512


def asl_rows_to_canonical_rows(
    rows: Sequence[AslDailyBarRow],
) -> list[dict[str, Any]]:
    """Map adapter daily facts to the existing canonical daily schema.

    Only ``VALID_ROW`` facts are mapped (``MISSING_PRECLOSE`` /
    ``MISSING_REQUIRED_AMOUNT`` rows are not canonical-eligible; the writer
    also drops rows whose preclose is None).
    """

    out: list[dict[str, Any]] = []
    for row in rows:
        if row.row_status != "VALID_ROW":
            continue
        canonical: dict[str, Any] = {
            "code": row.code,
            "trade_date": row.trade_date,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "preclose": row.preclose,
            "volume": row.volume,
            "amount": row.amount,
            # No PIT-safe per-stock ASL turnover field; None by design.
            "turnover_rate": None,
            # Frozen sequential pct contract, derived by the adapter.
            "pct_change": row.pct_change,
            "trade_status": row.trade_status,
            "is_st": row.is_st,  # PIT-safe value or None (unknown stays unknown)
            "selected_provider": "ASL",
            # "accepted canonical fact from authoritative ASL"; NOT legacy
            # multi-provider reconciliation output.
            "reconciliation_status": "CONFIRMED",
            "source_row_hash": "",
        }
        canonical["source_row_hash"] = row_hash(DAILY_HASH_FIELDS, canonical)
        out.append(canonical)
    return out


def build_asl_candidate_snapshot(
    *,
    layout: WarehouseLayout,
    asl_root: str | Path,
    as_of: date,
    codes: Sequence[str] | None = None,
    start: date | None = None,
    universe_prefixes: Sequence[str] = FROZEN_UNIVERSE_PREFIXES,
    code_chunk_size: int | None = None,
    reader: str = "query",
) -> SnapshotRecord:
    """ASL → official Query API (primary) → canonical mapping →
    create_snapshot (CURRENT).

    ``codes=None`` (the CLI default when ``--codes`` is omitted) means
    "derive the current V Flash AS_OF pre-ST market scope from ASL" — NOT
    "load every main-board instrument in the ASL catalog".  Explicit
    ``codes`` keep exact-request semantics.

    ``reader="query"`` (default): the official ``ashare_lake.query`` API is
    the production read boundary (bounded code chunks, fail-closed gap
    guard, frozen status/preclose semantics preserved).
    ``reader="physical"``: LEGACY_MIGRATION_FALLBACK via the physical
    ``load_asl_daily_slice`` reader (migration audit only).

    Creates a CANDIDATE snapshot in the caller-provided (isolated / temp)
    warehouse.  Never promotes; never touches production pointers; never
    calls legacy/network providers.
    """

    if codes is None:
        resolved_codes = sorted(
            set(
                query_asof_scope(asl_root, as_of, universe_prefixes)
                if reader == "query"
                else resolve_asl_asof_scope(asl_root, as_of, universe_prefixes)
            )
        )
    else:
        resolved_codes = sorted(set(codes))
    chunk_size = code_chunk_size or ASL_SNAPSHOT_CODE_CHUNK_SIZE

    if reader == "query":
        def _row_chunks():
            for slice_ in query_daily_facts(
                asl_root,
                as_of=as_of,
                start=start,
                codes=resolved_codes,
                universe_prefixes=universe_prefixes,
                chunk_size=chunk_size,
            ):
                yield asl_rows_to_canonical_rows(slice_.rows)

        with WarehouseMetadata(layout.duckdb_path) as metadata:
            return create_snapshot(
                layout=layout,
                metadata=metadata,
                as_of=as_of,
                provider_versions={
                    "ASL": TESTED_COMPAT_REVISION,
                    "ASL_CONTRACT_VERSION": CONTRACT_VERSION,
                },
                daily_row_chunks=_row_chunks(),
                # Typed EMPTY pool: PRICE_ONLY is the frozen mode; no pool
                # source is added in Phase 1C-Q1.
                pool_rows=[],
                # PROVENANCE_GAP: the query API does not expose per-file
                # source hashes, so no truthful source_file_hashes are
                # fabricatable here; canonical_file_hashes are still
                # produced by create_snapshot.
                source_file_hashes={},
                reconciliation_policy_version=(
                    ASL_RECONCILIATION_POLICY_VERSION
                ),
                status="CURRENT",
            )

    # LEGACY_MIGRATION_FALLBACK (physical parquet reader; migration audit).
    slice_ = load_asl_daily_slice(
        asl_root,
        as_of=as_of,
        start=start,
        codes=resolved_codes,
        universe_prefixes=universe_prefixes,
    )
    daily_rows = asl_rows_to_canonical_rows(slice_.rows)
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        return create_snapshot(
            layout=layout,
            metadata=metadata,
            as_of=as_of,
            provider_versions={
                "ASL": slice_.tested_compat_revision,
                "ASL_CONTRACT_VERSION": slice_.contract_version,
            },
            daily_rows=daily_rows,
            # Typed EMPTY pool: PRICE_ONLY is the frozen mode; no pool source
            # is added in Phase 1C-1.
            pool_rows=[],
            # PROVENANCE_GAP: the adapter does not expose source-file paths,
            # so no truthful per-file source hashes are fabricatable here;
            # canonical_file_hashes are still produced by create_snapshot.
            source_file_hashes={},
            reconciliation_policy_version=ASL_RECONCILIATION_POLICY_VERSION,
            status="CURRENT",
        )
