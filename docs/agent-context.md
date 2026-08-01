# Agent Context Pointer

## Current phase

- Project: `a-share-limit-pullback`
- Phase: `2C.2C` post-close TradePlan execution layer
- Development branch: `feature/phase-2c2c-trade-plan`
- Draft PR: `#7 Add post-close B-point trade plans`
- Starting implementation commit: `22c7f79f22a68770c7000495493c514acc2867e1`

## Frozen strategy baseline

- Strategy version/tag: `phase-2c2b`
- Strategy content commit: `4a4fb8cb91b4f4fa1a8ba330254fe3b188f9ddbc`
- Main integration commit: `d9e2065fb1c09e2032e59db48c5bb06e0e5dc2a6`
- Frozen config entry: `config/strategy.yaml`
- Execution-only TradePlan config: `config/trade_plan.yaml`
- Frozen semantics source: `/Users/luke808/AI/a-share-strategy-brain/01_Strategy/STRATEGY_MASTER.md`
- Current phase source: `/Users/luke808/AI/a-share-strategy-brain/05_Codex/CURRENT_PHASE.md`
- Context Pack: `/Users/luke808/AI/a-share-strategy-brain/exports/LLM_CONTEXT_PACK.md`

## Product boundary

Use existing canonical snapshots and screen states to produce a stateless
post-close observation/transaction plan. `B1_PREP` is an execution label, not a
setup stage. Do not change frozen setup, B1/B2, S1/S2, Entry Room, scoring, or
point-in-time semantics. No intraday data, auto-trading, backtest, HTML, new
database, full-market re-scan, or provider download is part of this phase.

## Current validation snapshot

- Snapshot: `snap-2026-07-31-b5f84004de8a`
- Latest trade-plan output is generated from persisted screen states and
  memory-bounded row-group reads; raw data remains outside Git.
