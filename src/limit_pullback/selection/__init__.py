"""REF-R6 selection package.

Selection decides attention (eligibility -> ranking -> presentation); it
never mutates state. First slice: `ranking` hosts the frozen FULL/PRICE_ONLY
score construction moved verbatim from `strategy/scoring.py`.
"""

from limit_pullback.selection.ranking import build_score

__all__ = ["build_score"]
