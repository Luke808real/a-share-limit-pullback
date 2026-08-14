"""News brief observation-layer models. Strict, frozen, deterministic.

This layer is OBSERVATION ONLY for human decision-making. Nothing here is
a strategy input: no setup_stage, score, threshold, or B1/B2 semantics may
consume these values without explicit Owner approval.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field

from limit_pullback.models.base import DomainModel, FrozenDomainModel


class NewsItem(FrozenDomainModel):
    """One news/announcement/dragon-tiger row matched to a symbol."""

    table: str = Field(pattern=r"^(news_headlines|flash_news_wire|announcement_index|dragon_tiger)$")
    symbol: str  # ASL symbol form, e.g. 600468.SH
    event_date: date
    publish_time: str | None = None  # raw HH:MM[:SS] string, never parsed
    title: str | None = None
    summary: str | None = None
    importance: str | None = None
    category: str | None = None
    reason: str | None = None
    net_amount: str | None = None  # dragon_tiger net amount, kept as string
    url: str | None = None


class SymbolNews(FrozenDomainModel):
    code: str = Field(pattern=r"^[0-9]{6}$")
    items: tuple[NewsItem, ...] = ()


class TableAvailability(FrozenDomainModel):
    table: str
    exists: bool
    max_event_date: date | None = None
    rows_in_window: int = 0
    status: str = Field(pattern=r"^(OK|TABLE_MISSING|NO_ROWS_IN_WINDOW|STALE)$")


class NewsBriefOutput(DomainModel):
    """Deterministic cross-section of the observation layer."""

    as_of: date
    window_start: date
    symbols_requested: tuple[str, ...] = ()
    symbols_matched: int = 0
    availability: tuple[TableAvailability, ...] = ()
    symbol_news: tuple[SymbolNews, ...] = ()
    content_hash: str = Field(min_length=1)
    asl_db_path: str
