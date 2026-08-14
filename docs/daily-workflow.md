# Daily Workflow — V flash 每日选股流程与时间预算

Updated: 2026-08-14 (Asia/Shanghai). This file maps the post-close daily
pipeline, its owners, and the timing budget. Facts are from the 2026-08-14
agent audits (docs/agent-reports/2026-08-14/); refresh measurements before
tuning runtime.yaml.

## Current pipeline map (pre-orchestration)

| Step | Entrypoint | Agent | Output |
| --- | --- | --- | --- |
| daily catchup fetch (TDX/Tencent) | ops daily DATE | MAIN | data/tmp/canonical-catchup-DATE/fetch-summary.json |
| ADR-008 staging | ops daily DATE | MAIN | staging-summary.json, canonical_candidate.parquet |
| no-trade verification (BaoStock) | ops daily DATE | DATA_PROCESSING (audit) | verified_no_trade list |
| derived limit events | ops daily DATE | MAIN | derived-summary.json |
| snapshot promotion | ops daily DATE | MAIN | promotion-summary.json |
| state generation (fast path) | ops daily DATE | MAIN | stategen-summary.json, screen/generations/<id>/ |
| next-day plan (B1_PREP) | trade-plan --as-of DATE --snapshot-id SNAP | MAIN | plan JSON |
| ASL advance screen | research/asl_screen_*.py (ad-hoc) | MAIN | data/tmp/asl-screen-*/ |
| human review | research/daily-review/<date>-*.md | HUMAN | watchlist docs |

## Measured timings (2026-08-06 run, canonical-catchup-2026-08-06)

| Step | Wall time | Notes |
| --- | --- | --- |
| fetch catchup | UNKNOWN | fetch-summary.json has no wall field |
| staging | UNKNOWN | staging-summary.json has no wall field |
| promotion | 55.6 s | peak_rss 1.54 GB, validation 3.2 s |
| state generation | 384.4 s | fast-path incremental, peak_rss 10.3 GB, state_n 3191 |
| trade-plan cross-section | ~4 s | reads 3191 state JSONs |
| ASL advance screen cross-section | 1.46 s | reads persisted states, no rebuild |

## Target budget (post-close; A-share close 15:00)

| Time (Asia/Shanghai) | Step | Target |
| --- | --- | --- |
| ~15:05 | provider data ready check (TDX/Tencent/BaoStock lag) | gate |
| 15:05-15:15 | catchup + staging + no-trade verify | <90 s compute |
| 15:10-15:15 | promotion | ~60 s |
| 15:15-15:30 | state generation (fast path) | <180 s (now 384 s; tuning candidates below) |
| 15:30-15:35 | trade-plan (B1_PREP + next-day plan) | <5 s |
| 15:35-15:45 | news brief (ASL read-only join) | <120 s |
| ~15:45-16:00 | human watchlist publish + review | manual |

## Performance tuning candidates (proposal stage; runtime-only)

From the performance audit (2026-08-14):

- daily_window_calendar_days 400 -> smaller: directly shrinks fast-path
  incremental replay window and state-gen time.
- Reuse one DuckDB connection across _calendar_sessions /
  _verified_no_trade_from_previous / _previous_trading_session (three
  independent scans of the daily parquet today).
- canonical_reader_threads 4 -> 8/16 and canonical_reader_memory_limit 2GB ->
  larger: faster external-sort reads.
- screen_process_workers 4 -> larger: parallel state build, bounded by the
  10.3 GB peak_rss and the 4096 MB per-worker gate.

Every candidate is runtime-only or data-loading; any change that touches
screen/fast-path logic must reproduce stategen-2026-08-06-a846075a5ac7
(semantic hash 5d0817f484b4140061e731190d1863ca3d2f0ed0c7612d374d56eaae7640166e).

## Orchestration (target state, Phase 4)

ops daily-run DATE — fail-closed chain: daily -> trade-plan -> news brief ->
human watchlist markdown, with per-step timings in
data/tmp/daily-run-DATE/timing.json. Any step failure stops the chain and
keeps already-produced artifacts.
