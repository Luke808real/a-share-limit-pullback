from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from limit_pullback.execution_reality import (
    FILL_DAY_STOP_AMBIGUOUS,
    FILL_DAY_STOP_T1_BLOCKED,
    FILL_DAY_TARGET_MISSED,
    FILL_DAY_TARGET_ORDER_UNKNOWN,
    PRICE_LIMIT_LOCKED,
    PRICE_LIMIT_NOT_MODELED,
    STATUS_AMBIGUOUS,
    STATUS_CENSORED,
    STATUS_RESOLVED,
    STATUS_TIMEOUT,
    _tail_summary,
    _render_markdown,
    relabel_execution_episode,
)
from limit_pullback.models.enums import (
    EntryRoomState,
    ExecutionLabel,
    FillStatus,
    FillType,
    OutcomeStatus,
    SetupStage,
)
from limit_pullback.models.market import DailyBar
from limit_pullback.models.outcome import OutcomeEpisode
from limit_pullback.models.execution_reality import ExecutionRealitySummary


UTC = timezone.utc


def _bar(day: date, *, open: str, high: str, low: str, close: str) -> DailyBar:
    return DailyBar(
        trade_date=day,
        code="000001",
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        preclose=Decimal("10.00"),
        volume=Decimal("1"),
        amount=Decimal("1"),
        source="fixture",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _bars(*specs: tuple[str, str, str, str]) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 5)
    return tuple(
        _bar(start + timedelta(days=index), open=o, high=h, low=l, close=c)
        for index, (o, h, l, c) in enumerate(specs)
    )


def _event(*, fill_type: FillType = FillType.OPEN_FILL, actionable: bool = True) -> OutcomeEpisode:
    return OutcomeEpisode(
        code="000001",
        setup_id="000001:20260104:1000",
        execution_label=ExecutionLabel.B1_READY,
        setup_stage=SetupStage.B1_READY,
        signal_date=date(2026, 1, 4),
        anchor_date=date(2026, 1, 3),
        anchor_price=Decimal("10.00"),
        support_low=Decimal("9.80"),
        support_high=Decimal("10.00"),
        support_center=Decimal("9.90"),
        setup_quality_score=Decimal("80"),
        entry_quality_score=Decimal("80"),
        entry_room_state=EntryRoomState.SUFFICIENT,
        is_entry_candidate=actionable,
        preferred_entry=Decimal("10.00"),
        buy_zone_low=Decimal("9.80"),
        buy_zone_high=Decimal("10.00"),
        invalid_price=Decimal("9.70"),
        s1_price=Decimal("11.00"),
        entry_reference_price=Decimal("10.00"),
        next_trade_date=date(2026, 1, 5),
        fill_status=FillStatus.FILLED,
        fill_type=fill_type,
        fill_date=date(2026, 1, 5),
        fill_price=Decimal("10.00"),
        outcome=OutcomeStatus.NO_FILL,
        future_sessions_available=20,
        data_quality="OK",
        snapshot_id="snap-test",
        strategy_commit="strategy-test",
        strategy_config_hash="strategy-config-test",
        trade_plan_config_hash="trade-plan-test",
        outcome_config_hash="outcome-test",
        frozen_event_hash="frozen-hash",
    )


def test_open_fill_day_stop_is_t1_blocked_and_exits_next_open():
    result = relabel_execution_episode(
        _event(),
        _bars(
            ("10.00", "10.30", "9.60", "9.90"),
            ("9.50", "9.80", "9.40", "9.60"),
            ("9.70", "10.00", "9.70", "9.90"),
            *[("9.90", "10.00", "9.80", "9.90")] * 8,
        ),
    )

    assert result.fill_day_stop_state == FILL_DAY_STOP_T1_BLOCKED
    assert result.strict_execution_status == STATUS_RESOLVED
    assert result.execution_exit_type == "STOP_TRIGGERED_T1_BLOCKED"
    assert result.execution_exit_date == date(2026, 1, 6)
    assert result.execution_exit_price == Decimal("9.50")
    assert result.gross_execution_R is not None and result.gross_execution_R < Decimal("-1")


def test_breakout_gap_fill_has_same_t1_blocked_rule():
    event = _event(fill_type=FillType.BREAKOUT_GAP_FILL)
    result = relabel_execution_episode(
        event,
        _bars(
            ("10.00", "10.40", "9.60", "9.90"),
            ("9.50", "9.80", "9.40", "9.60"),
            *[("9.70", "10.00", "9.70", "9.90")] * 9,
        ),
    )
    assert result.fill_day_stop_state == FILL_DAY_STOP_T1_BLOCKED
    assert result.execution_exit_type == "STOP_TRIGGERED_T1_BLOCKED"


