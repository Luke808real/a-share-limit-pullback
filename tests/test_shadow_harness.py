"""Phase-1B shadow-harness tests (offline) - review-fix round 1.

Regressions cover the independent-review findings:

* mutual trailing absence keeps earlier history (code not dropped)
* skipped codes never count as evaluated; skips -> BLOCKED_DATA
* UNKNOWN_INPUT_DIVERGENCE is reachable (unproven preclose divergence)
* code-specific corporate-action attribution (CA for A cannot explain B)
* preclose-era attribution requires CA evidence
* corporate-action intersection compares the actual ASL row
* trade_status mismatch is a hard field conflict
* legacy ST=True + ASL None -> ST_COVERAGE_UNKNOWN (not PIT upgrade)
* trusted ST upgrade requires trusted ASL provenance
* common-calendar control produces >0 equivalent eval points, 0 mismatches
* episode exactness breaks when B2_READY timing differs
* success/control cases compared at candidate_date
* volume-only mismatch inside an eval window blocks; outside is inert
* final Phase-1B gate blocks control-vacuous / control-mismatch /
  unknown-AS_OF-root-cause / decision-relevant ST-unknown states
* counterfactual hole-mask ablation restores the legacy final signature
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "research" / "asl_phase1b")
)

import pyarrow as pa
import pyarrow.parquet as pq
import pytest  # noqa: E402

from shadow import (  # noqa: E402
    AS_OF,
    HISTORY_START,
    WINDOW_START,
    aggregate_success_control,
    classify_code_inputs,
    common_calendar_control,
    compute_phase1b_gate,
    derive_episodes,
    episode_signature,
    eval_point_classes,
    exit_code_for_gate,
    load_legacy_canonical,
    process_code,
    run_counterfactuals,
    strategy_signature,
)
from shadow import _load_asl_recursive  # noqa: E402
from limit_pullback.config import load_strategy_config  # noqa: E402

CONFIG = load_strategy_config("config/strategy.yaml")

# April 2026 trading sessions inside the window (Mon-Fri).
APRIL_DAYS = [
    date(2026, 4, 1),
    date(2026, 4, 2),
    date(2026, 4, 3),
    date(2026, 4, 6),
    date(2026, 4, 7),
    date(2026, 4, 8),
    date(2026, 4, 9),
    date(2026, 4, 10),
]


def _row(
    day: date,
    close: str,
    preclose: str,
    is_st=None,
    trade_status=True,
    volume="100000",
    amount="1000000.00",
    trust=None,
    code="000001",
    open_=None,
    high=None,
    low=None,
):
    return {
        "trade_date": day,
        "code": code,
        "open": open_ or close,
        "high": high or close,
        "low": low or close,
        "close": close,
        "preclose": preclose,
        "volume": volume,
        "amount": amount,
        "trade_status": trade_status,
        "is_st": is_st,
        "asl_status_trust": trust,
    }


def _days(count: int, start: date = HISTORY_START) -> list[date]:
    return [start + timedelta(days=index) for index in range(count)]


# ---------------------------------------------------------------- classification

def test_input_equivalent_when_identical():
    days = _days(10)
    legacy = [_row(day, "10.00", "9.90") for day in days]
    asl = [_row(day, "10.00", "9.90") for day in days]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"] is None
    assert info["st_class_counts"]["EXACT_STATUS_MATCH"] == len(days)
    classes, _windows = eval_point_classes(
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
    classes, _windows = eval_point_classes(
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
    classes, _windows = eval_point_classes(
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


def test_trade_status_mismatch_is_hard():
    days = _days(10)
    legacy = [_row(day, "10.00", "9.90", trade_status=True) for day in days]
    asl = [_row(day, "10.00", "9.90", trade_status=False) for day in days]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "HARD_FIELD_CONFLICT"
    assert "trade_status" in info["hard_conflicts"][0]["detail"]


def test_unknown_preclose_divergence_reachable():
    """A preclose mismatch WITHOUT code-specific CA evidence is UNKNOWN
    (never silently defaulted to a known class)."""

    days = _days(10)
    legacy = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "9.95"),  # legacy exchange-style preclose
    ]
    asl = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "10.00"),  # ASL sequential
    ]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "UNKNOWN_INPUT_DIVERGENCE"


def test_ca_for_code_a_cannot_explain_code_b():
    """A corporate action on ANOTHER stock on the same day must never explain
    this code's preclose difference."""

    days = _days(10)
    legacy = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "9.95"),
    ]
    asl = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "10.00"),
    ]
    ca = {("000002", days[1])}  # CA for a DIFFERENT code
    info = classify_code_inputs("000001", legacy, asl, ca)
    assert info["first_divergence"]["input_class"] == "UNKNOWN_INPUT_DIVERGENCE"


