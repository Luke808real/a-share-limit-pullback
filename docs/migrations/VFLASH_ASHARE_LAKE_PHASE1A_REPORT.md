# VFLASH × ASHARE-LAKE — PHASE 1A EVIDENCE REPORT (FINAL)

> Status: **field parity PASS with explicit deltas (evidence, not approval)**.
> This report records the completed Phase 1A work and the review-round-1,
> round-2, final-PIT (round-3) and finalization fixes that followed
> independent code review of commit `81146dc`.

> **PHASE1A = PASS** — this approves the ASL ADAPTER BOUNDARY only.
> It does NOT approve production cutover; it does NOT approve provider
> deletion; it does NOT resolve turnover; it does NOT resolve limit-up-pool
> enrichment; it does NOT constitute full historical episode parity.
> Phase 1B (shadow/pilot validation) is the next stage.
> It is NOT an approval to begin Phase 1B. **Phase 1B has NOT been approved.**

## 1. Source identity

| item | value |
|---|---|
| source HEAD | `0f08348fd1fa7e04bdf468acc5516d6001e169b9` |
| source branch | `feature/phase-2c2c-trade-plan` (agent-context development branch) |
| migration branch | `migration/asl-phase1a-adapter` (worktree `/Users/luke808/AI/V flash-asl-phase1a`) |
| review base branch | `review-base/daily-20260806` (remote, points exactly at `0f08348`) |
| ASL revision | `ba5681a` (ASL v0.5.0) — pinned as **tested_compat_revision** (declarative provenance; the runtime contract is validated from the lake) |
| original Phase-1A commit | `81146dc49a14b83496a1f27f7248105cc90e6afd` (reviewed) |
| repair commit | "Fix ASL Phase 1A review blockers" (this round) |

## 2. Architecture boundary

```
rootSunc/ashare-lake (tested_compat_revision ba5681a)
        ↓
ASL local Parquet lake (curated only)
        ↓
V Flash ASL Adapter  ← read-only; NOT wired into production
        ↓
V Flash frozen daily-bar facts (sequential preclose, pct_change, status)
        ↓
existing snapshot / state generation / strategy engine  (untouched)
```

ASL provides facts; V Flash computes strategy-specific market structure.

## 3. Frozen preclose contract

ADR-008 production rule (evidence: `warehouse/continuity.py`,
`build_sequential_preclose`, `load_seed_previous_closes` in
`warehouse/staging.py`, `preclose_continuity_issues` in
`warehouse/validate.py`, `test_adr008_*` suite):

> `preclose(code, session_t) == close(code, previous valid session for code)`

- sequential per-code chain; seed = last CONFIRMED close of the base snapshot;
- **no** provider exchange preclose, **no** corporate-action adjustment;
- chain holds across suspension gaps (advances only on `close > 0`);
- first row without predecessor → `MISSING_PREDECESSOR`, never published;
- continuity invariant: |preclose − prior close| ≤ max(0.01, 0.001×scale);
- rounding: prices 0.0001 ROUND_HALF_UP; pct_change (close−preclose)/preclose×100
  quantized 0.0001 ROUND_HALF_UP.

**Review-round-2 semantics (no day-count cutoff):** the predecessor is the
LAST VALID CLOSE PER CODE before the window (possibly thousands of sessions
earlier: suspension, halt, holiday).  The adapter enumerates ASL daily-bar
day partitions strictly before `start`, traverses newest → oldest, keeps a
set of unresolved requested codes, records the first valid positive close
per code as its predecessor, stops once all codes are resolved, and stops per
code at its instrument listing boundary.  Codes with no predecessor anywhere
in the available ASL history are classified MISSING_PRECLOSE, never guessed.
Regression: a predecessor ~517 calendar days before the window is found
(`test_predecessor_far_beyond_400_days_still_found`).

## 4. ASL input contract (Phase 1A)

| dataset | columns used | units | partition granularity |
|---|---|---|---|
| `daily_bars` | symbol, trade_date, open, high, low, close, volume, amount, source, data_version, fetched_at | OHLC raw yuan; volume **shares** (`data_version=="v2"` required); amount yuan | day |
| `instruments` | symbol, list_date, delist_date | — | single file |
| `trading_calendar` | trade_date, is_trading | — | year |
| `trading_status` | symbol, trade_date, is_trading, status | — | month |