@pytest.mark.parametrize("fill_type", [FillType.INTRADAY_TOUCH_FILL, FillType.BREAKOUT_TRIGGER_FILL])
def test_intraday_fill_day_stop_is_strict_ambiguous_and_conservative_next_open(fill_type):
    result = relabel_execution_episode(
        _event(fill_type=fill_type),
        _bars(
            ("10.50", "10.70", "9.60", "10.20"),
            ("9.50", "9.80", "9.40", "9.60"),
            *[("9.70", "10.00", "9.70", "9.90")] * 9,
        ),
    )
    assert result.fill_day_stop_state == FILL_DAY_STOP_AMBIGUOUS
    assert result.strict_execution_status == STATUS_AMBIGUOUS
    assert result.execution_exit_price is None
    assert result.conservative_execution_status == STATUS_RESOLVED
    assert result.conservative_execution_exit_type == "STOP_TRIGGERED_T1_BLOCKED"
    assert result.conservative_execution_exit_date == date(2026, 1, 6)


def test_fill_day_target_is_missed_and_cannot_be_same_day_win():
    result = relabel_execution_episode(
        _event(),
        _bars(
            ("10.00", "11.20", "9.90", "10.80"),
            *[("10.20", "10.50", "9.90", "10.10")] * 9,
        ),
    )
    assert result.fill_day_target_state == FILL_DAY_TARGET_MISSED
    assert result.execution_exit_date != date(2026, 1, 5)
    assert result.strict_execution_status == STATUS_TIMEOUT


def test_intraday_touch_fill_day_target_order_is_unknown_not_known_missed():
    bars = _bars(
        ("10.50", "11.20", "10.10", "10.80"),
        *[("10.20", "10.50", "9.90", "10.10")] * 9,
    )
    intraday = relabel_execution_episode(
        _event(fill_type=FillType.INTRADAY_TOUCH_FILL),
        bars,
    )
    open_fill = relabel_execution_episode(_event(fill_type=FillType.OPEN_FILL), bars)

    assert intraday.fill_day_target_state == FILL_DAY_TARGET_ORDER_UNKNOWN
    assert intraday.fill_day_target_state != FILL_DAY_TARGET_MISSED
    assert open_fill.fill_day_target_state == FILL_DAY_TARGET_MISSED
    # The reporting state is informational only; execution outcomes remain
    # identical for the same daily bars.
    for field in (
        "strict_execution_status",
        "conservative_execution_status",
        "execution_exit_type",
        "execution_exit_date",
        "execution_exit_price",
        "gross_execution_R",
        "conservative_gross_execution_R",
    ):
        assert getattr(intraday, field) == getattr(open_fill, field)


def test_b1_tail_reports_known_and_unknown_fill_day_targets_separately():
    bars = _bars(
        ("10.50", "11.20", "10.10", "10.80"),
        *[("10.20", "10.50", "9.90", "10.10")] * 9,
    )
    known = relabel_execution_episode(
        _event(fill_type=FillType.OPEN_FILL).model_copy(
            update={"outcome": OutcomeStatus.WIN_S1}
        ),
        bars,
    )
    unknown = relabel_execution_episode(
        _event(fill_type=FillType.INTRADAY_TOUCH_FILL).model_copy(
            update={"outcome": OutcomeStatus.WIN_S1}
        ),
        bars,
    )
    summary = _tail_summary([known, unknown], "B1_READY_SETUP_GE_80")

    assert summary["KNOWN_POST_ENTRY_FILL_DAY_TARGET"] == 1
    assert summary["TARGET_ORDER_UNKNOWN"] == 1
    assert summary["fill_day_target_touched_count"] == 1


def test_summary_markdown_uses_plain_fence():
    summary = ExecutionRealitySummary(
        snapshot_id="snap-test",
        source_episodes_sha256="episodes-test",
        episode_count=0,
        code_count=0,
        max_holding_sessions=1,
        price_limit_execution_model=PRICE_LIMIT_NOT_MODELED,
    )
    rendered = _render_markdown(summary)
    assert "```json" not in rendered
    assert "```\n" in rendered


def test_next_day_gap_below_invalid_allows_loss_less_than_minus_one_r():
    result = relabel_execution_episode(
        _event(),
        _bars(
            ("10.00", "10.20", "9.90", "10.00"),
            ("9.00", "9.20", "8.90", "9.10"),
            *[("9.70", "10.00", "9.70", "9.90")] * 9,
        ),
    )
    assert result.execution_exit_type == "GAP_STOP"
    assert result.execution_exit_price == Decimal("9.00")
    assert result.gross_execution_R is not None and result.gross_execution_R < Decimal("-1")