def test_preclose_cascade_from_repaired_hole_is_proven():
    """A preclose difference where BOTH chains are sequential but the
    predecessor DATES differ is the membership consequence of a repaired
    legacy session (LEGACY_HOLE_REPAIRED_BY_ASL), NOT UNKNOWN."""

    days = _days(10)
    legacy = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "10.00"),
        # legacy lacks days[2] (hole)
        _row(days[3], "10.10", "10.05"),  # legacy preclose = days[1] close
    ]
    asl = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "10.00"),
        _row(days[2], "10.08", "10.05"),
        _row(days[3], "10.10", "10.08"),  # ASL preclose = days[2] close
    ]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "LEGACY_HOLE_REPAIRED_BY_ASL"
    assert info["per_date_class"][days[3]] == "LEGACY_HOLE_REPAIRED_BY_ASL"
    assert info["per_date_class"][days[2]] == "LEGACY_HOLE_REPAIRED_BY_ASL"
    assert "UNKNOWN_INPUT_DIVERGENCE" not in info["per_date_class"].values()


def test_predecessor_divergence_without_asl_only_evidence_is_unknown():
    """Predecessor-date divergence ALONE is insufficient: without explicit
    evidence that the ASL predecessor is an ASL-only (legacy-hole-repaired)
    session, the preclose mismatch stays UNKNOWN (fail closed)."""

    days = _days(10)
    legacy = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "10.00"),
        # legacy has days[3]; ASL lacks days[1] (reverse direction)
        _row(days[3], "10.10", "10.05"),
    ]
    asl = [
        _row(days[0], "10.00", "9.90"),
        _row(days[3], "10.10", "10.00"),  # ASL preclose = days[0] close
    ]
    info = classify_code_inputs("000001", legacy, asl, set())
    # asl_prev_date (days[0]) is a COMMON row, not ASL-only -> not proven.
    assert info["per_date_class"][days[3]] == "UNKNOWN_INPUT_DIVERGENCE"


def test_preclose_era_proven_with_code_ca_evidence():
    """CA-era preclose attribution requires code-specific CA evidence ON the
    date plus the known exchange-precLose pattern."""

    days = _days(10)
    legacy = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "9.95"),
        _row(days[2], "10.10", "10.05"),
    ]
    asl = [
        _row(days[0], "10.00", "9.90"),
        _row(days[1], "10.05", "10.00"),
        _row(days[2], "10.10", "10.05"),
    ]
    ca = {("000001", days[1])}
    info = classify_code_inputs("000001", legacy, asl, ca)
    assert (
        info["first_divergence"]["input_class"]
        == "LEGACY_PRECLOSE_ERA_DIVERGENCE"
    )


def test_preclose_divergence_detected_at_high_price():
    """Preclose is an EXACT contract: a dividend-sized difference at a high
    price must NOT be swallowed by the relative price tolerance."""

    days = _days(10)
    legacy = [
        _row(days[0], "100.91", "92.65"),
        _row(days[1], "98.86", "100.81"),  # legacy exchange preclose
    ]
    asl = [
        _row(days[0], "100.91", "92.65"),
        _row(days[1], "98.86", "100.91"),  # ASL sequential
    ]
    info = classify_code_inputs("000001", legacy, asl, {("000001", days[1])})
    assert (
        info["first_divergence"]["input_class"]
        == "LEGACY_PRECLOSE_ERA_DIVERGENCE"
    )
    info2 = classify_code_inputs("000001", legacy, asl, set())
    assert info2["first_divergence"]["input_class"] == "UNKNOWN_INPUT_DIVERGENCE"


