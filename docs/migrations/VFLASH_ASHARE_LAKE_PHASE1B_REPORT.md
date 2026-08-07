# VFLASH × ASHARE-LAKE — PHASE 1B SHADOW STRATEGY VALIDATION REPORT

> Status: **PHASE1B_GATE = BLOCKED_PARITY (exit 2)** — fail-closed, honest.
> This is the SHADOW / RESEARCH validation of the ASL data backend against the
> frozen V Flash strategy after independent-review fix round 1 (Draft PR #27,
> commit b4da284).  It is NOT a production cutover, NOT a provider deletion,
> NOT approval to begin Phase 1C.

## 0. Review-round provenance

This revision replaces the earlier PASS claims of the initial Phase-1B report.
Independent ChatGPT review (PR #27 at b4da284) required: coverage skip
semantics, exhaustive per-date input classes with a reachable UNKNOWN,
trade_status as a hard field, ASL status-provenance ST semantics, a
non-vacuous common-calendar control, setup_id-keyed episodes, candidate-date
success/control comparison, actionable-vs-entry screen populations,
bounded AS_OF counterfactual attribution, strict volume policy, and an
aggregate-RSS resource gate.  The 2026-08-03 preclose cascade fix (18 codes)
was separately authorized for full-market validation after targeted
five-point proof; it is frozen in this run (section 5).

## 1. Scope and boundary

| item | value |
|---|---|
| comparison window | 2026-04-01 → 2026-08-06 (AS_OF = 2026-08-06; no 2026-08-07 data) |
| history window | 2024-01-16 → 2026-08-06 (MA250 max lookback; extension documented below) |
| frozen universe | Phase-2D0, N=3191, hash `8d1f99b1b9aac72a9ddfbe898def2f12c59938f83f012fe46017951e24ef1afb` |
| full-market runs | **1** (this authorized final run; workers=3, chunk=300) |
| lake | existing untouched Phase-1B lake `/tmp/asl_phase1b_lake`; **MANUAL_ASL_DATA_EDITS = 0**; no dataset rebuilt |

## 2. Data gate

* DATA_GATE = **PASS**
* FROZEN_UNIVERSE_N = 3191 · PROCESSED_CODE_N = 3191 · SKIPPED_CODE_N = 0
* ASL_CODE_COVERED_N = 3191 · EXPLAINED_MUTUAL_TERMINAL_ABSENCE_N = 1 (000838)
* LEGACY_ONLY_CODE_DATE_N = 72 (all IPO first days, 69 codes) ·
  ASL_ONLY_CODE_DATE_N = 118,383 (515 codes)
* data_blocked = [] · coverage_contract_ok = true
* Required datasets / columns / v2 / duplicate-PK / status-provenance checks:
  all clean (trusted_baostock_n=0, trusted_derived_gap_n=2928,
  trusted_eastmoney_same_day_n=0, non_pit_eastmoney_ignored_n=0,
  unknown_status_n=0)

## 3. Resource gate

* RESOURCE_GATE = **PASS**
* AGGREGATE_PEAK_RSS = **3,294 MB** (psutil parent + live children RSS sum,
  max over 2s samples) ≤ 4,096 MB budget (min(4 GiB, 25% of 16 GiB RAM))
* HARNESS_WALL_SECONDS = **834.4** (strategy execution only; excludes ASL
  backfill) · workers=3 · chunk=300

## 4. Hard field parity

* HARD_FIELD_PARITY_GATE = **PASS**: HARD_FIELD_CONFLICT_N = **0**
* TRADE_STATUS_PARITY_GATE = **PASS**: 0 trade_status conflicts on common rows
* VOLUME_DIVERGENCE rows = 3 (603007 ×2, 603559), all
  OUTSIDE_EVAL_HISTORY_VOLUME_DIVERGENCE (proven outside every 250-bar eval
  window; strategy-inert with explicit reasoning); volume-in-window = 0
* Preclose is an EXACT contract (relative tolerance removed): 344 per-date
  LEGACY_PRECLOSE_ERA_DIVERGENCE rows, all with code-specific corporate-action
  evidence (see section 12)

## 5. Preclose cascade (authorized fix) — resolved

The 18 previously-UNKNOWN 2026-08-03 rows are now classified
**LEGACY_HOLE_REPAIRED_BY_ASL** under the frozen strengthened rule.  The rule
requires ALL of: both chains sequential; ASL predecessor date differs from
legacy predecessor date; ASL predecessor date absent from legacy CONFIRMED
rows; ASL predecessor date exists as a valid ASL row; legacy predecessor date
exists on the ASL side; preclose difference fully membership-explained.
Otherwise UNKNOWN_INPUT_DIVERGENCE (no loosening).

* **UNKNOWN_INPUT_DIVERGENCE_N = 0** (per-date and eval-point)
* Per-code five-point proof for all 18 rows:
  `research/asl_phase1b/artifacts/preclose_diagnostic_20260803.json`
  (all `all_proofs_hold = True`; legacy predecessor 2026-07-30 vs ASL
  predecessor 2026-07-31, except 002828 2026-07-08 vs 2026-07-24)
* LEGACY_HOLE_REPAIRED_BY_ASL per-date = 118,401 (+18 vs prior run)

## 6. Input classification (per-date, exhaustive)

```
INPUT_EQUIVALENT                 12,737
LEGACY_HOLE_REPAIRED_BY_ASL     118,401  (legacy CONFIRMED holes incl. the
                                         18 preclose cascades)
LEGACY_ONLY                          72  (IPO first days; frozen adapter
                                         first-row MISSING_PRECLOSE semantics)
LEGACY_PRECLOSE_ERA_DIVERGENCE      344  (legacy exchange preclose vs ASL
                                         sequential, code-specific CA evidence)
VOLUME_DIVERGENCE                     3  (all outside every eval window)
ST_COVERAGE_UNKNOWN              83,973  (legacy non-PIT ST=True vs ASL None;
                                         no trusted ASL ST row in the lake)
LEGACY_NON_PIT_TO_ASL_UNKNOWN 1,729,041  (legacy ST=False vs ASL None;
                                         expected PIT semantic delta, inert)
HARD_FIELD_CONFLICT                    0
UNKNOWN_INPUT_DIVERGENCE              0
PIT_ST_DATA_UPGRADE / TRUSTED_ASL_NORMAL / TRUSTED_ASL_ST  0 (no trusted ST rows)
```

Eval-point classes are ASSOCIATED_INPUT_CLASS (window-based, 250 bars), NOT
proven root cause: LEGACY_HOLE_REPAIRED 249,946 · LEGACY_ONLY 2,831 ·
LEGACY_PRECLOSE_ERA 11,570 · ST_COVERAGE_UNKNOWN 12,523 ·
INPUT_EQUIVALENT 0 (structurally: legacy hole density) · UNKNOWN 0.

## 7. Common-calendar control (non-vacuous)

* COMMON_CALENDAR_CONTROL_GATE = **PASS**
* CONTROL_EQUIVALENT_EVAL_POINT_N = **224,328** (> 0 required)
* CONTROL_STRATEGY_MISMATCH_N = **0** (required = 0)
* control trade_status conflict dates = 0

## 8. Strategy timeline parity

* STRATEGY_ENGINE_PARITY_FAILURES_N = 0 (window-INPUT_EQUIVALENT mismatches)
* UNKNOWN_EPISODE_DIVERGENCE_N = **0** → EPISODE_PARITY_GATE = **PASS**
* DIVERGED_BUT_MATCHING_N = 205,522 · DIVERGED_AND_MISMATCHING_N = 71,348
  (by associated class: LEGACY_HOLE_REPAIRED 64,794 · LEGACY_PRECLOSE_ERA
  3,077 · ST_COVERAGE_UNKNOWN 2,794 · LEGACY_ONLY 683)
* FIRST_RESULT_DIVERGENCE_N = 3,191 · FIRST_INPUT_DIVERGENCE_N = 3,191

## 9. Episode parity (setup_id / transition-date model)

```
EXACT_EPISODE                       1,473
LEGACY_HOLE_CHANGED_EPISODE         2,353
LEGACY_PRECLOSE_ERA_CHANGED_EPISODE   117
ST_COVERAGE_UNKNOWN_EPISODE             9
ASL_NEW_VALID_EPISODE                  823
LEGACY_ONLY_EPISODE                     79
UNKNOWN_EPISODE_DIVERGENCE               0
```

Episodes are keyed by the production setup_id with first B1/B2_READY/
B2_CONFIRMED dates, invalidation date, end date, max/final stage and
transition scores; different B1/B2 timing is NOT exact.

## 10. Success / control cases (at candidate_date)

FROZEN_CASE_N = 1,947 (candidate_date in window) · COMPARED_CASE_N = 1,947
· INCLUSION_CHANGED_N = **165** · ANCHOR_CHANGED_N = 71 ·
STAGE_CHANGED_N = 199 · legacy_only_sig_n = 0 · asl_only_sig_n = 0.
Signatures compared AT each case's frozen candidate_date (not AS_OF finals);
frozen outcomes NOT relabeled.

## 11. Full-market screen at 2026-08-06

| population | legacy | ASL |
|---|---|---|
| ACTIONABLE_STAGE_N (stage-only) | 279 (B1 49 / B2_READY 197 / B2_CONFIRMED 33) | 273 (B1 52 / B2_READY 191 / B2_CONFIRMED 30) |
| ENTRY_CANDIDATE_N (is_entry_candidate) | 220 | 209 |

* ADDED_ENTRY/ACTIONABLE candidates = 26 · REMOVED = 32 (full lists in
  `research/asl_phase1b/shadow_summary.json`)
* TOP20 (deterministic ranking: normalized_score DESC, setup_quality DESC,
  entry_quality DESC (None last), code ASC; population = entry candidates):
  TOP20_COMMON_N = **7** · TOP20_EXACT_POSITION_N = **2**
  LEGACY_ONLY_TOP20 = 603630, 603779, 002597, 002387, 603058, 002775,
  603721, 603009, 600236, 002677, 603801, 603577, 002522
  ASL_ONLY_TOP20 = 001323, 002791, 600513, 002512, 002015, 600082,
  002580, 002279, 002292, 600578, 603373, 603258, 600702

## 12. Corporate-action intersection (real legacy-vs-ASL evidence)

CORPORATE_ACTION_INTERSECTION = **INTERSECTION_FOUND** — 20 real ex-dates
where ASL corporate_action + ASL bar + legacy CONFIRMED row all exist; every
case records code, ex_date, action_type, cash_dividend, and BOTH sides'
OHLC / preclose / recomputed pct / limit-close, with CA_MATCH_FOR_CODE_DATE
= True.  Full records in `research/asl_phase1b/artifacts/shadow_full.json`.

Summary: OHLC and close identical on all 20; limit-close state identical on
all 20; preclose exact on 1/20 (000681 2026-08-03); on the other 19 the
legacy value is the exchange (dividend-adjusted) reference while ASL
implements the frozen sequential previous-close — differences equal the
dividend amount (0.01–0.07 yuan).  pct_change differs accordingly.  These
are the 344 per-date LEGACY_PRECLOSE_ERA_DIVERGENCE rows, proven by
code-specific CA evidence (never date-only membership).

## 13. AS_OF causal attribution (bounded counterfactuals)

Affected codes (added/removed candidates + Top20 membership/rank changes) =
79.  Ablations per code: MASK_LEGACY_HOLE_ROWS,
NEUTRALIZE_STATUS_TO_LEGACY, RESTORE_LEGACY_PRECLOSE_CA_ERA (where
relevant), SUBSTITUTE_LEGACY_VALUES_COMMON_ROWS (last-resort diagnostic).

* PROVEN: MASK_LEGACY_HOLE_ROWS 46 · NEUTRALIZE_STATUS_TO_LEGACY 8
* **AS_OF_ROOT_CAUSE_UNKNOWN_N = 25** → AS_OF_CAUSAL_ATTRIBUTION_GATE = **FAIL**
  Codes: 000657, 001207, 001388, 002051, 002058, 002112, 002119, 002158,
  002174, 002292, 002467, 002577, 002597, 002910, 002918, 003020, 600749,
  600815, 600847, 603313, 603330, 603339, 603630, 603906, 603917

For every affected code the artifact records legacy/asl final signatures,
associated class at AS_OF, every attempted ablation with its resulting
stage/entry/anchor and restore result.  The 25 UNKNOWNs share the pattern:
no SINGLE input-class ablation restores the legacy decision — the strategy
state differences are compound consequences of the repaired-hole history,
CA-era preclose rows, and (for some) status coverage (e.g. legacy
B2_READY/B2_CONFIRMED/INVALID vs ASL INVALID/B2_READY/NORMAL with anchors on
2026-07-08 / 07-27 / 07-29 / 08-03..05).  No new explanatory classification
was invented; UNKNOWN remains blocking.

## 14. ST decision coverage

* TRUSTED_ASL_ST_N = 0 · TRUSTED_ASL_NORMAL_N = 0 (the lake has no trusted
  historical ST rows; the official baostock ST sweep is not complete)
* ST_COVERAGE_UNKNOWN per-date = 83,973 (legacy non-PIT ST=True snapshot vs
  ASL None) · LEGACY_NON_PIT_TO_ASL_UNKNOWN = 1,729,041 (strategy-inert)
* **DECISION_RELEVANT_ST_COVERAGE_UNKNOWN_N = 59** →
  ST_DECISION_COVERAGE_GATE = **FAIL**
* Breakdown (targeted per-code flags in
  `research/asl_phase1b/artifacts/st_decision_relevant_59.json`):
  * AS_OF candidate differences: 000826, 002528, 600730, 603398, 002512,
    600082 (6)
  * Top20 membership: 002512, 600082 (2, also candidates)
  * episode differences with ST coverage unknown association: all 59
    (53 episode-only)

  Full code list: 000010, 000016, 000056, 000078, 000609, 000632, 000639,
  000677, 000826, 000838, 000909, 002082, 002109, 002175, 002193, 002207,
  002217, 002360, 002431, 002485, 002501, 002512, 002514, 002528, 002542,
  002547, 002581, 002620, 002667, 002726, 002731, 002759, 002856, 002977,
  600082, 600165, 600180, 600187, 600238, 600243, 600289, 600302, 600337,
  600370, 600423, 600537, 600678, 600730, 600759, 601010, 603189, 603272,
  603378, 603398, 603429, 603789, 603843, 603922, 605336

No automatic multi-hour ST sweep was started; the decision on targeted ST
history for affected codes, broader ST completion, or an approved
neutralization/control experiment is deferred to ChatGPT.

## 15. PHASE1B_GATE

**PHASE1B_GATE = BLOCKED_PARITY** (exit 2) — fail-closed, not manufactured.

| gate | result |
|---|---|
| DATA_GATE | PASS |
| RESOURCE_GATE | PASS (3,294 MB ≤ 4,096 MB) |
| HARD_FIELD_PARITY_GATE | PASS (0 conflicts) |
| TRADE_STATUS_PARITY_GATE | PASS (0 conflicts) |
| COMMON_CALENDAR_CONTROL_GATE | PASS (224,328 / 0) |
| EPISODE_PARITY_GATE | PASS (0 unknown episodes) |
| AS_OF_CAUSAL_ATTRIBUTION_GATE | **FAIL** (25 UNKNOWN root causes) |
| ST_DECISION_COVERAGE_GATE | **FAIL** (59 decision-relevant ST unknown) |
| PHASE1B_GATE | **BLOCKED_PARITY** |

## 16. Open items

1. AS_OF decision differences of 25 codes lack a proven single input-class
   root cause (compound history divergence; no new class invented).
2. Decision-relevant ST coverage unknown (59 codes): the lake has no trusted
   historical ST facts; the legacy ST reference is
   NON_PIT_CODE_LEVEL_STOCK_BASIC_SNAPSHOT.
3. Turnover: remains NULL (no ASL source; separate enrichment track).
4. Limit-up pool: remains outside ASL (PRICE_ONLY comparison used).
5. INPUT_EQUIVALENT eval points structurally 0 (legacy hole density); engine
   parity proven by the non-vacuous common-calendar control instead.

## 17. Tests

`tests/test_shadow_harness.py` (34 tests) + ADR-008, warehouse validate,
corporate-action preclose, ASL adapter, parity harness suites: **134 passed**.
`compileall` OK; `git diff --check` clean.  No second full-market execution
after this run.

## 18. Artifact hygiene

Committed: this report, `research/asl_phase1b/shadow.py`,
`research/asl_phase1b/shadow_summary.json` (compact, no absolute paths),
`research/asl_phase1b/preclose_diagnostic.py`, `tests/test_shadow_harness.py`.
Raw full results and targeted diagnostics live under the gitignored
`research/asl_phase1b/artifacts/`.

## 19. Status statement

This report approves NO production cutover, NO provider deletion, NO
turnover derivation, NO limit-up-pool replacement, and NO Phase 1C.  The
authoritative gate is BLOCKED_PARITY pending resolution of the two blocker
groups (sections 13–14).
