# PRE_R9_PROTOCOL_HARDENING_V02

STATUS: COMPLETE — protocol hardening is frozen; R9 accumulation remains blocked.

BRANCH: research/second-launch-factor-pre-r9-hardening-v02

BASE_HEAD: cd57d9fa7cfa32cbec7f53e8165b12dcb6f86018

HEAD_AFTER: commit containing this report; resolve from Git metadata after commit.

REMOTE_SHA: NOT_PUSHED

INDEPENDENT_AUDIT_SHA: 79837ef9ea5d103f8032e081b20fa1519a35cb005c3f8c4d0bdace7f8acc3573

AUDIT_IMPORT: byte-identical import only; no other original dirty-worktree file was imported.

## R8_QA_CLOSE

The final R8 QA bug was reporting-only: activation_time is a full timestamp but a checkpoint is HH:MM, so direct string equality falsely printed all zeros. The runner now canonicalizes the activation clock before comparison. It changes no F7 formula, denominator, artifact content, or R8 interpretation.

| Metric | Value |
|---|---:|
| TOUCH_AT_CHECKPOINT_N_09_45 | 6 |
| TOUCH_AT_CHECKPOINT_N_10_00 | 6 |
| TOUCH_AT_CHECKPOINT_N_10_30 | 2 |
| TOUCH_AT_CHECKPOINT_N_11_30 | 0 |

## R8_RESULT_INVARIANCE

PASS — R8 core artifacts are byte-identical to cd57d9f:

| Artifact | SHA-256 |
|---|---|
| r8b_intraday_checkpoint_features_v01.csv | 022ce2f78e06fc6b225aee1787163b5073fd5388d538251e3bcf52e4e1cccd26 |
| r8b_intraday_acceptance_results_v01.csv | 6255e52cfd0219ff1225eab5c7512e29b5b87b764cd7238cc72e23bf93c5e231 |
| r8b_activation_results_v01.csv | 25652aa770551930441920a013750ff1183a97362d24c6cf2545133bf287773f |

The regression test performs these hash checks and the clock-count reconciliation without running the external lake. A future changed artifact must report STATUS=BLOCKED_R8_QA_CHANGED_RESULTS; this task did not rerun or reinterpret R8.

## R1_AUTHORITY_BOUNDARY

R1_PROVENANCE_STATUS = INTERIM_PARTIAL_PROVENANCE

R1_FORWARD_AUTHORITY = FALSE

LEGACY_LABEL_ROLE = SECONDARY_DIAGNOSTIC_ONLY_NOT_R9_PRIMARY_ENDPOINT

R9 V01 does not upgrade, rewrite, or reinterpret R1 as Forward-authorized provenance. SUCCESS, FAILED_BREAKOUT, NO_LAUNCH, and STRUCTURE_FAIL remain development labels. A future mature R9 endpoint ledger may attach a legacy acceptance label only as a secondary diagnostic; it is never a primary R9 pass/fail endpoint.

## R9_POPULATION

R9_POPULATION_STATUS = BLOCKED_R9_POPULATION_SEMANTIC_GAP

Historical R1 candidate rows cannot be proven prospectively reproducible as written:

1. build_success_control_caseset_v01.py filters future_sessions_available >= 3 before earliest-per-setup deduplication.
2. V01A has an outcome-blind pit_mask, but its final cases again apply future maturity before deduplication; V01B preserves that population.
3. R2 only consumes frozen cases and explicitly excludes outcome/event columns; it is not a prospective candidate generator.
4. Existing strategy/replay state is point-in-time, but no authoritative adapter maps it to the R1 historical candidate population without substituting a new generator.

This task does not silently replace R1 with pit_mask, use a replay/TradePlan event path, or invent a population rule. An independent outcome-blind population-generator contract is required before clean R9 can start.

## R9_SETUP_ID

R9_SETUP_ID = make_setup_id(symbol, anchor_date, anchor_price, price_tick)

This is the existing authoritative identity, code:YYYYMMDD:anchor-price-ticks, and is compatible with historical R1 episode_id. strategy_version remains provenance; it is deliberately not appended to the historical-compatible key.

## R9_EVENT_ID

FIRST_S1_TOUCH_EVENT

event_id = setup_id:S1:event-date-YYYYMMDD:first-touch-HHMM

REPEAT_CONFIRMATION_CREATES_NEW_EVENT = FALSE

The R9 event ledger is separate from production B2 stage transitions. A first event is immutable. An identical replay is idempotent; a different later touch for the same setup fails closed and cannot become a second event. A touch after 10:30 is retained as POST_CHECKPOINT_NOT_OBSERVABLE, rather than fabricated into the 10:30 feature.

## R9_TTL