def test_legacy_st_true_asl_none_is_st_coverage_unknown():
    """legacy ST=True + ASL is_st=None + no trusted ASL status row is
    ST_COVERAGE_UNKNOWN, NOT PIT_ST_DATA_UPGRADE."""

    days = _days(10)
    legacy = [_row(day, "10.00", "9.90", is_st=True) for day in days]
    asl = [_row(day, "10.00", "9.90", is_st=None, trust=None) for day in days]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "ST_COVERAGE_UNKNOWN"
    assert info["st_class_counts"]["ST_COVERAGE_UNKNOWN"] == len(days)


def test_legacy_st_false_asl_none_is_non_pit_unknown():
    """legacy ST=False + ASL None is the expected PIT semantic delta
    (LEGACY_NON_PIT_TO_ASL_UNKNOWN), strategy-inert and non-fatal."""

    days = _days(10)
    legacy = [_row(day, "10.00", "9.90", is_st=False) for day in days]
    asl = [_row(day, "10.00", "9.90", is_st=None, trust=None) for day in days]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert (
        info["first_divergence"]["input_class"]
        == "LEGACY_NON_PIT_TO_ASL_UNKNOWN"
    )


def test_trusted_st_upgrade_requires_trust():
    """A true PIT ST upgrade requires trusted ASL provenance."""

    days = _days(10)
    legacy = [_row(day, "10.00", "9.90", is_st=False) for day in days]
    asl = [
        _row(day, "10.00", "9.90", is_st=True, trust="BAOSTOCK_ST")
        for day in days
    ]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "PIT_ST_DATA_UPGRADE"
    assert info["st_class_counts"]["TRUSTED_ASL_ST"] == len(days)


def test_st_unknown_vs_trusted_normal_is_delta():
    """legacy is_st=None vs ASL trusted normal is a documented semantic
    delta (TRUSTED_ASL_NORMAL), not exact parity and not a hard failure."""

    days = _days(10)
    legacy = [_row(day, "10.00", "9.90", is_st=None) for day in days]
    asl = [
        _row(day, "10.00", "9.90", is_st=False, trust="EASTMONEY_SAME_DAY")
        for day in days
    ]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "TRUSTED_ASL_NORMAL"


def test_volume_divergence_in_window_blocks():
    """Volume outside Phase-1A tolerance inside a strategy window is a HARD
    field conflict (OHLC+amount matching is NOT sufficient proof of
    inertness)."""

    days = _days(40)
    legacy = [_row(day, "10.00", "9.90", volume="100000") for day in days]
    asl = [
        _row(day, "10.00", "9.90", volume="97000" if day == days[2] else "100000")
        for day in days
    ]
    info = classify_code_inputs("000001", legacy, asl, set())
    assert info["first_divergence"]["input_class"] == "VOLUME_DIVERGENCE"
    classes, _windows = eval_point_classes(
        info["per_date_class"], days, [days[2]], window_bars=10
    )
    assert classes[days[2]] == "HARD_FIELD_CONFLICT"
    gate = compute_phase1b_gate(
        data_blocked=False,
        resource_ok=True,
        hard_field_conflict_n=1,
        unknown_input_divergence_n=0,
        strategy_engine_parity_failures_n=0,
        control_equivalent_eval_point_n=5,
        control_strategy_mismatch_n=0,
        unknown_episode_divergence_n=0,
        as_of_root_cause_unknown_n=0,
        decision_relevant_st_unknown_n=0,
    )
    assert gate == "BLOCKED_PARITY"


def test_volume_divergence_outside_window_inert():
    """A volume divergence older than every eval window is explicitly
    classified OUTSIDE_EVAL_HISTORY_VOLUME_DIVERGENCE (strategy-inert)."""

    days = _days(40)
    legacy = [_row(day, "10.00", "9.90", volume="100000") for day in days]
    asl = [
        _row(day, "10.00", "9.90", volume="97000" if day == days[2] else "100000")
        for day in days
    ]
    info = classify_code_inputs("000001", legacy, asl, set())
    late = days[30]
    classes, _windows = eval_point_classes(
        info["per_date_class"], days, [late], window_bars=10
    )
    assert classes[late] == "OUTSIDE_EVAL_HISTORY_VOLUME_DIVERGENCE"


# ---------------------------------------------------------------- gate

