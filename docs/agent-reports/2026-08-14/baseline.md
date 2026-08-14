# Agent Architecture v01 — Baseline Lock (2026-08-14, Asia/Shanghai)

Recorded by MAIN at execution start. Facts below are authoritative for this
runbook; refresh with live Git state before acting on any branch or worktree.

## Repository & Git

- repo: /Users/luke808/AI/V flash (remote Luke808real/a-share-limit-pullback)
- feature branch (this work): feat/agent-architecture-v01 @ 0f08348
- parent HEAD: 0f08348 "DAILY_20260806: ADR-008 catch-up, generic promotion
  sessions, state generation" (branch stabilize/pr-e-atomic-state-generation)
- uncommitted local WIP: 68 entries preserved untouched (screen/strategy
  refactor + untracked research). This work never stages or commits them.

## Strategy authority (read-only for this work)

- frozen strategy: phase-2d0; frozen snapshot snap-2026-07-31-b5f84004de8a
- brain next-prompt flags: PRODUCTION=false FORWARD=false TRADEPLAN=false
  PRIMARY_OOS=false
- frozen semantics: setup_stage / B1/B2 / S1/S2 / Entry Room / quality scores /
  thresholds — no change without explicit Owner approval
- config/strategy.yaml must remain byte-identical unless separately approved

## Golden equivalence anchors (performance agent gate)

- golden generation: stategen-2026-08-06-a846075a5ac7
- state semantic root hash:
  5d0817f484b4140061e731190d1863ca3d2f0ed0c7612d374d56eaae7640166e
- compact output hash:
  d38716807b547dfd6e7217218d51cf79cfdc78e485d4b3ae52051b656c207975
- reference check script: .goal-task/refactor-check/equiv_0806.py

## Test baseline

- pytest: 512 passed, 25 deselected, 233.27s (offline, 2026-08-14)

## Data landscape

- V flash warehouse: data/ (protected zone, gitignored)
- ASL lake: /Users/luke808/AI/asl-shared/duckdb/ashare-lake.duckdb (read-only)
  - daily_bars: 4,887,134 rows, 2023-08-07 .. 2026-08-13
  - news/announcement tables exist with schema but 0 rows:
    news_headlines, flash_news_wire, announcement_index, dragon_tiger,
    sentiment_scores, analyst_consensus, regulatory_events, economic_calendar
- ASL ingestion machinery: ashare-lake-architecture-convergence-v01
  registered steps include flash_news_wire, news_headlines,
  announcement_index, dragon_tiger, economic_calendar; CLI: asl run /
  run-daily / run-catchup

## Daily pipeline (current, pre-orchestration)

1. ops daily DATE: fetch_daily_delta (TDX/Tencent) -> ADR-008 staging ->
   Baostock no-trade verify -> derived limit events -> promote_snapshot ->
   build_state_generation (fast path, seeded states) -> sentinel checks;
   summaries under data/tmp/canonical-catchup-DATE/
2. trade-plan --as-of DATE --snapshot-id SNAP (B1_PREP + next-day plan)
3. ASL advance-screen via research scripts (e.g. asl_screen_20260813_v01.py)
4. human review docs under research/daily-review/ (latest 2026-08-05)

## Performance anchors

- full-market cold rebuild ~7.3 min (PR #19 merged)
- trade-plan cross-section ~4 s
- known hotspot: load_canonical_market full materialization
- config/runtime.yaml: tencent_workers 16, canonical_reader_threads 4,
  canonical_reader_memory_limit 2GB, screen_process_workers 4,
  screen_worker_memory_limit_mb 512, daily_window_calendar_days 400

## Plan

Approved by Owner (2026-08-14). Phases: 0 baseline / 1 agent framework /
2 pipeline audit + perf baseline / 3 news capability / 4 daily-run
orchestration / 5 backtest cooperation study / 6 validation + handoff.
