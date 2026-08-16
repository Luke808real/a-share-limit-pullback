# July ASL Clean Repair V02 — Auditable Evidence Report

## Execution Identity

| Field | Value |
|---|---|
| execution_code_head | `bea3317f5193a2b993332ec5322b953616b8bf0c` |
| base_snapshot_id | `snap-2026-07-31-b5f84004de8a` |
| parent_run_id | `359774eea1675b329e747cbb` |
| repair_run_id | `59aad30e65ae8c8d43928bcd` |
| repair_lineage | `july-2026-gap-asl-v02` |
| provider_name | `ASL` |
| new_snapshot_id | `snap-2026-07-31-d34171a7e7ae` |
| snapshot_as_of | `2026-07-31` |
| snapshot_status | `RESEARCH_READY` |

## Gate Results (all PASS)

| Gate | Result |
|---|---|
| per_date_gate (12/12 dates) | PASS |
| canonical_provider_gate (selected_provider ASL_N=38269, TUSHARE_N=0, OTHER_N=0) | PASS |
| source_provider_gate (foreign=0, TUSHARE source/progress/failure=0) | PASS |
| snapshot_invariants (dup=0, non-repair diff=0, pool identical, July 23/23 sessions, gap=0) | PASS |
| adj_coverage_gate (predecessor 2026-07-08, 13/13 dates 100% consensus coverage) | PASS |
| old_lineage_immutable (base / parent / old run / old snapshot fingerprints unchanged) | PASS |

## Per-Date Summary

| Date | ASL_N | AK_N | BS_N | CONSENSUS_N | COVERAGE | CONFIRMED_N |
|---|---|---|---|---|---|---|
| 2026-07-09 | 3186 | 3186 | 3186 | 3186 | 3186 | 3186 |
| 2026-07-10 | 3186 | 3186 | 3186 | 3186 | 3186 | 3186 |
| 2026-07-13 | 3187 | 3187 | 3187 | 3187 | 3187 | 3187 |
| 2026-07-14 | 3189 | 3189 | 3189 | 3189 | 3189 | 3189 |
| 2026-07-15 | 3190 | 3190 | 3190 | 3190 | 3190 | 3190 |
| 2026-07-16 | 3190 | 3190 | 3190 | 3190 | 3190 | 3190 |
| 2026-07-17 | 3189 | 3189 | 3189 | 3189 | 3189 | 3189 |
| 2026-07-20 | 3191 | 3191 | 3191 | 3191 | 3191 | 3191 |
| 2026-07-21 | 3191 | 3191 | 3191 | 3191 | 3191 | 3191 |
| 2026-07-22 | 3190 | 3190 | 3190 | 3190 | 3190 | 3190 |
| 2026-07-23 | 3190 | 3190 | 3190 | 3190 | 3190 | 3190 |
| 2026-07-24 | 3190 | 3190 | 3190 | 3190 | 3190 | 3190 |

Totals: repaired_row_n=38269, confirmed_n=38269, provisional_n=0, quarantine_n=0.

## Artifact SHA256

| Artifact | SHA256 |
|---|---|
| receipt.json | `6d82cda2439a31ce21731d1c68c2cb273642cdfe5a5446ceeaaaa912ead0c87e` |
| validation.json | `a4c68d7edcfd092bbba6d1e53d5c896940c43a01524df5512d338fd5e5087df9` |
| report.md | `2c275505fe739f7827d7b6f4b4239c92cb3ab0687050787cc8c801aeae72f9f3` |

## Forbidden Checks

- NO TUSHARE network (data source: read-only ASL lake)
- NO AKSHARE / BAOSTOCK refetch (exact parent raw reuse, SHA-verified)
- NO full-history bootstrap, NO other repair dates
- NO snapshot promotion, NO T0 rebuild, NO transition rerun, NO metadata schema change
- Old experimental objects untouched: `72e05fe83ffb6f2317a76824`, `snap-2026-07-31-8016cdf17bc7`
