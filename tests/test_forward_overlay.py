from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq

from limit_pullback.forward_overlay import (
    CUTOFF,
    build_weekly_bars,
    run_overlay,
    weekly_metrics,
)


def _daily_row(code: str, trade_date: date, close: str) -> dict[str, object]:
    value = Decimal(close)
    return {
        "code": code,
        "trade_date": trade_date,
        "open": value,
        "high": value + Decimal("0.2"),
        "low": value - Decimal("0.1"),
        "close": value,
        "volume": Decimal("100000"),
        "amount": Decimal("1000000"),
        "reconciliation_status": "CONFIRMED",
    }


def _plan_row(code: str, label: str, rank: int, anchor_date: date) -> dict[str, object]:
    return {
        "code": code,
        "name": None,
        "execution_label": label,
        "setup_stage": label,
        "plan_date": CUTOFF,
        "anchor_date": anchor_date,
        "days_since_anchor": 2,
        "current_close": "10.00",
        "support_low": "9.50",
        "support_high": "9.80",
        "support_center": "9.65",
        "preferred_entry": "9.80",
        "buy_zone_low": "9.50",
        "buy_zone_high": "9.80",
        "trigger_price": "10.20",
        "invalid_price": "9.40",
        "s1_price": "11.00",
        "setup_quality_score": "70.00",
        "entry_quality_score": "60.00",
        "entry_room_state": "SUFFICIENT",
        "is_entry_candidate": True,
        "existing_rank": rank,
        "quality_flags": [],
        "reasons": [],
    }


def _write_inputs(
    tmp_path,
    *,
    include_future: bool = False,
):
    start = CUTOFF - timedelta(days=120)
    daily_rows = []
    for index in range(60):
        day = start + timedelta(days=index * 2)
        if day > CUTOFF:
            break
        daily_rows.append(_daily_row("000001", day, "10.00"))
        daily_rows.append(_daily_row("000002", day, "8.00"))
    if include_future:
        daily_rows.append(_daily_row("000001", date(2026, 8, 3), "10.50"))
        daily_rows.append(_daily_row("000002", date(2026, 8, 3), "8.50"))
    daily = (
        tmp_path / "daily_future.parquet"
        if include_future
        else tmp_path / "daily.parquet"
    )
    pq.write_table(pa.Table.from_pylist(daily_rows), daily)
    pool = tmp_path / "pool.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "code": "000001",
                    "trade_date": CUTOFF,
                    "industry": "测试行业",
                }
            ]
        ),
        pool,
    )
    plan = tmp_path / "plan"
    plan.mkdir(exist_ok=True)
    plan_rows = [
        _plan_row("000001", "B1_READY", 1, start + timedelta(days=4)),
        _plan_row("000002", "B2_READY", 2, start + timedelta(days=4)),
    ]
    pq.write_table(
        pa.Table.from_pylist(plan_rows),
        plan / "full_candidates.parquet",
    )
    (plan / "manifest.json").write_text(
        '{"payload_sha256":"test-source-hash"}',
        encoding="utf-8",
    )
    return daily, pool, plan


def test_weekly_aggregation_is_causal_and_position():
    rows = [
        _daily_row("000001", CUTOFF - timedelta(days=2), "10.00"),
        _daily_row("000001", CUTOFF, "11.00"),
        _daily_row("000001", date(2026, 8, 3), "99.00"),
    ]
    weekly = build_weekly_bars(rows, CUTOFF)
    assert weekly[-1]["close"] == Decimal("11.00")
    metrics = weekly_metrics(weekly)
    assert metrics["52w_low"] == Decimal("9.90")
    assert metrics["52w_high"] == Decimal("11.20")
    assert metrics["weekly_position_52w"] == (
        Decimal("11.00") - Decimal("9.90")
    ) / (Decimal("11.20") - Decimal("9.90"))


def test_overlay_causality_rank_and_missing_sector(tmp_path):
    daily, pool, plan = _write_inputs(tmp_path)
    first = run_overlay(
        plan_dir=plan,
        output_dir=tmp_path / "out",
        daily_path=daily,
        pool_path=pool,
        source_plan_hash="test-source-hash",
    )
    rows = first["overlay_rows"]
    assert len(rows) == 2
    by_code = {row["code"]: row for row in rows}
    assert by_code["000001"]["original_rank"] == 1
    assert by_code["000002"]["original_rank"] == 2
    assert by_code["000001"]["is_entry_candidate"] is True
    assert by_code["000002"]["is_entry_candidate"] is True
    assert by_code["000002"]["sector_context"] == "UNKNOWN"

    future_daily, _, _ = _write_inputs(tmp_path, include_future=True)
    second = run_overlay(
        plan_dir=plan,
        output_dir=tmp_path / "out2",
        daily_path=future_daily,
        pool_path=pool,
        source_plan_hash="test-source-hash",
    )
    assert first["payload_hash"] == second["payload_hash"]
