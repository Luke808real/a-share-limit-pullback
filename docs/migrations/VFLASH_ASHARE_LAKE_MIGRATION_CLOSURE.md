# V Flash × Ashare-Lake Data Foundation Migration Closure

> 数据地基迁移验证阶段收口文档（DATA FOUNDATION VALIDATION CLOSURE）。
> 本文记录 V Flash 为什么迁移到 `rootSunc/ashare-lake`（ASL）、各阶段证明了什么、
> 评审中发现了什么、设计如何演化、以及冻结后的最终数据架构。

## STATUS

```
ASL_DATA_FOUNDATION_MIGRATION = ACCEPTED / CLOSED

AUTHORITATIVE_MARKET_DATA_SOURCE = rootSunc/ashare-lake
LEGACY_DATA_BACKEND            = FROZEN_DEPRECATED
LEGACY_PARITY_AS_PRIMARY_ACCEPTANCE_CRITERION = DISABLED
PRODUCTION_STRATEGY_SEMANTICS_CHANGED = NO
```

This closes the **data-foundation validation phase**.  It does NOT mean
production cutover is complete — production wiring is the next phase
(Phase 1C) and remains `NO-GO` until reviewed and accepted.

## WHY WE MIGRATED

V Flash previously depended on a multi-provider acquisition / reconciliation
stack combining:

* TDX
* Tencent
* EastMoney / AKShare
* Baostock
* Sina
* provider failover
* repair
* cross-provider reconciliation

That stack caused:

* inconsistent preclose semantics
* missing historical rows
* provider-specific units
* historical ST / PIT ambiguity
* reconciliation complexity
* duplicated market-data ownership
* excessive engineering time spent maintaining the data layer instead of
  strategy research

This is described as an engineering constraint, not a criticism of the old
system: the legacy stack served V Flash well for years.  ASL now replaces it
as the local market-data fact source.

## TARGET

GitHub upstream: **`rootSunc/ashare-lake`** (tested compatibility revision
`ba5681a`).

ASL is the new local market-data fact source of truth.  V Flash keeps its own
immutable strategy snapshots and state generation.  Snapshots are NOT a second
market database: they are reproducible strategy-input checkpoints derived
from ASL.

## PHASE HISTORY

| Phase | Result | Main outcome |
| --- | --- | --- |
| Phase 0 | READY_FOR_PHASE1 | Architecture / contract assessment |
| Phase 1A | PASS / CLOSED | Read-only ASL adapter + PIT provenance contract |
| Phase 1B initial | REJECTED | Shadow harness had correctness gaps |
| Phase 1B corrected | BLOCKED_PARITY | Harness fixed; genuine ST coverage blocker exposed |
| Targeted ST investigation | COMPLETED | Official ASL Baostock historical-ST path validated |
| Universe simplification | ACCEPTED | Main-board non-ST universe frozen |
| ST readiness redesign | ACCEPTED | Positive exclusion set + dataset-level completeness |
| ST scope correction | ACCEPTED | Coverage required only for tradable main-board codes |
| Data foundation migration | ACCEPTED / CLOSED | ASL adopted as authoritative source |

## PHASE 0 — WHAT WAS LEARNED

ASL daily data does not natively provide every old V Flash derived field.
The contract differences were frozen:

### preclose

Frozen V Flash contract: **previous valid close per code**.  No
corporate-action adjustment in this field (exchange preclose on ex-dates is
legacy semantics; ASL implements the frozen sequential rule).

### turnover

ASL has no proven PIT-safe per-stock turnover field matching the old
contract.  Decision: `turnover_rate = None`.  Optional future enrichment
only.  Turnover is NOT allowed to force reintroduction of the legacy backend.

### universe

Use SH/SZ main-board common A-shares only.  Current operational prefixes:

```
000 / 001 / 002 / 003
600 / 601 / 603 / 605
```

ASL instruments remain the source of truth for exchange, asset type, listing
date and delisting date.

### ST

Historical ST must be PIT-safe.  Current-state stock names are not acceptable
for historical ST classification.

## PHASE 1A — ADAPTER / PIT CONTRACT

Phase-1A commit lineage (approved head `83c54e8`):
`81146dc → 1e278c3 → f572d85 → bfbf2a1 → 58e8eb2 → 37a24d1 → 83c54e8`.

Accepted rules:

* Trusted historical ST: `source = baostock`
* Trusted historical suspension: `source = derived_bar_gap`
* Current-state EastMoney / tdx_protocol status: trusted only for the same
  trading session