def test_gate_unknown_input_blocks():
    gate = compute_phase1b_gate(
        data_blocked=False,
        resource_ok=True,
        hard_field_conflict_n=0,
        unknown_input_divergence_n=1,
        strategy_engine_parity_failures_n=0,
        control_equivalent_eval_point_n=5,
        control_strategy_mismatch_n=0,
        unknown_episode_divergence_n=0,
        as_of_root_cause_unknown_n=0,
        decision_relevant_st_unknown_n=0,
    )
    assert gate == "BLOCKED_PARITY"
    assert exit_code_for_gate(gate) == 2


def test_gate_control_requires_nonzero_equivalent():
    """A vacuous zero may never satisfy the control gate."""

    gate = compute_phase1b_gate(
        data_blocked=False,
        resource_ok=True,
        hard_field_conflict_n=0,
        unknown_input_divergence_n=0,
        strategy_engine_parity_failures_n=0,
        control_equivalent_eval_point_n=0,
        control_strategy_mismatch_n=0,
        unknown_episode_divergence_n=0,
        as_of_root_cause_unknown_n=0,
        decision_relevant_st_unknown_n=0,
    )
    assert gate == "BLOCKED_PARITY"


def test_gate_control_mismatch_blocks():
    gate = compute_phase1b_gate(
        data_blocked=False,
        resource_ok=True,
        hard_field_conflict_n=0,
        unknown_input_divergence_n=0,
        strategy_engine_parity_failures_n=0,
        control_equivalent_eval_point_n=10,
        control_strategy_mismatch_n=1,
        unknown_episode_divergence_n=0,
        as_of_root_cause_unknown_n=0,
        decision_relevant_st_unknown_n=0,
    )
    assert gate == "BLOCKED_PARITY"


def test_gate_as_of_unknown_root_cause_blocks():
    gate = compute_phase1b_gate(
        data_blocked=False,
        resource_ok=True,
        hard_field_conflict_n=0,
        unknown_input_divergence_n=0,
        strategy_engine_parity_failures_n=0,
        control_equivalent_eval_point_n=10,
        control_strategy_mismatch_n=0,
        unknown_episode_divergence_n=0,
        as_of_root_cause_unknown_n=1,
        decision_relevant_st_unknown_n=0,
    )
    assert gate == "BLOCKED_PARITY"


def test_gate_decision_relevant_st_unknown_blocks():
    gate = compute_phase1b_gate(
        data_blocked=False,
        resource_ok=True,
        hard_field_conflict_n=0,
        unknown_input_divergence_n=0,
        strategy_engine_parity_failures_n=0,
        control_equivalent_eval_point_n=10,
        control_strategy_mismatch_n=0,
        unknown_episode_divergence_n=0,
        as_of_root_cause_unknown_n=0,
        decision_relevant_st_unknown_n=1,
    )
    assert gate == "BLOCKED_PARITY"


def test_gate_skipped_codes_are_data_blocked():
    gate = compute_phase1b_gate(
        data_blocked=True,
        resource_ok=True,
        hard_field_conflict_n=0,
        unknown_input_divergence_n=0,
        strategy_engine_parity_failures_n=0,
        control_equivalent_eval_point_n=10,
        control_strategy_mismatch_n=0,
        unknown_episode_divergence_n=0,
        as_of_root_cause_unknown_n=0,
        decision_relevant_st_unknown_n=0,
    )
    assert gate == "BLOCKED_DATA"
    assert exit_code_for_gate(gate) == 3


def test_gate_pass_all_conditions():
    gate = compute_phase1b_gate(
        data_blocked=False,
        resource_ok=True,
        hard_field_conflict_n=0,
        unknown_input_divergence_n=0,
        strategy_engine_parity_failures_n=0,
        control_equivalent_eval_point_n=100,
        control_strategy_mismatch_n=0,
        unknown_episode_divergence_n=0,
        as_of_root_cause_unknown_n=0,
        decision_relevant_st_unknown_n=0,
    )
    assert gate == "PASS"
    assert exit_code_for_gate(gate) == 0


def test_process_code_skip_not_evaluated():
    """A code with no ASL bars is skipped and never counted as evaluated."""

    days = APRIL_DAYS
    legacy = [_row(day, "10.00", "10.00") for day in days]
    result = process_code("000001", legacy, [], CONFIG, set(), [])
    assert result["skip"] == "NO_ASL_BARS"
    assert "eval_points" not in result


