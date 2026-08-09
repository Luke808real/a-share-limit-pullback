---
name: ashare-prospective-validation
description: "R9-style prospective validation and true out-of-sample accumulation: protocol freeze before OOS_START, outcome-blind candidate generation, immutable feature rows, later independent endpoints, fixed readiness rule. Use for forward observational research or any claim that a result is VALIDATED out-of-sample. Guards against fake OOS, refit, checkpoint switching, threshold scanning, and historical backfill into clean OOS."
---

# A-share Prospective Validation

Purpose: true prospective / out-of-sample accumulation (R9-style). NOT for
historical descriptive research (use `ashare-research-cycle`).

## Lifecycle

`PRE_AUDIT -> PROTOCOL_FREEZE -> OOS_START -> APPEND_ONLY_COLLECTION -> LABEL_MATURITY -> READINESS -> EVALUATION -> VALIDATION_RECOMMENDATION`

## Hard gate

```text
If PRE_R9_STATUS != GO:
    STOP
```

`PRE_R9_STATUS` comes from the current authoritative research report /
PROJECT_STATE_SNAPSHOT; never assume GO.

## Frozen guards

- candidate generation is outcome-blind: outcome / event date / future touch
  must never participate in candidate existence or identity
- population identity immutable (no drift in universe / eligibility)
- feature row immutable once appended (no recompute with later data)
- endpoint strictly later than decision time
- no refit on accumulated data
- no checkpoint switching after OOS starts
- no threshold scan
- no composite invented after OOS_START
- no historical rows backfilled into the clean OOS sample
- clustered uncertainty when repeated symbols exist (no naive iid assumption)
- fixed stopping / readiness rule pre-registered (no peeking)

## VALIDATED claim rule

`VALIDATED` may only be claimed after ALL of:

```text
prospective readiness reached
+
pre-registered gate passed
+
independent review passed (GO verdict)
```

Until then: `SUPPORTED_HYPOTHESIS` at most. `VALIDATED != PROMOTED`.

## Bans

- Fake OOS (historical split relabeled as clean validation)
- Refit / threshold search / checkpoint switching / composite invention
- Backfilling historical rows into OOS
- Any strategy / production / forward / TradePlan change without explicit
  authorization