* Historical current-state status: ignored as non-PIT (never injected
  backward through time)
* Unknown status sources: ignored / counted
* Missing bar: may only be authorized by a trusted non-trading fact

```
PHASE1A_CODE_ACCEPTANCE = PASS
PHASE1A_DATA_CONTRACT_ACCEPTANCE = PASS
PHASE1A = CLOSED
```

Production cutover was still NO-GO at this stage.

## PHASE 1B — INITIAL SHADOW VALIDATION AND REVIEW

The first Phase 1B PASS was independently rejected.  This history is
preserved on purpose.  Review defects found:

* mutual absence could hide coverage errors
* UNKNOWN_INPUT path was ineffective
* causal attribution was too optimistic
* corporate-action evidence was too coarse
* success/control evaluation used wrong timing in some paths
* episode equivalence did not fully respect lifecycle timing
* trade-status comparison was incomplete
* volume comparison had a loophole
* aggregate process memory accounting was incomplete
* equivalent control could pass vacuously

The harness was corrected before migration acceptance.  This is important
audit history.

## CORRECTED PHASE 1B RESULTS

Corrected full-market evidence (commit lineage around `bb3358a`):

```
UNIVERSE_N = 3191
ASL_COVERED = 3191
SKIPPED = 0
MUTUAL_TERMINAL_ABSENCE = 1
```

* Hard market-input conflicts: **0**
* Trade-status hard conflicts: **0**
* Common-calendar equivalent evaluation points: **224,328**
* Strategy mismatches on equivalent input: **0**
* Unknown input divergence: **0**
* Corporate-action actual-bar comparison errors: **0**
* Resource: peak RSS ≈ **3294 MB** within the 4096 MB limit

Architectural conclusion: when equivalent market inputs are supplied, the
production strategy engine produces equivalent results.  Remaining
strategy-output differences against the legacy backend were primarily caused
by input-history differences, legacy holes, ST coverage, preclose-era
semantics, or compound path-dependent effects.  Legacy output is no longer
treated as the absolute gold standard.

## PRECLOSE CASCADE INVESTIGATION

The 18-row 2026-08-03 preclose issue was caused by **legacy missing
predecessor sessions** — ASL had additional valid predecessor bars.  The
classifier was strengthened so a legacy-hole classification requires actual
predecessor-membership proof (ASL predecessor absent from legacy CONFIRMED +
legacy predecessor a common row + both chains sequential).

Targeted evidence resolved **18 / 18**.  No full-market rerun loop was
allowed afterward except the single authorized run.

This is an example of why ASL should not be modified merely to reproduce a
legacy data hole.

## ST DESIGN EVOLUTION

Documented honestly — rejected intermediate designs are part of history.

### V1

Initial attempt treated historical ST uncertainty as a strategy-comparison
blocker.

### Targeted ST

59 decision-relevant codes were backfilled using the official ASL Baostock
historical ST mechanism.  **9,007** trusted historical ST rows were obtained
(`source=baostock`, `status=st`, `is_trading=True`), with the official safe
pacing (batch 20 / rest 120s) and official write/compact/resume-marker paths.

### Universe simplification

Strategy scope frozen to **SH/SZ MAINBOARD NORMAL A-SHARES ONLY**.
Explicit exclusions: ST, *ST, suspended / no trading bar, delisted / not
listed, ChiNext, STAR, BSE, ETF / fund / bond / CDR.

### Incorrect intermediate design — history deletion

An early eligibility implementation removed historical ST bars before
strategy evaluation.  Rejected: it would corrupt moving averages, volume
averages, preclose continuity, trading-day distances, and support /
resistance history.

Final rule: ST bars remain in true market history.  Eligibility is a MASK on
user-facing evaluation dates.

### Incorrect intermediate design — per-stock non-ST proof

An intermediate version required `is_st=False` for every ordinary stock and
excluded `is_st=None`.  Rejected: ASL historical ST is a positive exclusion
dataset; ordinary non-ST dates generally do not have a per-stock status row.

Final rule: ST is a POSITIVE EXCLUSION SET.

### Incorrect intermediate design — non-empty ST set means READY

A version considered the dataset ready when at least one Baostock ST row
existed.  Rejected: a non-empty blacklist does not prove completeness.

### Final readiness model

Use official ASL completion evidence:
`meta/state/trading_status_st_backfill.json`.  Dataset readiness means the
required eligibility scope is covered by a completed trusted ST operation.
Missing or malformed coverage evidence fails closed.