# ---------------------------------------------------------------- episodes

class _FakeItem:
    pass


def _anchor_item(day, anchor_date, anchor_price, stage, setup_id, score="50.00"):
    item = _FakeItem()
    item.trade_date = day
    item.setup_stage = type("S", (), {"value": stage})()
    anchor = type("A", (), {})()
    anchor.anchor_date = anchor_date
    anchor.anchor_price = anchor_price
    item.anchor_snapshot = anchor
    item.setup_id = setup_id
    item.normalized_score = type("D", (), {"__str__": lambda s: score})()
    return item


def test_episode_derivation_uses_setup_id():
    anchor = date(2026, 6, 1)
    timeline = [
        _anchor_item(date(2026, 6, 1), anchor, "10.00", "LIMIT_ANCHOR", "000001:20260601:1000"),
        _anchor_item(date(2026, 6, 2), anchor, "10.00", "B1_READY", "000001:20260601:1000"),
        _anchor_item(date(2026, 6, 3), anchor, "10.00", "B2_READY", "000001:20260601:1000"),
    ]
    episodes = derive_episodes(timeline)
    assert len(episodes) == 1
    assert episodes[0]["setup_id"] == "000001:20260601:1000"
    assert episodes[0]["first_b1_date"] == date(2026, 6, 2).isoformat()
    assert episodes[0]["first_b2_ready_date"] == date(2026, 6, 3).isoformat()
    assert episodes[0]["b1_normalized_score"] == "50.00"
    assert episode_signature(episodes[0]) == episode_signature(
        derive_episodes(timeline)[0]
    )


def test_episode_b2_timing_differs_not_exact():
    """Same anchor/stages but B2_READY on different dates -> NOT exact."""

    anchor = date(2026, 6, 1)
    timeline_a = [
        _anchor_item(date(2026, 6, 1), anchor, "10.00", "LIMIT_ANCHOR", "000001:20260601:1000"),
        _anchor_item(date(2026, 6, 2), anchor, "10.00", "B1_READY", "000001:20260601:1000"),
        _anchor_item(date(2026, 6, 3), anchor, "10.00", "B2_READY", "000001:20260601:1000"),
    ]
    timeline_b = [
        _anchor_item(date(2026, 6, 1), anchor, "10.00", "LIMIT_ANCHOR", "000001:20260601:1000"),
        _anchor_item(date(2026, 6, 2), anchor, "10.00", "B1_READY", "000001:20260601:1000"),
        _anchor_item(date(2026, 6, 4), anchor, "10.00", "B2_READY", "000001:20260601:1000"),
    ]
    ep_a = derive_episodes(timeline_a)[0]
    ep_b = derive_episodes(timeline_b)[0]
    assert episode_signature(ep_a) != episode_signature(ep_b)


# ---------------------------------------------------------------- control

def test_common_calendar_control_nonvacuous():
    """Common-calendar control on shared membership produces >0 equivalent
    eval points with zero mismatches."""

    legacy = [_row(day, "10.00", "10.00") for day in APRIL_DAYS if day != APRIL_DAYS[3]]
    asl = [_row(day, "10.00", "10.00") for day in APRIL_DAYS]
    control = common_calendar_control("000001", legacy, asl, CONFIG)
    assert control["equivalent_eval_point_n"] > 0
    assert control["mismatch_n"] == 0


# ---------------------------------------------------------------- process_code

def test_process_code_mismatch_counting():
    """DIVERGED_AND_MISMATCHING is counted per eval point with its
    associated class (not only the first mismatch per code)."""

    legacy = [_row(day, "10.00", "10.00") for day in APRIL_DAYS]
    extra = date(2026, 4, 13)
    asl = [_row(day, "10.00", "10.00") for day in APRIL_DAYS] + [
        _row(extra, "11.00", "10.00", open_="10.50", high="11.00", low="10.30")
    ]
    result = process_code("000001", legacy, asl, CONFIG, set(), [])
    assert "skip" not in result
    assert result["diverged_and_mismatching"] >= 1
    assert (
        result["diverged_mismatch_by_class"]["LEGACY_HOLE_REPAIRED_BY_ASL"]
        >= 1
    )
    assert result["equivalent_mismatches"] == []
    assert result["first_result_divergence"]["associated_input_class"] == (
        "LEGACY_HOLE_REPAIRED_BY_ASL"
    )