All four datasets are REQUIRED: missing dataset/column → `AslAdapterError`
(no empty valid slice). Reads are partition-pruned to the requested
start/as_of plus the bounded predecessor window; out-of-range partitions are
never opened (proven by test with corrupt out-of-range files).

## 5. Implementation scope

- `src/limit_pullback/warehouse/asl_adapter.py` — read-only adapter:
  `load_asl_daily_slice`; required-dataset contract validation; duplicate-PK
  guards (`daily_bars`, `trading_status`, `trading_calendar`, `instruments`);
  missing-bar gate (absent bar allowed ONLY when explicitly proven
  suspended/not-listed/delisted, otherwise raises); review-round-1 status
  semantics; **round-2 backward predecessor search (no day-count cutoff)**;
  **centralized status-vocabulary validation applied BEFORE missing-bar
  interpretation**; Decimal quantization with parsable-value fail-closed;
  frozen pct_change; `turnover_rate` field present and always None;
  timezone-aware parsed `asl_fetched_at`; `AslAdapterError`
  (adapter-specific, narrow); **round-3 PIT status-provenance contract**
  (trusted sources baostock / derived_bar_gap / same-day EastMoney;
  NON_PIT_EASTMONEY and UNKNOWN_STATUS rows ignored and counted; strict
  Boolean contract; UNTRUSTED_STATUS_PROVENANCE fail-closed;
  partition-scoped predecessor duplicate validation).
- `tests/test_asl_adapter.py` — 33 offline unit tests.
- `research/asl_phase1a/parity.py` — read-only parity GATE
  (PASS / BLOCKED_PARITY / BLOCKED_DATA; exit 0 only for PASS) with
  round-2 strict status taxonomy, trade-status gate and observed maxima.
- `research/asl_phase1a/parity_summary.json` — compact deterministic summary
  (committed; no absolute machine paths) with observed maxima and
  status/trade-status counts (self-sufficient).
- `research/asl_phase1a/artifacts/.gitignore` — full row-level report lives
  under the gitignored artifacts dir.
- `tests/test_parity_harness.py` — MA-window classifier tests incl. the
  hole-aging regression (MA5 → MA10 → MA20), the 9-combination status
  taxonomy tests, and the trade-status/known-is_st hard-failure tests.
- `docs/migrations/VFLASH_ASHARE_LAKE_PHASE1A_REPORT.md` — this file.

The old ~23k-line `parity_report.json` was removed from the branch and
replaced by the compact summary; the full report is generated locally under
the gitignored artifacts path.

## 6. Production integration

**NONE.** No production module imports the adapter; no config file changed;
no CLI wiring; no snapshots, generations, or promotions; no provider deletion.

## 6a. PIT_STATUS_CONTRACT (round 3)

ASL upstream documents that EastMoney daily status is the CURRENT ST list,
historical ST comes from the Baostock ST-history backfill, and historical
suspension comes from `derived_bar_gap`.  The adapter therefore reads
`trading_status` WITH provenance (`source`, `data_version`, `fetched_at`)
and classifies every row before use:

| source | accepted semantics | trust |
|---|---|---|
| `baostock` | `status ∈ {st, *st}` AND `is_trading == True` | BAOSTOCK_ST (trusted historical ST); any other combination raises |
| `derived_bar_gap` | `status == "suspended"` AND `is_trading == False` | DERIVED_GAP_SUSPENDED (trusted historical suspension); any other combination raises |
| `eastmoney` / daily-status label `tdx_protocol` | fetched_at converted to Asia/Shanghai; trusted ONLY if `trade_date == fetched Shanghai date` (same-session observation) | EASTMONEY_SAME_DAY; otherwise NON_PIT_EASTMONEY (ignored, counted) |
| any other source | — | UNKNOWN_STATUS (ignored, counted) |

Consequences:

* Historical EastMoney current-state rows never set is_st / trade_status /
  suspension and are never called normal; a missing daily bar may be
  authorized ONLY by a trusted non-trading row (derived_bar_gap suspended or
  same-day observation) — otherwise MISSING_REQUIRED_BAR blocks.
* `trading_status.fetched_at` must exist, parse, and be timezone-aware
  (UNTRUSTED_STATUS_PROVENANCE otherwise).
* `is_trading` accepts actual Booleans only ("False" string fails closed).
* Sparse authoritative status is the intended historical model: positive
  bar + no trusted historical status → trade_status=True, is_st=None
  (unknown stays unknown; frozen strategy contract preserved).

**Untouched pilot build (official commands only, no hand edits):**

```
asl demo --symbols 000001.SZ,600519.SH,601318.SH,000010.SZ,000524.SZ,000593.SZ,002963.SZ,605179.SH,605198.SH,000037.SZ,300750.SZ --days 50 --trade-date 2026-08-06 --data-root /tmp/asl_phase1a_lake_r3 --config-out /tmp/asl_phase1a_lake_r3/demo.toml
asl compact --config /tmp/asl_phase1a_lake_r3/demo.toml --run-id <demo trading_calendar run>
asl backfill trading_status --config /tmp/asl_phase1a_lake_r3/demo.toml --start 2026-05-20 --end 2026-08-06
asl derive trading_status --config /tmp/asl_phase1a_lake_r3/demo.toml --start 2026-05-20 --end 2026-08-06
asl backfill corporate_actions --config /tmp/asl_phase1a_lake_r3/demo.toml --start 2026-05-01 --end 2026-08-06   (CA-intersection evidence)
```

**MANUAL_PILOT_DATA_EDITS = 0.**  Lake state: 501 baostock ST rows + 10
derived_bar_gap suspended rows; zero EastMoney rows; zero duplicate PKs.

## 7. Parity sample

Real ASL rows (TDX-sourced; official `asl demo`, 2026-05-28 → 2026-08-06,
50 sessions × 11 symbols; official `asl backfill trading_status` +
`asl derive trading_status`) vs legacy canonical
`snap-2026-08-06-e798f88ff67b.parquet` (CONFIRMED rows only).

| code | special case |
|---|---|
| 000001 | normal chain; corporate action 6/12 ex-div (legacy hole); high liquidity |
| 600519 / 601318 | normal chain, large caps |
| 000010 | ST (37 sessions adapter is_st=True from real ASL ST rows) |
| 000524 | suspension gap 6/24–7/7 (10 sessions, bar-gap derived) |
| 000037 | limit-up day 8/3 → anchor + B1_READY smoke |
| 605198 | limit-up day 7/31 → anchor + WATCH_PULLBACK smoke |
| 000593 / 002963 / 605179 | limit-up runs 8/3–8/6 (no frozen-qualifying anchor, agreement) |
| 300750 | outside frozen universe → excluded, not emitted |

## 8. Results — four distinct categories

### 8.1 FIELD PARITY (compared rows with data on both sides: 354)

| metric | result |
|---|---|
| OHLC | max abs diff 0.0000 (exact) |
| volume | max rel diff 3.9e-05 (0.0039% ≪ 0.5%) |
| amount | max rel diff 5.7e-08 (≪ 0.5%) |
| preclose | **354/354 exact** |
| pct_change (frozen rule) | max abs diff 0.0 |
| structure (limit-close / one-word / T-word) | 0 mismatches |
| MA5/10/20 on CLEAN windows | 0 mismatches (CLEAN counts below) |
| observed maxima | PRICE abs 0.0000 / rel 0; VOLUME rel 3.9e-05; AMOUNT rel 5.7e-08; PCT abs 0.0 |
| hard failure count | **0** |

### 8.2 DATA COMPLETENESS DELTA (non-fatal, explicitly classified)

- BOTH sessions 354, LEGACY_ONLY 10, ASL_ONLY 126.
- 126 legacy holes: the legacy canonical is missing CONFIRMED sessions
  (2026-07-09…07-24 run plus scattered single days: 000001 06-12,
  000524 06-18, 601318 06-10, 600519 06-26, 605179 06-08, 605198 07-09);
  ASL has complete bars on all of them.
