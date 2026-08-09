# R9 Gate 2B — Administrative TTL and Prospective Event Eligibility Freeze V01

## STATUS

```text
GATE2A_GENERATOR=PASS
GATE2B_TTL=PASS
GATE2=PASS
PRE_R9_STATUS=GO
R9_ACCUMULATION_AUTHORIZED=true
R9_OOS_ROWS_WRITTEN=0
```

This is a protocol authorization only. It creates no R9 accumulation, OOS row,
market-data fetch, TradePlan, Forward action, production change, historical
performance study, or strategy-engine change.

## OWNER_DECISION

```text
R9_ADMINISTRATIVE_TTL_VERSION=R9_V01_ADMINISTRATIVE_TTL
TTL_SELECTION_BASIS=OWNER_PROSPECTIVE_DESIGN
TTL_ANCHOR=anchor_date/T0
T0_AGE=0
R9_OBSERVATION_TTL=7 subsequent A-share trading sessions
```

This is an owner-selected prospective design decision. It is deliberately not
an inference from the historical development cohort.

## TTL_DEFINITION

For a setup whose anchor/T0 is an exchange session, `ttl_end_date` is the
seventh calendar member strictly after T0:

```text
ttl_end_date = frozen_calendar[index(anchor_date) + 7]
valid observation/event window = T+1 ... T+7
```

The pure contract rejects a missing, unordered, duplicated, hash-mismatched,
or insufficient calendar. It never uses calendar-day arithmetic or a symbol's
next available bar. A halt therefore consumes exchange-session age and cannot
extend a setup.

`candidate_date` does not reset age. For example, first observation at T+5 has
only T+6 and T+7 remaining for a prospective event search.

## TTL_RATIONALE

The project already has a frozen anchor-based B1 concept with an existing
1–7-session structural condition. That context explains why an owner can use a
seven-session administrative envelope, but it is not evidence that seven is
an optimal holding, activation, or performance horizon.

Structural invalidation remains an existing-state input, not a Gate 2B
recalculation. Existing engine invalidation is sticky and takes precedence over
B1/B2 state; Gate 2B accepts its already determined invalidation date and
terminates before TTL when it is earlier. No invalidation price, buffer, or
threshold was introduced. Same-session S1-touch/structural-invalidation order
fails closed as `SAME_SESSION_STRUCTURAL_INVALIDATION_AMBIGUITY`.

If a valid immutable first S1-touch was already registered and a later existing
structural invalidation occurs, the final setup status records
`STRUCTURALLY_INVALIDATED` while preserving
`activation_status=FIRST_VALID_S1_TOUCH` and the same `event_id`. A later
lifecycle state therefore cannot erase an earlier prospective event.

```text
STRUCTURAL_INVALIDATION_STATUS=DEFERRED_TO_EXISTING_STATE_SEMANTICS
```

## NON_OPTIMIZATION_DISCLOSURE

```text
NOT selected from R3-R8 outcome performance
NOT selected from B4 2-5 benchmark
NOT derived from 3D/5D outcome horizon
NOT claimed VALIDATED
```

No SUCCESS/FAILED rates, returns, AUC, or TTL performance comparison was read
or calculated. The Gate 2B source guard rejects TTL-search symbols.

## PROSPECTIVE_ELIGIBILITY

Gate 2A remains a post-close daily generator. Candidate-day intraday bars are
already historical at creation, so they are permanently ineligible for a new
R9 intraday decision.

For first observations in `B1_READY` or `B2_READY`:

```text
INTRADAY_ELIGIBLE_FROM = first frozen A-share session strictly after candidate_date
EVENT_SEARCH_START = INTRADAY_ELIGIBLE_FROM
EVENT_SEARCH_END = ttl_end_date
```

The event date must be a member of the same hash-pinned calendar and lie within
that inclusive window. Candidate-day touches are rejected. If no later session
exists within TTL (for example first observation at T+7), daily eligibility is
retained but no event window is opened:

```text
INTRADAY_PRIMARY_ELIGIBLE=false
INTRADAY_INELIGIBLE_REASON=NO_ELIGIBLE_SESSION_WITHIN_TTL
```

## PREOBSERVED_ACTIVATION

If first observation is `B2_CONFIRMED`:

```text
DAILY_POPULATION_ELIGIBLE=true
INTRADAY_PRIMARY_ELIGIBLE=false
INTRADAY_INELIGIBLE_REASON=PREOBSERVED_ACTIVATION
```

No candidate-day 10:30 bar is read retrospectively, and a later or repeated S1
touch cannot substitute for the preobserved activation. The daily setup remains
in the population without manufacturing an intraday event.

## EVENT_SEARCH_WINDOW

One setup can register one immutable first valid S1-touch event only:

```text
EVENT_SEARCH_START <= first_s1_touch_date <= TTL_END
REPEAT_CONFIRMATION_CREATES_NEW_EVENT=false
```

T+7 is included. A T+7 touch at or before 10:30 can have a primary feature;
after 10:30 it is retained with
`POST_CHECKPOINT_NOT_OBSERVABLE`. T+8 is rejected. The contract also requires
the upstream right-labeled minute grid to be verified before event registration.
Every registered event is revalidated before finalization: same setup identity,
calendar hash, inclusive event window, non-negative post-touch bar count, and
an exact right-labeled 5-minute A-share session clock. Datetime inputs require
an explicit timezone and are normalized to `Asia/Shanghai`; naive datetimes,
off-grid times, seconds, and forged T+8 events fail closed.

Finalization also rejects any first observation, event, or structural
invalidation dated after its `as_of` session. For timestamped event clocks, the
normalized Shanghai date must equal `event_date`; a future timestamp cannot be
relabeled as an earlier window day. `register_first_eligible_s1_touch` is the
only prospective event-registration API; the former identity-only protocol
helper is not exposed.

