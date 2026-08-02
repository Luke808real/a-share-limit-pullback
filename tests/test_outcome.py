from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from dataclasses import replace
from decimal import Decimal
import multiprocessing as mp
from types import SimpleNamespace

import pytest

from limit_pullback.config import load_strategy_config, load_trade_plan_config
import limit_pullback.outcome as outcome
from limit_pullback.models.enums import (
    DataQuality,
    EntryRoomState,
    ExecutionLabel,
    FillStatus,
    FillType,
    OutcomeStatus,
    PatternOutcome,
    SetupStage,
)
from limit_pullback.models.outcome import OutcomeStudyConfig, OutcomeStudySummary
from tests.synthetic_data import make_bar


def _bars(*rows: tuple[str, str, str, str, str, str]) -> list:
    return [
        make_bar(
            date.fromisoformat(trade_date),
            open_price=open_price,
            high=high,
            low=low,
            close=close,
            preclose=preclose,
            volume=volume,
        )
        for trade_date, open_price, high, low, close, preclose, volume in rows
    ]


def _event(
    *,
    signal_date: date,
    preferred: str = "10.00",
    invalid: str = "9.50",
    s1: str = "11.00",
    label: ExecutionLabel = ExecutionLabel.B1_READY,
) -> outcome._FrozenEvent:
    return outcome._FrozenEvent(
        code="603918",
        setup_id="603918:20260728:1000",
        execution_label=label,
        setup_stage=(
            SetupStage.WATCH_PULLBACK
            if label is ExecutionLabel.B1_PREP
            else SetupStage.B1_READY
        ),
        signal_date=signal_date,
        anchor_date=signal_date - timedelta(days=2),
        anchor_price=Decimal("10.00"),
        support_low=Decimal("9.90"),
        support_high=Decimal("10.10"),
        support_center=Decimal("10.00"),
        b2_trigger_price=None,
        setup_quality_score=Decimal("70"),
        entry_quality_score=Decimal("70"),
        days_since_anchor=2,
        entry_room_state=EntryRoomState.SUFFICIENT,
        is_entry_candidate=True,
        preferred_entry=Decimal(preferred) if preferred else None,
        buy_zone_low=Decimal("9.90"),
        buy_zone_high=Decimal("10.10"),
        invalid_price=Decimal(invalid) if invalid else None,
        s1_price=Decimal(s1) if s1 else None,
        entry_reference_price=Decimal(preferred) if preferred else None,
        data_quality=DataQuality.OK.value,
        quality_flags=(),
        snapshot_id="snap-test",
        strategy_commit="commit-test",
        strategy_config_hash="strategy-hash",
        trade_plan_config_hash="trade-plan-hash",
        outcome_config_hash="outcome-hash",
        frozen_event_hash="frozen-hash",
    )


def _b2_event(
    *,
    signal_date: date,
    trigger: str = "11.51",
    invalid: str = "10.37",
    s1: str = "12.00",
    actionable: bool = True,
) -> outcome._FrozenEvent:
    trigger_price = Decimal(trigger)
    return replace(
        _event(
            signal_date=signal_date,
            preferred=trigger,
            invalid=invalid,
            s1=s1,
            label=ExecutionLabel.B2_READY,
        ),
        setup_stage=SetupStage.B2_READY,
        b2_trigger_price=trigger_price,
        is_entry_candidate=actionable,
    )


def test_b2_ready_breakout_without_trigger_is_no_fill():
    signal_date = date(2026, 7, 30)
    bars = _bars(
        ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-31", "10.68", "11.40", "10.50", "11.00", "10.00", "100"),
    )
    result = outcome._complete_event(
        _b2_event(signal_date=signal_date), bars, OutcomeStudyConfig()
    )
    assert result.fill_status is FillStatus.NO_FILL
    assert result.fill_type is FillType.NONE
    assert result.outcome is OutcomeStatus.NO_FILL


