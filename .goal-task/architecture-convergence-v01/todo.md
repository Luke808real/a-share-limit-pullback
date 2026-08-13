# Architecture Convergence V01 — Work Items

Item state values: `pending`, `in_progress`, `needs_input`, `deferred`, `accepted`.

## REF-R0 — Baseline Freeze (`accepted`)

- Freeze exact Runtime, Brain, and ASL SHAs and repository cleanliness evidence. [done: evidence v02 sections 1,8]
- Resolve and record strategy/rule/config versions and hashes, TEST_HASH/GOLDEN_HASH, reference snapshot/generation/episodes, ASL contract/version, and current authority gates. [done: evidence v03 sections 2-3; TEST_HASH 9fb950f0..., GOLDEN_HASH 3891b170..., CONTRACT_HASH df33ec3f...; ASL contract anchors VFLASH_ASL_PHASE1A_V1 / ba5681a; authority gates via IMPLEMENTATION_LOG.md + 00_Project/CURRENT_STATE.md]
- Characterize existing public contracts, state/signal/artifact outputs, PIT prefixes, Runtime performance/RSS/artifact size, and legacy call/dependency inventory. [done: evidence v03 sections 5-6; providers=4 with stated criterion, StrategySignal=36 fields, lifecycle wording, 13 contract schema fingerprints]
- Confirm no frozen artifact was modified and store baseline evidence without raw market data or secrets in Git. [done: evidence v02 section 8; baseline hash files committed under .goal-task/architecture-convergence-v01/baseline/]
- Gate: reproducible, reviewer-approved baseline sufficient to detect semantic, lineage, and performance drift. [PASS: round-3 three-reader review, all ACCEPT]

Baseline findings to feed later phases:

- F1 RESOLVED: pytdx re-declared as integration extra `pytdx>=1.7,<2`; fresh-install verification 20/20 passed.
- F2: chunked `screen --rebuild` without `--start` raises AttributeError instead of a validation error.
- F3: single full-market run JSON embeds all rows (4.27 GB artifact).

Later-phase hard prerequisites recorded in evidence v03 section 7: Replay(D)=Daily(D) baseline, ASL-vs-Legacy equivalence, 20-stock frozen replay reproduction (needs frozen code list), Runtime/Brain CI gap.

## REF-R1 — Architecture Constitution (`in_progress`)

- Publish three-plane ownership, seven-domain boundary, dependency rules, truth ownership, promotion contract, and target mapping in the appropriate repositories. [done: Runtime docs/architecture-constitution.md, Brain ADR-007, ASL docs/architecture/plane-boundary.md]
- Add enforceable architecture/dependency contract checks where practical (only rules that already hold may be enforced; target rules are documented future gates). [done: tests/test_architecture_constitution.py, 6 passed]
- Behavior/strategy/data/schema/artifact change: NO. [verified: Runtime src/ zero diff vs 1cb5fb7a; three-repo docs/tests only]
- Gate: documentation and contract checks agree across Runtime, Brain, and ASL; zero runtime behavior diff on the frozen reference. [pending: three-reader review]

## REF-R2 — Domain Extraction (`pending`)

Phase contract (declared before start, per constitution):

- TASK_ID: REF-R2-ARCH-DOMAIN-V01
- BASE_SHA: Runtime code base `1cb5fb7a1792edccc18c70207340980377cbd4eb` (Brain `2b15b44a…`, ASL `e13a3830…` unchanged in this phase)
- ARCHITECTURE_DOMAIN: `domain/` (market, setup, state, features, signals, run, provenance)
- FILES_ALLOWED: new `src/limit_pullback/domain/**`; compatibility re-export/adapters only where existing importers require them; `tests/` domain unit/contract tests
- BEHAVIOR_CHANGE: NO; STRATEGY_CHANGE: NO; DATA_CHANGE: NO; SCHEMA_CHANGE: NO (serialization-compatible only); ARTIFACT_CHANGE: NO
- INVARIANT: existing models keep the same pydantic schemas and values; old API import paths keep working through compatibility adapters
- DIFFERENTIAL_TEST: CONTRACT_HASH (13 schemas) unchanged; default suite green; new domain types produce identical JSON schemas to the models they formalize
- GOLDEN_TEST: golden test files unchanged and passing
- PERFORMANCE_DELTA: no runtime path change; expected 0
- FILES_CHANGED/HEAD_SHA: recorded at phase close

