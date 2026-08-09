# R9 Gate 2A — Prospective Population Forensics and Generator Contract V01

## STATUS

`GATE2A_GENERATOR=PASS` for a new research-only, outcome-blind daily
generator. This is not authorization to accumulate R9 observations, evaluate
endpoints, or promote a strategy. Gate 2B remains unresolved.

```text
GENERATOR_READY=true
GATE2B_TTL=PENDING_OWNER_DECISION
R9_ACCUMULATION_AUTHORIZED=false
OOS_ROW_N=0
```

Scope was only population identity. No R7/R8 result, outcome attribution, AUC,
return, threshold, checkpoint, TTL, TradePlan, production, or market-data
source was changed or run.

## BASE_HEAD

- Requested base: `bcd60df1bd6e1603d259ddb64cf71b0de6f618ed`.
- Branch: `research/second-launch-factor-pre-r9-hardening-v02` in its isolated
  pre-R9 hardening worktree.
- Historical identity input:
  `.../corrected-b2-trigger-outcome/episodes.parquet`, frozen SHA
  `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093`.
  P0/P1 selected no outcome, event, factor, or return column.
- P2 identity source SHA:
  `01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d`.
- Quarantine identity source SHA:
  `c5d028ca60c1b73f454aeec4da098c13129968bce26ad3f70f5fae96f45a2d66`.

## HISTORICAL_PIPELINE

```text
raw structural event
  -> V01A PIT filter
  -> future availability / maturity filter
  -> earliest-per-setup dedup
  -> historical classification and V01B event alignment
  -> reproducibility quarantine
  -> final R1 cohort
```

| Step | Function / input | Order / filter | Future? | Identity effect |
| --- | --- | --- | --- | --- |
| Raw event | `outcome.py::_replay_code`; bars/pool | chronological prefix; first `(setup_id, execution_label)` (`:1234-1300`) | Prefix loop no; route calls TradePlan | Yes, not P1 semantics |
| Completion | `outcome.py::_complete_event` | adds next session, availability, forward patterns (`:471-535`) | Yes | supplies maturity |
| V01 | `build_success_control_caseset_v01.py::main` | valid invalid/S1, availability >=3, usable quality, then earliest setup (`:109-117`) | Yes | Yes |
| V01A | `build_success_control_caseset_v01a.py::main` | PIT (`:126-133`), then availability (`:134-135`), then earliest setup (`:137-138`) | Yes | Yes |
| V01/V01A classify | builder after case selection | candidate fields plus later bars | Yes | no new case discovery |
| V01B | `build_success_control_caseset_v01b.py::main` | copies V01, post-candidate event alignment (`:59-132`) | Yes | no discovery |
| Final subset | `build_second_launch_outcome_v01.py::publish_reproducible` | quarantine match then removal (`:779-807`) | Yes | 8,746 → 8,682 |

V01 implementation does not enforce its docstring's claimed B1/B2 stage
restriction; V01A is the exact source of the minimal pre-maturity predicate.
This task does not repair or reinterpret either historical builder.

## FUTURE_MATURITY_BEFORE_DEDUP

V01A executes `pit_rows`, then `future_sessions_available >= 3`, then sorts
and deduplicates by `setup_id`. The synthetic D1/D2 regression proves the
effect: D1 availability 2 / D2 availability 3 selects D2; changing only D1 to
3 selects D1. P0 retains D1/D2 and P1 retains D1 in both variants. The fixture
has no success/failure or return field.

Historical maturity can therefore change final candidate identity. It is
forbidden from the new generator and can only be an endpoint status under a
separately authorized later contract.

## P0_RAW_PIT

`r9_population_forensics_v01.py::p0_raw_pit_observations` applies exactly:

```text
setup_stage in {B1_READY, B2_READY, B2_CONFIRMED}
AND invalid_price is non-null
AND s1_price is non-null
AND data_quality != UNUSABLE
```

It retains only `(setup_id, candidate_date)` and uses no maturity,
classification, later touch, event date, factor, or return.

