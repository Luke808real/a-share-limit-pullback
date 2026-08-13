# REF-R7 Replay vs Daily Divergence Inventory

Pre-code inventory at Runtime code base `1cb5fb7a…` (post REF-R6, HEAD 94b9dae).
Both paths already share the same domain core (`state/engine.evaluate_strategy`,
features, selection); divergence is orchestration only.

## Shared core (already unified)

- `state/engine.evaluate_strategy` (same transition/snapshot/event logic)
- `features.common` math/views, `selection.ranking.build_score`
- PIT prefix semantics and frozen snapshot eligibility

## Divergence points

| Area | replay.py (`replay_stock`) | screen path (`screen/engine.py::screen_code` + `screen/runner.py`) |
| --- | --- | --- |
| Indicator preparation | `calculate_indicators(bars, config.indicators)` once per code, then per-day `evaluate_strategy` without `precomputed_indicators` | one-pass `calculate_indicators(ordered, ...)` per code, per-day calls pass `precomputed_indicators` + `indicator_end_index` (prefix view) |
| Predecessor | `previous_signal` from the in-memory timeline | `previous_signal` from persisted screen state files / generation predecessor resolution |
| Output assembly | `ReplayOutput` with `ReplayTimelineItem` summaries | spool rows → chunk JSON → merged run artifact (4.27 GB embedded rows) |
| Data source | provider-driven (`inspect/replay` fixed sources) | offline canonical snapshot (data layer) |
| Run loop | single stock, sequential days | full-market chunked multiprocess |

## Unification targets

- `runtime/common`: shared per-day evaluation helper (bars prefix + indicators +
  predecessor + policy) consumed by both loops.
- `runtime/replay`: replay orchestration wrapper (existing replay semantics).
- `runtime/daily`: daily orchestration wrapper (existing screen/runner semantics).
- `runtime/live`: interface reservation only.

## Parity anchors

- Frozen full-market rebuild `9abb16e4…` (R0 baseline, reproduced every phase).
- Frozen 20-stock rebuild replay: 11,378 rows, field-identical, hash
  `6c2ffc2235fabd9e32c3aff227fc27d9aac622cb68a1fa6c9ba99a8d1d18b418`
  (Brain CHANGELOG, phase-2c2b; local reproduction still needs the frozen
  code list).
- Per-day field parity probe: on the frozen snapshot, `screen_code` timeline
  must equal `replay`-equivalent per-day signals field-for-field.
