# REF-R5 State Transition Matrix and Golden Case List

Source of truth: `strategy/engine.py` at code base `1cb5fb7a…` (frozen behavior)
and the existing transition/golden tests. This list describes current behavior;
REF-R5 must not change it.

## Transition matrix (as implemented in evaluate_strategy)

| From (prior day) | To (today) | Condition (frozen) |
| --- | --- | --- |
| any | NORMAL | `detect_anchor` finds no anchor (incl. anchor expired out of lookback) |
| any | LIMIT_ANCHOR | `current.trade_date == anchor.snapshot.anchor_date` |
| any | INVALID | `invalidation_reasons` non-empty: HIT_INVALID_PRICE / SUPPORT_BREAK / ANCHOR_AND_MA10_BREAK / VOLUME_BREAK_B1_LOW / CONSECUTIVE_VOLUME_DISTRIBUTION / FAILED_SUPPORT_RECOVERY; INVALID is terminal and sticky for the same setup_id |
| B1_READY (prior) | B2_READY | prior B1_READY: new platform trigger frozen with `frozen_as_of=as_of`, `eligible_from=as_of+1d` |
| B2_READY/B2_CONFIRMED (prior trigger) | B2_CONFIRMED | frozen trigger `eligible_from <= as_of`; mandatory `intraday_trigger_breakout` + `close_holds_trigger` both matched; other available conditions meet `b2.minimum_condition_ratio` |
| trigger exists (frozen, eligible) | B2_READY | trigger present and not confirmed |
| WATCH_PULLBACK | B1_READY | support + initial invalid present; `b1_conditions.available_count > 0`; `match_ratio >= b1.minimum_condition_ratio`; first-day freeze writes Support/Invalid/Resistance/S1 snapshots with `eligible_from = as_of + 1d` |
| else | WATCH_PULLBACK | default fallthrough |

Lifecycle semantics (frozen vocabulary ACTIVE / INVALIDATED /
SUPERSEDED_BY_NEW_ANCHOR / EXPIRED):

- Supersede: a new valid anchor produces a new `setup_id` via `make_setup_id`;
  the old setup simply stops matching (`previous_same is None`).
- Expire: the anchor leaves the detection lookback window and the code returns
  to NORMAL.
- Invalid price may tighten with new evidence but never loosen within a setup;
  initial invalid price is preserved.

PIT invariants (must hold in every REF-R5 extraction):

- Every judgment at T uses only `trade_date <= T` inputs.
- Frozen snapshots used at T satisfy `eligible_from <= T`; snapshots frozen
  today have `eligible_from > frozen_as_of` and cannot affect today.
- Same-day anchor does not consume same-day structure/support (B1 first day).
- Prefix invariance: bars/pool added after T never change the T signal.

## Golden case list (nine categories, mapped to existing tests)

| # | Category | Evidence (existing tests) |
| --- | --- | --- |
| 1 | Corporate action | `tests/test_corporate_action_preclose.py` (divergence marker, quarantine, inconsistent pct_change blocks, missing preclose never published); `tests/test_strategy_math.py::test_point_in_time_continuous_price_handles_corporate_action` |
| 2 | ST | `tests/test_asl_adapter.py::test_status_semantics_explicit_cases` and `test_data_ports.py` UNKNOWN-not-NORMAL semantics; frozen `is_st` rows |
| 3 | Suspension | `tests/test_asl_adapter.py::test_missing_bar_suspended_allowed`, `::test_missing_bar_normal_status_blocks`, `::test_missing_bar_no_status_blocks`, `::test_historical_eastmoney_suspended_cannot_authorize_missing_bar` |
| 4 | B1 first day | `tests/test_replay.py::test_anchor_and_first_b1_do_not_use_same_day_structure` |
| 5 | Trigger freeze | `tests/test_strategy_engine.py::test_same_day_trigger_cannot_confirm_b2` |
| 6 | B2 confirm | `tests/test_strategy_engine.py::test_close_hold_of_frozen_b2_trigger_confirms`, `::test_intraday_b2_break_without_close_hold_stays_ready` |
| 7 | Invalid | `tests/test_strategy_engine.py::test_golden_invalid_preserves_initial_invalid_price`; `tests/test_replay.py::test_replay_invalid_is_terminal_until_a_new_setup`, `::test_replay_invalid_prices_never_loosen_within_setup` |
| 8 | Supersede | `tests/test_replay.py::test_new_anchor_supersedes_active_setup`; `tests/test_strategy_engine.py::test_new_limit_anchor_creates_new_setup_id` |
| 9 | Expire | `tests/test_replay.py::test_setup_expires_when_anchor_leaves_lookback` |

Plus PIT/prefix gates:
`tests/test_strategy_engine.py::test_signal_ignores_future_price_and_pool_data`,
`::test_future_pressure_change_does_not_change_historical_setup_timeline`,
`tests/test_replay.py::test_replay_timeline_before_t_is_unchanged_by_future_prices`,
`::test_future_bars_do_not_change_historical_s1_or_entry_room`,
`tests/test_screen_gates.py::test_future_pool_row_does_not_change_prefix_hash`.
