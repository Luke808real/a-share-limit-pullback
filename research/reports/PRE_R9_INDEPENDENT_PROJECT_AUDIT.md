# PRE_R9_INDEPENDENT_PROJECT_AUDIT

STATUS: COMPLETE — independent pre-R9 audit

AUDIT_HEAD: `cd57d9fa7cfa32cbec7f53e8165b12dcb6f86018`

AUDIT_MODE: Read-only. No code, strategy, configuration, data artifact, market-data fetch, backfill, full-market run, Forward, TradePlan, or R9 implementation was performed. This report is the only newly written file. The working tree is dirty and at another commit; all repository evidence was read directly from the Git object `cd57d9f`.

## EXECUTIVE_VERDICT

# NO_GO

The daily chain is a careful exploratory research chain and the R8 chronology repair is genuine. It is not sufficient to authorize an R9 operational walk-forward as committed.

- The authoritative R1 artifact is `INTERIM_PARTIAL_PROVENANCE`, allowed only for exploratory factor research, and explicitly prohibits `FORWARD`.
- R8's F7 features overlap with the same-event EOD acceptance definition used to label SUCCESS/FAILED_BREAKOUT. PIT safety does not make this independent discovery.
- R8 is a selected 146-event development subset, not a population or execution study, and all four checkpoints and four primary features have already been inspected.
- Prospective identity is not closed: B2 confirmation can regress, there is no EXPIRED/TTL state, and repeat-confirmation/de-duplication semantics are not frozen.

This finding does not assert a remaining future-bar leak in the repaired R8 program. It rejects direct conversion of exploratory, selected, partially circular evidence into a prospective decision rule without a new frozen protocol and independent endpoint.

## PROJECT_RECONSTRUCTION

| Phase | Question / input | Output / conclusion | Current authoritative status |
|---|---|---|---|
| R0 | Build causal daily outcome base and SUCCESS/control case set from frozen daily snapshots and episodes. | Legacy 8,746-row case set and event alignment. | `LEGACY_ONLY`: `research/intraday/success_control_cases_v01b.csv`. |
| R1 | Reconstruct labels with separate feature/label snapshots and quarantine conflicts. | 8,682 reproducible rows; 64 quarantined; 3D parity gate passed. | Current input: outcome SHA `01a9f2fa...` and `manifest_v01b_reproducible.json`; partial provenance/exploratory only. |
| R2 | Compute frozen daily factors at candidate D without labels. | 25 factors for 8,682 rows; output SHA `a485a484...`; outcome excluded in extractor. | Current factor CSV, contract SHA `a67e7e2...`, and factor manifest. |
| R3 | Screen individual factors and inspect factor structure. | Contraction is a hypothesis; not a validated trading factor. | R3A inference is superseded by tie-corrected R3A1; R3B is current descriptive interpretation. |
| R4 | Test stability across time/regime/board/T0 type. | Some directions stable; BOARD/T0 position data-limited; no promotion. | R4 V01 plus V01.1 coverage are current descriptive evidence. |
| R5 | Compare fixed B4--B7 simple benchmarks. | B6 was strongest observed baseline (AUC about 0.555); B5/B7 weak. | Current R5B report includes the classification precision patch. |
| R6 | Test contraction conditional on B6. | `median_range_ratio` conditionally discriminates within B6 signal cases. | Alignment closeout `3b858e4`; R6B results are current. Conditional discrimination is not causal independence. |
| R7 | Test fixed multivariable attribution ladder. | Range adds in-sample signal; quiet is tiny; pvr/mvr individual attribution unstable at correlation about 0.957. | R7B current, with interpretation corrected by `757772f`; CIs are non-clustered. |
| R8 | Test S1 activation versus post-activation acceptance on frozen 5m data. | `056cb2b` invalidated due unordered bars. `cd57d9f` sorts and reruns; F7 separates selected labels. | Only `cd57d9f` R8B artifacts/results are current; no old R8 value is used here. |

The authoritative chain is R1 final artifact -> R2 -> corrected R3 -> R4 -> patched R5 -> aligned R6 -> interpretation-corrected R7 -> chronology-fixed R8. It is a chain of exploratory evidence and corrections, not serial independent confirmations.

## ARCHITECTURE_ALIGNMENT

### A