## REF-R1 — Architecture Constitution (`pending`)

- Publish the three-plane ownership, seven-domain boundary, dependency rules, truth ownership, promotion contract, and target mapping in the appropriate repositories.
- Add enforceable architecture/dependency contract checks where practical.
- Behavior/strategy/data/schema/artifact change: NO.
- Gate: documentation and contract tests agree across Runtime, Brain, and ASL; zero runtime behavior diff.

## REF-R2 — Domain Extraction (`pending`)

- Extract canonical market facts, instrument/session/status, setup identity/stage/lifecycle, frozen snapshots, feature record/availability, run context, and provenance domain types.
- Keep old APIs operational through compatibility adapters.
- Behavior/strategy change: NO.
- Gate: serialization/contract compatibility, transition/golden tests, and differential parity PASS.

## REF-R3 — Data Boundary (`pending`)

- Establish the canonical data port and fixture/ASL/legacy adapters without exposing provider or ASL internals to Runtime domain logic.
- Keep legacy warehouse/providers in shadow mode until ASL equivalence and authority gates pass.
- Do not cut over while ST readiness or provenance remains open; do not add a new provider under this refactor.
- Gate: canonical schema/provenance/quality/universe/snapshot contracts, provider-row lineage, fail-closed missing/conflict behavior, ASL-vs-legacy parity, and bounded resource acceptance PASS.

## REF-R4 — Feature Extraction (`pending`)

- Extract pure anchor, pullback, structure, launch, context, and common math features with explicit availability and lineage.
- Remove policy thresholds and state/ranking mutations from feature calculations.
- Rule/threshold/strategy change: ZERO.
- Gate: pure unit tests plus old/new feature and downstream semantic differential parity PASS.

## REF-R5 — State Consolidation (`pending`, HIGH_RISK)

- Consolidate one setup lifecycle, state engine, snapshot eligibility model, transition evidence, invalidation priority, supersede, and expiry behavior.
- Preserve exact frozen stages and PIT timing. Ranking cannot rescue INVALID or affect transitions.
- Gate: complete transition matrix; corporate action, ST, suspension, B1 first day, trigger freeze, B2 confirmation, invalid, supersede, and expiry golden cases; prefix invariance; state diff zero; three-reader adversarial review PASS.

## REF-R6 — Selection Isolation (`pending`)

- Separate eligibility, ranking, and presentation; move R9 to a selection policy consuming candidate context only.
- Preserve cohort membership and ranking semantics; do not introduce R10, new coefficients, factors, thresholds, or state behavior.
- Gate: selection reads no raw provider/bars/filesystem, does not mutate state, and produces zero signal/artifact semantic diff.

## REF-R7 — Runtime Unification (`pending`, HIGH_RISK)

- Make Replay and Daily orchestration use the same feature, state, selection, and evidence core.
- Keep LIVE interface-only and do not create intraday behavior or a generic backtester.
- Gate: `ReplayRuntime(D) == DailyRuntime(D)` field-for-field under identical facts/predecessor/policy/engine; manifests, fingerprints, lineage, error taxonomy, observability, offline full validation, and performance gates PASS.

## REF-R8 — Legacy Retirement (`pending`, destructive gate)

- Inventory legacy providers, warehouse/orchestration, duplicate docs, adapters, tests, and artifact consumers.
- Delete only an individually proven retirement set; prefer keeping an adapter over an unsafe deletion.
- Gate for every deletion: runtime call count zero, test dependency zero, artifact dependency zero, adapter unnecessary, full differential parity PASS, rollback evidence recorded, three-reviewer approval, and explicit human approval for the destructive phase.

## Final convergence closeout (`pending`)

- Run all completion gates listed in `state.md` against frozen references and current repository-native validators.
- Reconcile exact commits, Draft PRs, hashes, performance, review findings, known limitations, and unchanged authorization boundaries.
- Update Brain project truth only with reviewed evidence; do not promote strategy, merge PRs, cut over production, publish data, or activate Forward/Live.
