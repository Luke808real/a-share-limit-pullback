---
name: ashare-research-cycle
description: "Full research lifecycle for A-share strategy questions: hypothesis, descriptive analysis, metric audit, chronological validation, edge gate, conclusion, and report. Use for robustness/edge/execution/position-sizing studies on frozen episodes (corrected episodes hash 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093), outcome/execution-reality artifacts, or any 'does this signal have edge' question. Enforces no same-sample tuning, no forward contamination, and no position sizing before a proven edge."
---

# A-share Research Cycle

## Lifecycle

`HYPOTHESIS -> DESCRIPTIVE -> METRIC_AUDIT -> CHRONOLOGICAL_VALIDATION -> EDGE_GATE -> CONCLUSION -> REPORT`

Conclusion status: `REJECT / OBSERVE_ONLY / SUPPORTED`.
**SUPPORTED != PROMOTED**; production promotion requires PR + human approval.

## Workflow

1. **HYPOTHESIS**: state the question and cohort definition using pre-existing fields only.
2. **DESCRIPTIVE**: analyze frozen corrected episodes + execution-reality parquet
   (`data/outcome-study/.../corrected-b2-trigger-outcome/`); `evaluate_strategy_calls = 0`.
3. **METRIC_AUDIT**: reconcile every number against the frozen canonical model
   (cohort, execution rules, same-day ordering, cost, exit rule) and report ONE aligned number.
   Label any proxy explicitly (e.g., fixed-principal sequential proxy is not a portfolio backtest).
4. **CHRONOLOGICAL_VALIDATION**: DISCOVERY <= 2025-06-30 vs VALIDATION >= 2025-07-01;
   also report 2024 / 2025 / 2026.
5. **EDGE_GATE**: only pre-existing production thresholds plus already-studied
   `entry_quality >= 80` / `setup_quality >= 80`. `EDGE_SUPPORTED` requires:
   discovery mean > 0, validation mean > 0, median not dependent on a single year,
   n >= 30 per period. Otherwise `OBSERVE_ONLY` / `REJECT`.
6. **Position sizing** only after `EDGE_SUPPORTED`. If no subgroup passes, output
   `NO_PROVEN_ENTRY_EDGE` and stop sizing promotion.
7. **REPORT**: write `research/*.md` + metrics.json; record input provenance/hash,
   script path, output path, and conclusion status.

## Reuse

- `research/execution_risk_v01.py`, `research/execution_risk_v01.md`
- `data/tmp/execution-risk-v01/metrics.json`
- Corrected episodes: SHA `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093`

## Bans

- Same-sample threshold tuning; new threshold scanning.
- Forward sample influencing historical parameter selection.
- Position sizing before proven entry edge.
- Modifying frozen artifacts or production strategy.