Necessary foundations: explicit daily snapshot IDs and hashes; quarantine; 1:1 episode joins; no-label factor extraction; separate activation/acceptance layers; completed right-labelled 5m slicing; and the target ASL -> Adapter -> Canonical -> Snapshot -> State -> Strategy boundary.

### B

Over-engineering risk: a separate absolute-path R8 research lake creates a second data contract before ASL_ACTIVE exists. Multiple registries/model ladders provide process hygiene but do not replace an independent endpoint, clustered uncertainty, or execution evidence.

### C

R3--R7 are historical-label association studies, not filled-trade studies. R8 is a label-adjacent same-day acceptance study. Neither establishes queues, liquidity, price limits, T+1, cost, or post-decision PnL.

### D

R9 remains the correct *future research design* only after the gates below. A retrospective train/test split is not clean OOS because the cohort, labels, factor families, benchmarks, F7 features, and all four checkpoints have been viewed. Without the gates, stop at R8 development evidence.

## DATA_LINEAGE

### Daily

- Outcome SHA: `01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d`; feature snapshot `snap-2026-07-31-b5f84004de8a` / `e7243dee...`; label snapshot `snap-2026-08-06-e798f88ff67b` / `7cc614bf...`.
- Feature SHA: `a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8`; factor contract SHA `a67e7e2...`.
- R5 signals SHA `ee1c132b...`; R6 registry SHA `08b8e01d...`; R7 registry SHA `828a3148...`. The runners hash-gate and identity-gate these joins.

Output identity is strong. Regeneration lineage is incomplete: R2 reads a mutable adjustment-factor glob under `data/raw/...`; R1 records `cohort_provenance: PARTIAL` and 64 quarantined rows. A hash-pinned output is auditable, but this is not proof that all upstream historical data are independently reproducible or suitable for Forward use.

### Intraday

R8 pins ASL candidate SHA `04bd94936587b35cae55c833627260866d025184`, 40 TDX 5m partitions / 270,000 rows, and dataset lock SHA `3914887a81908dfc6745c412a3f0406c3ba6a7ddc7e7e2902b0af0fb730add9a`; it declares shares/RMB and right-labelled bars. The S1/event provenance CSV pins S1 to the current outcome and event dates to the legacy case set.

The raw lake is uncommitted and absolute-path dependent (`/Users/luke808/AI/asl-r8-5m-lake`). Partition hashes establish byte identity only while that lake exists; they do not prove ASL_ACTIVE equivalence, vendor non-revision, or daily/intraday scale compatibility. No targeted “latest file” or mtime selector was found in these research paths; the material mutable dependencies are the adjustment glob and external lake.

## PIT_LOOKAHEAD

### Daily R2--R7

The extractor whitelists candidate-time columns, explicitly bans outcome/event columns, sorts bars, and uses pullback information through D for this post-close task. Future bars are read only by the outcome builder after candidate D. No direct daily feature look-ahead was found.

Limitation: this is a final-vintage canonical snapshot, not a demonstrated historical as-of vendor-vintage replay. It cannot prove the absence of revision/survivorship bias.

### Intraday R8

The repaired code sorts `(symbol, trade_date, bar_time)`, asserts strict time increase, slices `bar_time <= checkpoint`, anchors on first completed `high >= S1`, excludes the anchor from F7, uses checkpoint-only VWAP, and compares to D1 same-time volume. The 5,625/5,625 physical-order defect is therefore repaired for the consumer. Shuffle/monotonicity tests support this.

Right-label semantics are still an external source assertion rather than an independently reproducible raw-data proof. R9 needs an ingestion-level chronological invariant and right-label fixture, not merely consumer sorting.

## LABEL_OUTCOME

SUCCESS means S1 before invalidation plus, on the first S1-touch day, `close >= S1` and volume at least candidate-day volume. FAILED_BREAKOUT is a first S1 touch failing close acceptance or expansion. This is a legitimate daily label, but it overlaps R8's post-touch close-above-S1, retest, and below-S1 duration measures.

- No checkpoint future-bar leakage was found.
- There is partial label tautology: a morning acceptance path is used to predict an EOD acceptance label partly defined by the same construct.
- SUCCESS and FAILED_BREAKOUT use the same first-S1-touch anchor rule, so the pair has a fair anchor conditional on being in that pair.
- Membership is outcome-conditioned: only SUCCESS/FAILED obtain S1 event dates, and R8 then keeps intraday-available dates. R8 cannot estimate candidate-to-activation or all-candidate acceptance probabilities.