R9_OBSERVATION_TTL = UNRESOLVED

STATUS = BLOCKED_TTL_UNRESOLVED

There is no unique pre-existing maximum observation horizon. R1 outcomes use 3/5/10-session horizons; B1 eligibility uses a 7-session anchor window; anchor/replay lifecycle behavior uses 10-session lookback; and R2 records, rather than defines, elapsed-time variables. None is an authoritative R9 administrative TTL. Selecting 5, 7, or 10 here would be result-driven invention, so no TTL, ttl_end_date, candidate row, or non-activation row is created.

When an approved TTL exists, NO_ACTIVATION_WITHIN_TTL is contractually required to remain in the setup population; it must never silently vanish as in the selected R8 event cohort.

## PRIMARY_CHECKPOINT

R9_PRIMARY_CHECKPOINT = 10:30

LOCKED_SENSITIVITY_CHECKPOINTS = 09:45, 10:00, 11:30

10:30 is acknowledged as development-selected. Its only permitted rationale is chronology-fixed R8 development evidence: breakout_hold_ratio about 0.711, retest_depth about 0.644, and false_break_duration about 0.317 in the negative direction. This protocol never selects a later best checkpoint.

## PRIMARY_DAILY_HYPOTHESIS

PRIMARY_DAILY_COMPARISON = M1 vs M0

M0 = B4 + B5 + B6 + B7

M1 = B4 + B5 + B6 + B7 + median_range_ratio

M2 = SECONDARY_LOCKED_NO_REFIT

The R7 model registry SHA is 828a31484df655a02cb4c34452c26e70a954eb9221a517b5c5c098513677341f. The frozen coefficient artifact SHA is 39de709f424194be1a28d7e8e21be24c09824abc734027b29299a4b0452749ed.

M0/M1 are raw-coefficient rank-linear scores from published outcome_3d CORE_LADDER rows; no intercept is published, which does not affect Spearman rank. M1 uses its full refit B4--B7-plus-range vector, not M0 coefficients plus an added range term. No refit, standardization, calibration, threshold, or composite is allowed.

## PRIMARY_INTRADAY_HYPOTHESIS

PRIMARY_INTRADAY_FEATURE = breakout_hold_ratio

CHECKPOINT = 10:30

EXPECTED_DIRECTION = POSITIVE

Locked secondary features are retest_depth (positive: closer to zero is shallower), false_break_duration (negative), and vwap_acceptance_ratio (positive). They cannot replace or promote over the primary after outcomes mature.

## PRIMARY_ENDPOINT

DECISION_REFERENCE_TIME = 10:30 completed 5m bar

DECISION_REFERENCE_PRICE = 10:30 completed 5m close

FWD3_CLOSE_RETURN = close of E+3 A-share trading session / reference_price - 1

The endpoint calendar counts sessions strictly after event day. It never uses event-day EOD close, post-10:30 event-day path, or a later available stock bar to skip a missing third-session close. An unavailable E+3 close is DATA_UNAVAILABLE, not an adaptive substitution.

## SECONDARY_ENDPOINTS

FWD5_CLOSE_RETURN

MFE_NEXT_3_SESSIONS

MAE_NEXT_3_SESSIONS

FWD3_POSITIVE = FWD3_CLOSE_RETURN > 0, AUC diagnostic only.

FWD5 uses E+5 by the same calendar rule. There is no selected positive-return threshold, and no binary diagnostic is a primary success gate.

## LEGACY_LABEL_ROLE

The old daily acceptance label is SECONDARY_DIAGNOSTIC_ONLY_NOT_R9_PRIMARY_ENDPOINT. It cannot decide the primary continuous-return replication or authorize R10.

## MULTIPLICITY_PLAN

One daily primary comparison and one intraday primary feature/checkpoint are frozen. Three secondary intraday features and three sensitivity checkpoints are locked descriptive/sensitivity outputs. No feature promotion, checkpoint replacement, return-threshold search, composite, or mid-window model change is permitted.

## UNCERTAINTY_PLAN

PRIMARY: SYMBOL_CLUSTER_BOOTSTRAP, N_BOOTSTRAP=2000, SEED=20260809

SENSITIVITY: TRADE_WEEK_BLOCK_BOOTSTRAP, N_BOOTSTRAP=2000, SEED=20260809

Both CIs must be reported. If either resampling design is too sparse to be stable, result is UNCERTAINTY_STATUS=DATA_LIMITED; no iid CI fallback is allowed.

## STOPPING_RULE

NO_EARLY_STOP_FOR_PERFORMANCE = TRUE

INITIAL_WINDOW = 60 A-share trading sessions after clean OOS start

MIN_DAILY_MATURED_SETUP_N = 120