def test_b2_ready_breakout_trigger_fills_at_trigger_not_open():
    signal_date = date(2026, 7, 30)
    bars = _bars(
        ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-31", "10.68", "12.20", "10.50", "11.80", "10.00", "100"),
    )
    result = outcome._complete_event(
        _b2_event(signal_date=signal_date), bars, OutcomeStudyConfig()
    )
    assert result.fill_type is FillType.BREAKOUT_TRIGGER_FILL
    assert result.fill_price == Decimal("11.51")
    assert result.outcome is OutcomeStatus.WIN_S1
    assert result.fill_price != Decimal("10.68")


def test_b2_ready_gap_breakout_fills_at_open():
    signal_date = date(2026, 7, 30)
    bars = _bars(
        ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-31", "11.60", "12.20", "11.50", "12.00", "10.00", "100"),
    )
    result = outcome._complete_event(
        _b2_event(signal_date=signal_date), bars, OutcomeStudyConfig()
    )
    assert result.fill_type is FillType.BREAKOUT_GAP_FILL
    assert result.fill_price == Decimal("11.60")
    assert result.outcome is OutcomeStatus.WIN_S1


def test_b2_trigger_fill_includes_high_but_excludes_fill_day_low_from_mae():
    signal_date = date(2026, 7, 30)
    bars = _bars(
        ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-31", "10.68", "12.20", "10.50", "11.80", "10.00", "100"),
        ("2026-08-03", "11.80", "11.90", "11.40", "11.70", "11.80", "100"),
    )
    result = outcome._complete_event(
        _b2_event(signal_date=signal_date, s1="12.50"),
        bars,
        OutcomeStudyConfig(),
    )
    assert result.fill_type is FillType.BREAKOUT_TRIGGER_FILL
    assert result.mfe_pct == Decimal("0.0599")
    assert result.mae_pct == Decimal("-0.0096")


def test_b2_trigger_fill_low_invalid_is_ambiguous_not_loss():
    signal_date = date(2026, 7, 30)
    bars = _bars(
        ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-31", "10.68", "11.80", "10.00", "11.20", "10.00", "100"),
    )
    result = outcome._complete_event(
        _b2_event(signal_date=signal_date), bars, OutcomeStudyConfig()
    )
    assert result.fill_type is FillType.BREAKOUT_TRIGGER_FILL
    assert result.outcome is OutcomeStatus.AMBIGUOUS_INTRADAY
    assert result.r_multiple is None
    assert result.conservative_r_multiple == Decimal("-1")


def test_b2_non_positive_reward_is_ineligible_but_structural_pattern_remains():
    signal_date = date(2026, 7, 30)
    bars = _bars(
        ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-31", "10.68", "12.20", "10.50", "11.80", "10.00", "100"),
    )
    result = outcome._complete_event(
        _b2_event(signal_date=signal_date, trigger="11.51", s1="11.46", actionable=False),
        bars,
        OutcomeStudyConfig(),
    )
    assert result.outcome is OutcomeStatus.NO_FILL
    assert result.eligibility_reason == "REWARD_NON_POSITIVE_AT_TRIGGER"
    assert result.pattern_1d is PatternOutcome.S1_BEFORE_INVALID
    assert outcome._stats([result]).eligible == 0


def test_b2_non_actionable_positive_room_is_not_a_trade():
    result = outcome._complete_event(
        _b2_event(signal_date=date(2026, 7, 30), actionable=False),
        _bars(
            ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
            ("2026-07-31", "10.68", "12.20", "10.50", "11.80", "10.00", "100"),
        ),
        OutcomeStudyConfig(),
    )
    assert result.outcome is OutcomeStatus.NO_FILL
    assert result.eligibility_reason == "NON_ACTIONABLE_STRUCTURAL_EVENT"
    assert outcome._stats([result]).eligible == 0


def test_b2_non_positive_reward_is_invariant_failure_for_actionable_event():
    with pytest.raises(ValueError, match="no positive reward room"):
        outcome._complete_event(
            _b2_event(
                signal_date=date(2026, 7, 30),
                trigger="11.51",
                s1="11.46",
                actionable=True,
            ),
            _bars(
                ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
                ("2026-07-31", "10.68", "12.20", "10.50", "11.80", "10.00", "100"),
            ),
            OutcomeStudyConfig(),
        )


