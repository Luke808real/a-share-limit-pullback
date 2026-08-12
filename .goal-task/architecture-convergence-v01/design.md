# Architecture Convergence V01 — Confirmed Design

## Status and source

This file records the durable, user-confirmed target decisions for the coordinated refactor. It is not a second strategy truth and cannot override reviewed/frozen Strategy Brain rules.

- Source title: `A股「涨停回调再启动」系统目标架构书 — ARCHITECTURE_CONVERGENCE_V01`
- Source SHA-256: `e2b467d89cdecb15c9cb18a74b81429caa66a8b8c602d47525afafd63669d064`
- Source attachment: `/Users/luke808/.codex/attachments/5d76ed95-8072-4513-9d05-d352668cbb96/pasted-text.txt`
- Confirmed implementation mode: phased deep-mode strangler refactor across Runtime, Brain, and ASL
- Conflict rule: latest user confirmation, then frozen Brain truth, then this target design; a conflict is surfaced and never silently resolved by changing strategy semantics

## Plane ownership

- Data Plane (`ashare-lake`) owns market facts: acquisition, providers/fallback, PIT history, corporate action, ST/suspension/calendar, provenance, quality, and data availability. It contains no B1/B2/R9/setup/TradePlan semantics.
- Runtime Plane (`a-share-limit-pullback`) owns deterministic computation: canonical consumer contracts, features, setup lifecycle/state, eligibility/ranking/presentation, Replay/Daily, future Live interfaces, and evidence.
- Control Plane (`a-share-strategy-brain`) owns human-readable strategy truth, research/ADR/cases/project state, promotion decisions, and agent/audit truth. Runtime never dynamically parses Brain to build rules.

## Runtime destination and dependency direction

The destination is a domain boundary, not a one-commit directory move:

```text
domain <- data facts
  ^
features
  ^
state
  ^
selection
  ^
runtime
  ^
interfaces

runtime -> evidence
```

Runtime converges on `domain/`, `data/`, `features/`, `state/`, `selection/`, `runtime/`, `evidence/`, `interfaces/`, and temporary `legacy/`. Domain imports none of the higher layers; features do not import selection/runtime/provider internals; state does not import selection/filesystem/provider; selection does not import raw providers, ASL internals, or filesystem.

## Semantic model

- Domain types describe names and meaning, not orchestration or business calculation.
- Raw Price is used for limit/support/resistance/B2 trigger/invalid/execution/chart semantics. PIT Continuous Price is used for moving averages, position, trends, and historical comparability.
- Each valid anchor creates a new SetupIdentity. Lifecycle (`ACTIVE`, `INVALIDATED`, `SUPERSEDED_BY_NEW_ANCHOR`, `EXPIRED`) is separate from frozen stage (`NORMAL`, `LIMIT_ANCHOR`, `WATCH_PULLBACK`, `B1_READY`, `B2_READY`, `B2_CONFIRMED`, `INVALID`).
- Frozen Support, Trigger, Invalidation, and S1 values carry value, freeze time, eligible time, source context, method/version, and lineage. Newly frozen values apply only in the future.
- FeatureRecord carries identity/version, symbol/setup/as-of, value/unit, explicit availability/missing reason, input window, data snapshot, calculation version, and source references. Feature answers what a fact is; Policy decides what it means.
- State evaluates previous state + canonical facts + feature vector + frozen policy + eligible snapshots. It emits transition evidence and owns terminal safety priority. It never ranks.
- Selection is eligibility -> ranking -> presentation. R9 belongs only to ranking and consumes candidate context; presentation does not change ranks or state.
- Replay and Daily are orchestration modes over the same core. Live is interface-only until separately authorized.

## Data and evidence contracts

- Runtime consumes CanonicalDataPort-like contracts, never provider APIs or ASL internal tables directly.
- A canonical row has one coherent provider lineage; nullable fields are explicit, missing is not silent, and UNKNOWN is not FALSE.
- Universe and Snapshot are versioned, hashed, as-of contracts with quality states, not `DISTINCT symbol` or cache booleans.
- Missing predecessor, ambiguous lineage, incomplete coverage, source conflict, unknown ST, invalid preclose, corrupt snapshot, or artifact-write failure fails closed with classified evidence.
- Every formal run emits an input manifest, version fingerprint, feature/state/selection evidence, output artifact, hash, receipt, and resolvable predecessor lineage. Outcome is future labeling and cannot modify historical state or features; censoring is explicit.

## Governance and promotion

- Human strategy truth exists only in Brain. Runtime comments/README/config cannot become a second strategy definition.
- Strategy changes require observation/hypothesis/research evidence, promotion decision, ADR, frozen contract, implementation, golden verification, human review, and runtime activation as separate states.
- A formal Brain-to-Runtime change specifies strategy version, ADR/rule/feature IDs, expected semantic/artifact impact, compatibility, migration, and golden requirements. Runtime returns implementation SHA, tests, differential/golden results, artifact hash, contract version, and review result.
- `SUPPORTED != PROMOTED`; architecture refactoring is not feature, Forward, Production, TradePlan, Live, or data-cutover authorization.

## Migration policy

- Execute REF-R0 through REF-R8 as independently gated milestones.
- Use old -> compatibility adapter -> new shadow path -> differential validation -> new default -> proven retirement.
- Each phase declares exact files and behavior/strategy/data/schema/artifact change flags. Refactor PRs contain no new factor, threshold, coefficient, rule, provider, production feature, or Forward behavior.
- R5 state consolidation is the highest-risk phase. R8 retirement is destructive and requires proof and explicit approval.
- The objective is one data boundary, one state engine, one strategy semantics implementation, one Replay/Daily core, and one auditable evidence lineage—not a generic quant platform or aesthetically rearranged directory tree.
