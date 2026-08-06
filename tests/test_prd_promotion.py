"""PR-D unit tests: lifecycle, formal pointer, promotion, fault injection."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.derived_limit_event import (
    build_derived_limit_events,
    derived_event_content_hash,
)
from limit_pullback.universe import phase2d0_universe_from_snapshot
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import write_rows_atomic
from limit_pullback.warehouse.promotion import (
    PromotionError,
    PromotionFailpointError,
    promote_snapshot,
)
from limit_pullback.warehouse.snapshot import FormalPointerError
from limit_pullback.warehouse.staging import staged_candidate_content_hash
from tests.test_screen import _build_warehouse

SESSIONS = [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)]


def _raw_schema():
    return pa.schema(
        [
            pa.field("code", pa.string()),
            pa.field("trade_date", pa.date32()),
            pa.field("raw_hash", pa.string()),
        ]
    )


def _staged_rows(seed_closes):
    rows = []
    for code in ("603318", "002640"):
        previous = Decimal(str(seed_closes[code]))
        for index, session in enumerate(SESSIONS):
            if code == "002640" and index == 2:
                ticks = (
                    previous * Decimal("1.10") / Decimal("0.01")
                ).quantize(Decimal("1"))
                close = (ticks * Decimal("0.01")).quantize(Decimal("0.01"))
            else:
                close = (
                    previous + Decimal("0.50")
                    if index == 0
                    else previous + Decimal("0.20")
                )
            rows.append(
                {
                    "code": code,
                    "trade_date": session,
                    "open": close,
                    "high": close + Decimal("0.01"),
                    "low": close - Decimal("0.01"),
                    "close": close,
                    "preclose": previous,
                    "volume": Decimal("1000000"),
                    "amount": Decimal("11000000"),
                    "pct_change": (
                        (close - previous) / previous * Decimal("100")
                    ),
                    "selected_provider": "TDX",
                    "confirmation_provider": "TENCENT",
                    "selected_source_hash": f"tdx-{code}-{session.isoformat()}",
                    "confirmation_source_hash": f"tx-{code}-{session.isoformat()}",
                    "reconciliation_status": "CONFIRMED",
                    "ingest_run_id": "test-prd",
                    "corporate_action_status": "UNKNOWN",
                }
            )
            previous = close
    return rows


def _seed_closes(layout, snapshot) -> dict:
    from limit_pullback.warehouse.staging import load_seed_previous_closes

    return load_seed_previous_closes(layout, snapshot)


def _raw_artifacts(layout, staged_rows):
    import pyarrow.parquet as pq

    tdx_rows = [
        {
            "code": row["code"],
            "trade_date": row["trade_date"],
            "raw_hash": row["selected_source_hash"],
        }
        for row in staged_rows
    ]
    tx_rows = [
        {
            "code": row["code"],
            "trade_date": row["trade_date"],
            "raw_hash": row["confirmation_source_hash"],
        }
        for row in staged_rows
    ]
    tdx_path = layout.root / "tmp" / "raw_tdx.parquet"
    tx_path = layout.root / "tmp" / "raw_tencent.parquet"
    write_rows_atomic(tdx_rows, _raw_schema(), tdx_path)
    write_rows_atomic(tx_rows, _raw_schema(), tx_path)
    return tdx_path, tx_path


def _promote_inputs(tmp_path, layout, snapshot, config):
    seed = _seed_closes(layout, snapshot)
    staged = _staged_rows(seed)
    events = build_derived_limit_events(
        [
            {
                "code": row["code"],
                "trade_date": row["trade_date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "preclose": row["preclose"],
                "source_daily_hash": row["selected_source_hash"],
            }
            for row in staged
        ],
        source_id="test-prd",
        config=config,
        universe_members=set(phase2d0_universe_from_snapshot(layout, snapshot).members),
    )
    universe = phase2d0_universe_from_snapshot(layout, snapshot)
    tdx_path, tx_path = _raw_artifacts(layout, staged)
    verified = [
        ("603318", SESSIONS[0]),
        ("002640", SESSIONS[1]),
    ]
    for session in SESSIONS:
        verified.append(("600199", session))
    return {
        "base_snapshot_id": snapshot.snapshot_id,
        "staged_rows": staged,
        "prb_staging_hash": staged_candidate_content_hash(staged),
        "universe": universe,
        "derived_events": events,
        "derived_event_hash": derived_event_content_hash(events),
        "config": config,
        "raw_tdx_path": tdx_path,
        "raw_tencent_path": tx_path,
        "verified_no_trade": tuple(verified),
    }


@pytest.fixture
def promotion_env(tmp_path):
    layout, _, sid = _build_warehouse(tmp_path)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(sid)
    config = load_strategy_config(
        Path(__file__).resolve().parents[1] / "config" / "strategy.yaml"
    )
    return layout, snapshot, config


def _pointer(layout):
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        return metadata.get_formal_pointer()


def _snapshot_status(layout, snapshot_id):
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(snapshot_id)
    return snapshot.status if snapshot else None


def test_staged_snapshot_not_formally_visible(promotion_env, tmp_path):
    layout, snapshot, config = promotion_env
    kwargs = _promote_inputs(tmp_path, layout, snapshot, config)
    result = promote_snapshot(layout, **kwargs, dry_run=True)
    assert _snapshot_status(layout, result.snapshot_id) is None
    assert _pointer(layout) == (snapshot.snapshot_id, "test")


def test_validated_snapshot_not_formally_visible(promotion_env, tmp_path):
    layout, snapshot, config = promotion_env
    kwargs = _promote_inputs(tmp_path, layout, snapshot, config)
    kwargs["staged_rows"][-1]["preclose"] = kwargs["staged_rows"][0]["preclose"]
    kwargs["prb_staging_hash"] = staged_candidate_content_hash(
        kwargs["staged_rows"]
    )
    with pytest.raises(PromotionError) as exc_info:
        promote_snapshot(layout, **kwargs)
    assert "VALIDATION_FAILED" in str(exc_info.value)
    assert _pointer(layout) == (snapshot.snapshot_id, "test")


def test_only_screen_ready_snapshot_formally_visible(promotion_env):
    layout, snapshot, _config = promotion_env
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.set_snapshot_status(
            snapshot_id=snapshot.snapshot_id,
            status="CURRENT",
            reason="test demote",
        )
    from limit_pullback.screen.canonical import load_canonical_metadata

    with pytest.raises(FormalPointerError) as exc_info:
        load_canonical_metadata(layout)
    assert exc_info.value.code == "FORMAL_POINTER_INVALID"


def test_formal_pointer_has_no_backward_scan_fallback(promotion_env):
    layout, snapshot, _config = promotion_env
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.set_snapshot_status(
            snapshot_id=snapshot.snapshot_id,
            status="CURRENT",
            reason="test demote",
        )
    from limit_pullback.screen.canonical import load_canonical_metadata

    with pytest.raises(FormalPointerError):
        load_canonical_metadata(layout)
    # The pointer still references the unusable snapshot; nothing older is used.
    assert _pointer(layout)[0] == snapshot.snapshot_id


def test_quarantined_snapshot_cannot_promote(promotion_env, tmp_path):
    layout, snapshot, config = promotion_env
    kwargs = _promote_inputs(tmp_path, layout, snapshot, config)
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.set_snapshot_status(
            snapshot_id=snapshot.snapshot_id,
            status="QUARANTINED",
            reason="test quarantine",
        )
    with pytest.raises(PromotionError) as exc_info:
        promote_snapshot(layout, **kwargs)
    assert "QUARANTINED_SNAPSHOT_CANNOT_PROMOTE" in str(exc_info.value)


def test_validation_failure_prevents_promotion(promotion_env, tmp_path):
    layout, snapshot, config = promotion_env
    kwargs = _promote_inputs(tmp_path, layout, snapshot, config)
    kwargs["staged_rows"][-1]["preclose"] = Decimal("1.00")
    kwargs["prb_staging_hash"] = staged_candidate_content_hash(
        kwargs["staged_rows"]
    )
    with pytest.raises(PromotionError):
        promote_snapshot(layout, **kwargs)
    assert _pointer(layout) == (snapshot.snapshot_id, "test")


def test_promotion_transaction_all_or_nothing(promotion_env, tmp_path):
    layout, snapshot, config = promotion_env
    kwargs = _promote_inputs(tmp_path, layout, snapshot, config)
    dry = promote_snapshot(layout, **kwargs, dry_run=True)
    with pytest.raises(PromotionFailpointError):
        promote_snapshot(layout, **kwargs, failpoint="during_metadata_transaction")
    assert _pointer(layout) == (snapshot.snapshot_id, "test")
    assert _snapshot_status(layout, dry.snapshot_id) is None
    # Recovery: same inputs promote successfully afterwards.
    result = promote_snapshot(layout, **kwargs)
    assert result.status == "SCREEN_READY"
    assert _pointer(layout)[0] == result.snapshot_id


def test_screen_ready_snapshot_is_immutable(promotion_env, tmp_path):
    layout, snapshot, config = promotion_env
    kwargs = _promote_inputs(tmp_path, layout, snapshot, config)
    result = promote_snapshot(layout, **kwargs)
    from limit_pullback.warehouse.parquet import sha256_file

    daily_before = sha256_file(
        layout.canonical_daily_dir / f"{result.snapshot_id}.parquet"
    )
    pool_before = sha256_file(
        layout.canonical_pool_dir / f"{result.snapshot_id}.parquet"
    )
    manifest_before = sha256_file(
        layout.manifests_dir / f"{result.snapshot_id}.json"
    )
    again = promote_snapshot(layout, **kwargs)
    assert again.idempotent is True
    assert again.snapshot_id == result.snapshot_id
    assert sha256_file(
        layout.canonical_daily_dir / f"{result.snapshot_id}.parquet"
    ) == daily_before
    assert sha256_file(
        layout.canonical_pool_dir / f"{result.snapshot_id}.parquet"
    ) == pool_before
    assert sha256_file(
        layout.manifests_dir / f"{result.snapshot_id}.json"
    ) == manifest_before


def test_pool_legacy_rows_preserved(promotion_env, tmp_path):
    layout, snapshot, config = promotion_env
    kwargs = _promote_inputs(tmp_path, layout, snapshot, config)
    result = promote_snapshot(layout, **kwargs)
    import pyarrow.parquet as pq

    pool = pq.read_table(
        layout.canonical_pool_dir / f"{result.snapshot_id}.parquet"
    ).to_pylist()
    legacy = [
        row
        for row in pool
        if row["trade_date"] <= snapshot.as_of
    ]
    import pyarrow.parquet as _pq

    base_pool = _pq.read_table(
        layout.canonical_pool_dir / f"{snapshot.snapshot_id}.parquet"
    ).to_pylist()
    assert len(legacy) == len(base_pool)
    assert all(
        row["selected_provider"] != "CANONICAL_DERIVED"
        for row in legacy
    )


def test_new_derived_rows_remain_price_only(promotion_env, tmp_path):
    layout, snapshot, config = promotion_env
    kwargs = _promote_inputs(tmp_path, layout, snapshot, config)
    result = promote_snapshot(layout, **kwargs)
    import pyarrow.parquet as pq

    pool = pq.read_table(
        layout.canonical_pool_dir / f"{result.snapshot_id}.parquet"
    ).to_pylist()
    derived = [
        row for row in pool if row["trade_date"] >= date(2026, 8, 3)
    ]
    assert derived
    assert all(
        row["first_seal_time"] is None
        and row["last_seal_time"] is None
        and row["open_count"] is None
        and row["consecutive_count"] is None
        for row in derived
    )


FAULT_POINTS = (
    "after_daily_write",
    "after_pool_write",
    "after_manifest_write",
    "after_validation",
    "after_finalize_before_db",
    "during_metadata_transaction",
    "before_pointer_update",
)


@pytest.mark.parametrize("failpoint", FAULT_POINTS)
def test_crash_fault_injection_pointer_unchanged(
    promotion_env, tmp_path, failpoint
):
    layout, snapshot, config = promotion_env
    kwargs = _promote_inputs(tmp_path, layout, snapshot, config)
    with pytest.raises(PromotionFailpointError):
        promote_snapshot(layout, **kwargs, failpoint=failpoint)
    assert _pointer(layout) == (snapshot.snapshot_id, "test")