def test_603918_b2_regression_has_no_open_fill_or_positive_r():
    result = outcome._complete_event(
        _b2_event(
            signal_date=date(2026, 7, 30),
            trigger="11.51",
            invalid="10.37",
            s1="11.46",
            actionable=False,
        ),
        _bars(
            ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
            ("2026-07-31", "10.68", "12.20", "10.50", "11.38", "10.00", "100"),
        ),
        OutcomeStudyConfig(),
    )
    assert result.fill_price is None
    assert result.fill_type is FillType.NONE
    assert result.r_multiple is None
    assert result.outcome is OutcomeStatus.NO_FILL
    assert result.eligibility_reason == "REWARD_NON_POSITIVE_AT_TRIGGER"


def test_b2_confirmed_keeps_limit_entry_semantics():
    event = replace(
        _event(
            signal_date=date(2026, 7, 30),
            preferred="11.51",
            invalid="10.37",
            s1="12.00",
            label=ExecutionLabel.B2_CONFIRMED,
        ),
        setup_stage=SetupStage.B2_CONFIRMED,
        b2_trigger_price=Decimal("11.51"),
    )
    result = outcome._complete_event(
        event,
        _bars(
            ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
            ("2026-07-31", "10.68", "12.20", "10.50", "11.80", "10.00", "100"),
        ),
        OutcomeStudyConfig(),
    )
    assert result.fill_type is FillType.OPEN_FILL
    assert result.fill_price == Decimal("10.68")


def test_relabel_preserves_frozen_fields_and_corrects_only_b2_outcome():
    signal_date = date(2026, 7, 30)
    bars = _bars(
        ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-31", "10.68", "12.20", "10.50", "11.80", "10.00", "100"),
    )
    correct = outcome._complete_event(
        _b2_event(signal_date=signal_date), bars, OutcomeStudyConfig()
    )
    old = correct.model_copy(
        update={
            "fill_type": FillType.OPEN_FILL,
            "fill_price": Decimal("10.68"),
            "outcome": OutcomeStatus.WIN_S1,
            "r_multiple": Decimal("2.5161"),
            "conservative_r_multiple": Decimal("2.5161"),
        }
    )
    relabeled, metrics = outcome.relabel_frozen_episodes(
        [old], bars_by_code={old.code: bars}, config=OutcomeStudyConfig()
    )
    result = relabeled[0]
    assert metrics["changed_episodes"] == 1
    assert result.fill_type is FillType.BREAKOUT_TRIGGER_FILL
    assert result.fill_price == Decimal("11.51")
    assert result.outcome is OutcomeStatus.WIN_S1
    for field in old.__class__.model_fields:
        if field not in outcome._RELABEL_MUTABLE_FIELDS:
            assert getattr(result, field) == getattr(old, field)


def test_relabel_leaves_b1_and_b2_confirmed_outcomes_unchanged():
    signal_date = date(2026, 7, 30)
    bars = _bars(
        ("2026-07-30", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-31", "10.00", "11.10", "9.95", "10.80", "10.00", "100"),
    )
    b1 = outcome._complete_event(
        _event(signal_date=signal_date), bars, OutcomeStudyConfig()
    )
    b2_confirmed = outcome._complete_event(
        replace(
            _event(
                signal_date=signal_date,
                preferred="10.00",
                invalid="9.50",
                s1="11.00",
                label=ExecutionLabel.B2_CONFIRMED,
            ),
            setup_stage=SetupStage.B2_CONFIRMED,
            b2_trigger_price=Decimal("10.00"),
        ),
        bars,
        OutcomeStudyConfig(),
    )
    relabeled, metrics = outcome.relabel_frozen_episodes(
        [b1, b2_confirmed],
        bars_by_code={b1.code: bars},
        config=OutcomeStudyConfig(),
    )
    assert metrics["changed_episodes"] == 0
    assert relabeled == [b1, b2_confirmed]


def test_no_fill_is_not_a_win_even_if_target_hits_later():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.50", "10.60", "10.50", "10.55", "10.00", "100"),
        ("2026-07-30", "10.60", "11.20", "10.55", "11.00", "10.55", "100"),
    )
    result = outcome._complete_event(_event(signal_date=signal_date), bars, OutcomeStudyConfig())
    assert result.fill_status is FillStatus.NO_FILL
    assert result.outcome is OutcomeStatus.NO_FILL


