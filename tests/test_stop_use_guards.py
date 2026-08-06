"""PR-A stop-use guards: formal consumers must fail closed on non-SCREEN_READY.

These tests pin the mandatory acceptance behavior for PROJECT_STABILIZATION
PR-A.  They intentionally never select an older SCREEN_READY snapshot when the
latest/default snapshot is unusable, and never delete/rewrite canonical bytes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.screen.canonical import load_canonical_metadata
from limit_pullback.screen.models import ScreenState
from limit_pullback.screen.runner import run_screen
from limit_pullback.trade_plan import build_trade_plan_output
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.models import (
    SCREEN_READY_STATUS,
    is_snapshot_formally_usable,
)
from limit_pullback.warehouse.parquet import sha256_file, write_json_atomic
from limit_pullback.warehouse.pipeline import bootstrap
from limit_pullback.warehouse.snapshot import (
    FormalPointerError,
    SnapshotUsabilityError,
    forward_preflight,
    require_state_snapshot_usable,
    snapshot_status_map,
)
from tests.test_screen import _build_warehouse, _chain_rows, _weekdays
from tests.warehouse_fakes import FakeProviderSet


AUDIT_REPORT_SHA256 = "2f535cd3537460c552564f2123f01be369f39d9ae897d095613e02d7dbceb0f0"
QUARANTINE_REASON = "PRECLOSE_CONTINUITY_FAILURE_20260804_20260805"


def _layout_with_current_snapshot(tmp_path) -> tuple[WarehouseLayout, str]:
    layout, _, snapshot_id = _build_warehouse(
        tmp_path,
        snapshot_status="CURRENT",
    )
    return layout, snapshot_id


def _write_state(layout: WarehouseLayout, *, snapshot_id: str, code: str = "603318") -> Path:
    path = layout.root / "screen" / "states" / f"{code}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state = ScreenState(
        code=code,
        last_processed_date=date(2026, 7, 31),
        signal_json="{}",
        setup_id=None,
        snapshot_id=snapshot_id,
        bars_prefix_hash="b" * 64,
        limit_pool_prefix_hash="p" * 64,
        strategy_commit="c" * 40,
        config_hash="d" * 64,
        reconciliation_policy_version="phase-2c2a-r1",
        processed_at=datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc),
    )
    write_json_atomic(state.model_dump(mode="json"), path)
    return path


def _set_pointer(layout: WarehouseLayout, snapshot_id: str) -> None:
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.set_formal_pointer(
            snapshot_id=snapshot_id,
            validation_report_hash="test",
        )


def test_current_snapshot_is_not_implicitly_usable():
    assert is_snapshot_formally_usable("CURRENT") is False
    assert is_snapshot_formally_usable("RESEARCH_READY") is False
    assert is_snapshot_formally_usable("QUARANTINED") is False
    assert is_snapshot_formally_usable(SCREEN_READY_STATUS) is True


def test_non_screen_ready_snapshot_rejected_by_screen(tmp_path):
    layout, snapshot_id = _layout_with_current_snapshot(tmp_path)
    with pytest.raises(SnapshotUsabilityError) as exc_info:
        run_screen(layout=layout, as_of=date(2026, 7, 31), snapshot_id=snapshot_id)
    assert exc_info.value.code == "SNAPSHOT_NOT_SCREEN_READY"
    assert exc_info.value.snapshot_id == snapshot_id
    assert exc_info.value.snapshot_status == "CURRENT"


def test_explicit_screen_ready_snapshot_can_be_read(tmp_path):
    layout, _, snapshot_id = _build_warehouse(tmp_path)
    snapshot, _, _ = load_canonical_metadata(layout, snapshot_id=snapshot_id)
    assert snapshot.snapshot_id == snapshot_id
    assert snapshot.status == SCREEN_READY_STATUS
    preflight = forward_preflight(layout, snapshot_id)
    assert preflight.snapshot_id == snapshot_id


def test_no_silent_fallback_to_previous_screen_ready(tmp_path):
    """Adversarial: latest CURRENT must fail even when older SCREEN_READY exists."""

    layout = WarehouseLayout(tmp_path / "data")
    dates = _weekdays(date(2026, 1, 5), 60)
    mid = dates[30]
    codes = ("603318", "002640")

    def market_rows(up_to_index):
        rows = []
        for code in codes:
            rows.extend(_chain_rows(code, dates[: up_to_index + 1]))
        return rows

    fake_old = FakeProviderSet(
        calendar=dates[:31],
        tushare_daily=market_rows(30),
        akshare_daily=market_rows(30),
        baostock_daily=market_rows(30),
    )
    old = bootstrap(
        layout=layout,
        start=dates[0],
        end=mid,
        codes=codes,
        provider_set=fake_old,
        today=mid,
        snapshot_status=SCREEN_READY_STATUS,
    )
    assert old.snapshot_id is not None

    fake_new = FakeProviderSet(
        calendar=dates,
        tushare_daily=market_rows(59),
        akshare_daily=market_rows(59),
        baostock_daily=market_rows(59),
    )
    new = bootstrap(
        layout=layout,
        start=dates[0],
        end=dates[-1],
        codes=codes,
        provider_set=fake_new,
        today=dates[-1],
        snapshot_status="CURRENT",
    )
    assert new.snapshot_id is not None
    assert new.snapshot_id != old.snapshot_id
    _set_pointer(layout, new.snapshot_id)

    with pytest.raises(FormalPointerError) as exc_info:
        run_screen(layout=layout, as_of=dates[-1])
    assert exc_info.value.code == "FORMAL_POINTER_INVALID"
    assert exc_info.value.snapshot_id == new.snapshot_id


def test_bad_snapshot_screen_fails_before_strategy_evaluation(tmp_path, monkeypatch):
    layout, snapshot_id = _layout_with_current_snapshot(tmp_path)
    _set_pointer(layout, snapshot_id)
    calls: list[dict] = []

    def fake_screen_code(**kwargs):
        calls.append(kwargs)
        return [], None

    monkeypatch.setattr("limit_pullback.screen.runner.screen_code", fake_screen_code)
    with pytest.raises(FormalPointerError):
        run_screen(layout=layout, as_of=date(2026, 7, 31))
    assert calls == []


def test_bad_snapshot_screen_writes_no_state(tmp_path):
    layout, snapshot_id = _layout_with_current_snapshot(tmp_path)
    _set_pointer(layout, snapshot_id)
    states_dir = layout.root / "screen" / "states"
    with pytest.raises(FormalPointerError):
        run_screen(layout=layout, as_of=date(2026, 7, 31))
    assert not states_dir.exists() or list(states_dir.glob("*.json")) == []


def test_state_bound_to_unusable_snapshot_rejected(tmp_path):
    layout, snapshot_id = _layout_with_current_snapshot(tmp_path)
    _write_state(layout, snapshot_id=snapshot_id)
    status_map = snapshot_status_map(layout)
    with pytest.raises(SnapshotUsabilityError) as exc_info:
        require_state_snapshot_usable(
            status_map,
            snapshot_id=snapshot_id,
        )
    assert exc_info.value.code == "STATE_BOUND_TO_UNUSABLE_SNAPSHOT"
    assert exc_info.value.snapshot_id == snapshot_id
    assert exc_info.value.snapshot_status == "CURRENT"


def test_tradeplan_rejects_unusable_state_snapshot(tmp_path, project_root):
    layout, dates, safe_snapshot_id = _build_warehouse(tmp_path)
    # Publish a second, unusable CURRENT snapshot in the SAME warehouse.
    new_date = dates[-1] + timedelta(days=3)
    while new_date.weekday() >= 5:
        new_date += timedelta(days=1)
    extended: list[dict] = []
    for code in ("603318", "002640"):
        extended.extend(_chain_rows(code, dates))
        extended.extend(_chain_rows(code, [new_date]))
    fake = FakeProviderSet(
        calendar=[*dates, new_date],
        tushare_daily=extended,
        akshare_daily=extended,
        baostock_daily=extended,
    )
    bad = bootstrap(
        layout=layout,
        start=dates[0],
        end=new_date,
        codes=("603318", "002640"),
        provider_set=fake,
        today=new_date,
        snapshot_status="CURRENT",
    )
    assert bad.snapshot_id is not None
    bad_snapshot_id = bad.snapshot_id
    # Contaminated state references the unusable snapshot, not the safe one.
    _write_state(layout, snapshot_id=bad_snapshot_id)
    config = load_strategy_config(project_root / "config" / "strategy.yaml")
    with pytest.raises(SnapshotUsabilityError) as exc_info:
        build_trade_plan_output(
            layout=layout,
            as_of=dates[-1],
            snapshot_id=safe_snapshot_id,
            config=config,
            config_hash="d" * 64,
        )
    assert exc_info.value.code == "STATE_BOUND_TO_UNUSABLE_SNAPSHOT"
    assert exc_info.value.snapshot_id == bad_snapshot_id


def test_forward_preflight_rejects_unusable_snapshot(tmp_path):
    layout, snapshot_id = _layout_with_current_snapshot(tmp_path)
    with pytest.raises(SnapshotUsabilityError) as exc_info:
        forward_preflight(layout, snapshot_id)
    assert exc_info.value.code == "SNAPSHOT_NOT_SCREEN_READY"
    with pytest.raises(SnapshotUsabilityError) as exc_info:
        forward_preflight(layout)
    assert exc_info.value.code == "LATEST_SNAPSHOT_NOT_SCREEN_READY"


def test_research_snapshot_read_requires_forensic_opt_in(tmp_path):
    from limit_pullback.outcome import _load_snapshot

    layout, snapshot_id = _layout_with_current_snapshot(tmp_path)
    with pytest.raises(SnapshotUsabilityError) as exc_info:
        _load_snapshot(layout, snapshot_id)
    assert exc_info.value.code == "SNAPSHOT_NOT_SCREEN_READY"
    loaded = _load_snapshot(
        layout,
        snapshot_id,
        allow_unusable_snapshot_for_forensics=True,
    )
    assert loaded.snapshot_id == snapshot_id


def test_quarantine_preserves_canonical_bytes(tmp_path):
    layout, snapshot_id = _layout_with_current_snapshot(tmp_path)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(snapshot_id)
    assert snapshot is not None
    daily_rel = next(
        key for key in snapshot.canonical_file_hashes
        if key.endswith("/daily_bars/" + snapshot_id + ".parquet")
    )
    pool_rel = next(
        key for key in snapshot.canonical_file_hashes
        if key.endswith("/limit_up_pool/" + snapshot_id + ".parquet")
    )
    manifest_path = layout.manifests_dir / f"{snapshot_id}.json"
    daily_before = sha256_file(layout.root / daily_rel)
    pool_before = sha256_file(layout.root / pool_rel)
    manifest_before = sha256_file(manifest_path)

    with WarehouseMetadata(layout.duckdb_path) as metadata:
        status_from, status_to = metadata.set_snapshot_status(
            snapshot_id=snapshot_id,
            status="QUARANTINED",
            reason=QUARANTINE_REASON,
            audit_report_sha256=AUDIT_REPORT_SHA256,
        )
    assert (status_from, status_to) == ("CURRENT", "QUARANTINED")
    assert sha256_file(layout.root / daily_rel) == daily_before
    assert sha256_file(layout.root / pool_rel) == pool_before
    assert sha256_file(manifest_path) == manifest_before
    assert not is_snapshot_formally_usable("QUARANTINED")

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(snapshot_id)
        gov = metadata._connection.execute(
            """
            SELECT snapshot_id, status_from, status_to, reason, audit_report_sha256
            FROM snapshot_governance_records
            WHERE snapshot_id = ?
            """,
            [snapshot_id],
        ).fetchall()
    assert stored is not None and stored.status == "QUARANTINED"
    assert gov == [
        (
            snapshot_id,
            "CURRENT",
            "QUARANTINED",
            QUARANTINE_REASON,
            AUDIT_REPORT_SHA256,
        )
    ]
