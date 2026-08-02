# Project Purpose

This repository implements a post-close A-share limit-up pullback system:
strong launch/limit-up -> pullback -> B-point observation/plan -> relaunch.
It is research and screening software, not an intraday monitor, broker client,
auto-trader, report generator, or backtester.

The current product is a next-day execution plan from an existing canonical
snapshot. `B1_PREP` is an execution label; it is not a `setup_stage`.

# Required Context

Before a strategy or TradePlan task, read only the smallest relevant set:

- `docs/agent-context.md`
- `config/strategy.yaml`
- `config/trade_plan.yaml` for execution-only observation thresholds
- the directly relevant source and tests
- the current Context Pack in `/Users/luke808/AI/a-share-strategy-brain/exports/LLM_CONTEXT_PACK.md`
- the phase pointer in `/Users/luke808/AI/a-share-strategy-brain/05_Codex/CURRENT_PHASE.md`

For frozen-rule questions also read the relevant sections of
`STRATEGY_MASTER.md`, `RULE_CATALOG.md`, and `BASELINE_MANIFEST.yaml`.
Do not scan the whole code repository or Vault for a small task. If chat and
the knowledge base disagree, the reviewed/frozen knowledge-base rule wins.

# Frozen Semantics

Without explicit user approval, do not change `setup_stage`, LIMIT_ANCHOR,
WATCH_PULLBACK, B1_READY, B2_READY, B2_CONFIRMED, INVALID, S1/S2, Entry Room,
setup/entry quality scores, or the frozen B1/B2 thresholds.

Keep structure and execution separate. A setup may be `B2_READY` while
`is_entry_candidate` is false. Execution-layer labels and buy-zone checks must
not rewrite a frozen setup lifecycle. All calculations remain point-in-time.

# Project Invariants

- Frozen artifacts immutable.
- Research cannot tune and validate on same sample.
- Forward sample cannot influence historical parameter selection.
- Production changes require PR + human approval.
- Research artifacts must record: input provenance/hash, script, output, conclusion status.
- Research conclusion taxonomy: REJECT / OBSERVE_ONLY / SUPPORTED.
- SUPPORTED != PROMOTED.
- Position sizing research requires proven entry edge first.

# Development Principles

- Make the smallest implementation that fixes a demonstrated problem.
- Do not loosen thresholds to manufacture candidates.
- Do not pre-build future services, databases, caches, or abstractions.
- Do not guess paths, commands, data, or provider behavior.
- Keep default tests offline; run real-provider integration only when requested.
- Keep large snapshots memory-bounded; never materialize the full market unless
  the task explicitly requires it and the memory cost is known.

# Multi-Agent Rule

Use at most three read-only readers by default: CODE_READER,
DATA_READER (the existing data/strategy reader), and ADVERSARIAL_REVIEWER.
They inspect and report only.
The main agent is the only writer. Do not let multiple agents edit the same
business module, tests, configuration, or strategy code.

# Adaptive Parallel Execution

- `FAST_ANALYSIS`: Main plus an optional `DATA_READER` for existing frozen
  artifacts (Parquet/JSON/reports), descriptive statistics, diagnosis,
  robustness, or hash validation. Do not start CODE_READER or
  ADVERSARIAL_REVIEWER by default; Main may work alone for simple aggregation
  or formatting.
- `SMALL_CODE`: Main plus an optional `CODE_READER`.
- `NORMAL`: Main with `CODE_READER` and `DATA_READER` in parallel while Main
  performs read-only preparation.
- `HIGH_RISK`: Main with all three readers in parallel for strategy semantics,
  B1/B2, execution models, PIT, backtest correctness, reconciliation, or
  historical statistical claims that may alter strategy conclusions.
- For `HIGH_RISK`, `ADVERSARIAL_REVIEWER` must report before final validation.
- Keep exactly one writer (Main); readers are read-only and do not spawn agents.
- For routes with two independent readers, Main may implement after their
  reports agree; use targeted tests during development and run full validation
  once at the end.
- Reuse frozen artifacts before expensive computation. Keep reader reports to
  20 lines or fewer.
- `FAST_ANALYSIS` latency guard: do not scan the whole repository, create a
  worktree, or run full replay; use targeted tests during development and run
  full pytest at most once. If data analysis exceeds 60 seconds, check for an
  accidentally expensive path. Aim for a 3–8 minute wall time.

# Git

Work on the requested feature branch. Never rebase, force-push, or squash a PR.
Do not merge a PR unless the user explicitly requests merge after human review.
Keep Draft PRs Draft until human review. Never commit raw行情, `/tmp` artifacts,
tokens, environment files, screenshots, or caches.

# Validation

Default checks:

```bash
pytest -q
python -m compileall -q src tests
git diff --check
```

# Handoff

End each task with the compact structure in `docs/HANDOFF_TEMPLATE.md`:
STATUS, CHANGED, OBSERVED, DECISIONS_NEEDED, VALIDATION, BLOCKERS, NEXT.
