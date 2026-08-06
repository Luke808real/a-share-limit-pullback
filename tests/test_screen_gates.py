from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from limit_pullback.config import load_strategy_config
from limit_pullback.screen.runner import _pool_prefix_hash, run_screen
from limit_pullback.screen.state import state_path
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.pipeline import bootstrap
from tests.test_screen import (
    _build_warehouse,
    _chain_rows,
    _rows_of,
    _weekdays,
)
from tests.warehouse_fakes import FakeProviderSet


def test_new_anchor_not_repeated_on_continuation_days(tmp_path):
    layout, dates, snapshot_id = _build_warehouse(tmp_path)
    anchor_day = dates[30]  # index % 30 == 0 -> limit-up day with pool row
    first = run_screen(layout=layout, as_of=anchor_day, snapshot_id=snapshot_id)
    first_rows = _rows_of(first.output_path)
    anchor_rows = [
        row
        for row in first_rows.values()
        if row["trade_date"] == anchor_day.isoformat()
    ]
    assert anchor_rows
    assert all(row["setup_stage"] == "LIMIT_ANCHOR" for row in anchor_rows)

    continuation = run_screen(
        layout=layout, as_of=dates[31], snapshot_id=snapshot_id
    )
    continuation_rows = _rows_of(continuation.output_path)
    statuses = {
        row["trade_date"]: row["setup_stage"]
        for row in continuation_rows.values()
    }
    assert dates[31].isoformat() in statuses
    # No NEW_ANCHOR may repeat for an existing setup on the next day.
    assert "LIMIT_ANCHOR" not in statuses.values()
    run_json = json.loads(Path(continuation.output_path).read_text(encoding="utf-8"))
    assert run_json["status_counts"].get("NEW_ANCHOR", 0) == 0


