"""PR-E resume: corrected coverage classifier and session-by-session proof."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.coverage import (
    CONFIRMED_TRADED_BAR,
    DATA_MISSING_UNEXPLAINED,
    STATE_DATA_MISSING_UNEXPLAINED,
    STATE_MISSING_CONFIRMED_BAR_PROCESSING,
    VERIFIED_NO_TRADE,
    classify_daily_coverage,
    state_is_covered_through,
)
from limit_pullback.screen.generation import (
    StateGenerationError,
    build_state_generation,
)
from limit_pullback.universe import (
    Phase2d0Universe,
    phase2d0_universe_from_snapshot,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import sha256_file
from tests.test_screen import _build_warehouse


def _staged_row(code, day, *, close, status="CONFIRMED"):
    return {
        "code": code,
        "trade_date": day,
        "close": close,
        "reconciliation_status": status,
    }


def test_provisional_static_price_is_not_confirmed_traded_bar():
    day = date(2026, 8, 5)
    audit = classify_daily_coverage(
        contract_version="PHASE2D0_UNIVERSE_V1",
        as_of=day,
        universe_members=["000838"],
        staged_rows=[
            _staged_row("000838", day, close=2.5, status="PROVISIONAL")
        ],
        verified_no_trade=[("000838", day)],
    )
    assert audit.traded_n == 0
    assert audit.verified_no_trade_n == 1
    assert audit.unexplained_n == 0


def test_verified_no_trade_with_static_price_classified_correctly():
    day = date(2026, 8, 5)
    audit = classify_daily_coverage(
        contract_version="PHASE2D0_UNIVERSE_V1",
        as_of=day,
        universe_members=["603221"],
        staged_rows=[
            _staged_row("603221", day, close=22.54, status="PROVISIONAL")
        ],
        verified_no_trade=[("603221", day)],
    )
    assert audit.traded_n == 0
    assert audit.verified_no_trade_n == 1
    assert audit.ready is True


def test_confirmed_positive_trade_bar_classified_traded():
    day = date(2026, 8, 5)
    audit = classify_daily_coverage(
        contract_version="PHASE2D0_UNIVERSE_V1",
        as_of=day,
        universe_members=["600000"],
        staged_rows=[
            _staged_row("600000", day, close=11.25, status="CONFIRMED")
        ],
    )
    assert audit.traded == (("600000", day),)
    assert audit.ready is True


def test_unexplained_missing_not_verified_no_trade():
    day = date(2026, 8, 5)
    audit = classify_daily_coverage(
        contract_version="PHASE2D0_UNIVERSE_V1",
        as_of=day,
        universe_members=["600000"],
        staged_rows=[],
    )
    assert audit.unexplained_n == 1
    assert audit.ready is False


def test_last_processed_date_means_last_actual_bar():
    as_of = date(2026, 8, 5)
    status, through, _ = state_is_covered_through(
        last_processed_date=date(2026, 7, 31),
        as_of=as_of,
        session_calendar=[date(2026, 8, 3), date(2026, 8, 4), as_of],
        confirmed_traded_sessions=[],
        verified_no_trade_sessions=[
            ("000838", date(2026, 8, 3)),
            ("000838", date(2026, 8, 4)),
            ("000838", as_of),
        ],
        code="000838",
    )
    assert status == "STATE_COVERED_THROUGH_AS_OF"
    assert through == as_of


def test_verified_no_trade_advances_coverage_not_last_processed():
    status, through, _ = state_is_covered_through(
        last_processed_date=date(2026, 7, 31),
        as_of=date(2026, 8, 5),
        session_calendar=[
            date(2026, 8, 3),
            date(2026, 8, 4),
            date(2026, 8, 5),
        ],
        confirmed_traded_sessions=[],
        verified_no_trade_sessions=[
            ("603221", date(2026, 8, 3)),
            ("603221", date(2026, 8, 4)),
            ("603221", date(2026, 8, 5)),
        ],
        code="603221",
    )
    assert status == "STATE_COVERED_THROUGH_AS_OF"
    assert through == date(2026, 8, 5)


def test_multiple_no_trade_sessions_coverage():
    sessions = [
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
    ]
    status, through, _ = state_is_covered_through(
        last_processed_date=date(2026, 7, 31),
        as_of=date(2026, 8, 5),
        session_calendar=sessions,
        confirmed_traded_sessions=[],
        verified_no_trade_sessions=[("000838", day) for day in sessions],
        code="000838",
    )
    assert status == "STATE_COVERED_THROUGH_AS_OF"
    assert through == sessions[-1]


def test_confirmed_bar_after_last_processed_fails_verification():
    status, through, reasons = state_is_covered_through(
        last_processed_date=date(2026, 7, 31),
        as_of=date(2026, 8, 5),
        session_calendar=[
            date(2026, 8, 3),
            date(2026, 8, 4),
            date(2026, 8, 5),
        ],
        confirmed_traded_sessions=[("600000", date(2026, 8, 4))],
        verified_no_trade_sessions=[],
        code="600000",
    )
    assert status == STATE_MISSING_CONFIRMED_BAR_PROCESSING
    assert through == date(2026, 7, 31)
    assert any("CONFIRMED_BAR_UNPROCESSED" in reason for reason in reasons)


def test_unexplained_missing_fails_coverage():
    status, _, reasons = state_is_covered_through(
        last_processed_date=date(2026, 7, 31),
        as_of=date(2026, 8, 5),
        session_calendar=[
            date(2026, 8, 3),
            date(2026, 8, 4),
            date(2026, 8, 5),
        ],
        confirmed_traded_sessions=[],
        verified_no_trade_sessions=[],
        code="600000",
    )
    assert status == STATE_DATA_MISSING_UNEXPLAINED
    assert any("UNEXPLAINED_SESSION" in reason for reason in reasons)


def _env(tmp_path):
    layout, dates, sid = _build_warehouse(tmp_path)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(sid)
    config = load_strategy_config(
        Path(__file__).resolve().parents[1] / "config" / "strategy.yaml"
    )
    members = tuple(sorted(("603318", "002640", "600199")))
    universe = Phase2d0Universe(
        contract_version="PHASE2D0_UNIVERSE_V1",
        strategy_version="phase-2d0",
        exchange_allowlist=("SH", "SZ"),
        board_allowlist=("MAIN",),
        as_of=dates[-1],
        members=members,
        member_hash=hashlib.sha256(
            "|".join(members).encode("utf-8")
        ).hexdigest(),
    )
    return layout, snapshot, universe, config, dates


def _build(layout, snapshot, universe, config, dates, *, verified=(),
           calendar=(), as_of=None, build_root=None):
    build_root = build_root or (layout.root / "tmp" / "pr-e" / "cov")
    return build_state_generation(
        layout,
        snapshot_id=snapshot.snapshot_id,
        universe=universe,
        config_path=Path(__file__).resolve().parents[1]
        / "config"
        / "strategy.yaml",
        as_of=as_of or dates[-1],
        start=dates[0],
        rebuild=True,
        build_root=build_root,
        dry_run=True,
        verified_no_trade=verified,
        session_calendar=calendar,
    )


def test_generation_3189_processed_plus_2_no_trade_is_complete():
    # Synthetic analog: 600199's bars end at index 9 and every later session is
    # verified no-trade; 603318/002640 process through as_of.
    tmp = __import__("tempfile").mkdtemp()
    layout, snapshot, universe, config, dates = _env(Path(tmp))
    calendar = dates[10:]
    verified = [
        ("600199", day)
        for day in calendar
    ]
    result = _build(
        layout,
        snapshot,
        universe,
        config,
        dates,
        verified=verified,
        calendar=calendar,
    )
    manifest = json.loads(
        (layout.root / "tmp" / "pr-e" / "cov" / "generation.json").read_text(
            encoding="utf-8"
        )
    )
    assert result.state_n == 3
    assert manifest["state_coverage_through_as_of_n"] == 3
    assert manifest["state_uncovered_n"] == 0
    assert manifest["verified_no_trade_covered_n"] == 1


def test_no_synthetic_bar_for_verified_no_trade():
    tmp = __import__("tempfile").mkdtemp()
    layout, snapshot, universe, config, dates = _env(Path(tmp))
    calendar = dates[10:]
    result = _build(
        layout,
        snapshot,
        universe,
        config,
        dates,
        verified=[("600199", day) for day in calendar],
        calendar=calendar,
    )
    import pyarrow.parquet as pq

    coverage = pq.read_table(
        layout.root / "tmp" / "pr-e" / "cov" / "state-coverage.parquet"
    ).to_pylist()
    row = next(row for row in coverage if row["code"] == "600199")
    assert row["state_last_processed_date"] < row["generation_as_of"]
    assert row["latest_confirmed_traded_bar_date"] == row[
        "state_last_processed_date"
    ]
    assert row["verified_no_trade_session_n"] == len(calendar)
    assert row["coverage_through"] == row["generation_as_of"]
    assert row["coverage_status"] == "STATE_COVERED_THROUGH_AS_OF"


def test_unexplained_missing_fails_generation():
    tmp = __import__("tempfile").mkdtemp()
    layout, snapshot, universe, config, dates = _env(Path(tmp))
    calendar = dates[41:]
    with pytest.raises(StateGenerationError) as exc_info:
        _build(
            layout,
            snapshot,
            universe,
            config,
            dates,
            verified=[],
            calendar=calendar,
        )
    assert "STATE_VERIFICATION_FAILED" in str(exc_info.value)


def test_coverage_root_deterministic():
    tmp = __import__("tempfile").mkdtemp()
    layout, snapshot, universe, config, dates = _env(Path(tmp))
    calendar = dates[41:]
    verified = [("600199", day) for day in calendar]
    first = _build(
        layout,
        snapshot,
        universe,
        config,
        dates,
        verified=verified,
        calendar=calendar,
        build_root=layout.root / "tmp" / "pr-e" / "cov1",
    )
    second = _build(
        layout,
        snapshot,
        universe,
        config,
        dates,
        verified=verified,
        calendar=calendar,
        build_root=layout.root / "tmp" / "pr-e" / "cov2",
    )
    m1 = json.loads(
        (layout.root / "tmp" / "pr-e" / "cov1" / "generation.json").read_text(
            encoding="utf-8"
        )
    )
    m2 = json.loads(
        (layout.root / "tmp" / "pr-e" / "cov2" / "generation.json").read_text(
            encoding="utf-8"
        )
    )
    assert m1["state_coverage_root_hash"] == m2["state_coverage_root_hash"]
    assert first.generation_id == second.generation_id


def test_prd_validation_correction_does_not_mutate_snapshot(tmp_path):
    layout, _, sid = _build_warehouse(tmp_path)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        snapshot = metadata.snapshot_by_id(sid)
    daily_path = (
        layout.canonical_dir / "daily_bars" / f"{snapshot.snapshot_id}.parquet"
    )
    pool_path = (
        layout.canonical_dir
        / "limit_up_pool"
        / f"{snapshot.snapshot_id}.parquet"
    )
    daily_before = sha256_file(daily_path)
    pool_before = sha256_file(pool_path)
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.insert_snapshot_validation_correction(
            record_id="corr-test",
            snapshot_id=snapshot.snapshot_id,
            original_validation_hash="orig",
            correction_type="COVERAGE_CLASSIFICATION",
            old_summary={"n": 10},
            corrected_summary={"n": 9},
            snapshot_bytes_affected=False,
            publication_eligibility_changed=False,
            reason="STATIC_OR_PROVISIONAL_ROW_MISCLASSIFIED_AS_TRADED",
            created_at=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )
    assert sha256_file(daily_path) == daily_before
    assert sha256_file(pool_path) == pool_before
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        rows = metadata._connection.execute(
            """
            SELECT snapshot_bytes_affected, publication_eligibility_changed
            FROM snapshot_validation_correction_records
            WHERE record_id = 'corr-test'
            """
        ).fetchall()
    assert rows == [(False, False)]
