# Existing Incremental Daily Screen Audit

Date: 2026-08-02 (read-only code audit; no full-market benchmark completed this turn)

## Current implementation exists

- `python -m limit_pullback screen --as-of YYYY-MM-DD --snapshot-id <id>`
- Per-code persisted state: `data/screen/states/<code>.json`
- State binds `snapshot_id`, `bars_prefix_hash`, `limit_pool_prefix_hash`,
  `strategy_commit`, `config_hash`, `reconciliation_policy_version`.
- Incremental advance uses `previous_signal` + `last_processed_date` when state is valid.

## Why it is not the default fast path today

1. `run_screen()` still calls `load_canonical_market()` and materializes the
   full canonical daily/pool dataset for every screen invocation, even when
   per-code states are valid. State is incremental; data loading is not.
2. State invalidation is strict: a changed `strategy_commit`, `config_hash`,
   `reconciliation_policy_version`, bars prefix, or pool prefix invalidates the
   state and forces that code to be re-evaluated from its full history.
3. No single daily orchestration command exists for
   `update data -> screen latest -> trade-plan -> overlay -> human report`.

## Rebuild fallback conditions

- `--rebuild` requires `--start` and recomputes from that start date.
- Without `--rebuild`, any stale state (commit/config/prefix/date mismatch)
  falls back to full-history evaluation for that code.

## Benchmark status

- Full-market 7/30 rebuild / 7/31 incremental benchmark was NOT run in this
  turn to avoid unbounded memory/time on M5 16GB; existing cached screen runs
  show the full-market path was previously executed successfully.
- `trade-plan` latest cross-section runtime measured earlier: ~4s.
- Recommendation: before optimizing, profile `load_canonical_market` vs
  per-code `screen_code`; the data-load path is the suspected dominant cost.

## Target daily command

No orchestration implemented this turn. Existing building blocks:

```bash
python -m limit_pullback update --as-of <T>
python -m limit_pullback screen --as-of <T> --snapshot-id <id>
python -m limit_pullback trade-plan --as-of <T> --snapshot-id <id>
```
