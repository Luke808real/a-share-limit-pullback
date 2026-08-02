# Project Operating Model — Four Truth Layers

## 1. PRODUCTION TRUTH

The merged `main` branch: frozen strategy/config, screen, trade-plan, and
execution semantics. Changes require a PR + human approval. Performance-only
merges must not change strategy semantics.

## 2. FROZEN HISTORICAL EVIDENCE

Immutable, hash-recorded artifacts: corrected episodes
(SHA `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093`),
execution-reality episodes, canonical snapshots. Research conclusions derive
from these; they are never rewritten.

## 3. FORWARD OBSERVATION

Frozen forward plans (e.g., FORWARD_EPOCH_0 / 2026-08-03 final human watch) and
future observations. Fully isolated: they must never influence historical
parameter selection, and historical research must not retroactively modify a
frozen forward epoch.

## 4. RESEARCH OVERLAY

Hypotheses and human overlays (e.g., premarket context, non-standard first-board
readings). Always labeled `RESEARCH_OVERLAY_ONLY`. Research overlays must not
automatically enter production decisions.

## Promotion Path

RESEARCH OVERLAY -> EDGE_SUPPORTED (research gate) -> PROMOTION_CANDIDATE ->
human review -> PR -> PRODUCTION TRUTH.

`SUPPORTED != PROMOTED`; position sizing research requires a proven entry edge
first.
