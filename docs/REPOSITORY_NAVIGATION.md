# Repository Navigation — /Users/luke808/AI/V flash

Updated: 2026-08-12 (Asia/Shanghai)

## Purpose

This repository implements a post-close A-share limit-up pullback system:
strong launch/limit-up -> pullback -> B-point observation/plan -> relaunch.
It is research and screening software; it is not an intraday monitor, broker
client, auto-trader, report generator, or backtester. The current product is a
next-day execution plan derived from an existing canonical snapshot.

## Current progress authority (read first)

This repository does not own project current truth. Read, in order:

1. `/Users/luke808/AI/a-share-strategy-brain/00_Project/AGENT_HANDOFF.md`
2. `/Users/luke808/AI/a-share-strategy-brain/00_Project/CURRENT_STATE.md`
3. `/Users/luke808/AI/a-share-strategy-brain/05_Codex/CURRENT_PHASE.md`
4. `/Users/luke808/AI/a-share-strategy-brain/exports/LLM_CONTEXT_PACK.md`

Resolve those files at the verified Brain remote `main` SHA recorded in
[CURRENT_STATE.md](CURRENT_STATE.md). Local copies of the Brain checkout
may lag the remote; never substitute cached refs for the verified remote SHA.

Historical entrypoints (not current truth):

- `.codex/HANDOFF.md` — provider-switch handoff dated 2026-08-02; stale against
  the current Git state, preserved as history.
- [HANDOFF_2026-08-05.md](HANDOFF_2026-08-05.md) — dated environment/API
  handoff, historical.
- [HANDOFF_TEMPLATE.md](HANDOFF_TEMPLATE.md) — the compact task handoff
  template still in use.

## Directory map

| Path | Role |
| --- | --- |
| `src/limit_pullback/` | Package: models, screen, strategy, warehouse, providers, ops/runtime entrypoints. |
| `tests/` | Offline test suite (defaults stay offline; provider integration only on request). |
| `config/` | `strategy.yaml`, `trade_plan.yaml`, `outcome_study.yaml`, `runtime.yaml`. |
| `research/` | Research scripts, dated study reports, case sets, runs, and study outputs. |
| `research/factor-lab/` | L2/L3 research layer: factor catalog, cohort scripts, reports (see its README). |
| `src/limit_pullback/factor_lab/` | PIT factor pure functions (research layer; never feeds frozen semantics). |
| `docs/ARCHITECTURE_GOAL.md` | Three-layer decoupling goal (frozen engine / factor lab / validation). |
| `docs/` | Navigation, handoffs, current-state pointer, strategy/operating docs. |
| `data/` | Local market-data warehouse (real data, gitignored, protected; never commit or clean). |
| `.venv/` | Local virtualenv (protected, regenerable). |
| `.codex/` | Local Codex metadata plus versioned workflow contract (`config.toml`, skills). |
| `.goal-task/` | Active goal execution state (cleanup task in progress). |
| `ops` | Bash wrapper: `exec .venv/bin/python -m limit_pullback.ops "$@"`. |
| `examples/` | Example scripts (untracked; usage to be documented during cleanup). |

## Protected data boundary

`data/**` is a no-write protected zone: raw provider files, canonical
snapshots, manifests, lineage, validation, screen runs, forward/outcome
studies, receipts, logs, and `warehouse.duckdb` must never be moved, renamed,
deleted, compacted, or opened read-write. DuckDB/SQLite/Parquet/market-data
files anywhere else in the repository are protected by default too. This
repository tracks no committed market data; `.gitignore` excludes `data/`.

## Frozen semantics and research boundaries

Do not change `setup_stage`, LIMIT_ANCHOR, WATCH_PULLBACK, B1_READY, B2_READY,
B2_CONFIRMED, INVALID, S1/S2, Entry Room, setup/entry quality, or the frozen
B1/B2 thresholds without explicit user approval. Structure and execution stay
separate. Research conclusions use the REJECT / OBSERVE_ONLY / SUPPORTED
taxonomy; SUPPORTED is not PROMOTED. Production changes require a PR plus human
approval.

## Cleanup task state

The active repository-cleanup goal keeps its execution contract and item-level
tracker in `.goal-task/vflash-repository-cleanup/` (`state.md`, `todo.md`,
`evidence/`). Cleanup decisions must preserve data, frozen artifacts, Git
history, and all pre-existing local work; anything `UNKNOWN` stays.

## Development history map (2026-08-12 snapshot)

Snapshot facts from `git log`/`git for-each-ref`/`git worktree list`; refresh
with live Git state before acting on any branch or worktree.

### Current main worktree

- Branch `stabilize/pr-e-atomic-state-generation` has no upstream, but its HEAD
  `0f08348` (DAILY_20260806: ADR-008 catch-up, generic promotion sessions,
  state generation) is an ancestor of `origin/main` `1cb5fb7` — it was merged
  through PR #36/#37. The branch itself remains the local development line;
  the product baseline is `origin/main`.
- The branch history is a PR-series stack (PR-A stop-use guards, PR-B
  ADR-008 data correctness, PR-C derived pool universe, PR-D atomic snapshot
  promotion, PR-E state generation) built on top of merged production work.
- The worktree carries local-only development: modified tracked files plus
  untracked `ops`/`runtime`/`fast_path`/`b2_confirmation`/`daily_catchup`
  modules, config, tests, and research scripts. These are coupled (tracked
  `screen/generation.py`, `strategy/engine.py`, `models/*`, `strategy/*`
  import them), so they are active local work, not debris.

### Registered worktrees (2026-08-12 cleanup applied)

As of 2026-08-12, the 60 non-main worktrees (ASL migration/query/validator,
second-launch/R9 factor research, cloudflare PoCs, governance, and the two
Codex automatic worktrees) were removed by the worktree-cleanup goal. All
branches, commits, tags, stashes, and remotes were preserved; every removed
checkout can be re-created with `git worktree add <path> <branch>`.

- The before/after worktree inventory and per-checkout recovery receipts are
  in `.goal-task/vflash-worktree-cleanup/` (inventory TSV, archive/<slug>/
  receipts, evidence/removal/ logs, evidence/FINAL_REPORT.md).
- `git worktree list` currently returns exactly one entry: this main worktree.

### Merged production history

27 local branches and 23 remote branches are merged into `origin/main`
(`1cb5fb7`). Recent merged work includes PR #22/#23 (intraday success pattern
research), PR #24 closeout, ADR-008 data correctness, and snapshot/state
generation. Use `git log origin/main` for the authoritative merged line.