def test_next_day_gap_above_s1_exits_at_s1_not_open():
    result = relabel_execution_episode(
        _event(),
        _bars(
            ("10.00", "10.20", "9.90", "10.00"),
            ("11.50", "11.80", "11.40", "11.60"),
            *[("10.70", "10.90", "10.60", "10.80")] * 9,
        ),
    )
    assert result.execution_exit_type == "GAP_TARGET"
    assert result.execution_exit_price == Decimal("11.00")


def test_next_day_both_target_and_invalid_is_strict_ambiguous_stop_first_conservative():
    result = relabel_execution_episode(
        _event(),
        _bars(
            ("10.00", "10.20", "9.90", "10.00"),
            ("10.20", "11.20", "9.60", "10.00"),
            *[("9.70", "10.00", "9.70", "9.90")] * 9,
        ),
    )
    assert result.strict_execution_status == STATUS_AMBIGUOUS
    assert result.execution_exit_price is None
    assert result.conservative_execution_exit_type == "STOP_FIRST"
    assert result.conservative_execution_exit_price == Decimal("9.70")


def test_max_holding_is_fill_inclusive_and_short_history_is_censored():
    ten_sessions = _bars(
        ("10.00", "10.20", "9.90", "10.00"),
        *[("10.10", "10.30", "9.90", "10.10")] * 9,
    )
    timeout = relabel_execution_episode(_event(), ten_sessions)
    assert timeout.strict_execution_status == STATUS_TIMEOUT
    assert timeout.holding_sessions == 10

    censored = relabel_execution_episode(_event(), ten_sessions[:4])
    assert censored.strict_execution_status == STATUS_CENSORED
    assert censored.holding_sessions == 4


def test_frozen_fields_and_hash_are_unchanged():
    event = _event()
    result = relabel_execution_episode(
        event,
        _bars(
            ("10.00", "10.20", "9.90", "10.00"),
            ("10.10", "11.20", "10.00", "10.90"),
            *[("10.70", "10.90", "10.60", "10.80")] * 9,
        ),
    )
    for field in type(event).model_fields:
        assert getattr(result, field) == getattr(event, field)
    assert result.frozen_event_hash == event.frozen_event_hash


def test_price_limit_guard_blocks_locked_limit_down_then_exits_next_session():
    result = relabel_execution_episode(
        _event(),
        _bars(
            ("10.00", "10.20", "9.60", "9.90"),
            ("9.00", "9.00", "9.00", "9.00"),
            ("9.50", "9.80", "9.40", "9.60"),
            *[("9.70", "10.00", "9.70", "9.90")] * 8,
        ),
        price_limits={
            date(2026, 1, 6): {"down_limit": Decimal("9.00")},
        },
    )
    assert result.price_limit_execution_status == PRICE_LIMIT_LOCKED
    assert result.execution_exit_date == date(2026, 1, 7)


def test_without_price_limit_data_is_explicitly_not_modeled():
    result = relabel_execution_episode(
        _event(),
        _bars(
            ("10.00", "10.20", "9.90", "10.00"),
            ("9.50", "9.80", "9.40", "9.60"),
            *[("9.70", "10.00", "9.70", "9.90")] * 9,
        ),
    )
    assert result.price_limit_execution_status == PRICE_LIMIT_NOT_MODELED


def test_non_actionable_filled_event_is_not_executed():
    result = relabel_execution_episode(
        _event(actionable=False),
        _bars(
            ("10.00", "11.20", "9.60", "10.80"),
            *[("10.20", "10.50", "9.90", "10.10")] * 9,
        ),
    )
    assert result.strict_execution_status == "NON_ACTIONABLE"
    assert result.execution_exit_date is None


def test_execution_reality_does_not_call_strategy_evaluator(monkeypatch):
    import limit_pullback.strategy.engine as engine

    def fail(*args, **kwargs):
        raise AssertionError("evaluate_strategy must not run in Phase 2D.1A")

    monkeypatch.setattr(engine, "evaluate_strategy", fail)
    result = relabel_execution_episode(
        _event(),
        _bars(
            ("10.00", "10.20", "9.90", "10.00"),
            ("11.50", "11.80", "11.40", "11.60"),
            *[("10.70", "10.90", "10.60", "10.80")] * 9,
        ),
    )
    assert result.strict_execution_status == STATUS_RESOLVED
