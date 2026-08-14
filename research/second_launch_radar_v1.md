# SECOND_LAUNCH_RADAR_V1 — Research-Only Strategy Evolution Spec

Status: RESEARCH_ONLY · Not production · Based on current main
(`34a4a13a74548163f27b72602115352dab922440`)

Production B1–B2 / S1–S2 / Entry Room / scoring / PIT semantics remain
**unchanged**. This spec does not modify the production engine, strategy
config, frozen snapshot, position sizing, or execution semantics.

## 1. Purpose

The radar target is **not an automatic buy point**. The intended chain is:

`FULL MARKET -> PREPOSITION -> LAUNCH_READY -> HUMAN EXECUTION`

Research conclusions that motivate it (all DESCRIPTIVE / OBSERVE_ONLY):

- Mechanical exact-entry optimization: PAUSED (no proven positive edge at
  10bp; entry geometry G1/G2 did not improve anchor-level expectancy).
- Old buy-zone fill shows ADVERSE_SELECTION evidence (fell-to-zone fills are
  weaker; strong names that gap above the old zone are excluded).
- B_ACTIONABLE_WINDOW (future 1–3d near-S1 / new-high / expansion) is a better
  prediction target than an exact entry price.
- GEOMETRY_ONLY ranking (close_vs_s1 + dist_20d_high) is the most stable
  research ranking; quality features add little (COMBINED < GEOMETRY).
- Gate sensitivity: ranking weight > gate loosening; B2_READY non-candidates
  and DATA_LIMITED/manual pools matter for human watch coverage.

## 2. Frozen HUMAN_WATCH_V1 (unchanged)

- Base watch pool: existing production plan universe.
- Additional allowed: **B2_READY non-candidates with valid invalid/S1 levels**
  (no expansion to other untested stages).
- Primary ranking: **locked G geometry** (`close_vs_s1` + `dist_20d_high`,
  discovery-standardized params from `b_actionable_state_v01`).
- `entry_quality / RR / room / Q`: explanatory fields only, not ranking.
- `DATA_LIMITED / PROVISIONAL / unmapped`: not deleted, **not mixed into the
  G ranking**; output separately as MANUAL_REVIEW (≤5).
- Daily output: TOP15 HUMAN_WATCH + MANUAL_REVIEW ≤5.
- Human feedback: `HUMAN_SELECTED / HUMAN_REJECTED` recorded verbatim; never
  used to modify the model.

## 3. Research-Only State Semantics (not mapped to production enums)

| state | meaning |
|---|---|
| FIRST_ATTACK | first capital expression (limit-up or strong volume attack) observed |
| STRUCTURE_ALIVE | base/range not broken after attack (no structural invalid) |
| RECLAIM | price reclaims short MAs (MA5/MA10) / attack midpoint before relaunch |
| PREPOSITION | structure alive + reclaiming; candidate for next-launch watch |
| LAUNCH_READY | next-day intraday-watch priority (B_ACTIONABLE-like state) |
| SECOND_LAUNCH | confirmed second push (new high / near-S1 / expansion) |
| POST_B | S1 reached / launch fulfilled; observation only, no chase |

These are research semantics only; they do not alter `setup_stage` or any
production enum.

## 4. PREPOSITION v0 Features (no optimized score, no threshold scan)

Recorded per candidate, descriptive only:

- first attack: date, type (limit-up vs volume attack), magnitude
- retained move: attack high / close retention
- pullback depth (vs attack high)
- reclaim MA5 / MA10
- distance to attack high
- distance to 20d high
- days since attack
- volume state (contraction/expansion reference)
- sector context (human / overlay field; no automated sector model)

No score, no thresholds; thresholds remain frozen production ones only.

## 5. Daily Research Output Design

- PREPOSITION: 8–12
- LAUNCH_READY: 3–5
- MANUAL_REVIEW: ≤3
- POST_B / NO_CHASE: separate list (observe only)
- Per candidate: HUMAN_SELECTED / HUMAN_REJECTED (verbatim reasons)

## 6. Forward Plan (from 2026-08-04)

For every candidate, record future:

- 1d / 3d / 5d MFE and MAE
- S1 touch / invalid touch
- whether SECOND_LAUNCH occurred
- TIME_TO_SECOND_LAUNCH

Constraints:

- 2026-08-04 onwards only (forward sessions); 8/3 and earlier are hypothesis /
  historical evidence only.
- Frozen history and 8/3 EOD observation must not be rewritten.
- G is not refit; no daily winner/loser adjusts the radar.

## 7. Design Cases (illustrative only, never used to tune thresholds)

- 600756 浪潮软件: DATA_LIMITED (7/9–24 gap); passed all hard gates but was
  low-priority (rank 42); human overlay surfaced the 8/3 opportunity.
- 600468 百利电气: FIRST_ATTACK on 7/23 (PROVISIONAL-only in frozen snapshot);
  8/3 SECOND_LAUNCH (6.22 > prior high 6.18), TIME_TO_SECOND_LAUNCH ≈ 7 days.
- 603980 吉华集团: non-limit volume attack (6/22–23) precedes the 7/28 anchor;
  shows why FIRST_ATTACK ≠ limit-up only.

## 8. Architecture Gaps (current production vs this radar)

- No actionable-window state: production only has entry-candidate semantics;
  watch/launch stages are absent.
- Old buy-zone fill causes adverse selection; strong names are excluded.
- Ranking is entry-quality-centric, underestimating near-high strong structures.
- DATA_LIMITED / PROVISIONAL / unmapped are not systematically surfaced to a
  human review pool.
- No per-candidate forward outcome logging (1/3/5d MFE/MAE, second-launch
  latency) for iterative research.

## 9. FILES / ARTIFACTS

- This spec: `research/second_launch_radar_v1.md`
- Prior research: `research/human_watch_gate_sensitivity_v01.py`,
  `research/forward_paper_test_human_watch_v1.py`,
  `research/b_actionable_state_v01.py`
- Forward output dir: `data/forward-paper/human-watch-v1/`