## COHORT_SELECTION

The 8,682 rows are not iid. A direct count of the committed cohort gives 2,393 symbols, median 3 and maximum 15 episodes per symbol; 8,163 rows belong to repeated symbols. There are 63 same-symbol candidate pairs within three calendar days and 619 within ten. Market/calendar dependence further reduces effective sample size.

Therefore nominal unclustered p-values, CIs, and AUC uncertainty are anti-conservative. R8 is narrower still: 146 episodes, 141 symbols, 25 dates, 43 SUCCESS / 103 FAILED_BREAKOUT, 2026-06-05 through 2026-07-30. It is a conditional availability-filtered development subset, not the 8,682-candidate population.

## STATISTICAL_VALIDITY

Mechanical controls are good: tie correction, zero-cell policy, fixed contracts, common samples, alignment checks, and hashes. Researcher degrees of freedom remain material: 24 daily factors, factor families, stability strata, B4--B7, conditional groups, 3D/5D outcomes, model ladders, and 4 x 4 R8 feature/checkpoint looks have been observed.

B6 may have been a frozen structural threshold, but it became the primary R6 benchmark after R5 showed it strongest. `median_range_ratio`, quiet days, and the highlighted 10:30 results are observed-data selections. The absence of a formal threshold scan does not remove development optimism. All effects are development estimates, not calibration, significance, or expected-return evidence.

## R5_R6_REVIEW

R5's own/common eligibility, known-label handling, binary AUC, and zero-cell policy are explicit. B6's common-sample AUC about 0.555 and OR 1.63 are modest association, not a trading edge. B4 is weaker and B5/B7 effectively neutral.

R6's three-way identity and denominator alignment are sound. `median_range_ratio` establishes conditional discrimination in a B6 signal subset, not independent causal information. Conditioning on a signal sharing T0/D construction with the outcome can change composition; collider/subset-selection explanations remain open. Direction consistency at 5D helps but does not solve clustering or selection.

## R7_REVIEW

R7 correctly uses a same complete-case core sample (3D N=7,837; SUCCESS=370), an intercept, raw predictors, converged `statsmodels.Logit`, and equal denominators within model families.

- `median_range_ratio` adds about 0.0235 in-sample AUC from M0 to M1 and preserves direction at 5D: conditionally supported, not independently validated.
- `quiet_days_n` adds roughly 0.0038 AUC: sign-consistent but no established practical significance and mechanically time-exposed.
- pvr/mvr correlation about 0.957 makes individual attribution unstable; the current mixed-joint/unstable-individual interpretation is appropriate.
- Model CIs are explicitly `MODEL_BASED_NON_CLUSTERED`; iid inference is unsupported.

## R8_REVIEW

Only fixed R8 is considered. The chronology repair is credible: the loader and feature row sort, strict ordering is asserted, shuffle-invariance is tested, and the local lake test observes all 5,625 physical symbol-days unordered before canonicalization. The old `056cb2b` results are invalid and not evidence.

At 10:30 the finite F7 denominator is 26 SUCCESS / 80 FAILED (106), versus activated 27 / 81. The audit interpretation is:

| Measure | AUC | Verdict |
|---|---:|---|
| breakout_hold_ratio | 0.711 | Moderate-to-strong conditional same-day diagnostic; development-selected and label-adjacent. |
| retest_depth | 0.644 | Moderate conditional diagnostic; same restrictions. |
| false_break_duration | 0.317 | Moderate separation in its negative direction; same restrictions. |
| VWAP acceptance | 0.570 | Weak-to-moderate conditional association. |

`ACTIVATE != ACCEPT` is partially supported: activation is more frequent for FAILED in this selected pair. It does not mean activation is useless in the full candidate population. R8 supplies no CI, missingness-by-label analysis, clustered uncertainty, calibration, fill, cost, or trading outcome.

## LABEL_CIRCULARITY

HIGH finding:

```text
Daily label: first S1 touch + EOD close acceptance / volume expansion
R8 F7:      first intraday S1 touch + post-touch holding / retest / false-break
```

The features are PIT-safe but partly restate the label's economic/structural construct. They may be retained as same-day operational diagnostics. They cannot be claimed as independent discovery of second-launch or trading edge. A valid R9 must evaluate a distinct post-decision endpoint and report the daily acceptance label only as a secondary diagnostic.

