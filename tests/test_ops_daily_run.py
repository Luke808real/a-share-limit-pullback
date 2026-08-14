"""Offline tests for the ops daily-run orchestration (fail-closed chain)."""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from limit_pullback.models.enums import DataQuality, ExecutionLabel, SetupStage
from limit_pullback.models.trade_plan import TradePlan, TradePlanOutput
from limit_pullback.ops import _render_watchlist_md, cmd_daily_run


def _fake_plan(codes: tuple[str, ...]) -> TradePlanOutput:
    plans: list[TradePlan] = []
    for code in codes:
        plans.append(
            TradePlan(
                code=code,
                plan_date=date(2026, 8, 13),
                for_trade_date=date(2026, 8, 14),
                setup_stage=SetupStage.B1_READY,
                execution_label=ExecutionLabel.B1_PREP,
                setup_quality_score=Decimal("80"),
                data_quality=DataQuality.OK,
                is_actionable=True,
                snapshot_id="snap-test",
                strategy_commit="cafebabe",
                config_hash="c0ffee",
                preferred_entry=Decimal("10.0"),
                buy_zone_low=Decimal("9.8"),
                buy_zone_high=Decimal("10.2"),
                trigger_price=Decimal("11.0"),
                invalid_price=Decimal("9.5"),
            )
        )
    return TradePlanOutput(
        plan_date=date(2026, 8, 13),
        for_trade_date=date(2026, 8, 14),
        snapshot_id="snap-test",
        strategy_commit="cafebabe",
        config_hash="c0ffee",
        universe=1,
        watch_count=len(plans),
        b1_prep_count=len(plans),
        b1_ready_count=0,
        b2_ready_count=0,
        b2_confirmed_count=0,
        actionable_count=len(plans),
        entry_room_none_reject_count=0,
        invalid_reject_count=0,
        price_above_buy_zone_reject_count=0,
        plans=tuple(plans),
        top_candidates=tuple(plans[:2]),
    )


def test_render_watchlist_no_trade_day() -> None:
    plan = _fake_plan(())
    md = _render_watchlist_md(plan, None, date(2026, 8, 13))
    assert "NO_TRADE_DAY" in md
    assert "重点候选" not in md


def test_render_watchlist_with_candidates() -> None:
    plan = _fake_plan(("600468", "000659"))
    brief = SimpleNamespace(
        symbol_news=[
            SimpleNamespace(code="600468", items=[1]),
            SimpleNamespace(code="000659", items=[]),
        ],
        content_hash="deadbeef",
    )
    md = _render_watchlist_md(plan, brief, date(2026, 8, 13))
    assert "600468" in md
    assert "B1_PREP" in md
    assert "deadbeef" in md
    assert "NO_TRADE_DAY" not in md


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    """Mock every external dependency of cmd_daily_run."""
    import limit_pullback.ops as ops_mod

    layout = SimpleNamespace()
    layout.root = Path(tmp_path)
    layout.duckdb_path = Path(tmp_path) / "warehouse.duckdb"

    class FakeMetadata:
        def __init__(self, path, read_only=True):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_formal_pointer(self):
            return "snap-new"

        def get_formal_state_pointer(self):
            return "stategen-new"

    monkeypatch.setattr(ops_mod, "_layout", lambda: layout)
    monkeypatch.setattr(ops_mod, "WarehouseMetadata", FakeMetadata)

    def fake_daily(args):
        cache_root = layout.root / "tmp" / f"canonical-catchup-{args.date:%Y-%m-%d}"
        cache_root.mkdir(parents=True, exist_ok=True)
        (cache_root / "daily-summary.json").write_text(
            json.dumps(
                {
                    "snapshot": {"id": "snap-new", "status": "SCREEN_READY"},
                    "generation": {"id": "stategen-new", "status": "ACTIVE"},
                    "sentinel_checks": [{"code": "603980", "match": True}],
                }
            )
        )
        return 0

    monkeypatch.setattr(ops_mod, "cmd_daily", fake_daily)
    return layout


def _run(layout, *, codes=("600468",)) -> int:
    args = SimpleNamespace(date=date(2026, 8, 13), window_days=3)
    return cmd_daily_run(argparse.Namespace(**vars(args)))


def test_daily_run_success_chain(run_env, monkeypatch) -> None:
    import limit_pullback.news_brief as news_mod
    import limit_pullback.trade_plan as tp_mod

    monkeypatch.setattr(
        tp_mod, "build_trade_plan_output", lambda **kwargs: _fake_plan(("600468",))
    )
    brief = SimpleNamespace(
        symbols_matched=1,
        content_hash="deadbeef",
        symbol_news=[],
        model_dump_json=lambda **kwargs: "{}",
    )
    monkeypatch.setattr(news_mod, "build_news_brief", lambda **kwargs: brief)
    monkeypatch.setattr(news_mod, "render_markdown", lambda b: "markdown")

    rc = _run(run_env)
    assert rc == 0
    run_dir = run_env.root / "tmp" / "daily-run-20260813"
    timing = json.loads((run_dir / "timing.json").read_text())
    assert timing["status"] == "OK"
    assert [s["name"] for s in timing["steps"]] == [
        "daily",
        "trade-plan",
        "news-brief",
        "watchlist",
        "reconcile",
    ]
    assert all(s["ok"] for s in timing["steps"])
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "brief.md").exists()
    assert (run_dir / "watchlist.md").exists()
    watch = (run_dir / "watchlist.md").read_text()
    assert "600468" in watch


def test_daily_run_fails_closed_on_daily_error(run_env, monkeypatch) -> None:
    import limit_pullback.ops as ops_mod

    def failing_daily(args):
        raise ValueError("STAGING_NOT_ELIGIBLE")

    monkeypatch.setattr(ops_mod, "cmd_daily", failing_daily)
    rc = _run(run_env)
    assert rc == 1
    run_dir = run_env.root / "tmp" / "daily-run-20260813"
    timing = json.loads((run_dir / "timing.json").read_text())
    assert timing["status"] == "FAILED"
    assert timing["completed"] == []
    assert not (run_dir / "plan.json").exists()


def test_daily_run_sentinel_failure_stops_chain(run_env, monkeypatch) -> None:
    import limit_pullback.ops as ops_mod

    def bad_sentinel_daily(args):
        cache_root = run_env.root / "tmp" / f"canonical-catchup-{args.date:%Y-%m-%d}"
        cache_root.mkdir(parents=True, exist_ok=True)
        (cache_root / "daily-summary.json").write_text(
            json.dumps(
                {
                    "snapshot": {"id": "snap-new", "status": "SCREEN_READY"},
                    "generation": {"id": "stategen-new", "status": "ACTIVE"},
                    "sentinel_checks": [{"code": "603980", "match": False}],
                }
            )
        )
        return 0

    monkeypatch.setattr(ops_mod, "cmd_daily", bad_sentinel_daily)
    rc = _run(run_env)
    assert rc == 1
    timing = json.loads(
        (run_env.root / "tmp" / "daily-run-20260813" / "timing.json").read_text()
    )
    assert timing["completed"] == []
    assert timing["steps"][0]["ok"] is False
