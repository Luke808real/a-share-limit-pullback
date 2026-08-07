"""Phase 1C-1: build immutable V Flash candidate snapshots from ASL facts.

Wiring (frozen architecture):

    ASL
    → load_asl_daily_slice()          (existing ASL adapter)
    → asl_rows_to_canonical_rows()    (thin mapping to the existing canonical
                                       daily schema — no new format)
    → create_snapshot()               (existing immutable snapshot writer)
    → candidate snapshot (status CURRENT)

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

#: Bounded-construction chunk size: resolved codes are split into chunks of
#: this size; each chunk is loaded through the existing adapter, mapped, and
#: written before the next chunk is loaded (peak-memory bound).  Internal
#: implementation constant; not a CLI knob.
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
) -> SnapshotRecord:
    """ASL → adapter → canonical mapping → create_snapshot (CURRENT).

    ``codes=None`` (the CLI default when ``--codes`` is omitted) means
    "derive the current V Flash AS_OF pre-ST market scope from ASL" via
    :func:`resolve_asl_asof_scope` — NOT "load every main-board instrument
    in the ASL catalog".  Explicit ``codes`` keep exact-request semantics
    (the adapter sorts/dedupes requested codes identically for direct and
    chunked requests).

    BOUNDED CONSTRUCTION: the resolved code set is sorted deterministically
    and split into chunks of ``code_chunk_size`` (default
    :data:`ASL_SNAPSHOT_CODE_CHUNK_SIZE`); each chunk is loaded through the
    existing adapter, mapped to canonical rows, and handed to
    ``create_snapshot(daily_row_chunks=...)`` which writes ONE atomic daily
    parquet.  Row order stays (code, trade_date); no global sort is added.

    Creates a CANDIDATE snapshot in the caller-provided (isolated / temp)
    warehouse.  Never promotes; never touches production pointers; never
    calls legacy/network providers.
    """

    resolved_codes = sorted(
        set(
            resolve_asl_asof_scope(asl_root, as_of, universe_prefixes)
            if codes is None
            else list(codes)
        )
    )
    chunk_size = code_chunk_size or ASL_SNAPSHOT_CODE_CHUNK_SIZE

    def _row_chunks():
        for index in range(0, len(resolved_codes), chunk_size):
            chunk = resolved_codes[index : index + chunk_size]
            slice_ = load_asl_daily_slice(
                asl_root,
                as_of=as_of,
                start=start,
                codes=chunk,
                universe_prefixes=universe_prefixes,
            )
            rows = asl_rows_to_canonical_rows(slice_.rows)
            del slice_
            yield rows

    with WarehouseMetadata(layout.duckdb_path) as metadata:
        return create_snapshot(
            layout=layout,
            metadata=metadata,
            as_of=as_of,
            # Adapter-declared contract/revision constants: every slice
            # copies these verbatim, so this is the same provenance the
            # adapter reports at runtime.
            provider_versions={
                "ASL": TESTED_COMPAT_REVISION,
                "ASL_CONTRACT_VERSION": CONTRACT_VERSION,
            },
            daily_row_chunks=_row_chunks(),
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
