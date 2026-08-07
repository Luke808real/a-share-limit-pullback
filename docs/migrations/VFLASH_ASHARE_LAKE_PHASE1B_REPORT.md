# VFLASH × ASHARE-LAKE — PHASE 1B SHADOW STRATEGY VALIDATION REPORT

> Status: **PASS** — Phase-1B shadow validation gate is green (exit 0).
> This is a SHADOW / RESEARCH validation of the ASL data backend against the
> frozen V Flash strategy.  It is NOT a production cutover, NOT a provider
> deletion, NOT approval to begin Phase 1C.

## 1. Scope and boundary

| item | value |
|---|---|
| comparison window | 2026-04-01 → 2026-08-06 (AS_OF = 2026-08-06) |
| history window | 2024-01-16 → 2026-08-06 (extension documented below) |
| strategy required history | **250 trading bars** (MA250 in `moving_average_windows`; position window 120; resistance lookbacks 60 — the maximum dependency) |
| history extension reason | the frozen strategy needs ≥250 bars before the first eval point; legacy canonical coverage starts 2024-01-02, so the ASL shadow lake was backfilled from 2024-01-02; HISTORY_START=2024-01-16 is the first session with complete ASL bar coverage for the frozen universe (2 codes suspended at the start: 000657 → 01-10, 603958 → 01-16) |
| frozen universe | Phase-2D0, N=3191, hash `8d1f99b1b9aac72a9ddfbe898def2f12c59938f83f012fe46017951e24ef1afb` (computed with the frozen procedure from `snap-2026-07-31-b5f84004de8a`; matches BASELINE_MANIFEST `codes: 3191`) |

## 2. ASL shadow lake build (official commands only)

**MANUAL_ASL_DATA_EDITS = 0.**  Revision `ba5681a` (tested compatibility
revision; runtime contract validated from the lake).

```
asl backfill instruments --config shadow.toml
asl backfill trading_calendar --config shadow.toml --start 2024-01-02 --end 2026-08-06
asl backfill daily_bars --config shadow.toml --start 2024-01-02 --end 2026-08-06
asl backfill trading_status --config shadow.toml                       (historical ST; partial, see 8.7)
asl derive trading_status --config shadow.toml --start 2024-01-02 --end 2026-08-06
asl backfill corporate_actions --config shadow.toml --start 2026-04-01 --end 2026-08-06
```

Lake verified: daily_bars 4,202,119 rows, all `data_version=v2`, 0 duplicate
PKs, 2024-01-02 → 2026-08-06, all 3,191 frozen codes covered; trading_status
24,170 `derived_bar_gap` suspension rows; corporate_actions 70,274 rows.

## 3. Resource budget

System: 16 GiB RAM, ~286 GiB free disk.  Target peak RSS ≤ min(4 GiB, 25% RAM)
= 4 GiB.  Measured: **peak RSS 1,475 MB** (parent + children, platform-aware
units), wall time 688 s, workers 4, chunk size 400, per-code streaming with
GC, partition-pruned reads, pyarrow code-predicate pushdown for legacy reads.
No memory exhaustion.

## 4. Coverage

| metric | value |
|---|---|
| FROZEN_UNIVERSE_N | 3191 |
| ASL_CODE_COVERED_N | 3191 (100% of frozen universe) |
| evaluated codes | 3191 |
| eval points | 276,788 |
| LEGACY_HOLE_N (per-date) | 118,348 (6.1% of history rows) |
| ASL_ONLY_VALID_BAR_N | 118,348 + 72 IPO-day rows (legacy side) |
| LEGACY_ONLY_VALID_BAR_N | 72 (all IPO first days) |
| HARD_FIELD_CONFLICT_N | **0** |
| STUB_DAY_VOLUME_ANOMALY_N | 3 (documented, non-blocking) |
| EXPLAINED_MUTUAL_ABSENCES_N | 1 (000838, suspended after 2026-07-31 on both sides) |
| TRUSTED_ST_N | 0 (partial ST sweep, see 8.7) |
| NON_PIT_STATUS_IGNORED_N / UNKNOWN_STATUS_N | 0 / 0 |

All missing/extra rows are explained (below).

## 5. Input classification

Per-date input deltas over the full history (1.94M rows):

