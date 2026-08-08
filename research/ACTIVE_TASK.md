# ACTIVE_TASK — Research Handoff

## RUN_ID: ANALOG_V03_OOS_CALIBRATION

- **Task**: verify Historical Analog Engine (v0.2 RAW vs BLOCK_BALANCED) on
  historical pseudo-current queries; strict PIT (analogs only from earlier
  dates); probability calibration (5d S1_FIRST / INVALID_FIRST), corridor
  coverage, rank correlation, Brier; fixed A/B/C/D ablation across many
  queries by DISCOVERY / VALIDATION / 2024 / 2025 / 2026; duplicate-anchor /
  leave-same-stock-out audit.
- **Constraints**: no production / strategy.yaml / frozen artifacts / G /
  position-sizing changes; 600756 / 603980 not used for tuning.
- **Comparators**: RAW_V02 (v0.2 distance) vs BLOCK_BALANCED (four blocks
  internally normalized, then equal weight). No weight/threshold tuning.
- **Status**: COMPLETED
- **Owner**: Main Agent (single writer)
- **Outputs**: `research/runs/ANALOG_V03_OOS_CALIBRATION/{REPORT.md, metrics.json}`
- **Result**: ANALOG_DESCRIPTIVE_ONLY — no OOS predictive/calibration value
  (MFE rho ≈ 0, Brier ≈ naive, corridor coverage ≈ chance); descriptive
  similarity only; no promotion.

## V03A_STRICT_PIT（PR #21 更新）

- PIT fix: per-query z-standardization only over analog universe with date < T.
- Sampling fix: deterministic evenly-spaced per year/stage (max 500/year,
  full-year coverage).
- Result: **ANALOG_DESCRIPTIVE_ONLY_CONFIRMED**（原结论不变；V03 的弱 S1-rank
  信号在严格 PIT 下收缩，Brier 略改善，MFE rho 仍 ≈0）。
- BASE_DRIFT detected: origin/main 34a4a13 -> d3ed5cb (PR #20 merge);
  synced via ordinary merge (no rebase/force).

## V03B_SAMPLING_FIX（PR #21 更新）

- Fixed V03A sampling bug (in-year positions misused as absolute recs
  indices); V03B maps positions back via `year_indices[selected_position]`.
- SAMPLING_AUDIT all asserts passed (selected<=500, duplicates=0,
  wrong_year=0, first/last covered when available>500).
- Result: **ANALOG_DESCRIPTIVE_ONLY_CONFIRMED**（采样修复不改结论；
  MFE rho ≈0、走廊≈随机、Brier ≤ naive、S1 rank 仍弱）。