## FINAL ST REQUIRED SCOPE

Accepted eligibility order:

```
NON_MAINBOARD
→ NOT_LISTED / DELISTED
→ SUSPENDED / NO VALID AS_OF BAR
→ ST
→ ELIGIBLE
```

ST completeness is required only for codes that reach the ST step.

Accepted AS_OF 2026-08-06 metadata:

```
MAINBOARD_INSTRUMENT_N = 3485
NOT_LISTED_OR_DELISTED_N = 292
SUSPENDED_OR_NO_BAR_N = 1
REQUIRED_ST_CODE_N = 3192

COMPLETED_ST_CODE_N_WITHIN_REQUIRED = 671
MISSING_ST_COVERAGE_N = 2521

SCREEN_GATE = ST_DATA_NOT_READY
```

`ST_DATA_NOT_READY` is an operational data-readiness state.  It is NOT a
blocker to accepting ASL as the data foundation.

## 3191 VS 3192 FINAL EXPLANATION

Final metadata reconciliation:

Required ST scope minus frozen universe:

* **001232** — list date 2026-08-04, valid AS_OF bar; newly listed after the
  earlier frozen Phase-2D0 membership snapshot
* **603468** — list date 2026-08-06, IPO-day stock, valid AS_OF bar

Frozen universe minus required scope:

* **000838** — listed, but no AS_OF valid trading bar (suspended), therefore
  excluded before ST coverage is required

Net: `3191 + 2 - 1 = 3192`.

Conclusion: normal market-universe evolution, not data drift.

## FINAL UNIVERSE CONTRACT

```
VFLASH_MAINBOARD_UNIVERSE_V1

INCLUDE:
- SH/SZ
- common stock
- main-board prefixes
- listed on evaluation date
- not delisted
- valid trading bar
- positive volume
- not in trusted ST/*ST exclusion set

EXCLUDE:
- ChiNext
- STAR
- BSE
- ETF
- funds
- bonds
- CDR
- ST / *ST
- suspended
- not listed
- delisted
```

Historical ST bars remain in price history.  Excluded evaluation dates do not
produce user-facing strategy candidates.

## LEGACY BACKEND POLICY

```
LEGACY_DATA_BACKEND = FROZEN_DEPRECATED
```

Deprecated as primary market-data infrastructure: TDX acquisition, Tencent
acquisition, EastMoney / AKShare acquisition, Baostock audit path, Sina
minute audit, provider failover, repair, cross-provider reconciliation.

NOT deleted in this task.  They remain temporarily for audit, rollback
reference and migration provenance.  No new feature should depend on them.
No new provider should be added without explicit architecture approval.

## OPEN ITEMS — NONBLOCKING

### ST coverage

2,521 required AS_OF symbols are not yet present in official ST completion
scope.  Operational consequence: `ST_DATA_NOT_READY`.  This can be completed
later as a dedicated ASL data-readiness job.  It is not a migration
architecture blocker.

### Turnover

Still nullable.  Optional future: `TURNOVER_ENRICHMENT_V01`.  Do not
reintroduce the legacy backend just to fill turnover.

### Limit-up pool enrichment

Optional.  PRICE_ONLY remains valid.

### Counterfactual attribution

Remaining complex legacy-vs-ASL causal-attribution cases are retained only as
historical audit evidence, labeled conceptually:
`LEGACY_COUNTERFACTUAL_ATTRIBUTION_OPEN_ITEM`.  Nonblocking for ASL
foundation acceptance because equivalent-input strategy parity is already
proven.

## NEXT PHASE

### Phase 1C — Production Wiring

Purpose ONLY:

```
ASL
→ ASL Adapter
→ immutable V Flash snapshot
→ state generation
→ strategy
```

Phase 1C must NOT reopen: legacy full-market parity, preclose theory, ST
architecture, episode attribution, provider reconciliation design.

Phase 1C should focus on: production entrypoint wiring, fail-closed
readiness, immutable snapshot provenance, small smoke validation, rollback
safety.

Production cutover remains `NO-GO` until Phase 1C is reviewed and accepted.

## FUTURE RESEARCH DIRECTION

After production wiring, the main research direction becomes
`HISTORICAL_EPISODE_SIMILARITY_V01`:

```
ASL history
→ one-time feature build
→ Episode Warehouse
→ similarity index
```

Similarity features may include: T0 quality, position, pullback days,
pullback drawdown, volume contraction, MA structure, support distance,
B1/B2 state.  Future outcome labels must NOT leak into similarity features.