## TIME_DIMENSION

`days_since_t0`, `days_to_pullback_low`, and `pullback_duration` exist, but no primary study establishes setup ageing, TTL, or time-to-second-launch. R3B records formal days-to-launch analysis as not yet contracted. This is an R10/promotion blocker, not a reason to tune a TTL now: R9 must record age/timing and pre-specify descriptive strata without adaptive expiry selection.

## B1_B2_STATE_MACHINE_GAPS

| Gap | Classification | Disposition |
|---|---|---|
| B2_CONFIRMED can fall back to B2_READY; no one-time confirmation event/test. | HIGH, R9 blocker | Freeze an absorbing/event-record meaning and first timestamp. |
| No EXPIRED/TTL state; B2_READY can persist. | HIGH, R9 blocker | Freeze expiry and observation semantics. |
| Repeat confirmation / TradePlan de-duplication. | HIGH for R9 identity; production blocker for execution. | Use immutable setup/event keys; do not infer new events after downgrade/re-upgrade. |
| Fill, queue, T+1, limits, costs. | Production/trading blocker, not data-collection blocker. | Keep R9 paper/observational. |
| S1 timing | Not a blocker in daily code. | Retain `eligible_from > frozen_as_of`; record S1 vintage. |

## R9_DESIGN_REVIEW

Starting a truly prospective observational study on 2026-08-10 is the correct next design only after a versioned immutable protocol freezes: population including non-activations; one event/TTL/de-duplication rule; S1 vintage; one primary checkpoint/feature/rule; a post-decision endpoint separate from EOD acceptance; horizon/stopping/multiplicity/cluster plan; and append-only provider/input/output provenance.

Do not choose 10:30, a threshold, or score after new results. Do not promote F7 directly to a frozen strategy rule.

## PRACTICAL_TRADING_VALUE

Current evidence supports hypotheses, not action. AUC about 0.55 is modest after selection, base rate, and friction. AUC 0.60--0.71 on 106 finite selected 10:30 rows is interesting but uncalibrated and endpoint-adjacent. Slippage, fees, ticks/limits, auction mechanics, partial fills, queue position, liquidity, T+1 exits, and post-decision PnL are **NOT YET TESTED**. No order was placed or implied.

## ENGINEERING_CI

# NEEDS_FIX

Daily hash gates and deterministic local checks are sufficient for exploratory research. R8's full lake-lock, disorder, and repeat-run tests are `local_data`; cloud CI covers synthetic ordering only. The R8 runner writes output CSVs before all QA completes. R9 needs immutable per-run output, temporary/atomic publication, input/output hashes, and an executable data gate. This does not require designing a larger CI system.

## ASL_ARCHITECTURE

`ASL_UPSTREAM_HEAD -> ASL_CANDIDATE -> validation -> ASL_ACTIVE`, followed by Adapter -> Canonical -> Snapshot -> State -> Strategy, is sound. The independent R8 lake is acceptable only as quarantined research input; it does not prove future ASL_ACTIVE semantic equivalence.

R9 provenance must pin upstream commit, candidate/active status, adapter/schema, partition hashes, source/query semantics, timezone/right-label assertion, units, and daily/intraday S1 reconciliation. Fail closed on provider/version/scale conflict.

## UNKNOWN_UNKNOWNS

| Risk | Why it matters / evidence | Severity | Disposition |
|---|---|---|---|
| Vendor revisions / timestamp semantics | Raw 5m bars are external and “right labelled” is declared rather than Git-replayable. | HIGH | Archive/hash partitions and verify session/bar-end semantics. |
| Auction or single-print touches | A 5m high can activate without executable crossing/fill. | HIGH | Freeze touch/auction handling and stratum/exclusion. |
| Daily/intraday scale/rounding | Cross-feed S1 boundary can flip activation. | MEDIUM | Reconcile ticks/prices with declared tolerance and fail closed. |
| Halt/special session grid | Morning completeness applies only to selected events. | MEDIUM | Keep exchange-calendar exception log. |
| Regime/sector/calendar correlation | 25 dates and repeated symbols can mimic edge. | MEDIUM | Predefine calendar-block/concentration reporting. |
| Survivorship/coverage | Partial R1 provenance and R4 coverage gaps limit generalization. | MEDIUM | State exact universe; do not generalize. |
| Post-selection optimism | 16 R8 looks plus R3--R7 historical inspection. | HIGH | One preregistered rule or multiplicity control. |

