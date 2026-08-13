# Architecture Constitution — ARCHITECTURE_CONVERGENCE_V01

Status: REF-R1 target-state protocol. This document defines the long-term
architecture and which rules are enforceable today. It is not a second strategy
truth: reviewed/frozen Strategy Brain truth always wins.

Source: `A股「涨停回调再启动」系统目标架构书 — ARCHITECTURE_CONVERGENCE_V01`,
SHA-256 `e2b467d89cdecb15c9cb18a74b81429caa66a8b8c602d47525afafd63669d064`.

## Three planes

| Plane | Repository | Owns |
| --- | --- | --- |
| Data Plane | `rootSunc/ashare-lake` | market facts: acquisition, adapters, fallback, lake, corporate action, historical ST, suspension, calendar, raw OHLCV/minute bars, adjustment facts, provenance, quality, availability, PIT data boundary |
| Runtime Plane | `Luke808real/a-share-limit-pullback` | deterministic computation: canonical consumer contract, features, setup lifecycle/state, eligibility/ranking/presentation, replay/daily, future live interfaces, evidence |
| Control Plane | `Luke808real/a-share-strategy-brain` | human-readable strategy truth, research/ADR/cases/project state, promotion decisions, agent and audit truth |

## Seven runtime domains

`domain`, `data`, `features`, `state`, `selection`, `runtime`, `evidence`,
with `interfaces` as the external entry and a temporary `legacy` area. The
destination layout is a direction, not a one-commit directory move.

## Dependency rules

Target direction:

```text
domain <- data facts
  ^
features
  ^
state
  ^
selection
  ^
runtime
  ^
interfaces

runtime -> evidence
```

Forbidden imports (target state):

- Domain must not import data, features, state, selection, runtime, evidence, or CLI.
- Features must not import selection, runtime, ASL internals, or CLI.
- State must not import selection, filesystem, provider, or CLI.
- Selection must not import raw providers, ASL internals, or filesystem.
- Runtime strategy code must not call providers or ASL table internals directly; it consumes canonical contracts.

## Truth ownership

- Strategy truth exists only in the Brain (`01_Strategy/`). Runtime README, SPEC,
  comments, or config must not become a second strategy definition.
- Runtime must never dynamically read Brain at startup to build strategy rules
  (AC-10). Rule changes flow through ADR → frozen contract → code change →
  regression → human review.
- Data Plane contains no B1/B2/R9/setup/TradePlan semantics.

## Promotion contract

Lifecycle: OBSERVATION → HYPOTHESIS → RESEARCH_CANDIDATE → SUPPORTED →
PROMOTION_CANDIDATE → ADR_APPROVED → FROZEN_CONTRACT → IMPLEMENTED →
GOLDEN_VERIFIED → RUNTIME_ACTIVE. `SUPPORTED != PROMOTED`.

Brain → Runtime must specify: STRATEGY_VERSION, ADR_ID, RULE_IDS, FEATURE_IDS,
expected semantic and artifact change, backward compatibility, migration
requirement, golden update requirement.

Runtime → Brain must return: IMPLEMENTATION_SHA, test result, differential
result, golden result, artifact hash, contract version, code review result.

## Target mapping (direction only)

| Current | Target |
| --- | --- |
| `warehouse/asl_*` | `data/asl` |
| `screen/canonical` | `data/canonical` |
| `universe.py`, `quality.py` | `data/universe`, `data/quality` |
| `strategy/indicators`, `strategy/math` | `features/*`, `features/common` |
| `strategy/patterns`, `strategy/structure` | `features/structure`, Feature + State |
| `strategy/scoring` | `selection/ranking` |
| `screen/state`, `screen/generation`, `screen/runner`, `screen/chunks`, `screen/verify` | `state`, `evidence/generation`, `runtime/daily`, `runtime/common`, `evidence/verification` |
| `replay.py`, `outcome.py`, `cli.py` | `runtime/replay`, `evidence/outcome`, `interfaces/cli` |

## Enforced today (REF-R1)