| View | Observation N | Setup N | Candidate-date range |
| --- | ---: | ---: | --- |
| P0 raw PIT observations | 15,535 | 8,865 | 2024-07-03 to 2026-07-31 |

## P1_PROSPECTIVE_FIRST

P1 stably sorts only `(setup_id, candidate_date)` and keeps first per setup.

| View | Setup N |
| --- | ---: |
| P1 prospective first observation | 8,865 |

The prospective API is daily, not whole-file dedup:

```python
generate_setups(as_of=D, daily_source=...)
```

It emits only D observations. A replay concatenates daily calls and derives
P1. The source must declare daily and limit-pool coverage through D and supply
a D-prefix hash for daily bars, pool, config, and source vintage.

## P2_HISTORICAL

P2 is the frozen R1 reproducible identity only, not prospective truth or a
tuning target.

| View | Setup N |
| --- | ---: |
| P2 historical R1 population | 8,682 |

`R1_8682_DEVELOPMENT` remains a `DEVELOPMENT_COHORT`; no rule was adjusted to
make P1 equal P2.

## POPULATION_RECONCILIATION

| Comparison | Count |
| --- | ---: |
| P0 observations | 15,535 |
| P0 setups | 8,865 |
| P1 setups | 8,865 |
| P2 setups | 8,682 |
| P1 ∩ P2 | 8,682 |
| P1 only | 183 |
| P2 only | 0 |
| Same setup and same candidate date | 8,682 |
| Same setup but different candidate date | 0 |

| Difference reason | Count | Explanation |
| --- | ---: | --- |
| `MATURITY_BEFORE_DEDUP` | 0 observed | no frozen intersection date shift; synthetic proof remains binding |
| `QUARANTINE` | 64 | registered reproducibility quarantine |
| `DATA_AVAILABILITY` | 119 | no setup row met historical availability >=3 |
| `OTHER` | 0 | no residual identity difference |

The historical pre-quarantine maturity-first count is 8,746 (= 8,682 P2 + 64
quarantined); it is not a new benchmark or performance sample.

## EXISTING_GENERATOR_AUDIT

Columns are `OUTCOME_BLIND / AS_OF_SAFE / SETUP_ID_COMPATIBLE /
CANDIDATE_SEMANTICS_COMPATIBLE / USES_FUTURE / PRODUCTION_COUPLED`. `P` means
date-prefix safe but not proof of vendor-vintage availability at D.

| Existing path | O | A | I | C | F | P | Finding |
| --- | --- | --- | --- | --- | --- | --- | --- |
| State Generation | Y | P | Y | N | N | Y | prefix-safe, but writes/promotes and lacks immutable first observation |
| B1/B2 Strategy Engine | Y | Y* | Y | N | N | Y | filters supplied bars/pool through AS_OF; emits daily state, not P1 |
| Replay | Y | P | Y | N | N | Y | AS_OF-bounded but lacks V01A P0 and first-observation contract |
| R1 V01/V01A raw chain | N | N | Y | N | Y | N | availability precedes dedup; not prospective |
| V01B | N | N | inherited only | N | Y | N | post-selection classifier/aligner, not discovery |

`Y*` is safe only if the supplied daily/pool input is pinned through D. This
task does not assert a vendor-vintage proof.

## POPULATION_EQUIVALENCE

```text
POPULATION_EQUIVALENCE=PARTIAL
```

P1 and P2 agree on candidate date for every shared setup, but P1 has 183
additional identities due to historical availability and quarantine rules.
Exact parity is neither claimed nor pursued.

## GENERATOR_CLASSIFICATION

```text
C — NO_VALID_GENERATOR (before this task)
```

No existing module is both outcome-blind and semantically complete for P1. The
new minimal replacement is
`research/second_launch/walk_forward_v01/r9_population_generator_v01.py`,
version `NEW_PROSPECTIVE_V01`. It is research-only and has no provider,
filesystem, outcome, event-alignment, maturity, replay, State Generation, or
ledger-write dependency. It uses no new structural threshold or feature.

