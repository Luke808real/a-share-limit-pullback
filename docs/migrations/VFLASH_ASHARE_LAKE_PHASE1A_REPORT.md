# VFLASH × ASHARE-LAKE — PHASE 1A EVIDENCE REPORT

> Status: **PASS (evidence, not approval)**. This report records the already
> completed Phase 1A work for independent review. It is NOT an approval to
> begin Phase 1B. Phase 1B has **NOT** been approved.

## 1. Source identity

| item | value |
|---|---|
| source HEAD | `0f08348fd1fa7e04bdf468acc5516d6001e169b9` (`DAILY_20260806: ADR-008 catch-up, generic promotion sessions, state generation`) |
| source branch | `feature/phase-2c2c-trade-plan` (agent-context development branch; source HEAD descends from its tip `b49c912`) |
| migration branch | `migration/asl-phase1a-adapter` (isolated worktree `/Users/luke808/AI/V flash-asl-phase1a`) |
| ASL revision pinned | `ba5681a` (ASL v0.5.0) — inspected at that commit; demo lake produced by that exact checkout |

## 2. Architecture boundary

```
rootSunc/ashare-lake (ba5681a)
        ↓
ASL local Parquet lake (curated only)
        ↓
V Flash ASL Adapter  ← read-only, Phase-1A scope, NOT wired into production
        ↓
V Flash frozen daily-bar facts (sequential preclose, pct_change, status)
        ↓
existing snapshot / state generation / strategy engine  (untouched)
```

ASL provides facts; V Flash computes strategy-specific market structure.
Strategy semantics are not moved into ASL and not changed.

## 3. Frozen preclose contract

ADR-008 production rule (evidence: `warehouse/continuity.py` module docstring,
`build_sequential_preclose`, `load_seed_previous_closes` in
`warehouse/staging.py`, `preclose_continuity_issues` in
`warehouse/validate.py`, `test_adr008_*` suite):

> `preclose(code, session_t) == close(code, previous valid session for code)`

- sequential per-code chain; seed = last CONFIRMED close of the base snapshot;
- **no** provider exchange preclose, **no** corporate-action adjustment
  (`corporate_action_status="UNKNOWN"`, `price_domain="RAW_UNADJUSTED"`);
- chain holds across suspension gaps (advances only on rows with `close > 0`);
- first row without predecessor → `MISSING_PREDECESSOR`, never published;
- continuity invariant: |preclose − prior close| ≤ max(0.01, 0.001×scale);
- rounding: prices 0.0001 ROUND_HALF_UP; pct_change
  (close−preclose)/preclose×100 quantized 0.0001 ROUND_HALF_UP.

Contract is unambiguous → reproduced by the adapter verbatim
(`build_sequential_preclose` semantics, seed-from-prior-session).

## 4. ASL input contract (Phase 1A)

