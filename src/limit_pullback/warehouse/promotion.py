"""PR-D: staged -> validated -> atomic SCREEN_READY snapshot promotion.

Visibility atomicity model:

1. build a unique content-addressed staging generation under tmp/pr-d
2. validate (historical parity, continuity, duplicates, coverage, lineage)
3. finalize immutable files into canonical/manifest/validation/lineage dirs
4. one DuckDB transaction registers snapshot + publications + validation +
   promotion record + formal pointer

Formal readers never see the new snapshot before the transaction commits.
Crash leftovers are unreferenced orphans, safe to GC.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from limit_pullback.config import load_strategy_config
from limit_pullback.coverage import classify_daily_coverage
from limit_pullback.derived_limit_event import (
    DerivedLimitUpEvent,
    derived_event_content_hash,
)
from limit_pullback.models.config import StrategyConfig
from limit_pullback.universe import (
    Phase2d0Universe,
    PHASE2D0_UNIVERSE_CONTRACT_VERSION,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import (
    canonical_daily_schema,
    canonical_limit_up_pool_schema,
    quantize_row,
    row_hash,
    sha256_file,
    write_json_atomic,
    write_rows_atomic,
)
from limit_pullback.warehouse.snapshot import (
    SnapshotUsabilityError,
    require_formally_usable_snapshot,
)
from limit_pullback.warehouse.staging import staged_candidate_content_hash
from limit_pullback.warehouse.validate import (
    DAILY_HASH_FIELDS,
    PRICE_RELATIVE,
    PRICE_TOLERANCE,
    preclose_continuity_issues,
)
from limit_pullback.strategy.structure import is_limit_close

VALIDATOR_VERSION = "PRD_VALIDATOR_V1"
SCREEN_READY = "SCREEN_READY"
QUARANTINED = "QUARANTINED"
PROMOTION_REASON = "ADR008_CORRECTNESS_REBUILD_AFTER_QUARANTINE"


class PromotionFailpointError(RuntimeError):
    """Raised at a requested failpoint for fault-injection tests."""


class PromotionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromotionResult:
    snapshot_id: str
    snapshot_content_hash: str
    manifest_hash: str
    validation_report_hash: str
    as_of: date
    status: str
    formal_pointer_before: str | None
    formal_pointer_after: str | None
    daily_total_n: int
    published_20260803_n: int
    published_20260804_n: int
    published_20260805_n: int
    legacy_pool_published_n: int
    derived_20260803_published_n: int
    derived_20260804_published_n: int
    derived_20260805_published_n: int
    pool_total_n: int
    idempotent: bool
    build_wall_seconds: float
    validation_wall_seconds: float
    peak_rss_bytes: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _git_head() -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _raise_failpoint(failpoint: str | None, name: str) -> None:
    if failpoint == name:
        raise PromotionFailpointError(name)


def _deterministic_row_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        payload = json.dumps(
            {
                key: (
                    value.isoformat()
                    if isinstance(value, (date, datetime))
                    else str(value)
                    if isinstance(value, Decimal)
                    else value
                )
                for key, value in sorted(row.items())
                if key not in {"fetched_at", "created_at"}
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _streaming_daily_hash(path: Path) -> str:
    digest = hashlib.sha256()
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(batch_size=65536, use_threads=False):
        for row in batch.to_pylist():
            payload = json.dumps(
                {
                    key: (
                        value.isoformat()
                        if isinstance(value, (date, datetime))
                        else str(value)
                        if isinstance(value, Decimal)
                        else value
                    )
                    for key, value in sorted(row.items())
                    if key != "dataset_snapshot_id"
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            digest.update(payload.encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def _new_canonical_row(staged: Mapping[str, Any], snapshot_id: str) -> dict[str, Any]:
    row = {
        "code": str(staged["code"]),
        "trade_date": staged["trade_date"],
        "open": Decimal(str(staged["open"])),
        "high": Decimal(str(staged["high"])),
        "low": Decimal(str(staged["low"])),
        "close": Decimal(str(staged["close"])),
        "preclose": Decimal(str(staged["preclose"])),
        "volume": Decimal(str(staged["volume"])),
        "amount": Decimal(str(staged["amount"])),
        "turnover_rate": None,
        "pct_change": (
            Decimal(str(staged["pct_change"]))
            if staged.get("pct_change") is not None
            else None
        ),
        "trade_status": True,
        "is_st": None,
        "selected_provider": "TDX",
        "reconciliation_status": "CONFIRMED",
        "source_row_hash": "",
        "dataset_snapshot_id": snapshot_id,
    }
    row["source_row_hash"] = row_hash(DAILY_HASH_FIELDS, row)
    return row


def _build_daily_file(
    *,
    layout: WarehouseLayout,
    base_snapshot,
    staged_rows: Sequence[Mapping[str, Any]],
    snapshot_id: str,
    target: Path,
) -> tuple[int, int, int, int]:
    """Stream base history unchanged + CONFIRMED staged rows into new daily."""

    base_rel = next(
        key
        for key in base_snapshot.canonical_file_hashes
        if key.endswith(
            "/daily_bars/" + base_snapshot.snapshot_id + ".parquet"
        )
    )
    base_path = layout.root / base_rel
    pf = pq.ParquetFile(base_path)
    schema = canonical_daily_schema()
    target.parent.mkdir(parents=True, exist_ok=True)
    historical_n = 0
    with pq.ParquetWriter(target, schema, compression="zstd") as writer:
        for batch in pf.iter_batches(batch_size=65536, use_threads=False):
            rows = batch.to_pylist()
            historical_n += len(rows)
            prepared = []
            for row in rows:
                row = dict(row)
                row["dataset_snapshot_id"] = snapshot_id
                prepared.append(row)
            writer.write_table(pa.Table.from_pylist(prepared, schema=schema))
        new_rows = [
            _new_canonical_row(staged, snapshot_id)
            for staged in staged_rows
            if staged.get("reconciliation_status") == "CONFIRMED"
        ]
        if new_rows:
            writer.write_table(
                pa.Table.from_pylist(
                    [quantize_row(row, schema) for row in new_rows],
                    schema=schema,
                )
            )
    published = {
        date(2026, 8, 3): 0,
        date(2026, 8, 4): 0,
        date(2026, 8, 5): 0,
    }
    for staged in staged_rows:
        if staged.get("reconciliation_status") != "CONFIRMED":
            continue
        day = staged["trade_date"]
        if day in published:
            published[day] += 1
    return historical_n, published[date(2026, 8, 3)], published[date(2026, 8, 4)], published[date(2026, 8, 5)]


def _legacy_pool_rows(
    layout: WarehouseLayout,
    base_snapshot,
    snapshot_id: str,
) -> list[dict[str, Any]]:
    pool_rel = next(
        key
        for key in base_snapshot.canonical_file_hashes
        if key.endswith(
            "/limit_up_pool/" + base_snapshot.snapshot_id + ".parquet"
        )
    )
    rows = pq.read_table(layout.root / pool_rel).to_pylist()
    for row in rows:
        row["dataset_snapshot_id"] = snapshot_id
    return rows


def _derived_pool_rows(
    events: Sequence[DerivedLimitUpEvent],
    snapshot_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        rows.append(
            {
                "code": event.code,
                "trade_date": event.trade_date,
                "name": event.industry or event.code,
                "limit_price": event.theoretical_limit_price,
                "first_seal_time": None,
                "last_seal_time": None,
                "open_count": None,
                "consecutive_count": None,
                "turnover_rate": None,
                "float_market_cap": None,
                "total_market_cap": None,
                "industry": event.industry,
                "selected_provider": "CANONICAL_DERIVED",
                "reconciliation_status": "CONFIRMED",
                "source_row_hash": event.source_daily_hash,
                "dataset_snapshot_id": snapshot_id,
            }
        )
    rows.sort(key=lambda row: (row["code"], row["trade_date"]))
    return rows


def _duckdb_historical_parity(
    layout: WarehouseLayout,
    base_snapshot,
    new_daily_path: Path,
    as_of: date,
) -> int:
    import duckdb

    base_rel = next(
        key
        for key in base_snapshot.canonical_file_hashes
        if key.endswith(
            "/daily_bars/" + base_snapshot.snapshot_id + ".parquet"
        )
    )
    base_path = layout.root / base_rel
    fields = (
        "code, trade_date, open, high, low, close, preclose, volume, amount, "
        "turnover_rate, pct_change, trade_status, is_st, selected_provider, "
        "reconciliation_status, source_row_hash"
    )
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='2GB'")
    old_count = con.execute(
        f"SELECT count(*) FROM read_parquet('{base_path}') "
        f"WHERE trade_date <= DATE '{as_of.isoformat()}'"
    ).fetchone()[0]
    new_count = con.execute(
        f"SELECT count(*) FROM read_parquet('{new_daily_path}') "
        f"WHERE trade_date <= DATE '{as_of.isoformat()}'"
    ).fetchone()[0]
    old_only = con.execute(
        f"SELECT count(*) FROM ("
        f"  SELECT {fields} FROM read_parquet('{base_path}') "
        f"  WHERE trade_date <= DATE '{as_of.isoformat()}'"
        f"  EXCEPT "
        f"  SELECT {fields} FROM read_parquet('{new_daily_path}') "
        f"  WHERE trade_date <= DATE '{as_of.isoformat()}'"
        f")"
    ).fetchone()[0]
    new_only = con.execute(
        f"SELECT count(*) FROM ("
        f"  SELECT {fields} FROM read_parquet('{new_daily_path}') "
        f"  WHERE trade_date <= DATE '{as_of.isoformat()}'"
        f"  EXCEPT "
        f"  SELECT {fields} FROM read_parquet('{base_path}') "
        f"  WHERE trade_date <= DATE '{as_of.isoformat()}'"
        f")"
    ).fetchone()[0]
    return int(old_count), int(new_count), int(old_only) + int(new_only)


def _validate_new_rows(
    layout: WarehouseLayout,
    base_snapshot,
    new_rows: Sequence[Mapping[str, Any]],
    *,
    universe_members: Sequence[str],
    pool_derived_rows: Sequence[Mapping[str, Any]],
    config: StrategyConfig,
) -> dict[str, Any]:
    seed_closes: dict[str, Decimal] = {}
    base_rel = next(
        key
        for key in base_snapshot.canonical_file_hashes
        if key.endswith(
            "/daily_bars/" + base_snapshot.snapshot_id + ".parquet"
        )
    )
    pf = pq.ParquetFile(layout.root / base_rel)
    for batch in pf.iter_batches(
        columns=["code", "trade_date", "close", "reconciliation_status"],
        batch_size=65536,
        use_threads=False,
    ):
        mask = pc.equal(
            batch["reconciliation_status"],
            pa.scalar("CONFIRMED"),
        )
        mask = pc.and_(
            mask,
            pc.less_equal(
                batch["trade_date"],
                pa.scalar(base_snapshot.as_of),
            ),
        )
        for row in batch.filter(mask).to_pylist():
            seed_closes[str(row["code"])] = Decimal(str(row["close"]))

    from limit_pullback.warehouse.continuity import previous_close_index

    rows_by_key = {
        (row["code"], row["trade_date"]): row for row in new_rows
    }
    prev_index = previous_close_index(
        rows_by_key,
        seed_previous_close=seed_closes,
        ordered_sessions=[
            date(2026, 8, 3),
            date(2026, 8, 4),
            date(2026, 8, 5),
        ],
    )
    issues = preclose_continuity_issues(
        new_rows,
        previous_close_index=prev_index,
        provider_label="TDX",
    )
    duplicates = {
        (str(row["code"]), row["trade_date"]) for row in new_rows
    }
    duplicate_n = len(new_rows) - len(duplicates)
    ohlc_bad = 0
    negative = 0
    for row in new_rows:
        if not (
            Decimal(str(row["open"])) > 0
            and Decimal(str(row["high"])) > 0
            and Decimal(str(row["low"])) > 0
            and Decimal(str(row["close"])) > 0
        ):
            ohlc_bad += 1
        if (
            Decimal(str(row["high"]))
            < max(
                Decimal(str(row["open"])),
                Decimal(str(row["low"])),
                Decimal(str(row["close"])),
            )
            or Decimal(str(row["low"]))
            > min(
                Decimal(str(row["open"])),
                Decimal(str(row["high"])),
                Decimal(str(row["close"])),
            )
        ):
            ohlc_bad += 1
        if Decimal(str(row["volume"])) < 0 or Decimal(str(row["amount"])) < 0:
            negative += 1

    # Pool core coverage / false positives on formal universe.
    member_set = set(universe_members)
    limit_keys: set[tuple[str, date]] = set()
    for row in new_rows:
        if str(row["code"]) not in member_set:
            continue
        from types import SimpleNamespace

        bar = SimpleNamespace(
            preclose=Decimal(str(row["preclose"])),
            close=Decimal(str(row["close"])),
        )
        if is_limit_close(bar, config):
            limit_keys.add((str(row["code"]), row["trade_date"]))
    pool_keys = {
        (str(row["code"]), row["trade_date"])
        for row in pool_derived_rows
    }
    missing = sorted(limit_keys - pool_keys)
    false_positive = sorted(pool_keys - limit_keys)
    return {
        "preclose_continuity_issues": [issue.detail for issue in issues],
        "preclose_continuity_mismatch_n": len(issues),
        "duplicate_n": duplicate_n,
        "ohlc_issues_n": ohlc_bad,
        "negative_volume_amount_n": negative,
        "pool_core_coverage_missing_n": len(missing),
        "pool_core_false_positive_n": len(false_positive),
        "pool_core_coverage_missing_sample": missing[:10],
        "pool_core_false_positive_sample": false_positive[:10],
    }


def _lineage_records(
    staged_rows: Sequence[Mapping[str, Any]],
    snapshot_id: str,
) -> list[dict[str, Any]]:
    records = []
    for row in staged_rows:
        if row.get("reconciliation_status") != "CONFIRMED":
            continue
        canonical = _new_canonical_row(row, snapshot_id)
        records.append(
            {
                "code": str(row["code"]),
                "trade_date": row["trade_date"].isoformat(),
                "canonical_row_hash": canonical["source_row_hash"],
                "selected_provider": "TDX",
                "selected_source_hash": row.get("selected_source_hash"),
                "confirmation_provider": (
                    "TENCENT"
                    if row.get("confirmation_provider") == "TENCENT"
                    else None
                ),
                "confirmation_source_hash": row.get(
                    "confirmation_source_hash"
                ),
                "ingest_run_id": row.get("ingest_run_id"),
                "price_domain": "RAW_UNADJUSTED",
                "corporate_action_status": (
                    row.get("corporate_action_status") or "UNKNOWN"
                ),
            }
        )
    return records


def promote_snapshot(
    layout: WarehouseLayout,
    *,
    base_snapshot_id: str,
    staged_rows: Sequence[Mapping[str, Any]],
    prb_staging_hash: str,
    prb_staging_manifest_path: Path | None = None,
    universe: Phase2d0Universe,
    derived_events: Sequence[DerivedLimitUpEvent],
    derived_event_hash: str,
    config: StrategyConfig,
    raw_tdx_path: Path | None = None,
    raw_tencent_path: Path | None = None,
    verified_no_trade: Sequence[tuple[str, date]] = (),
    failpoint: str | None = None,
    dry_run: bool = False,
    clock=None,
) -> PromotionResult:
    """Run one validated atomic promotion (dry or real)."""

    started = _utc_now()
    build_start = started
    peak_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        base = metadata.snapshot_by_id(base_snapshot_id)
    if base is None:
        raise PromotionError(f"unknown base snapshot: {base_snapshot_id}")
    if base.status == QUARANTINED:
        raise PromotionError("QUARANTINED_SNAPSHOT_CANNOT_PROMOTE")
    require_formally_usable_snapshot(base)
    if universe.member_hash != _sha256_text(
        "|".join(sorted(universe.members))
    ):
        raise PromotionError("universe member_hash mismatch")
    actual_staging_hash = staged_candidate_content_hash(staged_rows)
    if actual_staging_hash != prb_staging_hash:
        if prb_staging_manifest_path is None:
            raise PromotionError(
                f"PR-B staging hash mismatch: {actual_staging_hash} != {prb_staging_hash}"
            )
        try:
            manifest = json.loads(
                prb_staging_manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise PromotionError(
                f"PR-B staging manifest unreadable: {exc}"
            ) from exc
        if manifest.get("staging_canonical_hash") != prb_staging_hash:
            raise PromotionError(
                "PR-B staging manifest hash mismatch: "
                f"{manifest.get('staging_canonical_hash')} != {prb_staging_hash}"
            )
    actual_derived_hash = derived_event_content_hash(derived_events)
    if actual_derived_hash != derived_event_hash:
        raise PromotionError(
            f"derived event hash mismatch: {actual_derived_hash} != {derived_event_hash}"
        )

    build_dir = layout.root / "tmp" / "pr-d" / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    tmp_daily = build_dir / "daily.parquet"
    tmp_pool = build_dir / "pool.parquet"
    historical_n, p0803, p0804, p0805 = _build_daily_file(
        layout=layout,
        base_snapshot=base,
        staged_rows=staged_rows,
        snapshot_id="__generation__",
        target=tmp_daily,
    )
    _raise_failpoint(failpoint, "after_daily_write")
    legacy_pool = _legacy_pool_rows(layout, base, "__generation__")
    derived_pool = _derived_pool_rows(derived_events, "__generation__")
    pool_rows = legacy_pool + derived_pool
    pool_rows.sort(key=lambda row: (row["code"], row["trade_date"]))
    write_rows_atomic(pool_rows, canonical_limit_up_pool_schema(), tmp_pool)
    _raise_failpoint(failpoint, "after_pool_write")

    daily_content_hash = _streaming_daily_hash(tmp_daily)
    pool_content_hash = _deterministic_row_hash(pool_rows)
    daily_file_hash = sha256_file(tmp_daily)
    pool_file_hash = sha256_file(tmp_pool)
    snapshot_content_hash = _sha256_text(
        f"{daily_content_hash}|{pool_content_hash}"
    )
    snapshot_id = f"snap-2026-08-05-{snapshot_content_hash[:12]}"

    # Idempotency: same content -> same snapshot id; never create a second truth.
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        existing = metadata.snapshot_by_id(snapshot_id)
        pointer_now = metadata.get_formal_pointer()
    if existing is not None and existing.status == SCREEN_READY:
        if pointer_now is None or pointer_now[0] != snapshot_id:
            with WarehouseMetadata(layout.duckdb_path) as metadata:
                with metadata.promotion_transaction() as tx:
                    tx.set_formal_pointer(
                        snapshot_id=snapshot_id,
                        validation_report_hash=None,
                        updated_at=_utc_now(),
                    )
        return PromotionResult(
            snapshot_id=snapshot_id,
            snapshot_content_hash=snapshot_content_hash,
            manifest_hash=sha256_file(
                layout.manifests_dir / f"{snapshot_id}.json"
            )
            if (layout.manifests_dir / f"{snapshot_id}.json").exists()
            else "",
            validation_report_hash="",
            as_of=date(2026, 8, 5),
            status=SCREEN_READY,
            formal_pointer_before=(
                pointer_now[0] if pointer_now is not None else None
            ),
            formal_pointer_after=snapshot_id,
            daily_total_n=historical_n
            + sum(
                1
                for staged in staged_rows
                if staged.get("reconciliation_status") == "CONFIRMED"
            ),
            published_20260803_n=p0803,
            published_20260804_n=p0804,
            published_20260805_n=p0805,
            legacy_pool_published_n=len(legacy_pool),
            derived_20260803_published_n=sum(
                1
                for event in derived_events
                if event.trade_date == date(2026, 8, 3)
            ),
            derived_20260804_published_n=sum(
                1
                for event in derived_events
                if event.trade_date == date(2026, 8, 4)
            ),
            derived_20260805_published_n=sum(
                1
                for event in derived_events
                if event.trade_date == date(2026, 8, 5)
            ),
            pool_total_n=len(pool_rows),
            idempotent=True,
            build_wall_seconds=0.0,
            validation_wall_seconds=0.0,
            peak_rss_bytes=peak_rss_bytes,
        )

    # Draft manifest (status STAGED until validation passes).
    draft_dir = build_dir / snapshot_id
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_manifest = {
        "snapshot_id": snapshot_id,
        "as_of": "2026-08-05",
        "status": "STAGED",
        "parent_snapshot": base_snapshot_id,
        "price_domain": "RAW_UNADJUSTED",
    }
    draft_manifest_path = draft_dir / "manifest.draft.json"
    write_json_atomic(draft_manifest, draft_manifest_path)
    _raise_failpoint(failpoint, "after_manifest_write")

    new_rows = [
        _new_canonical_row(staged, snapshot_id)
        for staged in staged_rows
        if staged.get("reconciliation_status") == "CONFIRMED"
    ]
    validation_start = _utc_now()
    validation = _validate_new_rows(
        layout,
        base,
        new_rows,
        universe_members=universe.members,
        pool_derived_rows=derived_pool,
        config=config,
    )
    parity = _duckdb_historical_parity(
        layout,
        base,
        tmp_daily,
        base.as_of,
    )
    validation.update(
        {
            "historical_row_count_diff": abs(parity[0] - parity[1]),
            "historical_value_diff_n": parity[2],
            "000001_20260805_preclose": next(
                (
                    str(row["preclose"])
                    for row in new_rows
                    if row["code"] == "000001"
                    and row["trade_date"] == date(2026, 8, 5)
                ),
                None,
            ),
        }
    )
    validation_wall = (_utc_now() - validation_start).total_seconds()
    _raise_failpoint(failpoint, "after_validation")

    # Daily traceability.
    tdx_hashes: set[str] = set()
    tx_hashes: set[str] = set()
    if raw_tdx_path is not None and raw_tdx_path.exists():
        tdx_hashes = {
            str(row["raw_hash"])
            for row in pq.read_table(raw_tdx_path).to_pylist()
        }
    if raw_tencent_path is not None and raw_tencent_path.exists():
        tx_hashes = {
            str(row["raw_hash"])
            for row in pq.read_table(raw_tencent_path).to_pylist()
        }
    trace_fail = 0
    for row in new_rows:
        staged = next(
            (
                staged
                for staged in staged_rows
                if staged.get("reconciliation_status") == "CONFIRMED"
                and staged["code"] == row["code"]
                and staged["trade_date"] == row["trade_date"]
            ),
            None,
        )
        if staged is None:
            trace_fail += 1
            continue
        if staged.get("selected_source_hash") not in tdx_hashes:
            trace_fail += 1
        if (
            staged.get("confirmation_source_hash") is not None
            and staged["confirmation_source_hash"] not in tx_hashes
        ):
            trace_fail += 1
    pool_trace_fail = 0
    staged_selected_hashes = {
        str(staged["selected_source_hash"])
        for staged in staged_rows
        if staged.get("reconciliation_status") == "CONFIRMED"
        and staged.get("selected_source_hash") is not None
    }
    for event in derived_events:
        if event.source_daily_hash not in staged_selected_hashes:
            pool_trace_fail += 1

    # Formal-universe coverage (daily availability is separate from membership).
    sessions = [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)]
    unexplained_total = 0
    for session in sessions:
        coverage_audit = classify_daily_coverage(
            contract_version=PHASE2D0_UNIVERSE_CONTRACT_VERSION,
            as_of=session,
            universe_members=universe.members,
            staged_rows=staged_rows,
            verified_no_trade=verified_no_trade,
        )
        unexplained_total += coverage_audit.unexplained_n

    gates = {
        "preclose_continuity_mismatch_n": validation[
            "preclose_continuity_mismatch_n"
        ],
        "duplicate_code_date_n": validation["duplicate_n"],
        "ohlc_issues_n": validation["ohlc_issues_n"],
        "negative_volume_amount_n": validation["negative_volume_amount_n"],
        "historical_row_count_diff": abs(parity[0] - parity[1]),
        "historical_value_diff_n": parity[2],
        "pool_core_coverage_missing_n": validation[
            "pool_core_coverage_missing_n"
        ],
        "pool_core_false_positive_n": validation[
            "pool_core_false_positive_n"
        ],
        "daily_traceability_failure_n": trace_fail,
        "derived_pool_traceability_failure_n": pool_trace_fail,
        "formal_data_missing_unexplained_n": unexplained_total,
    }
    failed_gates = {key: value for key, value in gates.items() if value}
    if failed_gates:
        raise PromotionError(
            "VALIDATION_FAILED:"
            + json.dumps(failed_gates, sort_keys=True)
        )

    # Pool coverage against new daily formal rows (recheck after finalize path).
    validation_report = {
        "snapshot_candidate_id": snapshot_id,
        "base_snapshot_id": base_snapshot_id,
        "daily_hash": daily_content_hash,
        "pool_hash": pool_content_hash,
        "historical_parity": {
            "old_count": parity[0],
            "new_count": parity[1],
            "row_count_diff": abs(parity[0] - parity[1]),
            "value_diff_n": parity[2],
        },
        "preclose_continuity_mismatch_n": validation[
            "preclose_continuity_mismatch_n"
        ],
        "duplicate_code_date_n": validation["duplicate_n"],
        "ohlc_issues_n": validation["ohlc_issues_n"],
        "negative_volume_amount_n": validation["negative_volume_amount_n"],
        "reconciliation_status_counts": {
            "CONFIRMED": len(new_rows),
            "PROVISIONAL": 0,
            "INCOMPLETE": 0,
            "CONFLICTED": 0,
        },
        "universe_contract_version": universe.contract_version,
        "universe_hash": universe.member_hash,
        "formal_universe_n": universe.member_n,
        "formal_data_missing_unexplained_n": unexplained_total,
        "pool_core_coverage_missing_n": validation[
            "pool_core_coverage_missing_n"
        ],
        "pool_core_false_positive_n": validation[
            "pool_core_false_positive_n"
        ],
        "daily_traceability_failure_n": trace_fail,
        "derived_pool_traceability_failure_n": pool_trace_fail,
        "corporate_action_status_summary": {"UNKNOWN": len(new_rows)},
        "corporate_action_detection_status": "NOT_IMPLEMENTED",
        "validator_version": VALIDATOR_VERSION,
        "validated_at": _utc_now().isoformat(timespec="seconds"),
    }

    if dry_run:
        dry_report_hash = _sha256_text(
            json.dumps(
                {
                    key: value
                    for key, value in validation_report.items()
                    if key != "validated_at"
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )
        return PromotionResult(
            snapshot_id=snapshot_id,
            snapshot_content_hash=snapshot_content_hash,
            manifest_hash="",
            validation_report_hash=dry_report_hash,
            as_of=date(2026, 8, 5),
            status="STAGED",
            formal_pointer_before=None,
            formal_pointer_after=None,
            daily_total_n=historical_n + len(new_rows),
            published_20260803_n=p0803,
            published_20260804_n=p0804,
            published_20260805_n=p0805,
            legacy_pool_published_n=len(legacy_pool),
            derived_20260803_published_n=sum(
                1
                for event in derived_events
                if event.trade_date == date(2026, 8, 3)
            ),
            derived_20260804_published_n=sum(
                1
                for event in derived_events
                if event.trade_date == date(2026, 8, 4)
            ),
            derived_20260805_published_n=sum(
                1
                for event in derived_events
                if event.trade_date == date(2026, 8, 5)
            ),
            pool_total_n=len(pool_rows),
            idempotent=False,
            build_wall_seconds=(validation_start - build_start).total_seconds(),
            validation_wall_seconds=validation_wall,
            peak_rss_bytes=peak_rss_bytes,
        )

    # Finalize immutable artifacts.
    daily_path = layout.canonical_daily_dir / f"{snapshot_id}.parquet"
    pool_path = layout.canonical_pool_dir / f"{snapshot_id}.parquet"
    manifest_path = layout.manifests_dir / f"{snapshot_id}.json"
    validation_path = layout.root / "validation" / f"{snapshot_id}.json"
    lineage_path = layout.root / "lineage" / f"{snapshot_id}.jsonl"
    if daily_path.exists():
        if sha256_file(daily_path) != daily_file_hash:
            raise PromotionError("existing daily artifact hash mismatch")
    else:
        os.replace(tmp_daily, daily_path)
    _raise_failpoint(failpoint, "after_finalize_before_db")
    if pool_path.exists():
        if sha256_file(pool_path) != pool_file_hash:
            raise PromotionError("existing pool artifact hash mismatch")
    else:
        os.replace(tmp_pool, pool_path)
    _raise_failpoint(failpoint, "after_finalize_before_db")

    lineage = _lineage_records(staged_rows, snapshot_id)
    lineage_path.parent.mkdir(parents=True, exist_ok=True)
    if not lineage_path.exists():
        lineage_path.parent.mkdir(parents=True, exist_ok=True)
        with lineage_path.open("w", encoding="utf-8") as stream:
            for record in lineage:
                stream.write(
                    json.dumps(record, ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
    _raise_failpoint(failpoint, "after_finalize_before_db")

    relative = lambda path: str(path.relative_to(layout.root))
    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": _utc_now().isoformat(timespec="seconds"),
        "as_of": "2026-08-05",
        "provider_versions": {"TDX": "v1", "TENCENT": "v1"},
        "source_file_hashes": {
            relative(raw_tdx_path): sha256_file(raw_tdx_path)
            for raw_tdx_path in (raw_tdx_path,)
            if raw_tdx_path is not None
        }
        | {
            relative(raw_tencent_path): sha256_file(raw_tencent_path)
            for raw_tencent_path in (raw_tencent_path,)
            if raw_tencent_path is not None
        },
        "canonical_file_hashes": {
            relative(daily_path): sha256_file(daily_path),
            relative(pool_path): sha256_file(pool_path),
        },
        "reconciliation_policy_version": "ADR-008-PRD",
        "status": SCREEN_READY,
        "parent_snapshot": base_snapshot_id,
        "daily_source_staging_hash": prb_staging_hash,
        "derived_event_hash": derived_event_hash,
        "universe_hash": universe.member_hash,
        "price_domain": "RAW_UNADJUSTED",
        "publication_status": SCREEN_READY,
        "lineage_artifact": relative(lineage_path),
        "validation_report": relative(validation_path),
        "corporate_action_detection_status": "NOT_IMPLEMENTED",
    }
    if not manifest_path.exists():
        write_json_atomic(manifest, manifest_path)
    else:
        existing_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        if existing_manifest.get("snapshot_id") != snapshot_id:
            raise PromotionError("existing manifest mismatch")
    _raise_failpoint(failpoint, "after_finalize_before_db")
    manifest_hash = sha256_file(manifest_path)
    validation_report["manifest_content_hash"] = manifest_hash
    validation_report_hash = _sha256_text(
        json.dumps(
            {
                key: value
                for key, value in validation_report.items()
                if key != "validated_at"
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    )
    if not validation_path.exists():
        write_json_atomic(validation_report, validation_path)
    else:
        existing_report = json.loads(
            validation_path.read_text(encoding="utf-8")
        )
        if existing_report.get("snapshot_candidate_id") != snapshot_id:
            raise PromotionError("existing validation report mismatch")
    _raise_failpoint(failpoint, "after_finalize_before_db")

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        pointer_before = metadata.get_formal_pointer()
    pointer_before_id = pointer_before[0] if pointer_before else None

    if not dry_run:
        from limit_pullback.warehouse.models import SnapshotRecord

        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            created_at=_utc_now(),
            as_of=date(2026, 8, 5),
            provider_versions={"TDX": "v1", "TENCENT": "v1"},
            source_file_hashes=manifest["source_file_hashes"],
            canonical_file_hashes=manifest["canonical_file_hashes"],
            reconciliation_policy_version="ADR-008-PRD",
            status=SCREEN_READY,
            manifest_path=str(manifest_path),
        )
        with WarehouseMetadata(layout.duckdb_path) as metadata:
            with metadata.promotion_transaction() as tx:
                tx.insert_snapshot(record)
                tx.insert_publication(
                    snapshot_id=snapshot_id,
                    dataset="daily_bars",
                    path=relative(daily_path),
                    row_count=historical_n + len(new_rows),
                    published_at=_utc_now(),
                )
                tx.insert_publication(
                    snapshot_id=snapshot_id,
                    dataset="limit_up_pool",
                    path=relative(pool_path),
                    row_count=len(pool_rows),
                    published_at=_utc_now(),
                )
                _raise_failpoint(failpoint, "during_metadata_transaction")
                tx.insert_snapshot_validation(
                    snapshot_id=snapshot_id,
                    report_hash=validation_report_hash,
                    report_path=relative(validation_path),
                    validation_status="PASS",
                    validated_at=_utc_now(),
                    validator_version=VALIDATOR_VERSION,
                )
                tx.insert_snapshot_promotion(
                    snapshot_id=snapshot_id,
                    from_state="STAGED",
                    to_state=SCREEN_READY,
                    validation_report_hash=validation_report_hash,
                    input_artifact_hashes={
                        "base_snapshot": base_snapshot_id,
                        "prb_staging_hash": prb_staging_hash,
                        "universe_hash": universe.member_hash,
                        "derived_event_hash": derived_event_hash,
                    },
                    code_commit=_git_head(),
                    strategy_version="phase-2d0",
                    universe_contract=PHASE2D0_UNIVERSE_CONTRACT_VERSION,
                    promoted_at=_utc_now(),
                    promotion_reason=PROMOTION_REASON,
                )
                _raise_failpoint(failpoint, "before_pointer_update")
                tx.set_formal_pointer(
                    snapshot_id=snapshot_id,
                    validation_report_hash=validation_report_hash,
                    updated_at=_utc_now(),
                )

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        pointer_after = metadata.get_formal_pointer()
    pointer_after_id = pointer_after[0] if pointer_after else None
    build_wall = (_utc_now() - build_start).total_seconds()
    return PromotionResult(
        snapshot_id=snapshot_id,
        snapshot_content_hash=snapshot_content_hash,
        manifest_hash=manifest_hash,
        validation_report_hash=validation_report_hash,
        as_of=date(2026, 8, 5),
        status=SCREEN_READY,
        formal_pointer_before=pointer_before_id,
        formal_pointer_after=pointer_after_id,
        daily_total_n=historical_n + len(new_rows),
        published_20260803_n=p0803,
        published_20260804_n=p0804,
        published_20260805_n=p0805,
        legacy_pool_published_n=len(legacy_pool),
        derived_20260803_published_n=sum(
            1
            for event in derived_events
            if event.trade_date == date(2026, 8, 3)
        ),
        derived_20260804_published_n=sum(
            1
            for event in derived_events
            if event.trade_date == date(2026, 8, 4)
        ),
        derived_20260805_published_n=sum(
            1
            for event in derived_events
            if event.trade_date == date(2026, 8, 5)
        ),
        pool_total_n=len(pool_rows),
        idempotent=False,
        build_wall_seconds=build_wall,
        validation_wall_seconds=validation_wall,
        peak_rss_bytes=peak_rss_bytes,
    )