def test_gap_below_invalid_cancels_entry():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "9.40", "9.60", "9.30", "9.50", "10.00", "100"),
    )
    result = outcome._complete_event(_event(signal_date=signal_date), bars, OutcomeStudyConfig())
    assert result.fill_status is FillStatus.CANCEL_GAP_INVALID
    assert result.fill_type is FillType.NONE
    assert result.outcome is OutcomeStatus.CANCEL_GAP_INVALID


def test_target_first_is_win_and_r_mfe_mae_are_decimal():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.00", "11.10", "9.95", "10.80", "10.00", "100"),
    )
    result = outcome._complete_event(_event(signal_date=signal_date), bars, OutcomeStudyConfig())
    assert result.outcome is OutcomeStatus.WIN_S1
    assert result.fill_type is FillType.OPEN_FILL
    assert result.r_multiple == Decimal("2.0000")
    assert isinstance(result.mfe_pct, Decimal)
    assert isinstance(result.mae_pct, Decimal)


def test_stats_fill_rate_is_bounded_for_complete_non_actionable_plan():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.00", "11.10", "9.95", "10.80", "10.00", "100"),
    )
    event = _event(signal_date=signal_date)
    event = event.__class__(**{**event.__dict__, "is_entry_candidate": False})
    result = outcome._complete_event(event, bars, OutcomeStudyConfig())
    stats = outcome._stats([result])
    assert stats.eligible == 1
    assert stats.fill_rate == Decimal("1.0000")


def test_actionable_and_structural_cohorts_are_separate():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.00", "11.10", "9.95", "10.80", "10.00", "100"),
    )
    actionable = outcome._complete_event(_event(signal_date=signal_date), bars, OutcomeStudyConfig())
    structural_only = outcome._complete_event(
        replace(_event(signal_date=signal_date), is_entry_candidate=False),
        bars,
        OutcomeStudyConfig(),
    )
    structural = outcome._stats([actionable, structural_only])
    candidate = outcome._stats([actionable, structural_only], actionable_only=True)
    assert structural.eligible == 2
    assert structural.filled == 2
    assert candidate.episodes == 1
    assert candidate.eligible == 1
    assert candidate.filled == 1


def test_intraday_touch_excludes_fill_day_high_but_allows_fill_day_low():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.50", "11.20", "10.00", "10.60", "10.00", "100"),
        ("2026-07-30", "10.60", "11.10", "10.50", "10.90", "10.60", "100"),
    )
    result = outcome._complete_event(_event(signal_date=signal_date), bars, OutcomeStudyConfig())
    assert result.fill_type is FillType.INTRADAY_TOUCH_FILL
    assert result.outcome is OutcomeStatus.WIN_S1
    assert result.mfe_pct == Decimal("0.1100")
    assert result.mae_pct == Decimal("0.0000")


def test_intraday_touch_same_day_invalid_and_target_is_ambiguous():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.50", "11.20", "9.40", "10.00", "10.00", "100"),
    )
    result = outcome._complete_event(_event(signal_date=signal_date), bars, OutcomeStudyConfig())
    assert result.fill_type is FillType.INTRADAY_TOUCH_FILL
    assert result.outcome is OutcomeStatus.AMBIGUOUS_INTRADAY
    assert result.conservative_r_multiple == Decimal("-1")


def test_open_fill_holding_window_includes_fill_session_only():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.00", "10.20", "9.90", "10.00", "10.00", "100"),
        ("2026-07-30", "10.00", "10.30", "9.90", "10.00", "10.00", "100"),
        ("2026-07-31", "10.00", "10.30", "9.90", "10.00", "10.00", "100"),
        ("2026-08-03", "10.00", "11.20", "9.90", "11.00", "10.00", "100"),
    )
    result = outcome._complete_event(
        _event(signal_date=signal_date),
        bars,
        OutcomeStudyConfig(forward_horizons=(1,), max_holding_sessions=3),
    )
    assert result.outcome is OutcomeStatus.TIMEOUT
    assert result.holding_sessions_to_resolution == 3
    assert result.holding_sessions_to_resolution <= 3
    assert result.mfe_pct == Decimal("0.0300")