MIN_INTRADAY_10_30_FEATURE_OBSERVABLE_N = 40

Before the window ends, performance status is ACCUMULATING only. It cannot be VALIDATED, FAILED, or R10-authorizing. If fixed-window counts are insufficient, status is DATA_LIMITED; V01 does not auto-extend.

## ASL_CODE_SHA

ASL_CODE_SHA = 04bd94936587b35cae55c833627260866d025184

ASL_STATUS = RESEARCH_CANDIDATE_NOT_ASL_ACTIVE

R9_ASL_DATA_ROOT = /Users/luke808/AI/asl-r9-prospective-research-v01

The root is a protocol-only dedicated append-only research location at this stage; no directory contents or OOS partitions were created. Before later ingestion, each day requires source, schema version, partition list/hashes, units, timezone, bar-label semantics, ingested_at, and unchanged ASL code SHA. A vendor revision is a new data version, never an overwrite.

## DATA_PROVENANCE_CONTRACT

The future ingestion gate fails closed on duplicate symbol/trade-date/bar-time identity, physical chronological disorder, wrong full-session grid, or absent right-label verification. It does not rescue disorder by consumer-only sorting. Each R9 event also requires exact symbol/date match, exact tick alignment, and exact same S1 price across daily/minute representations; a mismatch is BLOCKED_PRICE_RECONCILIATION.

## ATOMIC_LEDGER_CONTRACT

Three header-only templates are frozen under research/second_launch/walk_forward_v01:

- r9_setup_ledger_schema_v01.csv
- r9_intraday_observation_ledger_schema_v01.csv
- r9_endpoint_ledger_schema_v01.csv

They contain no data rows. The protocol guards immutable feature key (setup_id, event_id, checkpoint): same hash is idempotent; a different hash is BLOCKED_FEATURE_DRIFT. A future versioned artifact must follow:

write temporary artifact -> schema check -> hash -> PIT check -> reconciliation -> atomic rename/promotion

The temporary-file helper refuses to overwrite an existing ledger destination; QA failure leaves no published artifact. Feature, observation, and future-endpoint records are separate so maturity cannot overwrite a feature row.

## EXECUTION_VALUE_BOUNDARY

R9_V01 = OBSERVATIONAL_PROSPECTIVE_RESEARCH

TRADING_VALUE_CLAIM = FALSE

Fills, queue position, price-limit mechanics, transaction costs, and T+1 execution are NOT YET TESTED. They remain R10/production blockers, not a reason to fabricate a cost model in this task.

## GATE_1_R1_AUTHORITY_BOUNDARY

PASS — R1 is frozen as non-Forward authority and legacy labels are secondary only.

## GATE_2_POPULATION_EVENT_TTL

BLOCKED — historical candidate semantics are not outcome-blind prospectively equivalent, and no unique authoritative R9 TTL exists. Event identity itself is frozen, but no population/TTL means no valid setup, event, or observation can be accumulated.

## GATE_3_INDEPENDENT_ENDPOINT

PASS — FWD3/FWD5 calendar-session close returns are distinct from same-day acceptance; legacy labels are secondary only.

## GATE_4_MULTIPLICITY_UNCERTAINTY

PASS — primary/secondary hypotheses, fixed bootstrap plans, and no-early-stop rules are frozen as contracts.

## GATE_5_ASL_PROVENANCE_ATOMICITY

PASS — contract-level gate only. Ingestion, exact reconciliation, append-only hash-drift, manifest, and atomic-publish guards are frozen and tested. No R9 partition has been accepted; every later ingestion must pass this gate independently.

## PRE_R9_STATUS

# NO_GO

## R9_RECOMMENDATION

# NOT_AUTHORIZED

PROTOCOL_FREEZE_COMMIT and OOS_START remain unset because all-gates-PASS is not satisfied. Clean OOS cannot be defined until Gate 2 is independently resolved and a new approved protocol version is committed. Candidate/event dates at or before any future protocol freeze are contractually rejected; the historical 8,682 cohort and 146 R8 events are explicitly rejected as R9 rows.

STRATEGY_CHANGED=false

PRODUCTION_CHANGED=false

FORWARD_CHANGED=false

TRADEPLAN_CHANGED=false

R9_OOS_ROWS_WRITTEN=0

## VALIDATION

tests/test_pre_r9_hardening_v02.py is a pure cloud_ci suite. It covers R1 boundary, blocked candidate/TTL guards, authoritative setup identity, one-event semantics, non-activation retention, 10:30/F7 primary freeze, frozen R7 M0/M1 score vectors, strict E+3/E+5 endpoint timing, multiplicity/bootstrap/stopping, exact reconciliation, ingestion disorder, append-only drift, atomic failure, pre-freeze/history rejection, and empty schema templates.
