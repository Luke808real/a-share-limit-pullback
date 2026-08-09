---
name: ashare-research-cycle
description: "A-share Development Research Cycle: full historical descriptive research lifecycle (hypothesis, descriptive analysis, metric audit, development stability, edge gate, conclusion, report) for frozen episodes, benchmark/stability/multivariate research, and intraday development research. Resolve the exact frozen dataset from the current research registry/report; enforces no same-sample tuning, no forward contamination, and no position sizing before a proven edge."
---

# A-share Development Research Cycle

## Lifecycle

`HYPOTHESIS -> DESCRIPTIVE -> METRIC_AUDIT -> DEVELOPMENT_STABILITY -> EDGE_GATE -> CONCLUSION -> REPORT`

Conclusion status taxonomy:
`OBSERVATION / HYPOTHESIS / SUPPORTED_HYPOTHESIS / VALIDATED / STRATEGY_CANDIDATE / PROMOTED`
with orthogonal `IMPLEMENTATION_STATUS` and `PRODUCTION_STATUS`.
**SUPPORTED != VALIDATED != PROMOTED**; production promotion requires PR + human approval.

## Workflow

1. **HYPOTHESIS**: state the question and cohort definition using pre-existing fields only.
2. **DESCRIPTIVE**: analyze frozen corrected episodes + execution-reality parquet
   (`data/outcome-study/.../corrected-b2-trigger-outcome/`); `evaluate_strategy_calls = 0`.
3. **METRIC_AUDIT**: reconcile every number against the frozen canonical model
   (cohort, execution rules, same-day ordering, cost, exit rule) and report ONE aligned number.
   Label any proxy explicitly (e.g., fixed-principal sequential proxy is not a portfolio backtest).
4. **DEVELOPMENT_STABILITY**: a historical time split is NOT clean OOS when
   the dataset already influenced discovery. Report year / period breakdowns
   as `DEVELOPMENT_STABILITY` only. If a specific frozen experiment defines
   its own split (e.g., discovery/validation cutoffs), read it from that
   experiment's registry/report — never from a global hardcode.
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
- Frozen dataset: resolve the exact corrected-episodes / outcome / feature
  artifact (with its SHA) from the current research registry/report; do not
  hardcode a single hash as the eternal default.

## Bans

- Same-sample threshold tuning; new threshold scanning.
- Forward sample influencing historical parameter selection.
- Position sizing before proven entry edge.
- Modifying frozen artifacts or production strategy.
