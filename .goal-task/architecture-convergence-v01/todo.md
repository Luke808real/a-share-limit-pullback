# Architecture Convergence V01 — Work Items

Item state values: `pending`, `in_progress`, `needs_input`, `deferred`, `accepted`.

## REF-R0 — Baseline Freeze (`in_progress`)

- Freeze exact Runtime, Brain, and ASL SHAs and repository cleanliness evidence. [done: evidence file section 1]
- Resolve and record strategy/rule/config versions and hashes, test/golden hashes, reference snapshot/generation/episodes, ASL contract/version, and current authority gates. [done: evidence file section 2]
- Characterize existing public contracts, state/signal/artifact outputs, PIT prefixes, Runtime performance/RSS/artifact size, and legacy call/dependency inventory. [done: evidence file sections 4-5; PIT prefix tests identified in test_strategy_engine/test_replay]
- Confirm no frozen artifact was modified and store baseline evidence without raw market data or secrets in Git. [done: evidence file section 6; evidence lives in .goal-task/architecture-convergence-v01/ref-r0-baseline-v01.md]
- Gate: reproducible, reviewer-approved baseline sufficient to detect semantic, lineage, and performance drift. [pending: three-reader review]

Baseline findings to feed later phases:

- F1: pytdx missing from declared extras while default tests import it (packaging gap at 1cb5fb7a).
- F2: chunked `screen --rebuild` without `--start` raises AttributeError instead of a validation error.
- F3: single full-market run JSON embeds all rows (4.27 GB artifact).

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
