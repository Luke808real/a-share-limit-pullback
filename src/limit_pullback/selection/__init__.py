"""REF-R6 selection package.

Selection decides attention (eligibility -> ranking -> presentation); it
never mutates state. First slice: `ranking` hosts the frozen FULL/PRICE_ONLY
score construction moved verbatim from `strategy/scoring.py`.

Target mapping (registered, not yet moved):
- eligibility: currently `_entry_quality_score`, `_entry_room` (state layer)
  and `ENTRY_CANDIDATE_STAGES` (models/signal); target `selection/eligibility`.
- ranking: `selection/ranking.py` (done).
- presentation: currently TradePlan/screen reporting layers; target
  `selection/presentation`.
- R9 policy: target slot `selection/policies/r9`; R9 code lives in separate
  research worktrees outside this repository.
"""

from limit_pullback.selection.ranking import build_score

__all__ = ["build_score"]
