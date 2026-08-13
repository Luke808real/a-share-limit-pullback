# Architecture Convergence V01 — Execution State

## Status

- Mode: deep, cross-repository strangler refactor
- Initialization: complete; implementation has not started
- Current phase: REF-R2 Domain Extraction
- Progress: 2/9 refactor phases accepted (REF-R0 and REF-R1 accepted with three-reader reviews; Draft PRs Runtime#40, Brain#5, ASL upstream#19)
- Next action: validate the new `domain/` package against the full default suite, then three-reader review and commit

## REF-R0 status

- Evidence file: `.goal-task/architecture-convergence-v01/ref-r0-baseline-v03.md` (v01/v02 retired after reviews)
- TEST_HASH `9fb950f016ab3436c76e90f8a4a80c5b3070c7e20d062818ea6453a396bb2abd`; GOLDEN_HASH `3891b170f6b7a232fcb84d8c2b92ca4226cef96a7726e712724dbc59c9c56c82` (includes golden_expectations.yaml); CONTRACT_HASH `df33ec3fcac22c4672fa4762659964dd77006a9dca23b4c6fd1c0e0dca2b00e2` (13 frozen JSON schemas); baseline files under `.goal-task/architecture-convergence-v01/baseline/`.
- Frozen full-market reproduction at clean Runtime HEAD: output_hash `9abb16e4…` equals Brain-recorded `FULL_MARKET_HASH`; 3191 universe, 1,844,543 rows, 269.84s, max RSS 2,386,182,144 bytes, run artifact 4,274,032,081 bytes.
- Runtime offline validation: 547 passed / 11 skipped / 25 deselected (pytdx pinned separately; see F1). Brain: 47 passed. ASL: 1479 passed full suite (18 network deselected) with local proxy env unset.
- F1 RESOLVED via focused pyproject commit; F2/F3 open and scheduled as later-phase prerequisites.
- Review disposition: round 1 and round 2 NEEDS_FIX items all incorporated in v03 (authority path, providers criterion, golden fixture, contract fingerprints, ASL contract anchors); round 3 all ACCEPT.
- REF-R0 accepted on 2026-08-13. Evidence: ref-r0-baseline-v03.md; frozen full-market reproduction `9abb16e4…` at code base `1cb5fb7a…`.

## REF-R1 status

- Phase: zero-behavior constitution publication across the three repositories.
- Rule: enforce only architecture rules that already hold; target-state rules are documented as future gates, not enforced prematurely.
- Runtime artifacts: `docs/architecture-constitution.md` (three planes, seven domains, dependency rules, truth ownership, promotion contract, target mapping; enforced-today vs future gates) and `tests/test_architecture_constitution.py` (6 tests: frozen strategy/trade-plan config hashes, frozen SetupStage, models/strategy provider-import boundary, CanonicalDailyBar lineage fields, StrategySignal contract surface, generation lifecycle constants). Commit `697caae`.
- Brain artifact: `03_Decisions/ADR-007-architecture-convergence-constitution.md` (PROPOSED; decision_date records proposal date until human decision). Branch pushed.
- ASL artifact: `docs/architecture/plane-boundary.md` plus `docs/architecture/overview.md` link (Data Plane owns data truth, no strategy semantics). Branch pushed to fork.
- Zero behavior change evidence: Runtime `src/` has zero diff versus code base `1cb5fb7a…`; the only non-doc/test task-branch change is the `pyproject.toml` `pytdx` extra line (R0-F1 environment pin, packaging metadata only). Targeted semantic tests and new constitution tests pass; Brain 47/47 and ASL 1473 unit tests pass with the new docs.
- REF-R1 accepted: round-2 three-reader review all ACCEPT. Draft PRs opened: Runtime `Luke808real/a-share-limit-pullback#40`, Brain `Luke808real/a-share-strategy-brain#5`, ASL `rootSunc/ashare-lake#19` (all Draft, base main, no merge/cutover language).

## REF-R2 status

- Phase contract declared in todo.md (TASK_ID REF-R2-ARCH-DOMAIN-V01; behavior/strategy/data/schema/artifact change all NO).
- Implementation: new `src/limit_pullback/domain/` package (market/setup/state/features/run/provenance) that only re-exports from `limit_pullback.models.*` plus additive documentation-grade contracts (SetupIdentity, FeatureRecord, FeatureAvailability, RunContext, DataProvenance, Lifecycle alias). No warehouse/provider import in the domain layer.
- Tests: `tests/test_domain_contracts.py` (12 tests incl. domain import boundary and unchanged existing schemas). Targeted run 18 passed (12 domain + 6 constitution). Full default suite run in progress.
- REF-R2 accepted: three-reader review all ACCEPT (recorded follow-ups applied: FeatureRecord missing-value explicitness; CanonicalDailyBar deferral to REF-R3 documented; R3 contract declared).

## REF-R3 status

- Phase contract declared in todo.md (TASK_ID REF-R3-ARCH-DATA-BOUNDARY-V01; FILES_ALLOWED amended to include the screen/canonical delegation-only rewrite).
- Implementation: `src/limit_pullback/data/` package with `CanonicalDataPort` (concept contract; minute/corporate-action are future interfaces), `SnapshotDataAdapter` (fail-closed snapshot resolution, memory-bounded canonical row stream, single-provider lineage), `InMemoryCanonicalAdapter` fixture, universe/quality re-exports; `screen/canonical.py` is now a re-export shim over the verbatim-moved `data/canonical.py`.
- Known temporary edge: pool provider keeps the lazy `screen.engine.pool_quality` import for byte-identical behavior (recorded for REF-R4/R6).
- Validation: data-port tests 7 passed (incl. per-field parity vs legacy reader and manifest-hash provenance); full default suite 573 passed / 11 skipped / 25 deselected; full-market frozen rebuild run `screen-rebuild-2026-07-31-snap-2026-07-5398b8e47d8f` produced output_hash `9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec` — identical to the R0 baseline artifact and Brain `FULL_MARKET_HASH` (1,844,543 rows, 3191 universe).
- REF-R3 accepted: three-reader review all ACCEPT. Review follow-ups applied: trading status returns UNKNOWN when is_st is unknown (never infers NORMAL from absence); remaining boundary debt registered below.
- Remaining data-boundary debt (not claimed as done): screen/chunk_child.py, screen/chunks.py, screen/generation.py, screen/runner.py, screen/state.py still import warehouse directly; data/canonical.py keeps the lazy screen.engine.pool_quality import. These are scheduled for REF-R4/R6/R7.

## REF-R4 status

- Phase contract declared in todo.md (TASK_ID REF-R4-ARCH-FEATURE-V01; rule/threshold change ZERO; differential = frozen rebuild hash unchanged).
- Implementation: `src/limit_pullback/features/` with `common/math.py` (continuous prices, kline metrics, indicators) and `common/views.py` (zero-copy prefix views) moved verbatim from `strategy/math.py`/`strategy/indicators.py`; legacy strategy modules are now re-export shims.
- Recorded coupling: kline classification flags stay threshold-coupled (frozen config) and are scheduled for policy extraction later; no threshold or rule changed.
- Validation: feature tests green (identity + layer boundary + PIT prefix invariance); full default suite 576 passed / 11 skipped / 25 deselected; frozen full-market rebuild run `screen-rebuild-2026-07-31-snap-2026-07-d10ee308b702` at HEAD `0fef278` produced output_hash `9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec` — identical to the R0 baseline artifact and Brain `FULL_MARKET_HASH` (1,844,543 rows, 3191 universe).
- REF-R4 accepted: three-reader review all ACCEPT. Follow-up: remaining feature families and kline-policy extraction are now REF-R4.2 (R5 prerequisite) with its own gate.

## REF-R4.2 status

- Kline fact/policy split implemented: `features/common/math.py` now exposes only policy-free `KlineRatios` facts; `strategy/kline_policy.py` owns frozen-threshold flag classification; `strategy/indicators_calc.py` is the strategy-side indicator glue; `strategy/math.py` shim preserves the public API for all existing callers.
- Pure geometry slice implemented: `features/structure/prices.py` holds `at_price` and deterministic `cluster_price_candidates` (verbatim from strategy/structure.py; caller-provided tolerances only); `strategy/structure.py` re-imports them by identity.
- Remaining families (anchor/pullback/launch/context and threshold-coupled structure/pattern policy) stay in the strategy layer by design; the adversarial recommendation (extract only R5-reusable pure geometry, do not force full-family extraction) is followed.
- Validation: targeted tests 18 passed; full default suite 579 passed / 11 skipped / 25 deselected; frozen full-market rebuild run `screen-rebuild-2026-07-31-snap-2026-07-1b667e1fd0ca` at HEAD `05f0332` produced output_hash `9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec` — identical to the R0 baseline artifact and Brain `FULL_MARKET_HASH` (1,844,543 rows, 3191 universe).
- REF-R4.2 accepted: three-reader review all ACCEPT. Remaining feature families intentionally stay in strategy until consumed by REF-R5; REF-R5 start conditions verified (contract declared, evidence backfilled).

## REF-R5 status

- Pre-code artifacts: `.goal-task/architecture-convergence-v01/ref-r5-transition-matrix.md` (transition matrix, PIT invariants, nine golden categories mapped to existing tests) landed before any code edit.
- Slice 1 (verbatim move): `src/limit_pullback/state/engine_helpers.py` holds setup identity, B1/B2 conditions, invalid reasons, event flags, entry room, risk/reward, and price-quantization helpers byte-identical to `1cb5fb7a`; `strategy/engine.py` imports them back and keeps `evaluate_strategy` orchestration unchanged.
- Validation: 52 transition/golden targeted tests pass; full default suite 579 passed / 11 skipped / 25 deselected; frozen rebuild differential in progress.
- Slice 2 attempted twice and reverted with two recorded findings:
  - F5a (test seams): seven golden tests monkeypatch `select_resistance_levels` on `limit_pullback.strategy.engine`; a plain module move breaks the seam, and changing golden test files is prohibited by the phase contract.
  - F5b (package-init cycle): `state.engine` importing `strategy.*` submodules while `strategy/__init__` imports `strategy.engine` creates an import cycle once the engine leaves the strategy package.
  - Planned R5.2 resolution (documented, not started): move pattern/scoring/structure consumption out of the engine or introduce lazy strategy package exports, preserving monkeypatch seams; requires an amended file-scope contract and its own three-reader review.
- R5 slice 1 remains the accepted milestone: transition helpers consolidated in `state/engine_helpers.py` with zero behavior change.
- R5.2 implemented (seam-preserving engine relocation): `evaluate_strategy` moved verbatim to `state/engine.py`; `strategy/engine.py` is an identity-level re-export shim with module-level structure seams and a lazy PEP 562 `evaluate_strategy`; `strategy/__init__.py` resolves `evaluate_strategy` lazily to break the package cycle; `select_resistance_levels` is called late-bound through the shim so golden monkeypatch tests keep passing. All import paths verified; targeted 69 passed; full suite 579 passed / 11 skipped / 25 deselected; frozen rebuild differential in progress.
- REF-R5 accepted: three-reader phase review all ACCEPT. Frozen full-market rebuild run `screen-rebuild-2026-07-31-snap-2026-07-1dbf5d5e20f0` at HEAD `df7e312` produced output_hash `9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec` (1,844,543 rows, 3191 universe) — identical to the R0 baseline and Brain `FULL_MARKET_HASH`.
- Shim contract (recorded in design.md): `strategy/engine.py` re-export face is a test contract; R6/R7 must keep identity-level exports for select_resistance_levels/build_score and the lazy evaluate_strategy seam, or update the contract with explicit review approval first.

## REF-R6 status

- Implementation: `src/limit_pullback/selection/` created with `ranking.py` (verbatim move of `strategy/scoring.py`: FULL/PRICE_ONLY frozen score construction, imports only models) and `policies/__init__.py` (R9 target slot documented; no R9 code fabricated — R9 lives in separate research worktrees).
- `strategy/scoring.py` is now an identity re-export shim; `state/engine.py` imports `build_score` from `selection.ranking` (transitional state→selection coupling recorded; composition-based inversion is a later slice).
- Tests: `tests/test_selection_isolation.py` (shim identity, selection layer boundary incl. no providers/filesystem, ScoreBreakdown frozen). Targeted 52 passed; full default suite 582 passed / 11 skipped / 25 deselected; frozen rebuild differential in progress.
- R6.2 implemented: state engine no longer imports selection at module level; ranking is resolved lazily and is injectable via `ranking_fn` (composition-ready, default behavior identical); eligibility/presentation target mapping registered in selection/__init__; strengthened "does not mutate state" test (frozen input snapshot + determinism). Full default suite 585 passed / 11 skipped / 25 deselected; frozen rebuild differential in progress.
- REF-R6 accepted: three-reader review all ACCEPT. Frozen full-market rebuild run `screen-rebuild-2026-07-31-snap-2026-07-e07ab746778a` at HEAD `88a0a75` produced output_hash `9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec` (1,844,543 rows, 3191 universe) — identical to the R0 baseline and Brain `FULL_MARKET_HASH`.
- R9 external contract recorded as pending: "R9 consumes candidate context only" applies to the separate research worktrees; Runtime registers the `selection/policies/r9` slot and does not claim the out-of-repo R9 behavior is verified here.

## REF-R7 status

- Pre-code divergence inventory landed (ref-r7-divergence-inventory.md).
- Implementation: `runtime/` package with `common.evaluate_day` (single per-day evaluation seam over the shared state engine), `replay.py`/`daily.py` identity re-exports of the existing orchestration entries, and `live.py` interface reservation only. `replay.py` and `screen/engine.py` now delegate both per-day loops to `evaluate_day` (kwargs identical; unused direct engine imports removed).
- Parity probe: on the frozen snapshot, precomputed-indicator mode and recompute mode produce field-identical per-day signals for a sampled code (test_runtime_common).
- Validation: targeted 29 passed; full default suite 588 passed / 11 skipped / 25 deselected; frozen rebuild differential in progress.
- Orchestration-level parity probe added per review: on the frozen snapshot, `replay_stock` (canonical provider injected, offline) vs `screen_code` produce field-identical `ReplayTimelineItem` sequences for three codes (000001/000002/600000) over the same window. Full default suite 589 passed / 11 skipped / 25 deselected; HEAD-level rebuild differential in progress.
- Probe strengthened per DATA_READER: codes 603221/603580 now carry real frozen pool records, and 603221 asserts non-NORMAL stages — anchor/state-transition paths are exercised, not just NORMAL days. Full default suite 589 passed / 11 skipped / 25 deselected; HEAD-level rebuild differential complete below.
- REF-R7 frozen rebuild at final parity-probe HEAD: output_hash `9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec` (1,844,543 rows, 3191 universe).
- REF-R7 accepted: three-reader review all ACCEPT (round 3). Frozen rebuild run `screen-rebuild-2026-07-31-snap-2026-07-e7c55287ff3f` at HEAD `3114aad`; parent RSS 158.7MB / max child 2.387GB within the 1.15×/1.10× gates. Outstanding external anchor: the 20-stock frozen replay hash `6c2ffc22…` remains library-external and is recorded as not locally reproduced (frozen code list missing).

## REF-R8 status

- Read-only inventory landed: ref-r8-legacy-inventory.md. No retirement set currently satisfies the deletion gate (every provider module still has runtime or test references).
- Authority blockers recorded: `ST_READY=NO`, `PROVENANCE_GAP=OPEN`, `PRODUCTION_CUTOVER=NO_GO` are Brain/ASL data-governance gates this task cannot flip; REF-R8 stays `needs_input` for human-approved retirement sets and rollback evidence.

## Handoff next actions (from final convergence audit)

- P1 done: `evidence/verification/frozen_differential.py` extracts bounded summaries from 4+ GB run artifacts (never fully materialized) and verifies output_hash/rows/universe/status_counts (plus per-chunk hashes when present) against the frozen reference manifest `baseline/frozen-rebuild-summary-v01.json`. Latest rebuild `e7c55287ff3f` verified diff=0 against the R0 baseline artifact. Full default suite 591 passed / 11 skipped / 25 deselected.
- P2 (in-repo): adopt evidence protocol end-to-end (provenance block, receipt, seven-item fingerprint, predecessor lineage) into formal runs.
- P2 done (additive slice): `evidence/verification/fingerprint.py` (eight-item §97 fingerprint incl. runtime commit / strategy version / config hash / ASL version / snapshot / universe / predecessor / engine versions, deterministic hash) and `evidence/verification/receipt.py` (hashable receipt beside run artifacts embedding fingerprint + frozen-reference verification). Existing run row artifacts unchanged; `output_hash` gate unchanged. Full default suite 593 passed / 11 skipped / 25 deselected.
- P3 (in-repo): zero-behavior migration of the five screen warehouse consumers toward the data layer, accumulating runtime_call=0 evidence for future R8 sets.
- P3 done (bridge slice): `data/facade.py` re-exports the five warehouse primitives (WarehouseLayout/WarehouseMetadata/sha256_file/write_json_atomic/require_state_snapshot_usable/snapshot_status_map) by identity; the five screen modules now import only from the data layer and the screen package has zero `limit_pullback.warehouse` imports (boundary test enforced). Full default suite 595 passed / 11 skipped / 25 deselected; frozen rebuild differential in progress.
- P3.2 done (read-side tool modules): execution_reality, outcome, prc_audit, trade_plan, universe now import the same primitives plus SnapshotRecord/require_formally_usable_snapshot through data/facade; boundary test enforces zero warehouse imports for these five read-side modules. cli.py remains the warehouse acquisition surface (bootstrap/update/probe/status/validate/asl-snapshot) and is deliberately exempt. Full default suite 596 passed / 11 skipped / 25 deselected; frozen rebuild differential in progress.
- Remaining in-repo debt (recorded, not claimed): data/canonical.py lazy screen.engine.pool_quality reverse dependency (needs a policy-placement design, not a mechanical bridge); cli.py acquisition command surface (moves with warehouse retirement).

## Final closeout (2026-08-13, HEAD ce175a1)

- Final frozen rebuild at final HEAD: run `a9e617fd38aa`, output_hash `9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec` (1,844,543 rows, 3191 universe); receipt fingerprint `runtime_commit=ce175a18b1b6c06925e638eab1276c364957e80c` (self-consistent with the emitting code).
- Receipt emission scope: every formal chunked full-market run; the non-chunked `run_screen` path does not yet emit a receipt (recorded honestly). `predecessor_generation_id=null` and `universe_hash=null` reflect that daily rebuild runs have no predecessor and the frozen universe hash is not yet computed into the fingerprint (lineage partial, recorded).
- Fingerprint item count note: the fingerprint object carries 9 fields (the architecture §97 list of 8 plus the engine_versions map).
- Three-reader final verdict: ALL_IN_REPO_DONE (CODE_READER), READY (DATA_READER), ACCEPT with active-waiting-human-input (ADVERSARIAL).
- Goal state: active, waiting on human inputs only. Remaining human inputs: (1) R8 per-set deletion approval + rollback authorization; (2) ST_READY/PROVENANCE_GAP/PRODUCTION_CUTOVER closure by Brain/ASL owners; (3) R9 out-of-repo verification; (4) 20-stock frozen replay code list or exemption (hash 6c2ffc22…); (5) explicit merge instruction for the three Draft PRs.
- P6.2 done: the non-chunked `run_screen` path now emits the same additive receipt (verified with single-code run `73fbeedf9c7b`); both formal run paths emit receipts. Full default suite 598 passed / 11 skipped / 25 deselected. The chunked path was unchanged since the `a9e617fd38aa` rebuild, whose hash/receipt evidence remains valid.
- 20-stock anchor recovery attempt: searched the read-only source worktrees for the frozen 11,378-row artifact and `6c2ffc22…` references; not recoverable from local artifacts. Item (4) remains a human input (frozen code list or explicit exemption).
- Final three-repo state verified 2026-08-13: Runtime branch `codex/architecture-convergence-v01` HEAD `663af4044c8d7a37b878c63212b35aad845b8844` (PR #40 Draft/OPEN/base main); Brain HEAD `95746b598c234ee9bc7c5c2bfb15f7c4ceaa84d1` (PR #5 Draft/OPEN/base main); ASL fork HEAD `418053daca1ec61e7c2fb84d20fa9fe6ce689b08` (upstream PR #19 Draft/OPEN/base main). All heads match their remote branches; no merge performed.
- P6.3 (incremental-run predecessor lineage in receipts) registered as needs-design: it touches the fragile generation-pointer machinery (PREDECESSOR_RESOLUTION history) and needs its own contract before implementation.

## Human approval received ("全部批准", 2026-08-13)

- Merges executed under explicit user approval:
  - Runtime PR #40 → main, regular merge commit `8e7affc8380cca0d4818e81240b0a7e216e08ade`.
  - Brain PR #5 (ADR-007) → main, regular merge commit `13ec1566fb9453f69fe05b3194f5d12c26cfcdeb`.
  - Brain governance PR #6 (integration records + BASELINE_MANIFEST approved_non_strategy_integrations entry) → main, regular merge commit `aa92ade5b809ed319f7b6d1f2ed478f0e3bcbfdc`.
  - ASL upstream PR #19: merge attempted; fork has no upstream write permission — remains OPEN awaiting the rootSunc maintainer.
- 20-stock frozen replay anchor (`6c2ffc22…`): human exemption granted and recorded in Brain IMPLEMENTATION_LOG; local reproduction no longer required.
- R8 deletions: user approval granted, but the fresh inventory at HEAD 9281de1 shows no retirement set satisfies the zero-dependency gate (acquisition path still live). Deletions remain pending the ASL acquisition retirement, which in turn requires the real ST/provenance closure (②).
- ST_READY/PROVENANCE_GAP/PRODUCTION_CUTOVER gates: remain NO/OPEN/NO_GO. Closing them is now authorized but requires actual ASL data-governance work (ST backfill + provenance closure), recorded as a follow-up data task, not fabricated here.
- R9 out-of-repo verification: R9 factor source is not locatable locally (only ledgers under `/Users/luke808/AI/asl-r9-prospective-research-v01/r9/ledgers`); verification deferred until the R9 code module is provided.
- R9 verification completed from git history (read-only): the frozen prospective factor producer `research/second_launch/walk_forward_v01/r9_prospective_factor_producer_v01.py` at branch `048b2c8a09d637275e511125853199eaa7e25232` (commit db488b3 ancestry) is a pure PIT producer — imports stdlib + pandas + its three research modules only; no provider/duckdb/filesystem I/O (json.dumps for hashing only); consumes the caller-supplied immutable Gate 2A slice plus bounded daily-bar/adjustment-factor PIT prefixes; frozen dataclasses, no runtime state mutation. The separate `r9_setup_accumulator_v01.py` is the ledger/evidence writer (csv/Path), not a ranking/state mutation. Condition 3 evidence: PASS for the producer surface.
- ST/provenance gate probe (②): ASL 0.6.0 environment check passes offline in the isolated worktree, but there is no production config/data root in this worktree, so ST readiness cannot be probed or closed from here. Closing `ST_READY/PROVENANCE_GAP/CUTOVER` is a production data-engineering deliverable that needs the real ASL config path + data root (or the ASL maintainer); recorded as the next external action, not fabricated.
- ST-readiness code path located and published: the dedicated branch `fix/asl-historical-st-negative-evidence-v01` (fork `Luke808real/ashare-lake`, head `0f16f39`) carries historical non-ST evidence persistence, partial-backfill failure surfacing, PIT suspension preference, and delisting/window-overlap separation. Upstream PR opened: `rootSunc/ashare-lake#21` (human-approved; maintainer merge requested). Merging this series plus the production ST backfill (per the existing resume-ledger operational procedure) is the concrete path to flipping `ST_READY` and then `PROVENANCE_GAP`/`PRODUCTION_CUTOVER`.
- P6.3 design contract delivered (design.md): predecessor lineage in receipts with fail-closed pointer resolution (`AMBIGUOUS`/`NONE` sentinels, no latest-directory guess), additive-only artifact impact, differential gate. Implementation waits for upstream ASL merges (PR #19/#21 still OPEN) or an explicit go-ahead.
- P5 done (pool-quality placement): `pool_quality` moved verbatim to `data/pool_quality.py` (data-quality classification of pool reconciliation status); `screen/engine.py` re-exports by identity; `data/canonical.py` no longer imports `limit_pullback.screen` at all — the last reverse dependency is removed. Full default suite 597 passed / 11 skipped / 25 deselected; frozen rebuild differential in progress.
- P6 done (formal-run receipt wiring): `evidence/wire.emit_formal_run_receipt` writes `<run_id>.receipt.json` beside every formal chunked run with fingerprint (runtime commit/strategy version/config hash/ASL contract/snapshot/universe/predecessor/engine versions) and hashable receipt. Additive-only per declared contract. Full default suite 598 passed / 11 skipped / 25 deselected; first real receipt emitted by the in-progress frozen rebuild.
- P4 (in-repo): record full-market runtime seconds at the latest HEAD (RSS already recorded in-gate).
- P4 done at HEAD 2f2520e: wall 266.99s vs baseline 269.84s (0.989×), max RSS 2,387,361,792 B vs 2,386,182,144 B (1.0005×), artifact 4,274,032,081 B unchanged (1.000×), output_hash `9abb16e4…` — all within the 1.15×/1.10× gates.
- Human inputs required: R8 per-set deletion approval + rollback authorization; ST_READY/PROVENANCE_GAP/CUTOVER closure by Brain/ASL owners; R9 out-of-repo verification; 20-stock frozen code list or exemption; three-repo PR merge only on explicit instruction.

## Active truth and authority

Authority order:

1. Latest explicit user confirmation
2. Reviewed/frozen Strategy Brain truth
3. This task's confirmed architecture decisions in `design.md`
4. Architecture source attachment, SHA-256 `e2b467d89cdecb15c9cb18a74b81429caa66a8b8c602d47525afafd63669d064`
5. Executable work state in `todo.md` and this file

Truth entrypoints:

- Runtime worktree: `/Users/luke808/AI/V flash-architecture-convergence-v01`
- Runtime branch/base: `codex/architecture-convergence-v01` from `origin/main@1cb5fb7a1792edccc18c70207340980377cbd4eb`
- Brain worktree: `/Users/luke808/AI/a-share-strategy-brain-architecture-convergence-v01`
- Brain branch/base: `codex/architecture-convergence-v01` from `origin/main@2b15b44a4d2b586199e3824b817220f9fdfa281f`
- ASL worktree: `/Users/luke808/AI/ashare-lake-architecture-convergence-v01`
- ASL branch/base: `codex/architecture-convergence-v01` from upstream `origin/main@e13a3830d020be555a5c79f3b7f8fc2d4ad9d011`
- ASL publication remote: user-owned `fork` (`Luke808real/ashare-lake`); upstream `origin` is comparison truth, not a direct-write target
- Architecture source: `/Users/luke808/.codex/attachments/5d76ed95-8072-4513-9d05-d352668cbb96/pasted-text.txt`
- Runtime repository rules: `AGENTS.md`, `docs/agent-context.md`, `docs/HANDOFF_TEMPLATE.md`
- Frozen strategy truth: Brain `01_Strategy/STRATEGY_MASTER.md`, `01_Strategy/RULE_CATALOG.md`, `01_Strategy/BASELINE_MANIFEST.yaml`
- Phase truth: Brain `05_Codex/CURRENT_PHASE.md`, `exports/LLM_CONTEXT_PACK.md`
- Work items: `todo.md`
- Confirmed architecture decisions: `design.md`

The original non-isolated worktrees contain user changes and are evidence sources only. Do not edit, clean, reset, commit, or absorb them.

## Scope and authorization

Authorized:

- Coordinated changes in the three isolated worktrees, limited to architecture convergence.
- Local milestone commits, pushes of the named `codex/architecture-convergence-v01` branches, and Draft PR creation/update.
- Read-only comparison against upstream branches and frozen artifacts.

Not authorized:

- Merge, rebase, squash, force-push, release, deployment, production cutover, data publication, Forward/OOS activation, TradePlan activation, or automated trading.
- Direct pushes to protected `main` or to upstream `rootSunc/ashare-lake`.
- New strategy factors, thresholds, coefficients, rules, providers, production behavior, or Forward behavior.
- Rewriting or deleting historical snapshots, generations, episodes, outcomes, receipts, hashes, or forward epochs.
- Legacy deletion before every REF-R8 retirement gate passes.

## Execution contract

1. Follow REF-R0 through REF-R8 in order. A later phase may be prepared read-only, but implementation starts only after its predecessor gate passes.
2. Before every phase, record the task ID, exact bases, owning plane/domain, allowed files, change flags, invariant, differential/golden/contract/transition tests, performance expectation, and expected artifact impact in `todo.md`.
3. Keep one writer. For HIGH_RISK phases use CODE_READER, DATA_READER, and ADVERSARIAL_REVIEWER as independent read-only readers. At every major milestone use exactly three independent read-only reviewers; the writer cannot substitute.
4. Use adapters and shadow execution. Preserve the old default until the new path passes targeted tests, full applicable validation, golden and differential parity, lineage verification, and performance gates.
5. Never treat local tests as CI, a Draft PR as review approval, a merged ASL technical change as production cutover, or `SUPPORTED` as `PROMOTED`.
6. Default validation in Runtime is `pytest -q`, `python -m compileall -q src tests`, and `git diff --check`; add repository-native checks in Brain and ASL after inspecting their current instructions/configuration. Default tests remain offline; real-provider/full-market runs require an explicit phase need, bounded resource plan, and immutable output location.
7. Full-market acceptance thresholds: runtime and peak RSS no greater than baseline x1.15; artifact bytes no greater than baseline x1.10. Any exceedance is an unmet gate until explained and explicitly accepted.
8. After validation and review pass, create a focused local milestone commit in each changed repository. Push only the task branch and create/update Draft PRs. Never merge automatically.
9. Try a failing item at most three times by default. Record evidence, defer it, and continue independent work. Permission or authorization gaps are `needs input`, not automatically `blocked`.
10. After each productive loop report exactly a gate-based progress line, this-loop/remaining evidence line, and one primary next action. Never report 100% until all applicable gates pass.
11. At each deep-mode loop end, summarize disproven assumptions and effective recovery here. Create `lessons.md` only if reusable evidence-backed lessons actually emerge.

## Global invariants

- Frozen setup stages, lifecycle, B1/B2, S1/S2, Entry Room, setup/entry scores, R9 coefficients, and thresholds remain unchanged unless a separately approved promotion contract explicitly authorizes a strategy change.
- `B1_PREP` remains an execution label, not a setup stage. `SECOND_LAUNCH` remains an outcome/event unless a separate ADR changes it.
- `known_as_of <= T`; every new Support/Invalid/S1/B2 Trigger snapshot has `eligible_from > frozen_as_of` and cannot affect its freeze day.
- Raw Price and PIT Continuous Price remain distinct.
- UNKNOWN is not FALSE. Missing, conflicting, ambiguous, or incomplete data and lineage fail closed.
- Canonical rows have one clear provider lineage; no cross-provider field stitching.
- Feature describes facts, Policy decides meaning, State owns lifecycle, Selection ranks attention, Runtime orchestrates, Evidence proves results, Brain owns strategy truth, and ASL owns data truth.
- Replay and Daily share one domain core and must match field-for-field for identical inputs, predecessor, policy, and engine versions.
- Refactoring creates new evidence; it never mutates frozen historical evidence.

## Completion gates

The goal is complete only when every condition below passes with durable evidence:

1. Runtime consumes one canonical boundary; direct provider calls and ASL-internal schema dependencies in strategy/runtime code are zero.
2. Each feature has one definition and explicit availability; feature code contains no policy decision.
3. One setup lifecycle, one state engine, and one snapshot eligibility model remain; state contains no ranking behavior.
4. R9/selection consumes candidate context only, reads no raw providers/bars or filesystem, and never mutates state.
5. Replay and Daily use the same core and match field-for-field under identical inputs.
6. Formal runs emit hashable manifests, provenance, receipts, generations/ledgers, and unambiguous predecessor lineage.
7. On frozen reference inputs, old versus new has `state diff = 0`, `signal diff = 0`, and `artifact semantic diff = 0`; PIT prefix, transition, contract, golden, fail-closed, and UNKNOWN tests pass.
8. Runtime, Brain, and ASL repository-native validation passes; performance gates pass or have explicit human acceptance.
9. Required three-reviewer reviews and re-reviews have no unresolved high-severity finding.
10. Legacy retirement proves runtime calls = 0, test dependencies = 0, artifact dependencies = 0, migration adapter unnecessary, and differential parity PASS before deletion.
11. Each changed repository has a focused reviewed commit and Draft PR with exact SHA/evidence. No merge, cutover, Forward, Production, or release is claimed.

## Recovery and blocking

Maintain item-level waiting/deferred state only in `todo.md`. Set the overall goal `blocked` only when bounded recovery, safe alternatives, splitting, reprioritization, and all independent work are exhausted and every meaningful remaining item jointly depends on the same verified logical conflict, safety boundary, or mandatory external dependency.

## Work summary

- Initialized three clean isolated worktrees and matching task branches from verified remote `main` SHAs.
- Collected and recorded the complete REF-R0 baseline evidence set (SHAs, frozen truth hashes, offline validation baselines, reference generation reproduction, performance and static characterization).
- Preserved all pre-existing dirty worktrees untouched.
- No production code, frozen truth, data artifact, remote branch, or PR was changed during initialization.
