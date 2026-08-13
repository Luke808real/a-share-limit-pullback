"""REF-R7 runtime common tests: shared per-day seam and parity probe."""

from __future__ import annotations

import ast
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from limit_pullback.runtime import evaluate_day
from limit_pullback.runtime.common import evaluate_day as common_evaluate_day
from limit_pullback.runtime.daily import run_screen
from limit_pullback.runtime.replay import replay_stock

ROOT = Path(__file__).resolve().parents[1]
ISOLATED_DATA = ROOT / "data" / "warehouse.duckdb"


def test_runtime_reexports_are_identity():
    assert evaluate_day is common_evaluate_day
    from limit_pullback.replay import replay_stock as source_replay_stock
    from limit_pullback.screen.runner import run_screen as source_run_screen

    assert replay_stock is source_replay_stock
    assert run_screen is source_run_screen


def test_runtime_common_import_boundary():
    """runtime/common depends only on state + models; no data/warehouse/screen."""

    forbidden = (
        "limit_pullback.data",
        "limit_pullback.warehouse",
        "limit_pullback.screen",
        "limit_pullback.providers",
        "limit_pullback.selection",
    )
    tree = ast.parse(
        (ROOT / "src" / "limit_pullback" / "runtime" / "common.py").read_text(
            encoding="utf-8"
        )
    )
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    hits = {
        name
        for name in names
        if name.startswith("limit_pullback")
        and any(name == root or name.startswith(root + ".") for root in forbidden)
    }
    assert not hits


@pytest.mark.skipif(
    not ISOLATED_DATA.exists(),
    reason="frozen snapshot data dir not present in this checkout",
)
def test_per_day_parity_between_replay_and_screen_modes():
    """Same facts through both orchestration modes give identical signals."""

    from limit_pullback.config import load_strategy_config
    from limit_pullback.data import SnapshotDataAdapter
    from limit_pullback.models.market import DailyBar
    from limit_pullback.strategy.math import calculate_indicators
    from limit_pullback.warehouse.layout import WarehouseLayout

    config = load_strategy_config(ROOT / "config" / "strategy.yaml")
    adapter = SnapshotDataAdapter(
        WarehouseLayout(ROOT / "data"),
        snapshot_id="snap-2026-07-31-b5f84004de8a",
    )
    canonical = adapter.get_daily(
        "000001",
        date(2026, 5, 1),
        date(2026, 7, 31),
    )
    bars = tuple(
        DailyBar(
            trade_date=bar.trade_date,
            code=bar.code,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            preclose=bar.preclose,
            volume=bar.volume,
            amount=bar.amount,
            turnover_rate=bar.turnover_rate,
            pct_change=bar.pct_change,
            trade_status=bar.trade_status,
            is_st=bar.is_st,
            source="CANONICAL_PARITY",
            fetched_at=datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
        for bar in canonical
    )
    full_indicators = calculate_indicators(bars, config.indicators)

    previous: object | None = None
    previous_recompute: object | None = None
    for index, bar in enumerate(bars):
        day = bar.trade_date
        from limit_pullback.strategy.indicators import SequencePrefixView

        prefix = SequencePrefixView(bars, 0, index + 1)
        precomputed = evaluate_day(
            bars=prefix,
            as_of=day,
            config=config,
            generated_at=datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc),
            limit_pool=(),
            previous_signal=previous,
            full_indicators=full_indicators,
            indicator_end_index=index + 1,
        )
        recomputed = evaluate_day(
            bars=prefix,
            as_of=day,
            config=config,
            generated_at=datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc),
            limit_pool=(),
            previous_signal=previous_recompute,
            full_indicators=None,
            indicator_end_index=None,
        )
        assert precomputed == recomputed, f"parity broken on {day}"
        previous = precomputed
        previous_recompute = recomputed
