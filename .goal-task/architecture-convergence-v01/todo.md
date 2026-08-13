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

## REF-R1 — Architecture Constitution (`accepted`)

- Publish three-plane ownership, seven-domain boundary, dependency rules, truth ownership, promotion contract, and target mapping in the appropriate repositories. [done: Runtime docs/architecture-constitution.md, Brain ADR-007, ASL docs/architecture/plane-boundary.md]
- Add enforceable architecture/dependency contract checks where practical (only rules that already hold may be enforced; target rules are documented future gates). [done: tests/test_architecture_constitution.py, 6 passed]
- Behavior/strategy/data/schema/artifact change: NO. [verified: Runtime src/ zero diff vs 1cb5fb7a; three-repo docs/tests only]
- Gate: documentation and contract checks agree across Runtime, Brain, and ASL; zero runtime behavior diff on the frozen reference. [PASS: round-2 three-reader re-review, all ACCEPT; Draft PRs Runtime#40, Brain#5, ASL upstream#19]

## REF-R2 — Domain Extraction (`accepted`)

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

- Extract canonical market facts, setup identity/stage/lifecycle, frozen snapshots, feature record/availability, run context, and provenance domain types. [done: domain/ package created; market/state re-exports, SetupIdentity, Lifecycle alias, FeatureRecord/FeatureAvailability, RunContext, DataProvenance]
- Keep old APIs operational through compatibility adapters.
- Behavior/strategy change: NO.
- Gate: serialization/contract compatibility, transition/golden tests, and differential parity PASS. [PASS: three-reader review all ACCEPT; 565 passed / 11 skipped / 25 deselected]

Note: "Canonical Market Facts" in this phase is covered by the `models.market`
vocabulary re-export (DailyBar/LimitUpRecord). The single-provider-lineage
`CanonicalDailyBar` stays in `warehouse/models.py` until REF-R3 moves the
canonical data contract behind CanonicalDataPort; this deferral is intentional
to keep the domain layer free of data-layer imports.

## REF-R3 — Data Boundary (`accepted`)

Phase contract (declared before start, per constitution):

- TASK_ID: REF-R3-ARCH-DATA-BOUNDARY-V01
- BASE_SHA: Runtime code base `1cb5fb7a…`; Brain/ASL unchanged in this phase
- ARCHITECTURE_DOMAIN: `data/` (ports/canonical/asl/snapshot/universe/quality) target; incremental only, legacy stays default
- FILES_ALLOWED: new `src/limit_pullback/data/**`; `src/limit_pullback/screen/canonical.py` delegation-only rewrite (becomes a re-export shim, bodies move verbatim to `data/canonical.py`); `.gitignore` root-anchor fix (`data/` -> `/data/` so the target `src/limit_pullback/data/` package is trackable); `tests/` contract tests
- BEHAVIOR_CHANGE: NO; STRATEGY_CHANGE: NO; DATA_CHANGE: NO; SCHEMA_CHANGE: NO (new port is additive); ARTIFACT_CHANGE: NO
- INVARIANT: legacy warehouse/providers remain default until ASL==Legacy equivalence evidence; ST_READY/PROVENANCE_GAP/PRODUCTION_CUTOVER stay blocking; no new provider; canonical rows keep single-provider lineage
- DIFFERENTIAL_TEST: default suite green; existing canonical reader behavior unchanged; ASL-vs-Legacy parity probe recorded as pending until authority gates allow
- GOLDEN_TEST: golden files unchanged and passing
- PERFORMANCE_DELTA: additive import-only path; expected 0

- Establish the canonical data port and fixture/ASL/legacy adapters without exposing provider or ASL internals to Runtime domain logic. [done: CanonicalDataPort + SnapshotDataAdapter + InMemoryCanonicalAdapter + universe/quality re-exports; screen/canonical shim delegates to data/canonical]
- Keep legacy warehouse/providers in shadow mode until ASL equivalence and authority gates pass. [done: legacy path is still the default via the shim; ASL parity remains gated by ST/PROVENANCE/CUTOVER]
- Do not cut over while ST readiness or provenance remains open; do not add a new provider under this refactor. [held]
- Gate: canonical schema/provenance/quality/universe/snapshot contracts, provider-row lineage, fail-closed missing/conflict behavior, ASL-vs-legacy parity, and bounded resource acceptance PASS. [PASS: three-reader ACCEPT; frozen rebuild differential output_hash 9abb16e4…; ASL-vs-legacy parity recorded as authority-gated, not proven]

Remaining boundary debt (for REF-R4/R6/R7): screen/chunk_child.py, screen/chunks.py, screen/generation.py, screen/runner.py, screen/state.py direct warehouse imports; data/canonical.py lazy screen.engine.pool_quality import.

## REF-R4 — Feature Extraction (`accepted`)

Phase contract (declared before start, per constitution):

- TASK_ID: REF-R4-ARCH-FEATURE-V01
- BASE_SHA: Runtime code base `1cb5fb7a…`; Brain/ASL unchanged
- ARCHITECTURE_DOMAIN: `features/` (anchor/pullback/structure/launch/context/common)
- FILES_ALLOWED: new `src/limit_pullback/features/**`; `strategy/` delegation-only edits where a pure-feature function moves verbatim; `tests/` unit/contract tests
- BEHAVIOR_CHANGE: NO; STRATEGY_CHANGE: NO; RULE/THRESHOLD_CHANGE: ZERO; DATA_CHANGE: NO; SCHEMA_CHANGE: NO; ARTIFACT_CHANGE: NO
- INVARIANT: extracted features are pure calculations with explicit availability; policy thresholds and state/ranking mutations stay out of feature code
- DIFFERENTIAL_TEST: default suite green; frozen full-market rebuild output_hash remains `9abb16e4…`
- GOLDEN_TEST: golden files unchanged and passing
- PERFORMANCE_DELTA: pure-function delegation only; expected 0

- Extract pure anchor, pullback, structure, launch, context, and common math features with explicit availability and lineage. [partial: common math/views extracted verbatim; anchor/pullback/structure/launch/context feature families remain in strategy/patterns+structure for later slices]
- Remove policy thresholds and state/ranking mutations from feature calculations. [held: kline flags remain threshold-coupled by design; recorded, no new coupling]
- Rule/threshold/strategy change: ZERO. [held]
- Gate: pure unit tests plus old/new feature and downstream semantic differential parity PASS. [PASS: three-reader ACCEPT; full suite 576 passed; frozen rebuild run d10ee308b702 output_hash 9abb16e4…]

## REF-R4.2 — Remaining Feature Families and Kline-Policy Extraction (`accepted`, R5 prerequisite)

- Kline fact/policy split: features/common/math.py keeps pure KlineRatios; strategy/kline_policy.py owns threshold flags; strategy/indicators_calc.py is the indicator glue. [done]
- Pure geometry extraction: features/structure/prices.py (at_price, cluster_price_candidates) moved verbatim; strategy/structure.py re-imports by identity. [done]
- Remaining families (anchor/pullback/launch/context + threshold-coupled structure/pattern policy) intentionally stay in strategy per adversarial recommendation; they move only as R5-consumed pieces, never as a forced full-family sweep.
- Rule/threshold change: ZERO; behavior change: NO; differential: frozen rebuild output_hash remains `9abb16e4…`. [PASS: rebuild run 1b667e1fd0ca output_hash 9abb16e4…]
- Gate: features consume no policy; three-reader review ACCEPT before REF-R5 starts. [PASS: three-reader review all ACCEPT]

## REF-R5 — State Consolidation (`pending`, HIGH_RISK)

Phase contract (declared before start, per constitution):

- TASK_ID: REF-R5-ARCH-STATE-V01
- BASE_SHA: Runtime code base `1cb5fb7a…`; Brain/ASL unchanged
- ARCHITECTURE_DOMAIN: `state/` (engine/lifecycle/transitions/snapshots/invalidation)
- FILES_ALLOWED: new `src/limit_pullback/state/**`; `strategy/engine.py` and `screen/state.py` delegation-only edits where the state logic moves verbatim; `tests/` transition/golden tests
- BEHAVIOR_CHANGE: NO; STRATEGY_CHANGE: NO; DATA_CHANGE: NO; SCHEMA_CHANGE: NO; ARTIFACT_CHANGE: NO
- INVARIANT: exact frozen stages and PIT timing; INVALID beats ranking; new anchor supersedes with new setup_id; invalid price never loosens; prefix invariance holds
- DIFFERENTIAL_TEST: frozen full-market rebuild output_hash remains `9abb16e4…`; state diff = 0 on frozen reference; transition matrix complete
- GOLDEN_TEST: corporate action, ST, suspension, B1 first day, trigger freeze, B2 confirm, invalid, supersede, expire cases pass unchanged
- PERFORMANCE_DELTA: full-market runtime/RSS <= baseline x1.15; artifact bytes <= baseline x1.10
- HIGH_RISK rules: three read-only readers (CODE/DATA/ADVERSARIAL) before acceptance; rollback anchor = last accepted commit; do not start before REF-R4.2 gate PASS

- Pre-code transition matrix and golden case list landed (ref-r5-transition-matrix.md). [done]
- Slice 1: state transition helpers moved verbatim to state/engine_helpers.py; strategy/engine.py imports them back; zero behavior change. [done: targeted 52 passed, full suite 579 passed, rebuild differential pending]
- Slice 2 (pending): move evaluate_strategy orchestration verbatim to state/engine.py with strategy/engine.py shim; then isolate scoring/ranking touchpoints for REF-R6.
- Gate: transition matrix complete; nine golden categories; prefix invariance; state diff=0; three-reader adversarial review PASS. [in progress]

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
