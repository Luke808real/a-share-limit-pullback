# ANALOG_V03_OOS_CALIBRATION — REPORT

RUN_ID: ANALOG_V03_OOS_CALIBRATION

Method: pseudo-current queries from the frozen episode library; analogs are
restricted to strictly earlier dates (PIT). Comparators: RAW_V02 vs
BLOCK_BALANCED (four blocks internally z-normalized then equal weight).
Queries: B2_READY 1,500 / LAUNCH_READY 1,411 / PREPOSITION 1,500 (4,411 total,
sampled 500/year/stage). No weight/threshold tuning; no production changes.

## Headline (5d)

| stage | variant | Brier S1 | Brier INV | \|AE mfe5\| | cov mfe p25-75 | cov mae p10-90 | rho mfe5 | rho s1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| B2_READY | RAW | 0.210 | 0.247 | 0.054 | 48.3% | 76.3% | 0.031 | 0.291 |
| B2_READY | BAL | 0.207 | 0.243 | 0.054 | 48.7% | 75.5% | 0.048 | 0.292 |
| LAUNCH_READY | RAW | 0.209 | 0.138 | 0.059 | 47.4% | 75.3% | -0.009 | 0.280 |
| LAUNCH_READY | BAL | 0.208 | 0.137 | 0.059 | 47.1% | 74.5% | -0.014 | 0.272 |
| PREPOSITION | RAW | 0.161 | 0.226 | 0.052 | 46.7% | 71.0% | 0.098 | 0.201 |
| PREPOSITION | BAL | 0.160 | 0.224 | 0.052 | 46.4% | 70.7% | 0.092 | 0.189 |

## Interpretation

- Analog median MFE has **no OOS rank correlation** with realized MFE
  (rho ≈ -0.01 to +0.10; near zero everywhere).
- Brier S1 ≈ naive base-rate benchmark (B2 ~0.21 vs 0.21; PREP 0.160 vs 0.148;
  LAUNCH 0.209 vs 0.214) -> no meaningful probability calibration.
- Corridor coverage ≈ chance (MFE p25-75 ~47-49% vs expected 50%; MAE p10-90
  71-76% vs expected 80%).
- BAL vs RAW: negligible differences (block balancing does not add value).
- S1-rate rank correlation is weak-moderate (0.19-0.29), the only signal that
  survives OOS, but it does not translate into calibrated probabilities.

## Feature ablation (fixed A/B/C/D, over many queries, not single-stock)

| set | B2 neighbor S1 rate | B2 realized S1 | B2 \|AE mfe5\| | PREP neighbor S1 | PREP realized |
|---|---:|---:|---:|---:|---:|
| A shape only | 0.262 | 0.298 | 0.0541 | 0.180 | 0.180 |
| B +price_state | 0.257 | 0.298 | 0.0534 | 0.173 | 0.180 |
| C +volume | 0.261 | 0.298 | 0.0539 | 0.177 | 0.180 |
| D full | 0.264 | 0.298 | 0.0539 | 0.178 | 0.180 |

Technical/volume blocks add essentially nothing over price-shape only
(D vs A differences < 0.02 in rates; error ~identical).

## Concentration / PIT audit

- unique stocks mean 135-137; unique anchors 62-79; same-stock share ~0.05%;
  leave-same-stock-out (v0.2) forward stats unchanged -> no concentration bias.
- Queries only use analog dates strictly earlier than query date.

## Conclusion

**ANALOG_DESCRIPTIVE_ONLY** — no OOS predictive/calibration value (MFE rho ~0,
Brier ~ naive, corridor coverage ~ chance); the engine remains a descriptive
similarity/case-retrieval tool only. No promotion; no production change.

## V03A_STRICT_PIT (PIT correction)

Fixes: (1) per-query z-standardization now uses ONLY the analog universe with
date < T (no future records in mean/std); (2) query sampling is deterministic
evenly-spaced per year/stage (max 500/year, full-year coverage).

Headline (5d):