- Frozen strategy config hashes are asserted by
  `tests/test_architecture_constitution.py`: `config/strategy.yaml`
  `47a0ea2b41952f06f43d1fe3a5e066993bade6ecec45c81103022008c7eae6bf`,
  `config/trade_plan.yaml`
  `06fd5dc96989a47015ad89ec543ad41784d7ef3eba074f17b679bd99d73a3c00`.
- `SetupStage` stays exactly
  `NORMAL/LIMIT_ANCHOR/WATCH_PULLBACK/B1_READY/B2_READY/B2_CONFIRMED/INVALID`.
- `models/` and `strategy/` contain no provider or warehouse imports.
- `CanonicalDailyBar` keeps single-provider lineage fields
  (`selected_provider`, `source_row_hash`, `dataset_snapshot_id`,
  `trade_status`, `is_st`, `reconciliation_status`).
- `screen/generation.py` lifecycle constants stay
  `STAGED/VERIFIED/ACTIVE/REJECTED`.

## Constitution MUST clauses (documented anchors, not enforced yet)

These Architecture Constitution MUST clauses are quoted as target-state anchors
so REF-R3..R8 gates have in-repository text to point at. They are documentation,
not new code enforcement:

- AC-01 single strategy truth: only Brain `01_Strategy/` may define human-readable
  strategy truth.
- AC-02 single data boundary: formal Runtime strategy consumes canonical market
  facts only; Strategy must not reach AKShare/TDX/Tencent/ASL table internals.
- AC-03 Feature != Rule: a computed fact and the policy threshold that judges it
  live in different places.
- AC-04 State != Ranking: lifecycle state and attention ranking are separate
  engines; B2_READY does not imply Top5.
- AC-05 one domain core: Replay, Daily, and future Live share the same domain
  core; no backtest/daily/live triple implementation.
- AC-06 PIT first: any judgment at time T uses only `known_as_of <= T` data;
  frozen snapshots satisfy `eligible_from > frozen_as_of`.
- AC-07 evidence first: important results become artifact + manifest + hash +
  provenance + verifier, not just a Python return value.
- AC-08 fail closed: source conflict, missing predecessor, ambiguous lineage,
  bad snapshot, unknown ST, invalid preclose, or incomplete coverage defaults to
  STOP/BLOCK, never silent fallback.
- AC-09 immutable historical evidence: refactoring never rewrites historical
  snapshots, generations, outcomes, episodes, receipts, hashes, or forward
  epochs; new runs produce new evidence.
- AC-10 no dynamic Brain reads: runtime startup never clones Brain and parses
  STRATEGY_MASTER to build rules.
- AC-11 refactoring is not feature authorization: interfaces for LIVE/FORWARD/
  PRODUCTION/TRADEPLAN may exist without being authorized; current state keeps
  `PRODUCTION=false`, `FORWARD=false`, `TRADEPLAN=false`, `PRIMARY_OOS=false`.
- AC-12 no generic quant platform: no Kafka/RabbitMQ/Redis/ClickHouse/MongoDB/
  Kubernetes/microservices/distributed workers/generic OMS/multi-strategy DSL
  without a real requirement.

## Future gates (documented, not enforced yet)

- Zero direct provider calls and zero ASL internal schema dependencies in
  runtime domain logic (REF-R3).
- Feature/Policy and State/Ranking separation (REF-R4/REF-R5/REF-R6).
- Replay(D) == Daily(D) field-for-field on identical inputs (REF-R7).
- Hashable manifest, provenance, receipt, and resolvable lineage for every
  formal run (REF-R7 evidence).
- PIT prefix invariance, `known_as_of <= T`, snapshot `eligible_from >
  frozen_as_of`, and no same-day retroactive trigger/support/invalid use
  (REF-R5/REF-R7 transition and replay gates).
- UNKNOWN is never coerced to FALSE; missing/conflicting data and ambiguous
  predecessor lineage fail closed (REF-R3/REF-R5).
- Frozen historical evidence immutability checks across refactor rounds
  (REF-R0 baselines reused at every later phase).
- Legacy retirement only after zero runtime/test/artifact dependencies and
  differential parity PASS (REF-R8).
