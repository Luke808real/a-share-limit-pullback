"""Phase-1B shadow-harness unit tests (offline)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "research" / "asl_phase1b")
)

import pytest  # noqa: E402

from shadow import (  # noqa: E402
    AS_OF,
    HISTORY_START,
    WINDOW_START,
    classify_code_inputs,
    compute_phase1b_gate,
    derive_episodes,
    episode_signature,
    eval_point_classes,
    exit_code_for_gate,
    strategy_signature,
)


def _row(day: date, close: str, preclose: str, is_st=None):
    return {
        "trade_date": day,
        "code": "000001",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "preclose": preclose,
        "volume": "100000",
        "amount": "1000000.00",
        "trade_status": True,
        "is_st": is_st,
    }


def _days(count: int, start: date = HISTORY_START) -> list[date]:
    return [start + timedelta(days=index) for index in range(count)]


def test_input_equivalent_when_identical():
    days = _days(10)
    legacy = [_row(day, "10.00", "9.90") for day in days]
    asl = [_row(day, "10.00", "9.90") for day in days]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"] is None
    classes = eval_point_classes(
        info["per_date_class"], days, [days[5]]
    )
    assert classes[days[5]] == "INPUT_EQUIVALENT"


def test_legacy_hole_repaired_by_asl():
    days = _days(10)
    legacy = [_row(day, "10.00", "9.90") for day in days if day != days[5]]
    asl = [_row(day, "10.00", "9.90") for day in days]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "LEGACY_HOLE_REPAIRED_BY_ASL"
    assert info["first_divergence"]["date"] == days[5].isoformat()
    classes = eval_point_classes(
        info["per_date_class"], days, [days[4], days[5]]
    )
    assert classes[days[4]] == "INPUT_EQUIVALENT"
    assert classes[days[5]] == "LEGACY_HOLE_REPAIRED_BY_ASL"


def test_old_hole_ages_out_of_window():
    """A hole older than the required window must not poison later eval
    points (uniform-shift invariance)."""

    days = _days(40)
    legacy = [_row(day, "10.00", "9.90") for day in days if day != days[5]]
    asl = [_row(day, "10.00", "9.90") for day in days]
    info = classify_code_inputs("000001", legacy, asl, set())
    late = days[30]
    classes = eval_point_classes(
        info["per_date_class"], days, [late], window_bars=10
    )
    assert classes[late] == "INPUT_EQUIVALENT"


def test_legacy_only_detected():
    days = _days(10)
    legacy = [_row(day, "10.00", "9.90") for day in days]
    asl = [_row(day, "10.00", "9.90") for day in days if day != days[3]]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "LEGACY_ONLY"


def test_hard_field_conflict_detected():
    days = _days(10)
    legacy = [_row(day, "10.00", "9.90") for day in days]
    asl = [_row(day, "11.00", "9.90") for day in days]  # close off by 10%
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "HARD_FIELD_CONFLICT"
    assert info["hard_conflicts"]


def test_preclose_era_detected_without_ca_evidence():
    days = _days(10)
    # Legacy exchange-precLose era: preclose != previous close.
    legacy = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "9.95"),  # exchange-style adjusted preclose
        _row(days[2], "10.10", "10.05"),
    ]
    # ASL sequential: preclose == previous close.
    asl = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "10.00"),
        _row(days[2], "10.10", "10.05"),
    ]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert (
        info["first_divergence"]["input_class"]
        == "LEGACY_PRECLOSE_ERA_DIVERGENCE"
    )


def test_pit_st_upgrade_detected():
    days = _days(10)
    legacy = [_row(day, "10.00", "9.90", is_st=False) for day in days]
    asl = [_row(day, "10.00", "9.90", is_st=True) for day in days]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "PIT_ST_DATA_UPGRADE"


def test_st_none_vs_false_is_not_a_divergence():
    """legacy is_st=None vs ASL is_st=False must NOT diverge (both are
    not-True; strategy behavior identical)."""

    days = _days(10)
    legacy = [_row(day, "10.00", "9.90", is_st=None) for day in days]
    asl = [_row(day, "10.00", "9.90", is_st=False) for day in days]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"] is None


def test_strategy_signature_deterministic():
    class Item:
        pass

    def make(stage):
        item = Item()
        item.setup_stage = type("S", (), {"value": stage})()
        item.anchor_snapshot = None
        item.score_profile = type("P", (), {"value": "PRICE_ONLY"})()
        item.normalized_score = type("D", (), {"__str__": lambda s: "50.00"})()
        item.setup_quality_score = type("D", (), {"__str__": lambda s: "50.00"})()
        item.entry_quality_score = None
        item.is_entry_candidate = False
        item.review_group = type("R", (), {"value": "STANDARD"})()
        item.event_flags = ()
        item.invalidation_reasons = ()
        item.primary_pattern = None
        return item

    assert strategy_signature(make("NORMAL")) == strategy_signature(make("NORMAL"))
    assert strategy_signature(make("NORMAL")) != strategy_signature(make("B1_READY"))


def test_episode_derivation_and_matching():
    class Item:
        pass

    def anchor_item(day, anchor_date, anchor_price, stage):
        item = Item()
        item.trade_date = day
        item.setup_stage = type("S", (), {"value": stage})()
        anchor = type("A", (), {})()
        anchor.anchor_date = anchor_date
        anchor.anchor_price = anchor_price
        item.anchor_snapshot = anchor
        item.score_profile = type("P", (), {"value": "PRICE_ONLY"})()
        return item

    anchor = date(2026, 6, 1)
    timeline = [
        anchor_item(date(2026, 6, 1), anchor, "10.00", "LIMIT_ANCHOR"),
        anchor_item(date(2026, 6, 2), anchor, "10.00", "WATCH_PULLBACK"),
        anchor_item(date(2026, 6, 3), anchor, "10.00", "B1_READY"),
    ]
    episodes = derive_episodes(timeline)
    assert len(episodes) == 1
    assert episodes[0]["anchor_date"] == anchor.isoformat()
    assert episodes[0]["max_stage"] == "B1_READY"
    assert episodes[0]["stage_dates"]["B1_READY"] == date(2026, 6, 3).isoformat()
    assert episode_signature(episodes[0]) == episode_signature(
        derive_episodes(timeline)[0]
    )


@pytest.mark.parametrize(
    ("data_blocked", "resource_ok", "hard", "unknown_input", "engine_fail", "unknown_ep", "expected"),
    [
        (True, True, 0, 0, 0, 0, "BLOCKED_DATA"),
        (False, False, 0, 0, 0, 0, "BLOCKED_RESOURCE"),
        (False, True, 3, 0, 0, 0, "BLOCKED_PARITY"),
        (False, True, 0, 1, 0, 0, "BLOCKED_PARITY"),
        (False, True, 0, 0, 2, 0, "BLOCKED_PARITY"),
        (False, True, 0, 0, 0, 1, "BLOCKED_PARITY"),
        (False, True, 0, 0, 0, 0, "PASS"),
    ],
)
def test_phase1b_gate(
    data_blocked, resource_ok, hard, unknown_input, engine_fail, unknown_ep, expected
):
    gate = compute_phase1b_gate(
        data_blocked=data_blocked,
        resource_ok=resource_ok,
        hard_field_conflict_n=hard,
        unknown_input_divergence_n=unknown_input,
        strategy_engine_parity_failures_n=engine_fail,
        unknown_episode_divergence_n=unknown_ep,
    )
    assert gate == expected
    assert (exit_code_for_gate(gate) == 0) == (gate == "PASS")


def test_unexplained_divergence_blocks():
    gate = compute_phase1b_gate(
        data_blocked=False,
        resource_ok=True,
        hard_field_conflict_n=0,
        unknown_input_divergence_n=1,
        strategy_engine_parity_failures_n=0,
        unknown_episode_divergence_n=0,
    )
    assert gate == "BLOCKED_PARITY"
    assert exit_code_for_gate(gate) == 2


def test_equivalent_input_strategy_mismatch_blocks():
    gate = compute_phase1b_gate(
        data_blocked=False,
        resource_ok=True,
        hard_field_conflict_n=0,
        unknown_input_divergence_n=0,
        strategy_engine_parity_failures_n=1,
        unknown_episode_divergence_n=0,
    )
    assert gate == "BLOCKED_PARITY"
