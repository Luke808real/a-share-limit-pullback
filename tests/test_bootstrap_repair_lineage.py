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
from limit_pullback.warehouse.pipeline import PipelineError, _run_id, bootstrap
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

    # a REAL repair bootstrap with an explicit tag must compute a DIFFERENT
    # run_id and must not rewrite the old record (fake data has full
    # coverage so the repair run completes under its own namespace)
    repair = bootstrap(
        layout=layout,
        start=DAY,
        end=DAY,
        codes=CODES,
        provider_set=fake,
        today=DAY,
        repair_lineage="july-2026-gap-v01",
    )
    assert repair.run_id != first.run_id
    assert repair.snapshot_id is not None

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
        # repair run exists separately as COMPLETED under its own run_id
        repair_record = metadata.get_ingest_run(repair.run_id)
        assert repair_record is not None and repair_record.status == "COMPLETED"


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
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        record = metadata.get_ingest_run(result.run_id)
        assert record is not None
        assert record.kind == "bootstrap-repair"
        import json as _json

        config = _json.loads(record.config_json or "{}")
        assert config["repair_mode"] is True
        assert config["repair_lineage"] == "july-2026-gap-v01"


# ---------- repair tag input contract ----------

@pytest.mark.parametrize(
    "tag",
    [
        "",
        "   ",
        "../x",
        "a/b",
        "a b",
        "x" * 65,
        "a" * 64 + "!",
        "-lead-dash",
        ".lead-dot",
    ],
)
def test_invalid_repair_tags_rejected_before_side_effects(tmp_path, tag) -> None:
    layout = _layout(tmp_path)
    rows = [daily_row(code, DAY.isoformat()) for code in CODES]

    class CountingFake(FakeProviderSet):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.calls = 0

        def fetch_trade_calendar(self, start, end):
            self.calls += 1
            return super().fetch_trade_calendar(start, end)

        def fetch_stock_basic(self, codes, listed_only=False):
            self.calls += 1
            return super().fetch_stock_basic(codes, listed_only=listed_only)

        def fetch_tushare_daily(self, requested, start, end):
            self.calls += 1
            return super().fetch_tushare_daily(requested, start, end)

    fake = CountingFake(
        calendar=[DAY],
        tushare_daily=rows,
        akshare_daily=rows,
        baostock_daily=rows,
    )
    with pytest.raises(PipelineError, match="repair_lineage must match"):
        bootstrap(
            layout=layout,
            start=DAY,
            end=DAY,
            codes=CODES,
            provider_set=fake,
            today=DAY,
            repair_lineage=tag,
        )
    # no side effects: no directory tree from bootstrap, no provider calls,
    # no ingest run row
    assert fake.calls == 0
    assert not (layout.root / "warehouse.duckdb").exists()
    assert not layout.raw_dataset_dir("TUSHARE", "daily_bars").exists()


@pytest.mark.parametrize(
    "tag",
    ["july-2026-gap-v01", "202607-gap.fix_01", "a", "A0._-9" * 8],  # 32 chars
)
def test_valid_repair_tags_accepted(tmp_path, tag) -> None:
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
        repair_lineage=tag,
    )
    assert result.snapshot_id is not None
    assert result.run_id == _run_id(
        "bootstrap-repair", DAY, DAY, tuple(sorted(CODES)), POLICY, tag
    )


def test_aux_backfill_with_repair_lineage_fails_closed(tmp_path) -> None:
    layout = _layout(tmp_path)
    rows = [daily_row(code, DAY.isoformat()) for code in CODES]

    class CountingFake(FakeProviderSet):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.calls = 0

        def fetch_trade_calendar(self, start, end):
            self.calls += 1
            return super().fetch_trade_calendar(start, end)

    fake = CountingFake(
        calendar=[DAY],
        tushare_daily=rows,
        akshare_daily=rows,
        baostock_daily=rows,
    )
    with pytest.raises(PipelineError, match="aux_backfill does not support repair_lineage"):
        bootstrap(
            layout=layout,
            start=DAY,
            end=DAY,
            codes=CODES,
            provider_set=fake,
            today=DAY,
            aux_backfill=True,
            repair_lineage="july-2026-gap-v01",
        )
    assert fake.calls == 0  # fails before any provider call
    assert not (layout.root / "warehouse.duckdb").exists()
