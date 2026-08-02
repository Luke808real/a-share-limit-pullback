"""Models for the Phase 2D.1A T+1 execution-reality artifact.

The model extends the frozen :class:`OutcomeEpisode` without changing any of
its fields.  New fields are derived only from the frozen fill and canonical
daily bars; they are deliberately kept outside the strategy signal models.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import Field

from limit_pullback.models.base import DecimalValue, DomainModel, PositiveDecimal
from limit_pullback.models.outcome import OutcomeEpisode


class ExecutionRealityEpisode(OutcomeEpisode):
    """A frozen episode plus T+1 daily-bar execution results.

    Inheriting the frozen episode model makes accidental omission or mutation
    of a frozen field visible at validation time.  All prices and returns stay
    Decimal-valued; parquet/json writers serialize them as decimal strings.
    """

    entry_price_theoretical: PositiveDecimal | None = None
    planned_risk_abs: PositiveDecimal | None = None
    planned_risk_pct: DecimalValue | None = None

    fill_day_stop_state: str = "NONE"
    fill_day_target_state: str = "NONE"
    sell_eligible_date: date | None = None

    execution_exit_type: str | None = None
    execution_exit_date: date | None = None
    execution_exit_price: PositiveDecimal | None = None
    gross_return_pct: DecimalValue | None = None
    gross_execution_R: DecimalValue | None = None
    net_return_pct_0bp: DecimalValue | None = None
    net_return_pct_10bp: DecimalValue | None = None
    net_return_pct_20bp: DecimalValue | None = None
    net_return_pct_30bp: DecimalValue | None = None
    net_execution_R_0bp: DecimalValue | None = None
    net_execution_R_10bp: DecimalValue | None = None
    net_execution_R_20bp: DecimalValue | None = None
    net_execution_R_30bp: DecimalValue | None = None

    conservative_execution_exit_type: str | None = None
    conservative_execution_exit_date: date | None = None
    conservative_execution_exit_price: PositiveDecimal | None = None
    conservative_gross_return_pct: DecimalValue | None = None
    conservative_gross_execution_R: DecimalValue | None = None
    conservative_net_return_pct_0bp: DecimalValue | None = None
    conservative_net_return_pct_10bp: DecimalValue | None = None
    conservative_net_return_pct_20bp: DecimalValue | None = None
    conservative_net_return_pct_30bp: DecimalValue | None = None
    conservative_net_execution_R_0bp: DecimalValue | None = None
    conservative_net_execution_R_10bp: DecimalValue | None = None
    conservative_net_execution_R_20bp: DecimalValue | None = None
    conservative_net_execution_R_30bp: DecimalValue | None = None

    holding_sessions: int | None = Field(default=None, ge=1)
    strict_execution_status: str
    conservative_execution_status: str
    price_limit_execution_status: str


class ExecutionRealitySummary(DomainModel):
    """Stable JSON summary for a derived execution-reality artifact."""

    title: str = "PHASE 2D.1A EXECUTION REALITY CHECK"
    mode: str = "T+1 DAILY-BAR MODEL"
    not_strategy_optimization: bool = True
    not_portfolio_backtest: bool = True
    snapshot_id: str
    source_episodes_sha256: str
    episode_count: int = Field(ge=0)
    code_count: int = Field(ge=0)
    max_holding_sessions: int = Field(ge=1)
    friction_bps: tuple[int, ...] = (0, 10, 20, 30)
    evaluate_strategy_calls: int = 0
    price_limit_execution_model: str
    cohorts: dict[str, dict[str, Any]] = {}
    comparison_2d0: dict[str, dict[str, Any]] = {}
    b1_tail: dict[str, dict[str, Any]] = {}
    b2_trigger_ambiguity: dict[str, Any] = {}
    performance: dict[str, Any] = {}


__all__ = ["ExecutionRealityEpisode", "ExecutionRealitySummary"]
