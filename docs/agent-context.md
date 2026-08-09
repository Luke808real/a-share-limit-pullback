# Agent Context

Authoritative current project state lives in:

```text
../a-share-strategy-brain/PROJECT_STATE_SNAPSHOT.md
(or the configured A_SHARE_STRATEGY_BRAIN_ROOT)
```

Do not use this file as historical authority.

## Current stable boundaries

```text
Production Plane:
ASL -> Snapshot -> State -> Strategy

Research Plane:
R0-R8 development evidence
-> pre-R9 hardening
-> R9 prospective validation
```

Production / Forward / TradePlan must remain exactly as explicitly authorized
by current state (PROJECT_STATE_SNAPSHOT). No old snapshot / PR is hardcoded
here; see the Authority Matrix in the root AGENTS.md.