def test_intraday_touch_holding_window_does_not_gain_an_extra_session():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.50", "10.80", "10.00", "10.60", "10.00", "100"),
        ("2026-07-30", "10.60", "10.70", "10.00", "10.60", "10.60", "100"),
        ("2026-07-31", "10.60", "10.80", "10.00", "10.60", "10.60", "100"),
        ("2026-08-03", "10.60", "11.20", "10.00", "11.00", "10.60", "100"),
    )
    result = outcome._complete_event(
        _event(signal_date=signal_date),
        bars,
        OutcomeStudyConfig(forward_horizons=(1,), max_holding_sessions=3),
    )
    assert result.fill_type is FillType.INTRADAY_TOUCH_FILL
    assert result.outcome is OutcomeStatus.TIMEOUT
    assert result.holding_sessions_to_resolution == 3
    assert result.holding_sessions_to_resolution <= 3
    # Outcome and excursion windows stop at 2026-07-31; 2026-08-03 is absent.
    assert result.mfe_pct == Decimal("0.0800")
    assert result.mae_pct == Decimal("0.0000")


def test_intraday_touch_target_on_last_allowed_session_wins():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.50", "10.80", "10.00", "10.60", "10.00", "100"),
        ("2026-07-30", "10.60", "10.70", "10.00", "10.60", "10.60", "100"),
        ("2026-07-31", "10.60", "11.20", "10.00", "11.00", "10.60", "100"),
        ("2026-08-03", "10.60", "11.30", "10.00", "11.10", "10.60", "100"),
    )
    result = outcome._complete_event(
        _event(signal_date=signal_date),
        bars,
        OutcomeStudyConfig(forward_horizons=(1,), max_holding_sessions=3),
    )
    assert result.outcome is OutcomeStatus.WIN_S1
    assert result.holding_sessions_to_resolution == 3
    assert result.holding_sessions_to_resolution <= 3


def test_intraday_touch_max_one_ends_on_fill_session():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.50", "10.80", "10.00", "10.60", "10.00", "100"),
        ("2026-07-30", "10.60", "11.20", "10.00", "11.00", "10.60", "100"),
    )
    result = outcome._complete_event(
        _event(signal_date=signal_date),
        bars,
        OutcomeStudyConfig(forward_horizons=(1,), max_holding_sessions=1),
    )
    assert result.outcome is OutcomeStatus.TIMEOUT
    assert result.holding_sessions_to_resolution == 1


def test_group_stats_keep_actionable_and_structural_cohorts_separate():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.00", "11.10", "9.95", "10.80", "10.00", "100"),
    )
    actionable = outcome._complete_event(_event(signal_date=signal_date), bars, OutcomeStudyConfig())
    structural_only = outcome._complete_event(
        replace(
            _event(signal_date=signal_date),
            is_entry_candidate=False,
            setup_quality_score=Decimal("85"),
        ),
        bars,
        OutcomeStudyConfig(),
    )
    events = [actionable, structural_only]
    actionable_groups = outcome._group_stats(
        events,
        lambda event: outcome._group_bucket(event.setup_quality_score),
        actionable_only=True,
        expected_keys=outcome.QUALITY_GROUP_KEYS,
    )
    structural_groups = outcome._group_stats(
        events,
        lambda event: outcome._group_bucket(event.setup_quality_score),
        expected_keys=outcome.QUALITY_GROUP_KEYS,
    )
    assert tuple(actionable_groups) == outcome.QUALITY_GROUP_KEYS
    assert actionable_groups["70-80"].episodes == 1
    assert actionable_groups[">=80"].episodes == 0
    assert structural_groups["70-80"].episodes == 1
    assert structural_groups[">=80"].episodes == 1
    days_groups = outcome._group_stats(
        events,
        lambda event: outcome._days_bucket(event.days_since_anchor),
        actionable_only=True,
        expected_keys=outcome.DAYS_GROUP_KEYS,
    )
    assert tuple(days_groups) == outcome.DAYS_GROUP_KEYS
    assert days_groups["D+2"].episodes == 1