| stage | variant | n | Brier S1 (V03 -> V03A) | rho mfe5 (V03 -> V03A) | rho s1 (V03 -> V03A) | cov mfe p25-75 (V03A) |
|---|---|---:|---:|---:|---:|---:|
| B2_READY | RAW | 1204 | 0.210 -> 0.189 | 0.031 -> 0.072 | 0.291 -> 0.181 | 46.5% |
| B2_READY | BAL | 1204 | 0.207 -> 0.187 | 0.048 -> 0.057 | 0.292 -> 0.207 | 47.3% |
| LAUNCH_READY | RAW | 575 | 0.209 -> 0.205 | -0.009 -> -0.003 | 0.280 -> 0.132 | 45.9% |
| PREPOSITION | RAW | 1310 | 0.161 -> 0.130 | 0.098 -> 0.065 | 0.201 -> 0.057 | 47.0% |

After the PIT fix:

- The modest S1-rate rank signal from V03 (0.19-0.29) largely shrinks
  (0.06-0.21); part of V03's signal was PIT leakage.
- Brier S1 improves slightly in all stages (PREP 0.130 is now better than the
  naive base-rate 0.148; B2/LAUNCH ~0.19-0.20 vs naive 0.21-0.21).
- MFE rank correlation remains ~0; corridor coverage remains ~chance.
- Ablation A-D: technical/volume still add ~nothing (D vs A differences
  < 0.01 in neighbor rates).

**V03A conclusion: ANALOG_DESCRIPTIVE_ONLY_CONFIRMED** — the original
conclusion is unchanged after strict PIT.

## V03B_SAMPLING_FIX

Bug fixed: V03A `per_year` stored absolute recs indices but `sample_year()`
returned in-year positions, and those positions were misused as absolute
indices. V03B maps year positions back to `year_indices[selected_position]`.

SAMPLING_AUDIT (all asserts passed):

| stage/year | available | selected | min_T | max_T |
|---|---:|---:|---|---|
| B2 2024/2025/2026 | 2083/2570/1490 | 500/500/500 | 2024-03-05/2025-01-02/2026-01-05 | 2024-12-31/2025-12-31/2026-07-30 |
| LAUNCH 2024/2025/2026 | 509/610/411 | 500/500/411 | full-year coverage | full-year coverage |
| PREP 2024/2025/2026 | 3518/4041/2678 | 500/500/500 | full-year coverage | full-year coverage |

duplicate_query_count = 0, wrong_year_count = 0, selected_n <= 500, and first/
last date covered whenever available > 500 (hard asserts).

Three-way comparison (RAW 5d):

| stage | Brier S1 V03 -> V03A -> V03B | rho mfe5 V03 -> V03A -> V03B | rho s1 V03 -> V03A -> V03B |
|---|---:|---:|---:|
| B2_READY | 0.210 -> 0.189 -> 0.195 | 0.031 -> 0.072 -> 0.048 | 0.291 -> 0.181 -> 0.217 |
| LAUNCH_READY | 0.209 -> 0.205 -> 0.207 | -0.009 -> -0.003 -> -0.010 | 0.280 -> 0.132 -> 0.194 |
| PREPOSITION | 0.161 -> 0.130 -> 0.137 | 0.098 -> 0.065 -> 0.124 | 0.201 -> 0.057 -> 0.086 |

After the sampling fix: MFE rank correlation remains ~0 (0.05-0.12);
corridor coverage remains ~chance (46-49%); Brier stays at/below naive
(PREP 0.137 < naive 0.148); S1 rank signal remains weak (0.09-0.24).
Ablation A-D unchanged (technical/volume add ~nothing).

**V03B conclusion: ANALOG_DESCRIPTIVE_ONLY_CONFIRMED** — sampling fix does not
change the conclusion.

## Limitations

- Query sampling 500/year/stage (not full library) to bound runtime.
- Analog library = frozen episode signals (not every session); forward bars
  capped at 10 sessions.
- NEW_20D_HIGH_PROXY is a proxy, not real SECOND_LAUNCH.
- Relative strength / sector unavailable.