Its source input must already be a post-close daily setup state with existing
V01A structural fields; it does not invoke or modify the Strategy Engine.

## SETUP_ID

```text
make_setup_id(symbol, anchor_date, anchor_price, price_tick)
```

The generator recomputes the key with the authoritative engine function and
rejects a supplied key that differs in symbol, anchor date, anchor-price ticks,
or price tick. Strategy version is provenance, not a suffix.

## OBSERVATION_ID

```text
observation_id = setup_id + ":" + candidate_date(YYYYMMDD)
```

One setup may produce D1/D2/D3 observations. P0 retains all; P1 retains first.
`append_first_eligible_observation` permits an identical row, preserves later
rows without overwrite, and rejects an earlier replacement or same-ID drift.

## PIT_VALIDATION

- `daily_source.daily_slice(as_of=D)` is called once and must return `as_of ==
  D`, `daily_coverage_through == D`, `limit_pool_coverage_through == D`, and
  a SHA-256 D-prefix source manifest.
- Each input state must have `state_as_of == D` and `anchor_date <= D`; each
  output row has `candidate_date == as_of`. A stale state, future anchor, or
  mismatched source slice is rejected.
- The only eligibility test is the V01A pre-maturity PIT predicate. Candidate
  discovery is separate from later maturity.
- `ACTIVATION_REQUIRED_FOR_POPULATION=false`; activation is neither input nor
  filter, and no TTL/non-activation row is produced.
- AST tests reject outcome, success-control, TradePlan, State Generation,
  replay, pandas, and pyarrow imports plus file read/write calls in generator.
- Synthetic D+1/D+2 deletion/modification leaves AS_OF=D serialized output
  byte-identical; incomplete prefix coverage is rejected.

## BOUNDED_REPLAY

The mechanically fixed three-week window is the final 15 sessions through the
frozen cutoff: 2026-07-13 through 2026-07-31. It was not outcome-selected and
is not a full-market or long-history replay.

The read-only local fixture filters frozen episodes at `signal_date <= AS_OF`,
supplies each day separately, and reads only nine PIT/source-identity columns.
Two runs produced:

| Artifact | Count | SHA-256 |
| --- | ---: | --- |
| P0 daily observations | 330 | `35b09cc262377db5df891a4478ccead95fe44fc6ce7e12080fe713ed28e9a473` |
| P1 first observations | 216 | `276576fa752a66ed98880ae39a93c9c598cd2f77e3e747edf2a5551cf440544d` |

The local test asserts the hashes are identical on rerun and every row has
`candidate_date == as_of`, the two fixed output hashes above, and the corrected
episodes SHA in BASE_HEAD. Its coverage declarations and source-prefix hash are
derived from this historical forensic fixture, not an actual daily+pool source
manifest. It is a mechanical PIT/determinism check, not a prospective
vendor-vintage archive proof.

## GATE2A_GENERATOR_STATUS

```text
R9_POPULATION_STATUS=PASS_NEW_PROSPECTIVE_V01
GATE2A_GENERATOR=PASS
GENERATOR_READY=true
```

`r9_protocol_v02.require_population_and_ttl_authority()` accepts the new
population status, then still fails closed on unresolved TTL. Gate 1/3/4/5
statuses are unchanged; the overall protocol remains
`BLOCKED_R9_TTL_UNRESOLVED`, never GO.

## GATE2B_TTL_STATUS

```text
R9_OBSERVATION_TTL_STATUS=BLOCKED_TTL_UNRESOLVED
R9_OBSERVATION_TTL=None
GATE2B_TTL=PENDING_OWNER_DECISION
```

No TTL, expiry behavior, or non-activation status was inferred.

## R9_ACCUMULATION_AUTHORIZED=false

Gate 2 remains aggregate-blocked pending an owner TTL decision. The generator
is a collection contract only: it does not start R9, create a ledger, add an
OOS row, or authorize Forward/TradePlan/Production use.