def test_summary_legacy_groups_are_actionable_and_markdown_orders_cohorts():
    empty = outcome._stats([])
    stage = {"B1_READY": empty}
    quality = {key: empty for key in outcome.QUALITY_GROUP_KEYS}
    days = {key: empty for key in outcome.DAYS_GROUP_KEYS}
    summary = OutcomeStudySummary(
        snapshot_id="snap-test",
        start=date(2026, 1, 1),
        end=date(2026, 1, 2),
        confirmed_date_count=0,
        confirmed_code_count=0,
        provisional_only_date_count=0,
        raw_signal_days=0,
        episode_count=0,
        b1_prep_episodes=0,
        stage_stats=stage,
        actionable_stage_stats=stage,
        structural_stage_stats=stage,
        actionable_setup_quality_groups=quality,
        actionable_entry_quality_groups=quality,
        actionable_days_since_anchor_groups=days,
        structural_setup_quality_groups=quality,
        structural_entry_quality_groups=quality,
        structural_days_since_anchor_groups=days,
        setup_quality_groups=quality,
        entry_quality_groups=quality,
        days_since_anchor_groups=days,
        strategy_commit="commit",
        strategy_config_hash="strategy",
        trade_plan_config_hash="trade",
        outcome_config_hash="outcome",
    )
    assert summary.setup_quality_groups == summary.actionable_setup_quality_groups
    assert summary.entry_quality_groups == summary.actionable_entry_quality_groups
    assert summary.days_since_anchor_groups == summary.actionable_days_since_anchor_groups
    markdown = outcome._summary_markdown(summary)
    assert markdown.index("ACTIONABLE setup_quality groups") < markdown.index(
        "STRUCTURAL setup_quality groups"
    )
    assert "strict resolved expectancy R" in markdown
    assert "conservative resolved expectancy R" in markdown


def test_resolved_strict_and_conservative_expectancy_are_explicit():
    signal_date = date(2026, 7, 28)
    base = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
    )
    win = outcome._complete_event(
        _event(signal_date=signal_date),
        base + _bars(("2026-07-29", "10.00", "11.10", "9.95", "10.80", "10.00", "100")),
        OutcomeStudyConfig(),
    )
    loss = outcome._complete_event(
        _event(signal_date=signal_date),
        base + _bars(("2026-07-29", "10.00", "10.10", "9.40", "9.60", "10.00", "100")),
        OutcomeStudyConfig(),
    )
    ambiguous = outcome._complete_event(
        _event(signal_date=signal_date),
        base + _bars(("2026-07-29", "10.00", "11.10", "9.40", "10.00", "10.00", "100")),
        OutcomeStudyConfig(),
    )
    timeout = outcome._complete_event(
        _event(signal_date=signal_date),
        base + _bars(("2026-07-29", "10.00", "10.30", "9.80", "10.00", "10.00", "100")),
        OutcomeStudyConfig(forward_horizons=(1,), max_holding_sessions=1),
    )
    stats = outcome._stats([win, loss, ambiguous, timeout])
    assert stats.strict_resolved == 2
    assert stats.conservative_resolved == 3
    assert stats.strict_resolved_expectancy_r == Decimal("0.5000")
    assert stats.conservative_resolved_expectancy_r == Decimal("0.0000")
    assert stats.timeout == 1


def test_invalid_first_is_loss():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.00", "10.10", "9.40", "9.60", "10.00", "100"),
    )
    result = outcome._complete_event(_event(signal_date=signal_date), bars, OutcomeStudyConfig())
    assert result.outcome is OutcomeStatus.LOSS_INVALID
    assert result.r_multiple == Decimal("-1")


def test_same_bar_target_and_invalid_is_ambiguous_and_conservative_loss():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.00", "11.10", "9.40", "10.00", "10.00", "100"),
    )
    result = outcome._complete_event(_event(signal_date=signal_date), bars, OutcomeStudyConfig())
    assert result.outcome is OutcomeStatus.AMBIGUOUS_INTRADAY
    assert result.r_multiple is None
    assert result.conservative_r_multiple == Decimal("-1")