def _weekdays(start: date, end: date) -> list[date]:
    days = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def test_counterfactual_hole_mask_restores():
    """Masking the repaired-hole rows restores the legacy final signature ->
    PROVEN_ROOT_CAUSE = LEGACY_HOLE_REPAIRED (not UNKNOWN)."""

    days = _weekdays(WINDOW_START, AS_OF)
    extra = date(2026, 8, 5)  # ASL-only limit-up anchor day (legacy hole)
    base = [day for day in days if day != extra]
    legacy = [_row(day, "10.00", "10.00") for day in base]
    asl = (
        [_row(day, "10.00", "10.00") for day in base if day < extra]
        + [_row(extra, "11.00", "10.00", open_="10.50", high="11.00", low="10.30")]
        + [_row(date(2026, 8, 6), "10.80", "11.00")]
    )
    from shadow import build_timeline

    items, _ = build_timeline(legacy, CONFIG, WINDOW_START, AS_OF)
    legacy_final = {i.trade_date: strategy_signature(i) for i in items}.get(AS_OF)
    assert legacy_final is not None and legacy_final[0] == "NORMAL"
    asl_items, _ = build_timeline(asl, CONFIG, WINDOW_START, AS_OF)
    asl_final = {i.trade_date: strategy_signature(i) for i in asl_items}.get(AS_OF)
    assert asl_final is not None and asl_final[0] != "NORMAL"
    cf = run_counterfactuals("000001", legacy, asl, CONFIG, set(), legacy_final)
    assert cf["proven_root_cause"] == "MASK_LEGACY_HOLE_ROWS"
    assert any(
        a["ablation"] == "MASK_LEGACY_HOLE_ROWS" and a["restored_legacy_final"]
        for a in cf["ablations"]
    )


# ---------------------------------------------------------------- success/control

def _dummy_sig(stage, anchor="2026-06-01"):
    return (
        stage,
        anchor,
        "10.00",
        "PRICE_ONLY",
        "50.00",
        "50.00",
        None,
        False,
        "STANDARD",
        (),
        (),
        None,
    )


def test_success_control_uses_candidate_date():
    """Success/control comparison must use the signature AT candidate_date,
    not the AS_OF final signature."""

    cases = [
        {
            "code": "000001",
            "candidate_date": date(2026, 4, 3),
            "candidate_state": "B2_READY",
            "outcome": "WIN",
        }
    ]
    result = {
        "000001": {
            "case_signatures": {
                "2026-04-03": {
                    "legacy": _dummy_sig("B1_READY"),
                    "asl": _dummy_sig("NORMAL"),
                }
            },
            "case_eval_classes": {
                "2026-04-03": "LEGACY_HOLE_REPAIRED_BY_ASL"
            },
        }
    }
    agg = aggregate_success_control(cases, result)
    assert agg["frozen_case_n"] == 1
    assert agg["compared_case_n"] == 1
    assert agg["inclusion_changed_n"] == 1
    assert agg["anchor_changed_n"] == 0
    assert agg["stage_changed_n"] == 1


# ---------------------------------------------------------------- coverage/skip