- MA window classification by exact last-N bar-date sequences:
  MA5 CLEAN 251 / HOLE_AFFECTED 63; MA10 CLEAN 131 / HOLE_AFFECTED 135;
  MA20 CLEAN 38 / HOLE_AFFECTED 131. CLEAN_MISMATCH = 0 everywhere.
  Hole-affected windows are legacy-completeness artifacts, not adapter
  failures; an old hole ages out of MA5, then MA10, then MA20 (regression
  test `test_old_hole_ages_out_of_ma5_then_ma10_then_ma20`).
- Adapter fail-closed rows: 10 × MISSING_PRECLOSE (window edge 2026-05-28,
  the ASL pilot lake starts at the window edge).
- Missing-required-bar evidence: 10 sessions (000524 suspension), all
  explicitly proven non-trading.

### 8.3 STATUS SEMANTIC DELTA (non-fatal, never hidden)

| category | count |
|---|---|
| EXACT_STATUS_MATCH | 69 |
| LEGACY_NON_PIT_TO_ASL_TRUSTED_ST | 4 |
| LEGACY_NON_PIT_TO_ASL_TRUSTED_NORMAL | 0 |
| LEGACY_NON_PIT_TO_ASL_UNKNOWN | 281 |
| ASL_TRUSTED_STATUS_INTERNAL_CONFLICT | 0 |

**LEGACY_ST_REFERENCE_CLASS = NON_PIT_CODE_LEVEL_STOCK_BASIC_SNAPSHOT.**
The frozen legacy bootstrap derives ``is_st`` from the CURRENT stock_basic
``name`` via ``_st_from_name`` (warehouse/units.py) and ``_fill_auxiliary``
(warehouse/pipeline.py) applies ONE ``code -> is_st`` mapping to all
historical daily rows.  It is NOT an authoritative per-session historical ST
reference, so it is excluded from hard field parity.

Finalization taxonomy: legacy/ASL matches are informational; legacy
non-PIT snapshot → ASL trusted historical ST is a DATA QUALITY UPGRADE
(non-fatal); legacy non-PIT True/False → ASL None is an EXPECTED PIT
SEMANTIC DELTA (non-fatal); only contradictions within trusted ASL facts
(ASL_TRUSTED_STATUS_INTERNAL_CONFLICT) are hard failures.  The 281
`LEGACY_NON_PIT_TO_ASL_UNKNOWN` rows are legacy name-based `is_st=False`
vs ASL `is_st=None` (no authoritative historical ST row) — documented,
non-fatal.  ST_SEMANTIC_DELTA_FATAL_N = 0.

TRADE_STATUS: exact 354, conflict 0 — trade_status mismatch remains a HARD
parity failure.  Invariant holds: STATUS_CATEGORY_TOTAL (354) ==
COMPARED_ROW_N (354).

### 8.4 PIT status provenance (round 3)

| metric | value |
|---|---|
| PIT_STATUS_PROVENANCE_GATE | **PASS** |
| TRUSTED_STATUS_BAOSTOCK_N | 50 |
| TRUSTED_STATUS_DERIVED_GAP_N | 10 |
| TRUSTED_STATUS_EASTMONEY_SAME_DAY_N | 0 |
| NON_PIT_EASTMONEY_STATUS_IGNORED_N | 0 |
| UNKNOWN_STATUS_N | 0 |

No manually curated ASL rows; no trusted historical current-state EastMoney
ST rows; no missing-bar session accepted from an untrusted status row.

### 8.5 Final Phase-1A gates (same untouched round-3 lake)

| gate | value |
|---|---|
| FIELD_PARITY_GATE | **PASS** |
| PIT_STATUS_PROVENANCE_GATE | **PASS** |
| TRADE_STATUS_PARITY_GATE | **PASS** |
| ST_LEGACY_REFERENCE | NON_PIT_CODE_LEVEL_STOCK_BASIC_SNAPSHOT |
| ST_SEMANTIC_DELTA_GATE | **PASS_WITH_DOCUMENTED_DELTAS** |
| STRATEGY_SMOKE_GATE | **PASS** |
| PHASE1A_GATE | **PASS** |
| CORPORATE_ACTION_INTERSECTION | REAL_EX_DATE_INTERSECTION_PARITY_NOT_PROVEN (Phase-1B evidence item) |

