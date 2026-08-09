"""Outcome-blind Gate 2A identity reconciliation for frozen historical inputs.

This research helper is deliberately separate from the prospective generator.
It may inspect the historical maturity and quarantine columns only to explain
why the frozen development cohort differs from the new prospective population.
It does not calculate performance, labels, events, or factors.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd


VALID_STAGES = frozenset({"B1_READY", "B2_READY", "B2_CONFIRMED"})
PIT_INPUT_COLUMNS = (
    "code",
    "setup_id",
    "setup_stage",
    "signal_date",
    "anchor_date",
    "anchor_price",
    "invalid_price",
    "s1_price",
    "data_quality",
)
HISTORICAL_MATURITY_COLUMN = "future_sessions_available"
IDENTITY_COLUMNS = ("setup_id", "candidate_date")


@dataclass(frozen=True)
class PopulationReconciliation:
    p0_observation_n: int
    p0_setup_n: int
    p1_setup_n: int
    p2_setup_n: int
    overlap_n: int
    p1_only_n: int
    p2_only_n: int
    same_candidate_date_n: int
    different_candidate_date_n: int
    reason_counts: dict[str, int]


def _required(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"missing required historical columns: {missing}")


def _identity(frame: pd.DataFrame, *, setup_column: str) -> pd.DataFrame:
    _required(frame, (setup_column, "candidate_date"))
    result = frame.loc[:, [setup_column, "candidate_date"]].copy()
    result = result.rename(columns={setup_column: "setup_id"})
    result["setup_id"] = result["setup_id"].astype(str)
    result["candidate_date"] = pd.to_datetime(result["candidate_date"]).dt.date
    if result["setup_id"].isna().any() or result["candidate_date"].isna().any():
        raise ValueError("historical identity contains null")
    return result


def pit_mask(episodes: pd.DataFrame) -> pd.Series:
    """The V01A pre-maturity structural/PIT predicate, verbatim in meaning."""

    _required(episodes, PIT_INPUT_COLUMNS)
    return (
        episodes["setup_stage"].isin(VALID_STAGES)
        & episodes["invalid_price"].notna()
        & episodes["s1_price"].notna()
        & (episodes["data_quality"] != "UNUSABLE")
    )


def p0_raw_pit_observations(episodes: pd.DataFrame) -> pd.DataFrame:
    """All candidate-time observations, with no maturity or label columns."""

    selected = episodes.loc[pit_mask(episodes), list(PIT_INPUT_COLUMNS)].copy()
    selected = selected.rename(columns={"signal_date": "candidate_date"})
    return _identity(selected, setup_column="setup_id")


def p1_prospective_first_observation(p0: pd.DataFrame) -> pd.DataFrame:
    """Earliest candidate date per setup using only P0 identity information."""

    identity = _identity(p0, setup_column="setup_id")
    return (
        identity.sort_values(["setup_id", "candidate_date"], kind="mergesort")
        .drop_duplicates(subset=["setup_id"], keep="first")
        .reset_index(drop=True)
    )


def historical_maturity_then_first(episodes: pd.DataFrame) -> pd.DataFrame:
    """Reproduce only V01A's historical maturity-before-dedup identity order."""

    _required(episodes, (*PIT_INPUT_COLUMNS, HISTORICAL_MATURITY_COLUMN))
    selected = episodes.loc[
        pit_mask(episodes) & (episodes[HISTORICAL_MATURITY_COLUMN] >= 3),
        ["setup_id", "signal_date"],
    ].rename(columns={"signal_date": "candidate_date"})
    return p1_prospective_first_observation(selected)


def p2_historical_r1_population(final_cohort: pd.DataFrame) -> pd.DataFrame:
    """Read only frozen-cohort identity for comparison with P1."""

    setup_column = "episode_id" if "episode_id" in final_cohort.columns else "setup_id"
    return p1_prospective_first_observation(_identity(final_cohort, setup_column=setup_column))


def reconcile_populations(
    *,
    p0: pd.DataFrame,
    p1: pd.DataFrame,
    p2: pd.DataFrame,
    historical_matured: pd.DataFrame,
    quarantined_setup_ids: Iterable[str],
) -> PopulationReconciliation:
    """Compare population identities without any outcome or factor metric."""

    p0_identity = _identity(p0, setup_column="setup_id")
    p1_identity = p1_prospective_first_observation(p1)
    p2_identity = p1_prospective_first_observation(p2)
    historical_identity = p1_prospective_first_observation(historical_matured)
    p1_by_setup = p1_identity.set_index("setup_id")["candidate_date"].to_dict()
    p2_by_setup = p2_identity.set_index("setup_id")["candidate_date"].to_dict()
    matured_by_setup = historical_identity.set_index("setup_id")["candidate_date"].to_dict()
    p1_set, p2_set = set(p1_by_setup), set(p2_by_setup)
    overlap = p1_set & p2_set
    p1_only = p1_set - p2_set
    p2_only = p2_set - p1_set
    quarantined = {str(value) for value in quarantined_setup_ids}
    reasons: Counter[str] = Counter()
    for setup_id in p1_only:
        if setup_id in quarantined:
            reasons["QUARANTINE"] += 1
        elif setup_id not in matured_by_setup:
            reasons["DATA_AVAILABILITY"] += 1
        else:
            reasons["OTHER"] += 1
    different_dates = sum(
        p1_by_setup[setup_id] != p2_by_setup[setup_id]
        for setup_id in overlap
    )
    maturity_identity_changes = sum(
        p1_by_setup[setup_id] != matured_by_setup[setup_id]
        for setup_id in (set(p1_by_setup) & set(matured_by_setup))
    )
    reasons["MATURITY_BEFORE_DEDUP"] = maturity_identity_changes
    reasons.setdefault("QUARANTINE", 0)
    reasons.setdefault("DATA_AVAILABILITY", 0)
    reasons.setdefault("OTHER", 0)
    return PopulationReconciliation(
        p0_observation_n=len(p0_identity),
        p0_setup_n=p0_identity["setup_id"].nunique(),
        p1_setup_n=len(p1_identity),
        p2_setup_n=len(p2_identity),
        overlap_n=len(overlap),
        p1_only_n=len(p1_only),
        p2_only_n=len(p2_only),
        same_candidate_date_n=len(overlap) - different_dates,
        different_candidate_date_n=different_dates,
        reason_counts=dict(sorted(reasons.items())),
    )


def fixed_three_week_dates() -> tuple[date, ...]:
    """The final fifteen sessions through the 2026-07-31 frozen cutoff."""

    return (
        date(2026, 7, 13), date(2026, 7, 14), date(2026, 7, 15),
        date(2026, 7, 16), date(2026, 7, 17), date(2026, 7, 20),
        date(2026, 7, 21), date(2026, 7, 22), date(2026, 7, 23),
        date(2026, 7, 24), date(2026, 7, 27), date(2026, 7, 28),
        date(2026, 7, 29), date(2026, 7, 30), date(2026, 7, 31),
    )
