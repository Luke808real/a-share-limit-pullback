# VFLASH × ASHARE-LAKE — PHASE 1A EVIDENCE REPORT (REVIEW ROUND 1)

> Status: **field parity PASS with explicit deltas (evidence, not approval)**.
> This report records the completed Phase 1A work and the review-round-1
> fixes that followed independent code review of commit `81146dc`.
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

**Review-round-1 clarification:** the predecessor is the LAST VALID CLOSE PER
CODE before the window (possibly several sessions earlier: suspension, halt,
holiday); the adapter searches a bounded 400-calendar-day predecessor window
with partition pruning and classifies MISSING_PRECLOSE (never guesses) when
no predecessor exists.

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
  semantics; bounded predecessor seeding; Decimal quantization; frozen
  pct_change; `turnover_rate` field present and always None; timezone-aware
  parsed `asl_fetched_at`; `AslAdapterError` (adapter-specific, narrow).
- `tests/test_asl_adapter.py` — 31 offline unit tests.
- `research/asl_phase1a/parity.py` — read-only parity GATE
  (PASS / BLOCKED_PARITY / BLOCKED_DATA; exit 0 only for PASS).
- `research/asl_phase1a/parity_summary.json` — compact deterministic summary
  (committed; no absolute machine paths).
- `research/asl_phase1a/artifacts/.gitignore` — full row-level report lives
  under the gitignored artifacts dir.
- `tests/test_parity_harness.py` — MA-window classifier tests incl. the
  hole-aging regression (MA5 → MA10 → MA20).
- `docs/migrations/VFLASH_ASHARE_LAKE_PHASE1A_REPORT.md` — this file.

The old ~23k-line `parity_report.json` was removed from the branch and
replaced by the compact summary; the full report is generated locally under
the gitignored artifacts path.

## 6. Production integration

**NONE.** No production module imports the adapter; no config file changed;
no CLI wiring; no snapshots, generations, or promotions; no provider deletion.

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
| EXACT_STATUS_MATCH | 33 |
| LEGACY_UNKNOWN_TO_ASL_TRUE | 4 |
| LEGACY_UNKNOWN_TO_ASL_FALSE | 281 |
| TRUE_STATUS_CONFLICT | 0 |

Legacy ADR-008-era rows carry `is_st=None`; the adapter derives ST from ASL
status rows. Unknown→known is a documented semantic upgrade, NOT exact
parity. Missing status row + positive bar → trade_status=True, is_st=None
(the adapter never claims normal from absence).

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
tests/test_asl_adapter.py        → 31 passed
tests/test_parity_harness.py     → 5 passed
test_adr008_data_correctness + test_warehouse_validate +
test_corporate_action_preclose + test_asl_adapter + test_parity_harness
                                 → 65 passed (combined run)
python3 -m compileall -q src/limit_pullback/warehouse/asl_adapter.py → OK
git diff --check                 → clean
parity gate (real ASL vs frozen canonical) → PASS, exit 0
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
in response to independent code review of commit `81146dc` (round 1).
Blocker-by-blocker resolution is recorded in the PR body
(`CHATGPT_REVIEW_ROUND_1 = FIXED_PENDING_REREVIEW`).

## 16. Phase 1B status

**NOT APPROVED.** Phase 1B must not begin until this repaired bundle has been
independently re-reviewed and a decision is returned.