Non-blocking data deltas (data correction ≠ parity failure): legacy holes
repaired by ASL (126 sessions); legacy non-PIT ST snapshot → ASL trusted
historical ST (4); legacy non-PIT ST snapshot → ASL unknown (281).

### 8.4 STRATEGY SMOKE PARITY (latest common date only)

- anchor smoke: matched 10/10 (000037 → 8/3 @ 10.08; 605198 → 7/31 @ 56.96;
  others none==none).
- stage smoke: matched 10/10 (`B1_READY`, `WATCH_PULLBACK`, `NORMAL`).
- **SMOKE CHECK ONLY**: timeline-level episode parity is Phase-1B work and
  was NOT performed.

## 9. Corporate-action intersection

ASL `corporate_actions` lists 6 ex-dates inside the window (000001 06-12,
000524 06-18, 600519 06-26, 601318 06-10, 605179 06-08, 605198 07-09 — all
cash dividends), but **every one falls inside a legacy hole**, so no real
ex-date row exists in the legacy/adapter intersection.

Result: **REAL_EX_DATE_INTERSECTION_PARITY_NOT_PROVEN** — reported honestly;
no fabricated case. The synthetic ex-div test
(`test_corporate_action_preclose_not_adjusted`) remains, and the adapter
reproduces the frozen rule (preclose = previous close, unadjusted) across
the legacy hole (000001 preclose 06-15 = 11.24 exact on both sides).

## 10. Turnover

**NULL_BY_DESIGN.** ASL has no PIT-safe per-stock turnover field. The adapter
emits `turnover_rate: Decimal | None`, always None, with no estimate. Parity
found 0 legacy rows with non-null turnover_rate in the window →
`TURNOVER_PARITY=NOT_COMPARABLE` (n=0). Turnover replacement remains an open
architecture decision.

## 11. Open blockers

1. Turnover: unresolved (separate architecture decision; research-only).
2. Limit-up pool enrichment (seal times, open counts, consecutive counts,
   industry): ASL has no equivalent; V Flash pool adapter stays.
3. Pre-2016 ST labels: ASL ST history starts ~2016 (baostock); pre-2016 is an
   explicitly documented ST-unfiltered zone on both sides.
4. Real ex-date intersection parity not proven (see §9).
5. ASL full history requires `asl init` / `asl backfill` (Phase-2 activity,
   deliberately not run). Demo-lake quirks recorded: demo does not compact
   `trading_calendar` into curated (fixed via `asl compact --run-id`);
   suspension derivation needs the compacted calendar.

## 12. Review-gate tests run (round 1)

```
tests/test_asl_adapter.py        → 43 passed
tests/test_parity_harness.py     → 28 passed
test_adr008_data_correctness + test_warehouse_validate +
test_corporate_action_preclose + test_asl_adapter + test_parity_harness
                                 → 100 passed (combined run, final)
python3 -m compileall -q src/limit_pullback/warehouse/asl_adapter.py → OK
git diff --check                 → clean
parity gate (real ASL, UNTOUCHED lake vs frozen canonical) →
  PHASE1A_GATE = PASS (exit 0), hard_failure_count 0,
  ST_SEMANTIC_DELTA_GATE = PASS_WITH_DOCUMENTED_DELTAS (281 UNKNOWN + 4
  TRUSTED_ST upgrades), PIT_STATUS_PROVENANCE_GATE PASS,
  TRADE_STATUS 354/0, invariant 354==354
```

No full-market verification; no state generations; no network inside tests.

## 13. Hashes of generated parity artifacts

```
SHA256(snap-2026-08-06-e798f88ff67b.parquet)
  7cc614bf4e1e7f91f34ed1a866827b3b70772a32ff5ff04a5ad67e205e23813e
```

Hashes of the committed artifacts are recorded in the commit/PR body after
finalization (self-hash excluded).

## 14. Caveats that must survive review

