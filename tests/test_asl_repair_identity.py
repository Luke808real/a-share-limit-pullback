"""ASL repair provider identity + canonical provenance — targeted tests.

Proves the provider-bound identity contract of ``repair_daily_sessions``:

* ASL and TUSHARE with identical inputs resolve DIFFERENT run ids
  (provider-bound namespaces; a completed TUSHARE run can never satisfy an
  ASL repair and vice versa);
* the reuse path rejects a recorded provider that does not match the
  requested one (REPAIR_PROVIDER_IDENTITY_MISMATCH);
* unsupported provider names fail closed BEFORE any side effect;
* a foreign-provider source file under a repair run fails closed
  (REPAIR_RUN_FOREIGN_SOURCE_PROVIDER);
* the ASL corporate-action path still resolves CONFIRMED rows;
* legacy TUSHARE semantics (run id, selected_provider, notes) stay
  bit-for-bit unchanged.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.pipeline import (
    PipelineError,
    _run_id,
    bootstrap,
    repair_daily_sessions,
)
from limit_pullback.warehouse.snapshot import read_snapshot_daily
from tests.test_asl_repair_provider import (
    CALENDAR,
    CODES,
    D21,
    D22,
    D24,
    DAY,
    REPAIR_DATES,
    _asl_provider,
    _base_bootstrap,
    _build_asl_lake,
)
from tests.warehouse_fakes import FakeProviderSet, daily_row

POLICY = "phase-2c2a-r1"
LINEAGE = "july-2026-gap-v01"


def _layout(tmp_path) -> WarehouseLayout:
    return WarehouseLayout(tmp_path / "data")


def _legacy_run_id(base_snapshot_id: str, parent_run_id: str) -> str:
    return _run_id(
        "daily-session-repair",
        base_snapshot_id,
        parent_run_id,
        tuple(REPAIR_DATES),
        POLICY,
        LINEAGE,
    )


def _asl_run_id(base_snapshot_id: str, parent_run_id: str) -> str:
    return _run_id(
        "daily-session-repair-asl",
        base_snapshot_id,
        parent_run_id,
        tuple(REPAIR_DATES),
        POLICY,
        LINEAGE,
    )


# ---------- 1. provider-bound run identity ----------

def test_provider_bound_run_ids_differ(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)
    assert _asl_run_id(base_snapshot_id, parent_run_id) != _legacy_run_id(
        base_snapshot_id, parent_run_id
    )


# ---------- 2/3. cross-provider reuse cannot cross namespaces ----------

def test_completed_tushare_run_never_satisfies_asl_repair(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    tushare_fake = FakeProviderSet(
        calendar=CALENDAR,
        tushare_daily=[daily_row(c, d.isoformat()) for c in CODES for d in REPAIR_DATES],
        akshare_daily=[daily_row(c, d.isoformat()) for c in CODES for d in CALENDAR],
        baostock_daily=[daily_row(c, d.isoformat()) for c in CODES for d in CALENDAR],
        adj_factor=[
            {"code": c, "trade_date": d, "adj_factor": Decimal("1.00")}
            for c in CODES
            for d in CALENDAR
        ],
    )
    tushare_result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=tushare_fake,
        today=DAY,
        repair_lineage=LINEAGE,
    )
    assert tushare_result.reused is False
    assert tushare_result.run_id == _legacy_run_id(base_snapshot_id, parent_run_id)

    # ASL repair with the same inputs must be a NEW run, not a reuse of the
    # TUSHARE lineage.
    asl_provider = _asl_provider(tmp_path)
    asl_result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=asl_provider,
        today=DAY,
        repair_lineage=LINEAGE,
        provider_name="ASL",
    )
    assert asl_result.reused is False
    assert asl_result.run_id == _asl_run_id(base_snapshot_id, parent_run_id)
    assert asl_result.run_id != tushare_result.run_id
    assert asl_result.snapshot_id != tushare_result.snapshot_id


def test_completed_asl_run_never_satisfies_tushare_repair(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    asl_provider = _asl_provider(tmp_path)
    asl_result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=asl_provider,
        today=DAY,
        repair_lineage=LINEAGE,
        provider_name="ASL",
    )
    assert asl_result.reused is False

    tushare_fake = FakeProviderSet(
        calendar=CALENDAR,
        tushare_daily=[daily_row(c, d.isoformat()) for c in CODES for d in REPAIR_DATES],
        akshare_daily=[daily_row(c, d.isoformat()) for c in CODES for d in CALENDAR],
        baostock_daily=[daily_row(c, d.isoformat()) for c in CODES for d in CALENDAR],
        adj_factor=[
            {"code": c, "trade_date": d, "adj_factor": Decimal("1.00")}
            for c in CODES
            for d in CALENDAR
        ],
    )
    tushare_result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=tushare_fake,
        today=DAY,
        repair_lineage=LINEAGE,
    )
    assert tushare_result.reused is False
    assert tushare_result.run_id != asl_result.run_id
    assert tushare_result.snapshot_id != asl_result.snapshot_id


# ---------- 4. reuse provider consistency gate ----------

def test_reuse_rejects_recorded_provider_mismatch(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    asl_provider = _asl_provider(tmp_path)
    first = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=asl_provider,
        today=DAY,
        repair_lineage=LINEAGE,
        provider_name="ASL",
    )
    assert first.reused is False

    # Tamper the recorded provider in the completed run's config: the reuse
    # gate must reject the mismatch fail closed.
    run_id = first.run_id
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        run = metadata.get_ingest_run(run_id)
        config = json.loads(run.config_json or "{}")
        config["provider_name"] = "TUSHARE"
        metadata._connection.execute(
            "UPDATE ingest_runs SET config_json = ? WHERE run_id = ?",
            [json.dumps(config, sort_keys=True), run_id],
        )

    with pytest.raises(PipelineError) as excinfo:
        repair_daily_sessions(
            layout=layout,
            base_snapshot_id=base_snapshot_id,
            parent_run_id=parent_run_id,
            repair_dates=REPAIR_DATES,
            provider_set=asl_provider,
            today=DAY,
            repair_lineage=LINEAGE,
            provider_name="ASL",
        )
    assert excinfo.value.code == "REPAIR_PROVIDER_IDENTITY_MISMATCH"


# ---------- 5. unsupported provider fails before any side effect ----------

def test_unsupported_provider_zero_side_effects(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    asl_provider = _asl_provider(tmp_path)
    with pytest.raises(PipelineError) as excinfo:
        repair_daily_sessions(
            layout=layout,
            base_snapshot_id=base_snapshot_id,
            parent_run_id=parent_run_id,
            repair_dates=REPAIR_DATES,
            provider_set=asl_provider,
            today=DAY,
            repair_lineage=LINEAGE,
            provider_name="QQQ",
        )
    assert excinfo.value.code == "REPAIR_PROVIDER_UNSUPPORTED"
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        rows = metadata._connection.execute(
            "SELECT count(*) FROM ingest_runs WHERE kind = 'daily-session-repair'"
        ).fetchone()[0]
        assert rows == 0


# ---------- 6. ASL corporate-action path stays CONFIRMED ----------

def test_asl_ca_path_confirmed_with_asl_selected(tmp_path) -> None:
    from decimal import Decimal

    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    asl_root = tmp_path / "asl-lake"
    _build_asl_lake(asl_root)
    # rewrite the D22 bar of 600000 with a CA preclose divergence: ASL
    # preclose derives from D21 close (10.00); make D21 close 9.00 and
    # adj factor change 1.00 -> 1.10 on D22 so the CA branch fires.
    import pyarrow as pa
    import pyarrow.parquet as pq

    for day in CALENDAR:
        p = asl_root / "curated" / "daily_bars" / f"trade_date={day.isoformat()}" / "part-merged.parquet"
        rows = [dict(r) for r in pq.read_table(p).to_pylist()]
        if day == D21:
            for r in rows:
                r["close"] = 9.00
        pq.write_table(pa.Table.from_pylist(rows), p)
    adj_path = asl_root / "derived" / "adj_factors" / f"trade_date={D22.isoformat()}" / "part-0.parquet"
    adj_rows = [dict(r) for r in pq.read_table(adj_path).to_pylist()]
    for r in adj_rows:
        if r["symbol"] == "600000.SH":
            r["factor"] = 1.10
    pq.write_table(pa.Table.from_pylist(adj_rows), adj_path)

    from limit_pullback.warehouse.asl_repair_provider import AslRepairProviderSet

    provider = AslRepairProviderSet(asl_root, as_of=D24, repair_dates=REPAIR_DATES)
    result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=provider,
        today=DAY,
        repair_lineage=LINEAGE,
        provider_name="ASL",
    )
    assert result.reused is False
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        repaired = metadata.snapshot_by_id(result.snapshot_id)
        daily = read_snapshot_daily(layout, repaired)
        ca_rows = [
            r for r in daily
            if r["trade_date"] == D22 and r["code"] == "600000"
        ]
        assert len(ca_rows) == 1
        assert ca_rows[0]["reconciliation_status"] == "CONFIRMED"
        assert ca_rows[0]["selected_provider"] == "ASL"
        notes = metadata._connection.execute(
            "SELECT notes FROM reconciliation_results "
            "WHERE snapshot_id = ? AND code = '600000' AND trade_date = ?",
            [result.snapshot_id, D22],
        ).fetchall()
        assert any(
            "CORPORATE_ACTION_PRECLOSE_DIVERGENCE" in (n or "")
            for (n,) in notes
        )


# ---------- 7. foreign provider source under repair run fails closed ----------

def test_foreign_provider_source_fails_closed(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    # Pre-compute the ASL run id and plant a foreign (TUSHARE) source file
    # record under it BEFORE the repair runs, then run the ASL repair: the
    # source isolation gate must fail closed and never publish a snapshot.
    run_id = _asl_run_id(base_snapshot_id, parent_run_id)
    foreign_dir = layout.raw_dataset_dir("TUSHARE", "daily_bars")
    foreign_dir.mkdir(parents=True, exist_ok=True)
    foreign_path = foreign_dir / f"{run_id}-0001.parquet"
    import pyarrow as pa
    import pyarrow.parquet as pq
    from limit_pullback.warehouse.parquet import raw_daily_schema

    table = pa.Table.from_pylist(
        [
            {
                "provider": "TUSHARE",
                "provider_version": "x",
                "fetched_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
                "ingest_run_id": run_id,
                "source_unit": "yuan;shares;yuan",
                "normalized_unit": "yuan;shares;yuan",
                "row_hash": "f" * 64,
                "code": "600000",
                "trade_date": D22,
                "open": Decimal("10.00"), "high": Decimal("10.50"),
                "low": Decimal("9.80"), "close": Decimal("10.20"),
                "preclose": Decimal("10.00"), "volume": Decimal("100000"),
                "amount": Decimal("1020000.00"),
                "turnover_rate": None, "pct_change": Decimal("2.00"),
                "trade_status": True, "is_st": None,
            }
        ],
        schema=raw_daily_schema(),
    )
    pq.write_table(table, foreign_path)
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.insert_source_file(
            __import__("limit_pullback.warehouse.models", fromlist=["SourceFileRecord"]).SourceFileRecord(
                path=str(foreign_path),
                provider="TUSHARE",
                ingest_run_id=run_id,
                sha256="a" * 64,
                row_count=1,
                recorded_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        )

    asl_provider = _asl_provider(tmp_path)
    with pytest.raises(PipelineError) as excinfo:
        repair_daily_sessions(
            layout=layout,
            base_snapshot_id=base_snapshot_id,
            parent_run_id=parent_run_id,
            repair_dates=REPAIR_DATES,
            provider_set=asl_provider,
            today=DAY,
            repair_lineage=LINEAGE,
            provider_name="ASL",
        )
    assert excinfo.value.code == "REPAIR_RUN_FOREIGN_SOURCE_PROVIDER"
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        run = metadata.get_ingest_run(run_id)
        assert run is not None and run.status == "FAILED"
        assert "published_snapshot_id" not in json.loads(run.config_json or "{}")


# ---------- 8. legacy TUSHARE semantics unchanged ----------

def test_legacy_tushare_identity_and_notes_unchanged(tmp_path) -> None:
    layout = _layout(tmp_path)
    parent_run_id, base_snapshot_id = _base_bootstrap(layout)

    tushare_fake = FakeProviderSet(
        calendar=CALENDAR,
        tushare_daily=[daily_row(c, d.isoformat()) for c in CODES for d in REPAIR_DATES],
        akshare_daily=[daily_row(c, d.isoformat()) for c in CODES for d in CALENDAR],
        baostock_daily=[daily_row(c, d.isoformat()) for c in CODES for d in CALENDAR],
        adj_factor=[
            {"code": c, "trade_date": d, "adj_factor": Decimal("1.00")}
            for c in CODES
            for d in CALENDAR
        ],
    )
    result = repair_daily_sessions(
        layout=layout,
        base_snapshot_id=base_snapshot_id,
        parent_run_id=parent_run_id,
        repair_dates=REPAIR_DATES,
        provider_set=tushare_fake,
        today=DAY,
        repair_lineage=LINEAGE,
    )
    assert result.run_id == _legacy_run_id(base_snapshot_id, parent_run_id)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        repaired = metadata.snapshot_by_id(result.snapshot_id)
        daily = read_snapshot_daily(layout, repaired)
        for row in daily:
            if row["trade_date"] in REPAIR_DATES:
                assert row["selected_provider"] == "TUSHARE"
        rec = metadata._connection.execute(
            "SELECT notes, selected_provider FROM reconciliation_results "
            "WHERE snapshot_id = ? AND status = 'CONFIRMED' LIMIT 3",
            [result.snapshot_id],
        ).fetchall()
        assert rec
        for notes, selected in rec:
            assert selected == "TUSHARE"
            assert "TUSHARE_AKSHARE_AGREEMENT" in (notes or "")
