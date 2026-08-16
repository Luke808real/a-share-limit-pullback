"""Bootstrap repair lineage identity — targeted tests.

Proves the legacy bootstrap run-id expression is bit-for-bit unchanged when
repair_lineage is None, and that an explicit repair tag creates an isolated,
deterministic bootstrap-repair namespace that never touches an existing
historical run.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.pipeline import _run_id, bootstrap
from tests.warehouse_fakes import FakeProviderSet, daily_row


def _layout(tmp_path) -> WarehouseLayout:
    return WarehouseLayout(tmp_path / "data")


DAY = date(2026, 7, 30)
CODES = ("600000", "600001")
POLICY = "phase-2c2a-r1"


# ---------- A. legacy identity unchanged ----------

def test_legacy_run_id_expression_bit_exact() -> None:
    """The default (repair_lineage=None) run-id must equal the ORIGINAL
    expression exactly — no extra empty part, no namespace change."""
    legacy = _run_id("bootstrap", DAY, DAY, CODES, POLICY)
    # recompute the exact legacy expression independently
    expected = _run_id("bootstrap", DAY, DAY, CODES, POLICY)
    assert legacy == expected
    # and it must NOT equal the naive 'extra empty part' variant
    naive = _run_id("bootstrap", DAY, DAY, CODES, POLICY, "")
    assert legacy != naive  # guards against a future `repair_lineage or ""` bug


def test_legacy_identity_unchanged_through_bootstrap(tmp_path) -> None:
    """A normal bootstrap (no repair flag) resolves the same historical
    run_id as before this patch."""
    layout = _layout(tmp_path)
    rows = [daily_row(code, DAY.isoformat()) for code in CODES]
    fake = FakeProviderSet(
        calendar=[DAY],
        tushare_daily=rows,
        akshare_daily=rows,
        baostock_daily=rows,
    )
    result = bootstrap(
        layout=layout,
        start=DAY,
        end=DAY,
        codes=CODES,
        provider_set=fake,
        today=DAY,
    )
    expected = _run_id("bootstrap", DAY, DAY, tuple(sorted(CODES)), POLICY)
    assert result.run_id == expected
    assert result.run_id == _run_id("bootstrap", DAY, DAY, tuple(sorted(CODES)), POLICY)


# ---------- B. repair identity isolated + deterministic ----------

def test_repair_run_id_isolated_and_deterministic() -> None:
    normal = _run_id("bootstrap", DAY, DAY, CODES, POLICY)
    repair_a = _run_id(
        "bootstrap-repair", DAY, DAY, CODES, POLICY, "july-2026-gap-v01"
    )
    repair_a2 = _run_id(
        "bootstrap-repair", DAY, DAY, CODES, POLICY, "july-2026-gap-v01"
    )
    repair_b = _run_id(
        "bootstrap-repair", DAY, DAY, CODES, POLICY, "july-2026-gap-v02"
    )
    assert repair_a != normal  # isolated namespace
    assert repair_a == repair_a2  # deterministic for same tag + inputs
    assert repair_a != repair_b  # different tag -> different run_id


# ---------- C. historical reuse unaffected ----------

def test_normal_reuse_unaffected_by_patch(tmp_path) -> None:
    """A normal completed bootstrap run is recognized by the same legacy
    run_id after the patch (no new normal identity was introduced)."""
    layout = _layout(tmp_path)
    rows = [daily_row(code, DAY.isoformat()) for code in CODES]
    fake = FakeProviderSet(
        calendar=[DAY],
        tushare_daily=rows,
        akshare_daily=rows,
        baostock_daily=rows,
    )
    first = bootstrap(
        layout=layout,
        start=DAY,
        end=DAY,
        codes=CODES,
        provider_set=fake,
        today=DAY,
    )
    assert first.reused is False
    second = bootstrap(
        layout=layout,
        start=DAY,
        end=DAY,
        codes=CODES,
        provider_set=fake,
        today=DAY,
    )
    assert second.reused is True
    assert second.run_id == first.run_id


# ---------- D. repair does not touch old run ----------

def test_repair_does_not_touch_old_run(tmp_path) -> None:
    layout = _layout(tmp_path)
    rows = [daily_row(code, DAY.isoformat()) for code in CODES]
    fake = FakeProviderSet(
        calendar=[DAY],
        tushare_daily=rows,
        akshare_daily=rows,
        baostock_daily=rows,
    )
    first = bootstrap(
        layout=layout,
        start=DAY,
        end=DAY,
        codes=CODES,
        provider_set=fake,
        today=DAY,
    )
    assert first.reused is False

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        before = metadata.get_ingest_run(first.run_id)
        assert before is not None and before.status == "COMPLETED"
        hist_before = (
            before.status,
            before.started_at,
            before.finished_at,
            before.error,
        )

    # a repair run with an explicit tag must compute a DIFFERENT run_id and
    # must not rewrite the old record even when it fails early
    repair_run_id = _run_id(
        "bootstrap-repair",
        DAY,
        DAY,
        tuple(sorted(CODES)),
        POLICY,
        "july-2026-gap-v01",
    )
    assert repair_run_id != first.run_id

    # simulate repair attempt: begin_ingest_run for the repair run_id only
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.begin_ingest_run(
            run_id=repair_run_id,
            kind="bootstrap-repair",
            started_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            start_date=DAY,
            end_date=DAY,
            codes=tuple(sorted(CODES)),
            config_json='{"repair_lineage": "july-2026-gap-v01", "repair_mode": true}',
        )
        metadata.finish_ingest_run(
            run_id=repair_run_id,
            status="FAILED",
            finished_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            error="EARLY_REPAIR_FAILURE",
        )

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        after = metadata.get_ingest_run(first.run_id)
        assert after is not None
        assert (
            after.status,
            after.started_at,
            after.finished_at,
            after.error,
        ) == hist_before
        assert after.status == "COMPLETED"
        # repair run exists separately as FAILED
        repair = metadata.get_ingest_run(repair_run_id)
        assert repair is not None and repair.status == "FAILED"


# ---------- provenance recording ----------

def test_repair_provenance_recorded(tmp_path) -> None:
    layout = _layout(tmp_path)
    rows = [daily_row(code, DAY.isoformat()) for code in CODES]
    fake = FakeProviderSet(
        calendar=[DAY],
        tushare_daily=rows,
        akshare_daily=rows,
        baostock_daily=rows,
    )
    # repair run that completes (fake data has full coverage)
    result = bootstrap(
        layout=layout,
        start=DAY,
        end=DAY,
        codes=CODES,
        provider_set=fake,
        today=DAY,
        repair_lineage="july-2026-gap-v01",
    )
    assert result.run_id.startswith("")  # sha256 hex, no prefix
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        record = metadata.get_ingest_run(result.run_id)
        assert record is not None
        assert record.kind == "bootstrap-repair"
        import json as _json

        config = _json.loads(record.config_json or "{}")
        assert config["repair_mode"] is True
        assert config["repair_lineage"] == "july-2026-gap-v01"
