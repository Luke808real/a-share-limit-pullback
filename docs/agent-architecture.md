# Agent Architecture — V flash 四 Agent 协作架构

Updated: 2026-08-14 (Asia/Shanghai). Owner-approved plan: four specialist
agents + one writer (MAIN). This file is the protocol and guardrail reference;
the operative rules live in AGENTS.md, and role defaults live in
.codex/agents/*.toml.

## Roles

| Role | Files | Mission | Sandbox (Codex) | Forbidden |
| --- | --- | --- | --- | --- |
| MAIN | — | orchestrator; only writer of src/, config/, tests/ | danger-full-access | changing frozen semantics without Owner approval |
| research-strategy | .codex/agents/research-strategy.toml | hypotheses, backtest protocols, studies under research/ | workspace-write | frozen rules/thresholds/strategy.yaml; tuning+validating on the same sample |
| data-processing | .codex/agents/data-processing.toml | provenance, lineage, coverage, reconciliation audits | read-only | data/ zone writes; bypassing ops/warehouse entrypoints |
| news-analysis | .codex/agents/news-analysis.toml | ASL news/announcement ingestion, daily news briefs | workspace-write | feeding news into strategy rules/scores/thresholds |
| performance | .codex/agents/performance.toml | profiling, timing budgets, golden-equivalence checks | read-only | strategy-semantic changes; unverified screen changes |

Generic readers (CODE_READER, DATA_READER, ADVERSARIAL_REVIEWER) remain for
small tasks and HIGH_RISK routes.

## Coordination protocol

1. **Planning**: MAIN decomposes the task and assigns a role route
   (FAST_ANALYSIS / SMALL_CODE / NORMAL / HIGH_RISK / RESEARCH_CYCLE /
   DAILY_RUN, per AGENTS.md).
2. **Parallel inspection**: at most three specialist agents inspect
   concurrently. Each returns a report of 20 lines or fewer plus one
   structured JSON artifact; MAIN archives both under
   docs/agent-reports/<date>/ (reports) and the artifact path the agent
   declares.
3. **Write gate**: only MAIN edits src/, config/, tests/. Specialist agents
   may write only their declared sandbox areas (research/ studies,
   docs/agent-reports/, data/tmp/ reports, ASL staging through ASL's own CLI).
   No two agents edit the same business module concurrently.
4. **Evidence**: every research artifact records input provenance/hash,
   script path, output path/hash, and conclusion status
   (REJECT / OBSERVE_ONLY / SUPPORTED). SUPPORTED != PROMOTED.
5. **Validation**: targeted tests during development; full pytest +
   compileall + git diff --check once at the end. Any screen/fast-path src
   change additionally must reproduce the golden generation
   stategen-2026-08-06-a846075a5ac7 (semantic hash
   5d0817f484b4140061e731190d1863ca3d2f0ed0c7612d374d56eaae7640166e);
   otherwise the change is reverted.

## Backtest division of labor (RESEARCH_CYCLE)

- research-strategy: protocol + study script + conclusion taxonomy; frozen
  input snap-2026-07-31-b5f84004de8a, episodes hash 66d5943f..., execution
  model = existing T+1 daily-bar strict/conservative; no new thresholds.
- data-processing: validates input hashes, snapshot ids, calendar integrity.
- news-analysis: observation-only episode tags (announcements, dragon_tiger);
  insufficient coverage => conclusion REJECT or OBSERVE_ONLY for the tag.
- performance: memory bound (4096 MB gate), time budget, output-hash
  determinism recheck.
- MAIN: archives the study with provenance manifest; nothing is promoted.

## Daily run division of labor (DAILY_RUN)

- MAIN: runs ops daily-run DATE (catchup -> staging -> promotion -> state
  generation -> trade-plan -> news brief -> human watchlist).
- data-processing: audits catchup reconciliation and fail-closed checkpoints.
- news-analysis: produces the daily news brief (OBSERVATION layer).
- performance: checks per-step timings against the budget and golden
  equivalence whenever screen code changed.
- HUMAN: final watch decisions stay outside the system.

## Guardrails

- Frozen artifacts immutable; no threshold loosening to manufacture
  candidates; smallest change that fixes a demonstrated problem.
- data/ is a protected zone for every agent including MAIN except the
  pipeline's own promotion paths.
- ASL lake is read-only from V flash; ingestion happens only through the ASL
  project's own CLI and staging.
- News briefs are OBSERVATION layer: deterministic, explicit N/A on empty or
  failed fetches, never guessed content, never a strategy input.
