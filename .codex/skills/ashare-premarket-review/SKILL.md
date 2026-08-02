---
name: ashare-premarket-review
description: "A-share premarket candidate review and opening decision card. Use when the user asks to review specific stocks before the next trading session, produce a watchlist/observation card, check TRADE_READINESS, compare with the frozen forward watch, or ask what to watch / not chase on the next trading day. Read-only: never modify strategy, config, or frozen forward artifacts; never use data after the plan date."
---

# A-share Premarket Review

## Inputs

- codes, plan_date, snapshot id, strategy baseline commit.
  Resolve the frozen snapshot dynamically from repo / KB / user input;
  never hardcode a snapshot id.

## Workflow

1. **Environment + date guard**: report branch / HEAD / strategy commit / config hash /
   snapshot id. Use only `trade_date <= plan_date`; next session is human-declared;
   never read or construct later bars.
2. **Production screen**: run the existing screen for the explicit codes only:
   `--codes ... --rebuild --start 2024-01-01 --snapshot-id <snapshot>` via
   `limit_pullback.cli.main`. Extract the latest row per code.
3. **Frozen watch compare (read-only)**: `data/forward-paper/<plan>-final-human-watch/decision_sheet.json`;
   report in/out of frozen universe and the reason (REJECT / not covered / past B / too far /
   different structure).
4. **Card per code**: stage, close, B1 support area, B2 trigger, invalid, S1,
   distance to trigger, distance to invalid, entry_quality, R/R,
   TRADE_READINESS (`READY | WAIT | EXTENDED | DATA_LIMITED | NO_NEW_ENTRY`).
5. **OPENING PLAN A–D**: A open in support zone, B open between support and trigger,
   C gap above trigger (chase or not), D break invalid (abandon).
6. **Ranking**: use the human-fixed priority, then independently challenge it if data supports.
   Output `TODAY_PRIMARY_WATCH` (max 3), `NO_CHASE` list, and one wait-signal sentence per code.

## Guardrails

- `DATA_LIMITED` when CONFIRMED daily bars have a gap (e.g., a PROVISIONAL-only
  window between two CONFIRMED sessions).
- `NO_NEW_ENTRY` for post-trigger / low R-R setups (e.g., B2_CONFIRMED with R/R < 1).
- No new price thresholds: reuse strategy levels, MAs, and platforms.
- Production classification unchanged; human overlay must be labeled
  `RESEARCH_OVERLAY_ONLY` and must not alter production labels.

## References

- `docs/agent-context.md`, `docs/project-operating-model.md`
- `research/execution_risk_v01.md` (historical edge context)