## NON_ACTIVATION_POLICY

At the close of T+7, when no valid first S1 touch exists:

```text
SETUP_TERMINAL_STATUS=NO_ACTIVATION_WITHIN_TTL
activation_status=NO_ACTIVATION_WITHIN_TTL
R9_ACTIVE_POPULATION=true
```

Before T+7 close the status remains pending. These rows are retained as the
candidate-to-activation denominator; they are never silently removed.

A first candidate observed after T+7 is separately retained for audit:

```text
SETUP_STATUS=FIRST_OBSERVED_AFTER_ADMINISTRATIVE_EXPIRY
R9_ACTIVE_POPULATION=false
```

## POPULATION_IDENTITY_INVARIANCE

TTL affects only event lifecycle and non-activation classification. It cannot
change `setup_id`, first `candidate_date`, or the immutable first daily feature
snapshot. Later daily observations are provenance only and cannot replace the
P1 primary identity.

## GATE2A_STATUS

`PASS_NEW_PROSPECTIVE_V01` remains frozen. The Gate 2A P0/P1 source is still
outcome-blind and remains only a post-close daily collection contract.

## GATE2B_STATUS

```text
R9_OBSERVATION_TTL_STATUS=PASS_OWNER_FROZEN_V01
R9_OBSERVATION_TTL=7
R9_PROSPECTIVE_EVENT_ELIGIBILITY_STATUS=PASS_OWNER_FROZEN_V01
```

The implementation is the pure module
`research/second_launch/walk_forward_v01/r9_ttl_event_eligibility_v01.py`.
It takes an explicit frozen calendar plus existing-state invalidation date; it
has no source/provider/ledger write dependency.

## GATE2_FINAL

```text
population generator=PASS
setup identity=PASS
one-event identity=PASS
owner-frozen TTL=PASS
prospective event observability=PASS
non-activation retention=PASS
GATE_2_POPULATION_EVENT_TTL=PASS
```

## ALL_PRE_R9_GATES

| Gate | Status |
| --- | --- |
| GATE_1_R1_AUTHORITY_BOUNDARY | PASS |
| GATE_2_POPULATION_EVENT_TTL | PASS |
| GATE_3_INDEPENDENT_ENDPOINT | PASS |
| GATE_4_MULTIPLICITY_UNCERTAINTY | PASS |
| GATE_5_ASL_PROVENANCE_ATOMICITY | PASS |

`PRE_R9_STATUS=GO` means the protocol is authorized to freeze and begin a
future clean accumulation only; it does not validate any historical edge.

## PROTOCOL_FREEZE_COMMIT

An ordinary Git commit cannot contain its own final SHA without changing that
SHA. Therefore the exact post-commit receipt is recorded in the local annotated
tag `r9-protocol-freeze-v01`, which points to the protocol-freeze commit and
contains `PROTOCOL_FREEZE_COMMIT=<HEAD_AFTER>`. This avoids a false
self-referential value in the committed protocol artifact.

`R9_ACCUMULATION_AUTHORIZED=true` is the policy decision shown above; it is not
write authority by itself. Before any future append, the pure contract requires
the actual local annotated Git tag to be read and checked. The reader verifies
the tag object type (not a lightweight tag), peeled commit target, full
40-character SHA, exact one-time message fields, and that the tag target is
the current `HEAD`. `atomic_publish_bytes` invokes that reader before it
creates a temporary output; no caller-supplied receipt object can authorize a
write.

```text
R9_ACCUMULATION_WRITE_AUTHORITY=POST_COMMIT_RECEIPT_REQUIRED
PROTOCOL_FREEZE_COMMIT=<HEAD_AFTER>
PROTOCOL_FREEZE_DATE=2026-08-09
OOS_START=2026-08-10
PROTOCOL_FREEZE_CALENDAR_HASH=9304f0409d7e95b54e2ba90f361d0228624cb313722ad4a97a2fa1b891087d2e
```

## PROTOCOL_FREEZE_DATE

```text
PROTOCOL_FREEZE_DATE=2026-08-09
```

The freeze date is a protocol provenance date, not an OOS row date.

## OOS_START

```text
PROTOCOL_FREEZE_CALENDAR_VERSION=R9_PROTOCOL_FREEZE_CALENDAR_V01
PROTOCOL_FREEZE_CALENDAR_ARTIFACT=r9_protocol_freeze_calendar_v01.csv
PROTOCOL_FREEZE_CALENDAR_SOURCE=OWNER_FROZEN_A_SHARE_SESSION_WITNESS
PROTOCOL_FREEZE_CALENDAR_HASH=9304f0409d7e95b54e2ba90f361d0228624cb313722ad4a97a2fa1b891087d2e
OOS_START=2026-08-10
```

`OOS_START` is calculated by `next_exchange_session_strictly_after` over the
frozen session witness; it is not assigned by weekday arithmetic or a constant
in the OOS guard. The guard requires both calendar membership and
`candidate_date >= OOS_START`, and rejects any caller attempt to substitute a
different freeze date, calendar, or OOS start. A future real collection run
must pin its own complete exchange-calendar slice and manifest hash; this
short witness only settles the protocol-freeze boundary without any network
fetch.

## R9_OOS_ROWS_WRITTEN=0

All committed ledger CSVs remain header-only. No candidate, event, feature,
endpoint, or OOS row was created in this task.

## R9_RECOMMENDATION

```text
AUTHORIZED_TO_FREEZE_AND_ACCUMULATE
```

This authorization begins no work automatically. Any first real row must pass
the clean OOS origin guard, be on/after the calendar-derived OOS start, and
carry a future run's immutable source and calendar provenance. It must also
pass the post-commit receipt guard before the append-only publication path is
called.