def test_timeout_and_censored_are_distinct():
    signal_date = date(2026, 7, 28)
    full = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.00", "10.30", "9.80", "10.00", "10.00", "100"),
        ("2026-07-30", "10.00", "10.30", "9.80", "10.00", "10.00", "100"),
    )
    short_config = OutcomeStudyConfig(forward_horizons=(1,), max_holding_sessions=2)
    timeout = outcome._complete_event(_event(signal_date=signal_date), full, short_config)
    assert timeout.outcome is OutcomeStatus.TIMEOUT
    censored = outcome._complete_event(_event(signal_date=signal_date), full[:2], short_config)
    assert censored.outcome is OutcomeStatus.CENSORED


def test_pattern_ambiguity_is_separate_from_trade_fill():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.50", "11.10", "9.40", "10.50", "10.00", "100"),
    )
    event = _event(signal_date=signal_date, preferred="10.00")
    # Fill and direction ambiguity are separate dimensions.
    result = outcome._complete_event(event, bars, OutcomeStudyConfig())
    assert result.fill_status is FillStatus.FILLED
    assert result.outcome is OutcomeStatus.AMBIGUOUS_INTRADAY
    assert result.pattern_1d is PatternOutcome.AMBIGUOUS


def test_b1_prep_is_conversion_only():
    signal_date = date(2026, 7, 28)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.00", "10.20", "9.90", "10.10", "10.00", "100"),
    )
    result = outcome._complete_event(
        _event(signal_date=signal_date, label=ExecutionLabel.B1_PREP),
        bars,
        OutcomeStudyConfig(),
    )
    assert result.outcome is OutcomeStatus.NO_FILL
    assert result.eligibility_reason == "B1_PREP_CONVERSION_ONLY"


def test_causal_replay_deduplicates_stage_episode_and_preserves_future_prefix(monkeypatch):
    signal_date = date(2026, 7, 29)
    bars = _bars(
        ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
        ("2026-07-29", "10.00", "10.20", "9.90", "10.10", "10.00", "100"),
        ("2026-07-30", "10.00", "10.20", "9.90", "10.10", "10.10", "100"),
        ("2026-07-31", "10.20", "10.50", "10.10", "10.40", "10.10", "150"),
    )
    calls = {"count": 0}

    def fake_signal(*, bars, as_of, **_):
        calls["count"] += 1
        if as_of == date(2026, 7, 28):
            stage = SetupStage.NORMAL
        elif as_of <= date(2026, 7, 30):
            stage = SetupStage.B1_READY
        else:
            stage = SetupStage.B2_READY
        return SimpleNamespace(
            code="603918",
            setup_id="603918:20260728:1000",
            trade_date=as_of,
            setup_stage=stage,
            anchor=SimpleNamespace(
                anchor_date=date(2026, 7, 28), anchor_price=Decimal("10.00")
            ),
            support=None,
            b2_trigger=None,
            setup_quality_score=Decimal("70"),
            entry_quality_score=Decimal("70"),
            entry_room_state=EntryRoomState.SUFFICIENT,
            is_entry_candidate=True,
            entry_reference_price=Decimal("10.10"),
            data_quality=DataQuality.OK,
            quality_flags=(),
        )

    def fake_plan(*, signal, **_):
        return SimpleNamespace(
            execution_label=(
                ExecutionLabel.B1_READY
                if signal.setup_stage is SetupStage.B1_READY
                else ExecutionLabel.B2_READY
            ),
            days_since_anchor=1,
            is_actionable=True,
            preferred_entry=Decimal("10.10"),
            buy_zone_low=Decimal("10.00"),
            buy_zone_high=Decimal("10.20"),
            invalid_price=Decimal("9.50"),
            s1_price=Decimal("11.00"),
        )

    monkeypatch.setattr(outcome, "evaluate_strategy", fake_signal)
    monkeypatch.setattr(outcome, "merge_signal_quality", lambda signal, *_args, **_kwargs: signal)
    monkeypatch.setattr(outcome, "build_trade_plan", fake_plan)
    kwargs = dict(
        code="603918",
        bars=bars,
        pool=(),
        start=date(2026, 7, 28),
        end=date(2026, 7, 31),
        config=SimpleNamespace(universe=SimpleNamespace(minimum_listing_trade_days=1)),
        trade_plan_config=object(),
        snapshot_id="snap",
        strategy_commit="commit",
        strategy_config_hash="s",
        trade_plan_config_hash="t",
        outcome_config_hash="o",
    )
    events, raw_counts, _, _ = outcome._replay_code(**kwargs)
    assert [event.execution_label for event in events] == [
        ExecutionLabel.B1_READY,
        ExecutionLabel.B2_READY,
    ]
    assert raw_counts[("603918:20260728:1000", ExecutionLabel.B1_READY)] == 2
    assert calls["count"] == len(bars)

    changed = [*bars, make_bar(date(2026, 8, 1), open_price="50", high="60", low="49", close="55", preclose="10", volume="999")]
    changed_events, _, _, _ = outcome._replay_code(**{**kwargs, "bars": changed})
    assert [event.frozen_event_hash for event in changed_events] == [event.frozen_event_hash for event in events]
    future_pool = (SimpleNamespace(trade_date=date(2026, 8, 1)),)
    pool_events, _, _, _ = outcome._replay_code(**{**kwargs, "pool": future_pool})
    assert [event.frozen_event_hash for event in pool_events] == [event.frozen_event_hash for event in events]


