# Handoff 2026-08-14 — AGENT_ARCH_V01

STATUS

branch: feat/agent-architecture-v01
commit: 3c6a867 (AGENT_ARCH_V01; 32 files, +2910)
PR: none (branch not pushed; Draft PR one step away, pending Owner request)
worktree: our files committed; pre-existing local WIP (screen/strategy refactor,
AGENTS.md path edit, ops.py as untracked user file) preserved untouched

CHANGED

- .codex/agents/{research-strategy,data-processing,news-analysis,performance}.toml — 4 agent role definitions
- .codex/config.toml — registered the 4 agents alongside the 3 generic readers
- AGENTS.md — Multi-Agent Rule rewritten for the 4-agent architecture + RESEARCH_CYCLE/DAILY_RUN routes (uncommitted: file carries pre-existing user WIP edit)
- docs/agent-architecture.md — roles, sandboxes, coordination protocol, guardrails
- docs/daily-workflow.md — current pipeline map, measured timings, target budget, tuning candidates
- docs/agent-reports/2026-08-14/ — baseline + 4 opening audits (archived)
- src/limit_pullback/news_brief/ — read-only ASL join (news/announcements/dragon-tiger), deterministic content hash, explicit N/A semantics; OBSERVATION layer only
- src/limit_pullback/ops.py — ops news-brief + ops daily-run (fail-closed daily -> trade-plan -> news-brief -> watchlist + timing.json + reconciliation receipt); uncommitted (user's untracked file)
- tests/test_news_brief.py (8) + tests/test_ops_daily_run.py (5) — 13 new offline tests
- research/news-observation-v01/ — ASL ingestion driver + run summary + coverage study + README (EM fast-news same-day-only finding)
- research/backtest-cooperation-v01/ — protocol, inputs-verified, provenance, conclusions; determinism recheck summary (parquet gitignored, hash in provenance)

OBSERVED

- ASL ingestion via ASL JobEngine: announcement_index 4,214 rows (08-10..08-13), dragon_tiger 254 rows; EM fast-news endpoints return only the latest ~200 items => historical backfill impossible, same-day capture only
- httpx rejects socks5h ALL_PROXY; ingestion runs with env -u ALL_PROXY
- execution-reality recompute: 21.5s, derived_rows=31,422, bit-identical output to frozen Phase 2D.1A artifacts (semantic_equal + identical parquet hash)
- frozen cohort E[R] reaffirmed unchanged (e.g. B1_READY_ALL 10bp -0.1730; B1_READY_ENTRY_GE_80 10bp +0.2605 remains observation-only)
- news tags on the frozen historical sample: zero coverage overlap -> REJECT_FOR_THIS_STUDY; forward-only via daily-run news-brief

DECISIONS_NEEDED

1. Whether to also commit AGENTS.md + src/limit_pullback/ops.py (they carry your pre-existing uncommitted work)
2. Whether to push feat/agent-architecture-v01 and open a Draft PR
3. Whether to adopt any runtime.yaml tuning candidate (requires golden-equivalence check first)
4. Whether to wire same-day EM news capture (asl run daily --group research) into the post-close routine
5. Any promotion of OBSERVE_ONLY conclusions — explicitly NOT done here

VALIDATION

pytest: 525 passed, 25 deselected (233s)
compileall: OK
diff-check: OK
runtime validation: execution-reality recheck bit-identical; real news brief produced data/tmp/news-brief-20260813/ (605198 announcement matched)

BLOCKERS

NONE

NEXT

- First real ops daily-run on the next trading day (needs provider data after close)
- Wire same-day EM news capture before news-brief, if Owner approves