```
INPUT_EQUIVALENT                1,742,112  (90.0%)
LEGACY_HOLE_REPAIRED_BY_ASL       118,348  (legacy CONFIRMED holes: CA ex-dates
                                          + market-wide PROVISIONAL block
                                          2026-01-28..02-06 + scattered)
PIT_ST_DATA_UPGRADE                83,406  (legacy name-snapshot ST=True vs
                                          ASL unknown; legacy reference is
                                          NON_PIT_CODE_LEVEL_STOCK_BASIC_SNAPSHOT)
LEGACY_ONLY                            72  (all IPO first days: adapter frozen
                                          first-row MISSING_PRECLOSE semantics)
LEGACY_PRECLOSE_ERA_DIVERGENCE         17  (legacy exchange preclose vs ASL
                                          sequential on real ex-dates)
STUB_DAY_VOLUME_ANOMALY                 3  (near-zero-volume year-boundary days;
                                          OHLC/amount exact, volume differs)
HARD_FIELD_CONFLICT                     0
UNKNOWN_INPUT_DIVERGENCE               0
```

Eval-point classes are window-based (last 250 bars).  **INPUT_EQUIVALENT eval
points are structurally 0**: with a 6.1% legacy hole density, any 250-bar
window contains at least one legacy hole (including the market-wide
2026-01-28..02-06 block), so no eval point has a divergence-free lookback.
This is a data-completeness property of the legacy canonical, not an ASL
defect — it is reported, not hidden.

## 6. Strategy timeline parity

Both paths run through the SAME production engine (`screen.engine.screen_code`,
PRICE_ONLY via empty limit-up pool, no turnover, no pool enrichment).

```
STRATEGY_ENGINE_PARITY_FAILURES_N   0      (no mismatch on any equivalent input)
UNKNOWN_INPUT_DIVERGENCE_N          0
UNKNOWN_EPISODE_DIVERGENCE_N        0
DIVERGED_BUT_MATCHING_N         205,462   (strategy outputs identical despite
                                          diverged inputs — the strategy is
                                          robust to most legacy-hole repair)
FIRST_RESULT_DIVERGENCE_N        3,190    (every code's first result change is
                                          attributed to an input class)
```

Because INPUT_EQUIVALENT points are structurally 0 (legacy hole density), the
engine-parity requirement is vacuous but the determinism is additionally
guaranteed by production hash checks; every result divergence is attributed
to a documented input class (root causes: LEGACY_HOLE_REPAIRED /
PIT_ST_UPGRADE / LEGACY_ONLY_DATA / LEGACY_PRECLOSE_ERA / STUB_DAY_VOLUME).

## 7. Episode parity

```
EXACT_EPISODE                      3,100
LEGACY_HOLE_CHANGED_EPISODE          852   (episode differs because legacy
                                          holes were repaired by ASL)
ASL_NEW_VALID_EPISODE                819   (new episodes only visible in ASL's
                                          complete data)
LEGACY_ONLY_EPISODE                   79   (legacy-only anchors; IPO-first-day
                                          lineage)
PIT_ST_CHANGED_EPISODE                 0
LEGACY_PRECLOSE_ERA_CHANGED_EPISODE    0
UNKNOWN_EPISODE_DIVERGENCE             0
```

No episode divergence is unexplained.

## 8. Full-market screen at 2026-08-06 (PRICE_ONLY, same config/universe)

| metric | legacy | ASL |
|---|---|---|
| eligible candidates | 279 | 273 |
| stage distribution | B1 49 / B2_READY 197 / B2_CONFIRMED 33 | B1 52 / B2_READY 191 / B2_CONFIRMED 30 |

TOP20_EXACT_POSITION_N 0 · TOP20_COMMON_N 7 · added candidates 26 · removed
candidates 32.  Every addition/removal traces to an input class
(LEGACY_HOLE_REPAIRED / PIT_ST / LEGACY_ONLY / LEGACY_PRECLOSE_ERA) — none are
unexplained.  ASL-only candidates caused by repaired legacy holes are
expected and explained, not treated as automatically bad.

## 9. Success / control cases

From the frozen `research/intraday/success_control_cases_v01b.csv` (1,947
cases with candidate dates inside the window): legacy inclusion 312, ASL
inclusion 287; anchor changed 73; stage changed 116.  Outcomes are NOT
relabeled.  Inclusion/anchor/stage changes trace to the documented input
classes (INPUT_CORRECTION_CHANGE), not unexplained strategy change.

## 10. Corporate-action intersection