## CLAIM_AUDIT_TABLE

| Current claim | Evidence | Independent verdict | Confidence | Can enter R9? |
|---|---|---|---|---|
| B6 volume contraction useful | R5 AUC about 0.555 / OR 1.63 | PARTIALLY_SUPPORTED | Medium | Frozen hypothesis only |
| median_range_ratio adds beyond B6 | R6 conditional AUC 0.4222/0.4099 | PARTIALLY_SUPPORTED | Medium | Exploratory/pre-specified |
| median_range_ratio independently adds in model | R7 M1 delta AUC about 0.0235 | PARTIALLY_SUPPORTED | Medium-low | Not validated rule |
| quiet_days small increment | R7 M2 delta AUC about 0.0038 | PARTIALLY_SUPPORTED | Low-medium | Descriptive only |
| pvr/mvr individual attribution unstable | correlation about 0.957 | SUPPORTED | High | Yes, as restriction |
| activation alone is not acceptance | R8 rates in selected pair | PARTIALLY_SUPPORTED | Medium | Diagnostic only |
| breakout hold predicts acceptance | R8 AUC 0.711 | PARTIALLY_SUPPORTED | Medium-low | Independent endpoint only |
| shallow retest predicts acceptance | R8 AUC 0.644 | PARTIALLY_SUPPORTED | Medium-low | Independent endpoint only |
| short false break predicts acceptance | R8 AUC 0.317 negative direction | PARTIALLY_SUPPORTED | Medium-low | Independent endpoint only |
| VWAP has weaker/moderate value | R8 AUC 0.570 | PARTIALLY_SUPPORTED | Low-medium | Exploratory only |

## FINDINGS_BY_SEVERITY

### CRITICAL

None remaining in repaired code. The physical-order defect was critical for `056cb2b`, but its outputs are formally invalidated.

### HIGH

- R1 is partial-provenance and Forward-prohibited; R2--R8 cannot silently become R9 rule authority.
- R8 label circularity overstates F7 as independent discovery.
- R8 selected cohort cannot generalize to candidate/trade population.
- Development multiplicity removes clean retrospective OOS.
- TTL/repeat-confirmation identity is undefined.
- There is no prospective trade/execution endpoint.

### MEDIUM

- iid uncertainty is invalid; clustered/calendar-block reporting is absent.
- External R8 lake and adjustment inputs can drift from future provider/ASL semantics.
- Finite-feature denominators differ from activated denominators; missingness by label is unexamined.
- R8 data CI is local-only and publication is non-atomic.
- Setup ageing is unresolved.

### LOW

- R8's historical network-acquisition note should be separated more clearly from locked local analysis in future protocol metadata.

### NOTE

- R6 alignment, R7 multicollinearity interpretation, and R8 invalidation are meaningful self-corrections. They improve auditability but are not independent validation.

## PRE_R9_REQUIRED_ACTIONS

R9 is NO_GO until all five are explicitly reviewed and frozen:

1. Resolve the R1 `FORWARD`-prohibited partial-provenance boundary without rewriting immutable R0--R8 artifacts or quarantine.
2. Freeze R9 population, S1 vintage, one-time event/TTL/de-duplication semantics, one primary rule/checkpoint, horizon, stopping/multiplicity, and clustered/calendar-block uncertainty before the first row.
3. Define a decision-after endpoint distinct from EOD acceptance; keep current SUCCESS/FAILED label secondary/diagnostic.
4. Pin and validate ASL provenance end to end, including units, right-label timing, price reconciliation, append-only inputs, and atomic outputs.
5. Keep R9 paper/observational and separately predefine fill/cost outcomes before any trading-value or promotion claim.

## FINAL_DECISION

# NO_GO

R0--R8 are credible exploratory evidence with a real chronology repair, but not a bias-controlled authorization for prospective validation of an operational B1/B2/S1 rule. A new frozen R9 protocol satisfying the five gates is required before its first observation. It must not tune, rewrite, or retroactively reclassify R0--R8.

Evidence inspected: Git lineage through `cd57d9f`; authoritative R1--R8 reports, manifests, CSVs, research modules, R8 chronology tests, and targeted daily/state-machine code. Tests were not rerun because the checked-out worktree is not the audit commit and contains unrelated local modifications.
