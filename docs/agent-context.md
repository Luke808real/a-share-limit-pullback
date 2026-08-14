# Agent Context Pointer

Do not maintain a second phase snapshot in this file. Start with
[CURRENT_STATE.md](CURRENT_STATE.md), the single repository-local current-state
and authority entry point.

Then read only the smallest relevant authoritative set:

1. `config/strategy.yaml` and the frozen strategy tag/tree;
2. `a-share-strategy-brain/01_Strategy/STRATEGY_MASTER.md`;
3. `a-share-strategy-brain/01_Strategy/RULE_CATALOG.md`;
4. `a-share-strategy-brain/01_Strategy/BASELINE_MANIFEST.yaml`;
5. `a-share-strategy-brain/05_Codex/CURRENT_PHASE.md`;
6. the directly relevant source, tests, data manifest, and gate report.

Stable boundaries:

- `B1_PREP` is an execution label, not a `setup_stage`.
- Execution labels and TradePlan thresholds cannot rewrite frozen B1/B2,
  S1/S2, Entry Room, score, invalidation, or PIT semantics.
- `OBSERVED`, `PROPOSED`, and descriptive research are not frozen rules.
- Missing or contradictory data/provenance fails closed.
- A next gate, review branch, passing test, or frozen protocol does not start
  Forward, TradePlan, PRIMARY_OOS, production, or a provider cutover.
- Re-check live Git refs and the worktree; do not trust a dated handoff or a
  copied branch/SHA as current authority.