def test_historical_as_of_ignores_future_revised_snapshot(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    dates = _weekdays(date(2026, 1, 5), 135)
    mid = dates[30]
    codes = ("603318", "002640", "600199")

    def market_rows(up_to_index, *, revised=False):
        rows = []
        for code in ("603318", "002640"):
            code_rows = _chain_rows(code, dates[: up_to_index + 1])
            if revised:
                for row in code_rows:
                    if row["trade_date"] == mid:
                        row["preclose"] = Decimal("20.00")
                        row["open"] = Decimal("22.00")
                        row["high"] = Decimal("22.10")
                        row["low"] = Decimal("21.90")
                        row["close"] = Decimal("22.00")
            rows.extend(code_rows)
        rows.extend(_chain_rows("600199", dates[:10]))
        return rows

    def pool_rows(up_to_index, *, revised=False):
        pool = []
        for code in ("603318", "002640"):
            for index, trade_date in enumerate(dates[: up_to_index + 1]):
                if index > 0 and index % 30 == 0:
                    limit_price = (
                        Decimal("22.00")
                        if revised and trade_date == mid
                        else Decimal("11.00")
                    )
                    pool.append(
                        {
                            "code": code,
                            "trade_date": trade_date,
                            "name": "测试公司",
                            "limit_price": limit_price,
                            "first_seal_time": None,
                            "last_seal_time": None,
                            "open_count": 0,
                            "consecutive_count": 1,
                            "turnover_rate": None,
                            "float_market_cap": None,
                            "total_market_cap": None,
                            "industry": "测试",
                        }
                    )
        return pool

    fake_s1 = FakeProviderSet(
        calendar=dates[:31],
        tushare_daily=market_rows(30),
        akshare_daily=market_rows(30),
        baostock_daily=market_rows(30),
        pool=pool_rows(30),
    )
    s1 = bootstrap(
        layout=layout,
        start=dates[0],
        end=mid,
        codes=codes,
        provider_set=fake_s1,
        today=mid,
        snapshot_status="SCREEN_READY",
    )
    assert s1.snapshot_id is not None

    old_run = run_screen(layout=layout, as_of=mid)
    old_hash = old_run.output_hash
    old_rows = _rows_of(old_run.output_path)
    old_anchor_price = old_rows[
        ("603318", mid.isoformat())
    ]["anchor_snapshot"]["anchor_price"]

    # Publish a second snapshot that revises the anchor-day row and adds a day.
    fake_s2 = FakeProviderSet(
        calendar=dates[:32],
        tushare_daily=market_rows(31, revised=True),
        akshare_daily=market_rows(31, revised=True),
        baostock_daily=market_rows(31, revised=True),
        pool=pool_rows(31, revised=True),
    )
    s2 = bootstrap(
        layout=layout,
        start=dates[0],
        end=dates[31],
        codes=codes,
        provider_set=fake_s2,
        today=dates[31],
        snapshot_status="SCREEN_READY",
    )
    assert s2.snapshot_id != s1.snapshot_id

    # as_of=mid must keep using the snapshot published at that frontier.
    historical = run_screen(layout=layout, as_of=mid)
    assert historical.output_hash == old_hash
    assert historical.snapshot_id == s1.snapshot_id
    historical_rows = _rows_of(historical.output_path)
    assert (
        historical_rows[("603318", mid.isoformat())]["anchor_snapshot"]["anchor_price"]
        == old_anchor_price
    )

    # as_of=dates[31] uses the revised snapshot.
    frontier = run_screen(layout=layout, as_of=dates[31])
    assert frontier.snapshot_id == s2.snapshot_id
    frontier_rows = _rows_of(frontier.output_path)
    assert (
        frontier_rows[("603318", mid.isoformat())]["anchor_snapshot"]["anchor_price"]
        != old_anchor_price
    )


def test_state_invalidated_on_pool_config_commit_changes(tmp_path):
    layout, dates, snapshot_id = _build_warehouse(tmp_path)
    mid = dates[40]
    run_screen(layout=layout, as_of=mid, snapshot_id=snapshot_id)
    state_file = state_path(layout.root, "603318")
    state = json.loads(state_file.read_text(encoding="utf-8"))

    # 1) Historical pool revision invalidates the state.
    broken_pool = state["limit_pool_prefix_hash"] + "-changed"
    state["limit_pool_prefix_hash"] = broken_pool
    state_file.write_text(json.dumps(state), encoding="utf-8")
    rerun = run_screen(layout=layout, as_of=dates[41], snapshot_id=snapshot_id)
    assert any("STATE_INVALIDATED:603318" in note for note in rerun.notes)

    # 2) Config hash change invalidates.
    run_screen(layout=layout, as_of=dates[41], snapshot_id=snapshot_id)
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["config_hash"] = "different-config"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    rerun = run_screen(layout=layout, as_of=dates[42], snapshot_id=snapshot_id)
    assert any("STATE_INVALIDATED:603318" in note for note in rerun.notes)

    # 3) Strategy commit change invalidates.
    run_screen(layout=layout, as_of=dates[42], snapshot_id=snapshot_id)
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["strategy_commit"] = "another-commit"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    rerun = run_screen(layout=layout, as_of=dates[43], snapshot_id=snapshot_id)
    assert any("STATE_INVALIDATED:603318" in note for note in rerun.notes)

    # 4) Matching state is kept: only the new trading day is processed.
    run_screen(layout=layout, as_of=dates[43], snapshot_id=snapshot_id)
    kept = run_screen(layout=layout, as_of=dates[44], snapshot_id=snapshot_id)
    assert not any("STATE_INVALIDATED:603318" in note for note in kept.notes)
    assert kept.rows_count == 2  # one new day for the two long-history codes


def test_future_pool_row_does_not_change_prefix_hash(tmp_path):
    layout, dates, snapshot_id = _build_warehouse(tmp_path)
    from limit_pullback.screen.canonical import load_canonical_market

    market = load_canonical_market(layout, snapshot_id=snapshot_id)
    up_to = dates[40]
    base_hash = _pool_prefix_hash(
        market.pool_records, market.pool_status, up_to
    )
    future_record = market.pool_records[0].model_copy(
        update={
            "trade_date": dates[-1] + timedelta(days=5),
            "code": "999999",
        }
    )
    assert (
        _pool_prefix_hash(
            [*market.pool_records, future_record], market.pool_status, up_to
        )
        == base_hash
    )


def test_pool_provisional_gate_formal_vs_debug(tmp_path):
    layout, dates, snapshot_id = _build_warehouse(tmp_path)
    formal = run_screen(
        layout=layout,
        as_of=dates[-1],
        start=dates[0],
        rebuild=True,
        snapshot_id=snapshot_id,
    )
    formal_rows = _rows_of(formal.output_path)
    anchor_rows = [
        row for row in formal_rows.values() if row["setup_stage"] == "LIMIT_ANCHOR"
    ]
    assert anchor_rows
    # Pool rows are published as CONFIRMED_SINGLE_SOURCE under the frozen
    # single-source policy, so formal mode may use them without suppression.
    assert all("LIMIT_POOL_PROVISIONAL" not in row["quality_flags"] for row in anchor_rows)
    late_anchor = next(
        row
        for row in formal_rows.values()
        if (
            row["setup_stage"] == "LIMIT_ANCHOR"
            and row["trade_date"] == dates[120].isoformat()
        )
    )
    assert late_anchor["data_quality"] in {"OK", "PARTIAL"}
    # CONFIRMED_SINGLE_SOURCE pool rows are formally usable under the frozen
    # single-source publication policy.
    assert formal.entry_candidate_count > 0
    assert all(
        "LIMIT_POOL_PROVISIONAL_BLOCKED_FORMAL" not in note
        for note in formal.notes
    )

    debug = run_screen(
        layout=layout,
        as_of=dates[-1],
        start=dates[0],
        rebuild=True,
        snapshot_id=snapshot_id,
        pool_debug=True,
    )
    debug_rows = _rows_of(debug.output_path)
    debug_anchors = [
        row
        for row in debug_rows.values()
        if row["setup_stage"] == "LIMIT_ANCHOR"
    ]
    assert all(
        "LIMIT_POOL_PROVISIONAL_WARNING" not in row["quality_flags"]
        for row in debug_anchors
    )
    late_debug = next(
        row
        for row in debug_rows.values()
        if (
            row["setup_stage"] == "LIMIT_ANCHOR"
            and row["trade_date"] == dates[120].isoformat()
        )
    )
    assert late_debug["data_quality"] in {"OK", "PARTIAL"}
    assert any("LIMIT_POOL_DEBUG_MODE" in note for note in debug.notes)

    from limit_pullback.screen.engine import pool_quality
    from limit_pullback.models.enums import DataQuality

    quality, flag = pool_quality("PROVISIONAL", pool_mode="formal")
    assert quality is DataQuality.UNUSABLE
    assert flag == "LIMIT_POOL_PROVISIONAL"
    quality, flag = pool_quality("PROVISIONAL", pool_mode="debug")
    assert quality is DataQuality.DEGRADED
    assert flag == "LIMIT_POOL_PROVISIONAL_WARNING"
    quality, flag = pool_quality("CONFIRMED_SINGLE_SOURCE", pool_mode="formal")
    assert quality is DataQuality.OK
    assert flag is None
    assert any("LIMIT_POOL_DEBUG_MODE" in note for note in debug.notes)


def test_cached_run_must_reverify_when_requested(tmp_path):
    layout, dates, snapshot_id = _build_warehouse(tmp_path)
    first = run_screen(
        layout=layout,
        as_of=dates[-1],
        start=dates[0],
        rebuild=True,
        snapshot_id=snapshot_id,
    )
    assert first.reused is False
    assert first.verify_replay_matched is None

    verified = run_screen(
        layout=layout,
        as_of=dates[-1],
        start=dates[0],
        rebuild=True,
        snapshot_id=snapshot_id,
        verify_replay=True,
    )
    assert verified.reused is False  # cache without verification is not reused
    assert verified.verify_replay_matched is True

    again = run_screen(
        layout=layout,
        as_of=dates[-1],
        start=dates[0],
        rebuild=True,
        snapshot_id=snapshot_id,
        verify_replay=True,
    )
    assert again.reused is True
    assert again.verify_replay_matched is True