def test_spawn_worker_round_trip_is_equivalent_for_a_causal_prefix(project_root):
    """The process boundary must preserve the serial per-code replay result."""

    bars = tuple(
        _bars(
            ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
            ("2026-07-29", "10.00", "10.20", "9.90", "10.10", "10.00", "100"),
        )
    )
    task = {
        "code": "603918",
        "bars": bars,
        "pool": (),
        "start": date(2026, 7, 28),
        "end": date(2026, 7, 29),
        "config": load_strategy_config(project_root / "config" / "strategy.yaml"),
        "trade_plan_config": load_trade_plan_config(
            project_root / "config" / "trade_plan.yaml"
        ),
        "snapshot_id": "snap-test",
        "strategy_commit": "commit-test",
        "strategy_config_hash": "strategy-hash",
        "trade_plan_config_hash": "trade-plan-hash",
        "outcome_config_hash": "outcome-hash",
    }
    serial = outcome._replay_code(**task)
    with ProcessPoolExecutor(
        max_workers=1,
        mp_context=mp.get_context("spawn"),
    ) as executor:
        parallel = executor.submit(outcome._replay_code_worker, task).result(timeout=30)
    assert parallel[:3] == serial[:3]
    assert parallel[3]["evaluate_strategy_calls"] == serial[3]["evaluate_strategy_calls"]
    assert parallel[3]["trade_plan_calls"] == serial[3]["trade_plan_calls"]


def test_worker_diagnostics_do_not_change_deterministic_replay_payload(project_root):
    bars = tuple(
        _bars(
            ("2026-07-28", "10.00", "10.10", "9.90", "10.00", "10.00", "100"),
            ("2026-07-29", "10.00", "10.20", "9.90", "10.10", "10.00", "100"),
        )
    )
    task = {
        "code": "603918",
        "bars": bars,
        "pool": (),
        "start": date(2026, 7, 28),
        "end": date(2026, 7, 29),
        "config": load_strategy_config(project_root / "config" / "strategy.yaml"),
        "trade_plan_config": load_trade_plan_config(project_root / "config" / "trade_plan.yaml"),
        "snapshot_id": "snap-test",
        "strategy_commit": "commit-test",
        "strategy_config_hash": "strategy-hash",
        "trade_plan_config_hash": "trade-plan-hash",
        "outcome_config_hash": "outcome-hash",
    }
    tasks = [task, {**task, "code": "603919"}]
    serial = [outcome._replay_code(**item) for item in tasks]
    with ProcessPoolExecutor(
        max_workers=8,
        mp_context=mp.get_context("spawn"),
    ) as executor:
        parallel = [future.result(timeout=30) for future in [
            executor.submit(outcome._replay_code_worker, item) for item in tasks
        ]]
    assert [item[:3] for item in parallel] == [item[:3] for item in serial]
    assert [len(item[0]) for item in parallel] == [len(item[0]) for item in serial]
    assert [item[3]["evaluate_strategy_calls"] for item in parallel] == [
        item[3]["evaluate_strategy_calls"] for item in serial
    ]