1. **Hole-affected MA windows differ** (by design, per-window classification;
   legacy-completeness artifact, CLEAN windows all match).
2. **Legacy `is_st=None` vs ASL known-ST is a semantic delta**, reported as
   LEGACY_UNKNOWN_TO_ASL_TRUE/FALSE — never exact parity.
3. **Direct real ex-date intersection parity NOT proven** (all window
   ex-dates fall in legacy holes).
4. **Turnover remains unresolved** (NULL_BY_DESIGN).
5. **Limit-up pool remains unresolved**.
6. **Stage comparison is a smoke check only**, not episode parity.

## 15. Repair-round provenance

This revision of the report and the accompanying code changes were produced
in response to independent code review of commit `81146dc` (round 1), its
rereview (round 2) and the final PIT status review (round 3).  Blocker
resolution is recorded in the PR body (`CHATGPT_REVIEW_ROUND_3 =
FIXED_PENDING_FINAL_APPROVAL`).

Round-2 fixes: (A) 400-day predecessor cutoff removed — partition-pruned
backward search, newest → oldest, per-code listing boundary, no day-count
cutoff; (B) status vocabulary validated before missing-bar interpretation;
(C) strict status taxonomy (None==None → EXACT, known→None → CONFLICT) with
the per-row invariant; (D) trade_status mismatch and TRUE_STATUS_CONFLICT are
hard parity failures; (E) summary carries observed maxima and
status/trade-status counts; (F) runtime-contract wording corrected to
exactly what is implemented (datasets, columns, parsable values,
`data_version==v2`, unit semantics — no claim of Arrow type validation).

Round-3 fixes (final PIT): (1) PIT status-source contract frozen — baostock
historical ST, derived_bar_gap suspension, same-day EastMoney only;
NON_PIT_EASTMONEY / UNKNOWN_STATUS ignored and counted; (2) sparse
authoritative status is the intended model — no dense historical EastMoney
required; (3) provenance counts exposed on the slice and in the parity
summary; (4) final parity evidence runs against a NEW untouched pilot lake
built from official ASL commands only (MANUAL_PILOT_DATA_EDITS = 0);
(5) predecessor duplicate-PK validation is partition-scoped; (6) strict
Boolean contract for is_trading; (7) trading_status fetched_at must be
valid, parsed and timezone-aware (UNTRUSTED_STATUS_PROVENANCE).

Finalization fixes: (1) legacy ST reference class frozen as
NON_PIT_CODE_LEVEL_STOCK_BASIC_SNAPSHOT (cited to units.py `_st_from_name`
and pipeline.py `_fill_auxiliary`); (2) legacy `is_st` removed from hard
field parity — new taxonomy EXACT / LEGACY_NON_PIT_TO_ASL_TRUSTED_ST /
LEGACY_NON_PIT_TO_ASL_TRUSTED_NORMAL / LEGACY_NON_PIT_TO_ASL_UNKNOWN /
ASL_TRUSTED_STATUS_INTERNAL_CONFLICT (only the last is fatal); (3)
trade_status remains a hard gate; (4) PIT status provenance remains a hard
gate; (5) explicit gate block in the summary (FIELD / PIT / TRADE_STATUS /
ST_LEGACY_REFERENCE / ST_SEMANTIC_DELTA / STRATEGY_SMOKE / PHASE1A /
CORPORATE_ACTION_INTERSECTION); (6) parity re-run on the SAME untouched
round-3 lake with no data edits → PHASE1A_GATE = PASS.

Gate-wiring fixes (final): ONE authoritative ``phase1a_gate``
(``compute_phase1a_gate``) drives the process exit code, the full report,
the compact summary and ``gates.PHASE1A_GATE``; PIT_STATUS_PROVENANCE_GATE
!= PASS yields BLOCKED_DATA (non-zero exit); field/trade-status/ASL-internal/
smoke failures yield BLOCKED_PARITY; component-gate regression tests A–D
prove the final decision (incl. the PIT-block and exit-code mapping).

## 16. Phase 1B status

**NOT APPROVED.** Phase 1B must not begin until this repaired bundle has been
independently re-reviewed and a decision is returned.
