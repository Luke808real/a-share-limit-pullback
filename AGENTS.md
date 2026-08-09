# Project Purpose — TWO PLANES

This repository has two distinct planes that must never be conflated.

## PRODUCTION PLANE

```text
ASL / Canonical data
-> immutable Snapshot
-> Universe
-> State Generation
-> Strategy Engine
-> post-close screening / planning
```

The production product is a next-day execution plan from an existing canonical
snapshot. It is not an intraday auto-trader or a broker client. `B1_PREP` is an
execution label; it is not a `setup_stage`.

## RESEARCH PLANE

```text
frozen historical datasets
-> factor research
-> stability / benchmark / multivariate research
-> ASL 5m intraday research
-> prospective observational validation
```

Research capability != Production capability. Research minute data does not
make the production strategy intraday. R0-R8 are development evidence; only a
successful prospective validation (R9) can upgrade a research result to a
strategy candidate.

# Authority Matrix

| Question | Authority |
|---|---|
| 当前用户明确任务 | 当前用户指令 |
| 代码实际行为 | exact HEAD + tests |
| 数据 lineage / availability | manifests / SHA / committed reports |
| 当前研究结论 | latest authoritative research report |
| frozen strategy semantics | STRATEGY_MASTER + RULE_CATALOG + BASELINE_MANIFEST |
| 当前项目阶段 | PROJECT_STATE_SNAPSHOT（KB） |
| 历史记录 | IMPLEMENTATION_LOG / archived reports |

Rules:

```text
- Frozen KB overrides only frozen strategy semantics.
- A stale KB phase note must not override:
  newer exact-HEAD implementation facts,
  newer data provenance,
  newer reviewed research reports.
- DESIGNED / IMPLEMENTED / VALIDATED / PROMOTED
  must not be treated as equivalent.
```

# Required Context

Before a strategy or TradePlan task, read only the smallest relevant set:

- `docs/agent-context.md` (pointer only)
- `config/strategy.yaml`
- `config/trade_plan.yaml` for execution-only observation thresholds
- the directly relevant source and tests
- the current Context Pack and phase pointer from the strategy-brain repo,
  located via `A_SHARE_STRATEGY_BRAIN_ROOT` (or sibling `../a-share-strategy-brain`);
  if not found: `KB_UNAVAILABLE` — do not guess another path.

For frozen-rule questions also read the relevant sections of
`STRATEGY_MASTER.md`, `RULE_CATALOG.md`, and `BASELINE_MANIFEST.yaml`.
Do not scan the whole code repository or Vault for a small task.
Disagreement handling: chat and KB are both subordinate to the Authority
Matrix above; a stale KB phase note never overrides newer exact-HEAD facts,
data provenance, or reviewed research reports.

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
- Research conclusion taxonomy:
  `OBSERVATION` / `HYPOTHESIS` / `SUPPORTED_HYPOTHESIS` / `VALIDATED` /
  `STRATEGY_CANDIDATE` / `PROMOTED`, with orthogonal
  `IMPLEMENTATION_STATUS` (RESEARCH_ONLY / IMPLEMENTED) and
  `PRODUCTION_STATUS` (NOT_PROMOTED / PROMOTED).
- SUPPORTED != VALIDATED != PROMOTED.
- Position sizing research requires proven entry edge first.

# PIT / Prospective Rules

- A historical chronological split is NOT automatically clean out-of-sample
  validation. If the historical cohort participated in feature discovery,
  threshold/checkpoint inspection, or model selection, any later split is
  `DEVELOPMENT_STABILITY` — never `CLEAN_OOS_VALIDATION`.
- Clean prospective validation requires: protocol freeze -> OOS_START strictly
  after freeze -> immutable feature observation -> later independent endpoint.

# Population / Label Rules (fail closed)

```text
- label maturity must never affect:
  candidate existence, setup identity, candidate ordering,
  first observation, event identity.
- outcome / event date / future touch must never participate in prospective
  candidate generation.
- development cohort != prospective population authority unless exact
  outcome-blind equivalence is proven.
```

# Superseded Artifact Rule

An artifact/result marked `SUPERSEDED` / `INVALIDATED` / `LEGACY_ONLY` must
NOT be used as current evidence. Keep its historical provenance, but never
quote it as current truth (e.g., results invalidated by a chronology fix).

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
  B1/B2, execution models, PIT, backtest correctness, reconciliation,
  prospective-validation claims, or historical statistical claims that may
  alter strategy conclusions.
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
  accidentally expensive path. Aim for a 3-8 minute wall time.

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