def _build_synthetic_lake(root: Path) -> tuple[Path, dict[str, list[date]]]:
    """Minimal ASL lake + legacy canonical snapshot for the 000838 shape.

    Codes: 000001 (full 8 April sessions) and 000002 (bars only through
    session index 5 -> trailing mutual absence at index 6).
    """

    predecessor_day = date(2024, 1, 15)
    days = APRIL_DAYS
    instruments = root / "curated" / "instruments"
    instruments.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": ["000001.SZ", "000002.SZ"],
                "list_date": [date(2020, 1, 2), date(2020, 1, 2)],
                "delist_date": [None, None],
            }
        ),
        instruments / "part-merged.parquet",
    )
    cal = root / "curated" / "trading_calendar" / "trade_date=2026"
    cal.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "trade_date": days,
                "is_trading": [True] * len(days),
            }
        ),
        cal / "part-merged.parquet",
    )
    bars_root = root / "curated" / "daily_bars"
    fetched = pa.scalar(
        __import__("datetime").datetime(2026, 8, 7, 2, 0, tzinfo=__import__("datetime").timezone.utc),
        type=pa.timestamp("us", tz="UTC"),
    )

    def bar_table(symbols, day, close="10.00"):
        return pa.table(
            {
                "symbol": symbols,
                "trade_date": [day] * len(symbols),
                "open": [float(close)] * len(symbols),
                "high": [float(close)] * len(symbols),
                "low": [float(close)] * len(symbols),
                "close": [float(close)] * len(symbols),
                "volume": [100000] * len(symbols),
                "amount": [1000000.0] * len(symbols),
                "source": ["tdx_protocol"] * len(symbols),
                "data_version": ["v2"] * len(symbols),
                "fetched_at": [fetched.as_py()] * len(symbols),
            }
        )

    pred = bars_root / "trade_date=2024-01-15"
    pred.mkdir(parents=True)
    pq.write_table(
        bar_table(["000001.SZ", "000002.SZ"], predecessor_day), pred / "part-merged.parquet"
    )
    for day in days:
        partition = bars_root / f"trade_date={day.isoformat()}"
        partition.mkdir(parents=True)
        if day == days[5]:
            # 000002's bar series ends here (trailing mutual absence later).
            symbols = ["000001.SZ", "000002.SZ"]
        elif day <= days[5]:
            symbols = ["000001.SZ", "000002.SZ"]
        else:
            symbols = ["000001.SZ"]
        pq.write_table(bar_table(symbols, day), partition / "part-merged.parquet")

    status_root = root / "curated" / "trading_status" / "trade_date=2026-04"
    status_root.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": pa.array([], type=pa.large_string()),
                "trade_date": pa.array([], type=pa.date32()),
                "is_trading": pa.array([], type=pa.bool_()),
                "status": pa.array([], type=pa.large_string()),
                "source": pa.array([], type=pa.large_string()),
                "data_version": pa.array([], type=pa.large_string()),
                "fetched_at": pa.array([], type=pa.timestamp("us", tz="UTC")),
            }
        ),
        status_root / "part-merged.parquet",
    )

    # Legacy canonical snapshot: CONFIRMED rows, 000002 stops at days[5].
    legacy_rows = []
    for code, max_index in (("000001", len(days) - 1), ("000002", 5)):
        for index, day in enumerate(days[: max_index + 1]):
            legacy_rows.append(
                {
                    "code": code,
                    "trade_date": day,
                    "open": "10.0000",
                    "high": "10.0000",
                    "low": "10.0000",
                    "close": "10.0000",
                    "preclose": "10.0000",
                    "volume": "100000.00000000",
                    "amount": "1000000.00000000",
                    "turnover_rate": None,
                    "pct_change": None,
                    "trade_status": True,
                    "is_st": None,
                    "selected_provider": "TDX",
                    "reconciliation_status": "CONFIRMED",
                    "source_row_hash": "x",
                    "dataset_snapshot_id": "snap-test",
                }
            )
    snapshot = root / "legacy_snapshot.parquet"
    pq.write_table(pa.Table.from_pylist(legacy_rows), snapshot)
    return snapshot, days


def test_mutual_trailing_absence_keeps_history(tmp_path):
    """One mutual trailing absence must NOT drop the code: earlier history is
    preserved and compared up to the last mutually available session."""

    snapshot, days = _build_synthetic_lake(tmp_path)
    legacy = load_legacy_canonical(snapshot, {"000001", "000002"}, HISTORY_START, AS_OF)
    assert set(legacy) == {"000001", "000002"}
    asl, errors, explained, _cov = _load_asl_recursive(
        tmp_path, ["000001", "000002"], HISTORY_START, AS_OF, legacy
    )
    assert not errors, errors
    assert asl is not None
    assert "000002" in asl, "000002 must NOT be dropped"
    assert asl["000002"][-1]["trade_date"] == days[5]
    assert any(item["code"] == "000002" for item in explained)
    result = process_code(
        "000002", legacy["000002"], asl["000002"], CONFIG, set(), []
    )
    assert "skip" not in result
    assert result["eval_points"] > 0
    assert result["final_legacy"] is None or result["final_legacy"][0] == "NORMAL"


# ---------------------------------------------------------------- signature

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
