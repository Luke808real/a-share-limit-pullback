"""NONTRADING STRATEGY OBSERVATION CONTRACT — canonical view + coverage.

Generic synthetic case (no real-symbol special-casing): a CONFIRMED canonical
row with trade_status=false must remain a provenance fact but must never be
emitted as a strategy-usable bar, and coverage must classify it
VERIFIED_NO_TRADE only with verified evidence (else DATA_MISSING_UNEXPLAINED).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from limit_pullback.coverage import (
    DATA_MISSING_UNEXPLAINED,
    classify_daily_coverage,
)
from limit_pullback.screen.canonical import (
    iter_canonical_code_bars,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.models import SnapshotRecord
from limit_pullback.warehouse.parquet import canonical_daily_schema

CODE = "603318"
D0 = date(2026, 8, 10)
D1 = date(2026, 8, 11)


def _row(code, day, *, trade_status, volume, close="10.0", open_="10.0",
         high="10.5", low="9.9", preclose="9.9", amount="100000"):
    return {
        "code": code,
        "trade_date": day,
        "open": Decimal(open_),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "preclose": Decimal(preclose),
        "volume": Decimal(volume),
        "amount": Decimal(amount),
        "turnover_rate": None,
        "pct_change": None,
        "trade_status": trade_status,
        "is_st": None,
        "selected_provider": "ASL",
        "reconciliation_status": "CONFIRMED",
        "source_row_hash": "hash",
        "dataset_snapshot_id": "snap-test",
    }


def _build_snapshot(tmp_path: Path) -> tuple[WarehouseLayout, object]:
    layout = WarehouseLayout(tmp_path / "data")
    layout.ensure_dirs()
    snap_id = "snap-nontrading-test"
    rows = [
        _row(CODE, D0, trade_status=True, volume=1000000),
        _row(CODE, D1, trade_status=False, volume=0),
    ]
    table = pa.Table.from_pylist(rows, schema=canonical_daily_schema())
    daily_path = layout.canonical_daily_dir / f"{snap_id}.parquet"
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, daily_path)
    record = SnapshotRecord(
        snapshot_id=snap_id,
        created_at=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
        as_of=D1,
        provider_versions={"ASL": "synthetic"},
        source_file_hashes={},
        canonical_file_hashes={
            f"canonical/daily_bars/{snap_id}.parquet": "synthetic",
        },
        reconciliation_policy_version="VFLASH_ASL_PHASE1A_V1",
        status="SCREEN_READY",
        manifest_path=None,
    )
    from limit_pullback.warehouse.metadata import WarehouseMetadata

    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.insert_snapshot(record)
        metadata.set_snapshot_status(
            snapshot_id=snap_id, status="SCREEN_READY",
            reason="NONTRADING_TEST",
        )
        metadata.set_formal_pointer(snapshot_id=snap_id)
    return layout, record


def test_nontrading_fact_retained_in_canonical_artifact(tmp_path):
    """The canonical parquet keeps the suspension placeholder row (fact)."""
    layout, snapshot = _build_snapshot(tmp_path)
    daily_path = layout.canonical_daily_dir / f"{snapshot.snapshot_id}.parquet"
    table = pq.read_table(daily_path)
    assert table.num_rows == 2
    statuses = table.column("trade_status").to_pylist()
    assert statuses == [True, False]
    dates = table.column("trade_date").to_pylist()
    assert dates == [D0, D1]


def test_nontrading_fact_not_emitted_as_strategy_bar(tmp_path):
    """trade_status=false CONFIRMED row must not reach strategy bars."""
    layout, snapshot = _build_snapshot(tmp_path)
    bars_by_code = dict(iter_canonical_code_bars(
        layout, snapshot, codes=(CODE,), as_of=D1
    ))
    bars = bars_by_code.get(CODE, ())
    assert len(bars) == 1
    assert bars[0].trade_date == D0
    assert bars[0].trade_status is True


def test_nontrading_with_evidence_verified_no_trade(tmp_path):
    """trade_status=false + verified evidence -> VERIFIED_NO_TRADE."""
    audit = classify_daily_coverage(
        contract_version="PHASE2D0_UNIVERSE_V1",
        as_of=D1,
        universe_members=[CODE],
        staged_rows=[_row(CODE, D1, trade_status=False, volume=0)],
        verified_no_trade=[(CODE, D1)],
    )
    assert audit.traded_n == 0
    assert audit.verified_no_trade_n == 1
    assert audit.unexplained_n == 0


def test_nontrading_without_evidence_fails_closed(tmp_path):
    """trade_status=false without evidence -> DATA_MISSING_UNEXPLAINED."""
    audit = classify_daily_coverage(
        contract_version="PHASE2D0_UNIVERSE_V1",
        as_of=D1,
        universe_members=[CODE],
        staged_rows=[_row(CODE, D1, trade_status=False, volume=0)],
        verified_no_trade=[],
    )
    assert audit.traded_n == 0
    assert audit.verified_no_trade_n == 0
    assert audit.unexplained_n == 1


def test_normal_trading_bar_control(tmp_path):
    """trade_status=true CONFIRMED bar keeps old behavior."""
    layout, snapshot = _build_snapshot(tmp_path)
    bars_by_code = dict(iter_canonical_code_bars(
        layout, snapshot, codes=(CODE,), as_of=D1
    ))
    bars = bars_by_code.get(CODE, ())
    assert [b.trade_date for b in bars] == [D0]
    assert bars[0].volume == Decimal("1000000")
    audit = classify_daily_coverage(
        contract_version="PHASE2D0_UNIVERSE_V1",
        as_of=D0,
        universe_members=[CODE],
        staged_rows=[_row(CODE, D0, trade_status=True, volume=1000000)],
        verified_no_trade=[],
    )
    assert audit.traded_n == 1
    assert audit.unexplained_n == 0