| dataset | columns used | units | notes |
|---|---|---|---|
| `daily_bars` | symbol, trade_date, open, high, low, close, volume, amount, source, data_version, fetched_at | OHLC raw yuan; volume **shares** (require `data_version=="v2"`); amount yuan | read with `pyarrow.ParquetFile` (no Hive partition discovery) |
| `instruments` | symbol | — | symbol `{code}.{SH\|SZ\|BJ}` → 6-digit code |
| `trading_calendar` | trade_date, is_trading | — | session ordering |
| `trading_status` | symbol, trade_date, is_trading, status | — | normal/suspended/st/*st |

`corporate_actions` / `adj_factors` are NOT consumed: the frozen preclose
contract does not require them (consumed only as external evidence for the
corporate-action finding below).

## 5. Implementation scope

- `src/limit_pullback/warehouse/asl_adapter.py` (new): `load_asl_daily_slice`
  → `AslDailySlice` / `AslDailyBarRow`; frozen-universe prefix filter
  (000/001/002/003/600/601/603/605); Decimal quantization; sequential
  preclose with seed; pct_change via frozen rule; status mapping; row_status
  classification (`VALID_ROW` / `MISSING_REQUIRED_AMOUNT` / `MISSING_STATUS` /
  `MISSING_PRECLOSE` / `UNSUPPORTED_SEMANTICS`); no turnover field at all.
- `tests/test_asl_adapter.py` (new): 16 offline unit tests.
- `research/asl_phase1a/parity.py` + `parity_report.json` (new): read-only
  parity harness and its output.
- `docs/migrations/VFLASH_ASHARE_LAKE_PHASE1A_REPORT.md` (this file).

Adapter may not write canonical data, promote snapshots, mutate ASL, call
network providers, repair ASL, silently fill rows, estimate turnover, or
compute strategy state.

## 6. Production integration

**NONE.** No production module imports the adapter; no config file changed;
no CLI wiring; no snapshots, generations, or promotions created. The adapter
is unreachable from production code in Phase 1A.

## 7. Parity sample

Real ASL rows (TDX-sourced; official `asl demo`, window 2026-05-28 →
2026-08-06, 50 sessions × 11 symbols; `asl backfill trading_status` ST rows;
`asl derive trading_status` suspension rows) vs legacy canonical
`snap-2026-08-06-e798f88ff67b.parquet` (CONFIRMED rows only).

| code | special case |
|---|---|
| 000001 | normal chain; corporate action 6/12 ex-div; legacy hole 6/12; high liquidity |
| 600519 / 601318 | normal chain, large caps |
| 000010 | ST (37 sessions mapped is_st=True from real ASL ST rows) |
| 000524 | suspension gap 6/24–7/7; legacy hole 6/18 |
| 000037 | limit-up day 8/3 → anchor + B1_READY stage |
| 605198 | limit-up day 7/31 → anchor + WATCH_PULLBACK stage (sentinel code) |
| 000593 / 002963 / 605179 | limit-up runs 8/3–8/6 (no frozen-qualifying anchor, agreement) |
| 300750 | outside frozen universe → excluded, not emitted |

## 8. Exact parity results

| metric | result |
|---|---|
| compared rows | 354 |
| OHLC | max abs diff **0.0000** (all exact to the cent) |
| volume | max rel diff 3.9e-05 (0.0039% ≪ 0.5% tolerance); unit shares confirmed |
| amount | max rel diff 5.7e-08 (≪ 0.5%); unit yuan confirmed |
| preclose | **354/354 exact** (abs diff 0.0000) |
| pct_change | recomputed with frozen rule both sides; max abs diff 0.0 |
| MA5/10/20 | 749 comparisons, **0 failures** at ≤0.001 rel on non-hole windows |
| limit-close / one-word / T-word | **0 mismatches** |
| anchor | 000037 → 8/3 @ 10.08 both sides; 605198 → 7/31 @ 56.96 both sides; others none==none |
| setup stage | 000037 `B1_READY==B1_READY`; 605198 `WATCH_PULLBACK==WATCH_PULLBACK`; others `NORMAL==NORMAL`; **0 mismatches** |
| status mapping | 0 issues (is_st/trade_status; legacy-None treated as compatible, see caveat 2) |

## 9. Legacy holes finding

The frozen canonical is missing 12–13 CONFIRMED sessions per sampled code
(2026-07-09…07-24 PROVISIONAL-era run, plus scattered single days such as
000001 06-12, 000524 06-18, 601318 06-10, 600519 06-26). ASL has complete
bars on all of them, and the adapter preclose chain reproduces the legacy
exchange-based preclose values across those holes **exactly** (e.g. 000001
preclose 06-15 = 11.24 on both sides). This is a completeness advantage of
ASL, not a parity defect — but see caveat 1.

## 10. ST semantics finding

ASL `trading_status` in the pilot lake contains sparse ST rows (baostock
backfill, 366 rows) and derived suspension rows; the dense daily path was not
run. Adapter mapping: st/*st → `is_st=True`; suspended → `trade_status=False`;
missing status row for a session → ASL missing-row-normal convention, made
explicit via `AslStatusCoverage.mode` (never silent). Fail-closed when the
dataset is absent entirely. Legacy canonical carries `is_st=None` on ADR-008
rows; see caveat 2.

## 11. Corporate-action finding

000001.SZ ex-date **2026-06-12**, cash dividend 0.36/share (confirmed from
ASL `corporate_actions` via official `asl backfill corporate_actions`, TDX
xdxr). The legacy canonical has no 6/12 session (hole); ASL has the full bar.
The adapter applies the frozen rule (preclose = previous close, unadjusted)
and reproduces legacy preclose 06-15 = 11.24 exactly via its chain. Caveat 3:
this is not a *same-row* ex-date intersection comparison — no ex-date falls
inside the legacy/ASL row intersection of this sample.

## 12. Turnover

**NULL_BY_DESIGN.** ASL has no PIT-safe per-stock turnover field. The adapter
emits no turnover at all. Parity found 0 legacy rows with non-null
turnover_rate in the window → `TURNOVER_PARITY=NOT_COMPARABLE` (n=0). No
estimate; turnover replacement remains an open architecture decision.

## 13. Open blockers

1. Turnover: unresolved (separate architecture decision; research-only).
2. Limit-up pool enrichment (seal times, open counts, consecutive counts,
   industry): ASL has no equivalent; V Flash pool adapter stays.
3. Pre-2016 ST labels: ASL ST history starts ~2016 (baostock); pre-2016 is an
   explicitly documented ST-unfiltered zone on both sides.
4. ASL full history requires `asl init` / `asl backfill` (Phase-2 activity,
   deliberately not run). Demo-lake quirks recorded: demo does not compact
   `trading_calendar` into curated (fixed via `asl compact --run-id`);
   suspension derivation needs the compacted calendar.

## 14. Review-gate tests run

```
PYTHONPATH=src python -m pytest tests/test_asl_adapter.py                      → 16 passed
PYTHONPATH=src python -m pytest tests/test_adr008_data_correctness.py \
                          tests/test_warehouse_validate.py \
                          tests/test_corporate_action_preclose.py \
                          tests/test_asl_adapter.py                            → 45 passed
python3 -m compileall -q src/limit_pullback/warehouse/asl_adapter.py           → OK
git diff --check                                                               → clean
python research/asl_phase1a/parity.py …                                        → report regenerated
```

No full-market verification; no state generations; no network inside tests.

## 15. Hashes of generated parity artifacts

```
SHA256(src/limit_pullback/warehouse/asl_adapter.py)
  71cdd1c08cf37a9ba440909b0aef6a86e80919c0eff90e9026631c0f3284529c
SHA256(tests/test_asl_adapter.py)
  d54dae93b60828c67469cf4716ebfe0af79ccd4628f9a2707e7140cf6604e50e
SHA256(research/asl_phase1a/parity.py)
  b966824b7ac03698cf51f947a598db4468e01c09af86e99ece357ba244b95c9d
SHA256(research/asl_phase1a/parity_report.json)
  a8c2af04ea896cdf56351ea07fe21d42a48be8f46f6c03244fe340c07e15a5bf
SHA256(docs/migrations/VFLASH_ASHARE_LAKE_PHASE1A_REPORT.md)
  recorded in the PR body (computed after this file was finalized)
```

## 16. Caveats that must survive review

1. **Hole-affected MA windows differ.** Where the legacy canonical misses
   sessions inside an MA window, MA5/10/20 differ (max ~3.8% on MA20) because
   the legacy chain skips those sessions; the adapter chain is complete. These
   are classified as hole-affected, not failures, and are a legacy
   data-completeness artifact.
2. **Legacy `is_st=None` vs ASL known-ST is NOT exact parity.** On ADR-008-era
   rows the legacy canonical stores `is_st=None`; the adapter derives
   `is_st` from ASL status rows. The parity treats legacy-None as compatible;
   a stock the ASL status data marks ST while legacy has `is_st=None` must
   not be reported as an exact ST match.
3. **Direct real ex-date intersection parity may still be incomplete.** The
   sample's ex-date (000001 06-12) falls in a legacy hole; a same-row
   ex-date comparison on both sides has not yet been exercised with real data
   (covered synthetically by `test_corporate_action_preclose_not_adjusted`).
4. **Turnover remains unresolved** (NULL_BY_DESIGN; no ASL source).
5. **Limit-up pool remains unresolved** (seal times / open counts / industry
   have no ASL replacement).

## 17. Phase 1B status

**NOT APPROVED.** Phase 1B (extended pilot parity, validators-on-adapter,
episode-level screen parity, dense trading_status, turnover decision) must
not begin until this evidence bundle has been independently reviewed and a
decision is returned.