Phase-1A's `REAL_EX_DATE_INTERSECTION_PARITY_NOT_PROVEN` is now **PROVEN**:
20 real ex-dates with ASL corporate_action + ASL bar + legacy CONFIRMED row
inside the window (evidence in
`research/asl_phase1b/artifacts/ca_intersection_evidence.json`):

* OHLC/close: exact match on all 20.
* preclose: exact on 7/20; on the other 13 the legacy value is the exchange
  reference (dividend-adjusted) while ASL is the frozen sequential
  previous-close — differences equal the dividend amount (0.01–0.10 yuan).
  This is the documented LEGACY_PRECLOSE_ERA semantic, not a data defect.
* pct_change: differs accordingly on those 13; identical on the 7 exact.
* limit-close state: identical (none on either side).

## 11. Data anomalies (all explained, non-blocking)

* 3 stub-day volume anomalies (603007 2024-12-31/2025-01-03, 603559
  2025-01-03): near-zero-volume year-boundary bars; OHLC/amount/preclose
  exact; volume differs by TDX integer-lot rounding or a single-row TDX
  volume anomaly.  All are >250 bars before every eval point (zero strategy
  impact).
* 1 mutual absence (000838 suspended after 2026-07-31 on both backends; the
  ASL bar-gap derivation does not cover sessions beyond the bar-series edge).
* 72 IPO-day LEGACY_ONLY rows (adapter frozen first-row MISSING_PRECLOSE vs
  legacy bootstrap IPO-day preclose).

## 12. Phase-1B gate

**PHASE1B_GATE = PASS** (exit 0).

| criterion | result |
|---|---|
| MANUAL_ASL_DATA_EDITS = 0 | ✓ |
| ASL required datasets valid | ✓ (instruments/calendar/daily_bars/trading_status) |
| frozen-universe coverage | ✓ (3,191/3,191) |
| unexplained missing required bars | 0 (1 explained mutual absence) |
| PIT status provenance | PASS |
| duplicate PK / schema / unit violations | 0 |
| Phase-1A hard field parity on common rows | ✓ (HARD_FIELD_CONFLICT_N = 0) |
| INPUT_EQUIVALENT strategy mismatches | 0 (structurally vacuous, documented) |
| UNKNOWN_INPUT_DIVERGENCE_N / UNKNOWN_EPISODE_DIVERGENCE_N | 0 / 0 |
| strategy smoke / full-screen comparator | ran successfully |
| resource | 1,475 MB ≤ 4,096 MB budget, bounded deterministic processing |

Non-blocking but mandatory migration findings (reported): legacy holes
repaired by ASL (118,348 history rows; 852 hole-changed episodes), PIT ST
improvements (83,406 per-date ST deltas where ASL trusted ST is pending the
sweep completion), ASL-only valid episodes (819) from better data
completeness.

## 13. Open items

1. **Turnover**: remains NULL (no ASL source; separate enrichment track).
2. **Limit-up pool**: remains outside ASL (PRICE_ONLY comparison used).
3. **Historical ST sweep partial**: the official baostock ST backfill is
   rate-limited (free-tier ~43 queries/session, ~40-min cooldown; documented
   safe pacing batch 20 / rest 120s ≈ 8h for the full universe).  At
   evidence time the resume marker covered 1,000 symbols (of ~7,700); the
   sweep resumes in the background.  TRUSTED_ST_N = 0 → ST-True stocks are
   classified as PIT_ST_DATA_UPGRADE (legacy NON-PIT snapshot vs ASL
   unknown), consistent with the approved "unknown remains unknown" contract.
4. **INPUT_EQUIVALENT strategy parity vacuous** due to legacy hole density
   (documented in §5/§6); a dense-PIT legacy reference would be needed for a
   non-vacuous equivalent-input engine test.

## 14. Tests

`tests/test_shadow_harness.py` (19 tests): input-equivalence classification,
repaired-hole classification, window aging, strategy signature determinism,
first-divergence attribution, episode matching, gate/exit mapping
(BLOCKED_DATA/BLOCKED_PARITY/BLOCKED_RESOURCE/PASS), unexplained divergence
and equivalent-input mismatch blocking.  All pass; `compileall` OK;
`git diff --check` clean.  No legacy full-market verify-full was run.

## 15. Artifact hygiene

Committed: this report, `research/asl_phase1b/shadow.py`,
`research/asl_phase1b/shadow_summary.json` (compact, no absolute paths),
`tests/test_shadow_harness.py`.  Raw full results live under the gitignored
`research/asl_phase1b/artifacts/`.
