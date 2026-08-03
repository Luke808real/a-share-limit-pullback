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
