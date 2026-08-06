"""CANONICAL_DERIVED_STRATEGY_LIMIT_EVENT layer.

Materializes deterministic DailyBar-based limit facts using the frozen
phase-2d0 price semantics (``theoretical_limit_price`` / ``is_limit_close`` /
``is_one_word_limit`` / ``is_t_word_limit``).  External enrichment
(first_seal_time, last_seal_time, open_count, seal_amount, industry) is never
synthesized from daily bars: missing enrichment keeps PRICE_ONLY.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.market import LimitUpRecord
from limit_pullback.strategy.structure import (
    is_limit_close,
    is_one_word_limit,
    is_t_word_limit,
    theoretical_limit_price,
)

DERIVATION_VERSION = "PHASE2D0_DERIVED_LIMIT_EVENT_V1"


@dataclass(frozen=True)
class _PriceBar:
    code: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    preclose: Decimal


@dataclass(frozen=True)
class DerivedLimitUpEvent:
    code: str
    trade_date: date
    reference_price: Decimal
    theoretical_limit_price: Decimal
    is_limit_close: bool
    is_one_word: bool
    is_t_word: bool
    source_daily_hash: str
    source_snapshot_or_staging_id: str
    derivation_version: str
    corporate_action_status: str
    quality_status: str
    price_profile: str
    first_seal_time: time | None = None
    last_seal_time: time | None = None
    open_count: int | None = None
    consecutive_count: int | None = None
    seal_amount: Decimal | None = None
    industry: str | None = None
    source: str = "CANONICAL_DERIVED_STRATEGY_LIMIT_EVENT"
    enrichment_profile: str = "NONE"

    def as_content_dict(self) -> dict[str, Any]:
        def convert(value: Any) -> Any:
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, (date, datetime, time)):
                return value.isoformat()
            return value

        return {
            key: convert(value)
            for key, value in sorted(self.__dict__.items())
            if key not in {"derivation_version", "source_daily_hash"}
        }


def _row_bar(row: Mapping[str, Any]) -> _PriceBar:
    return _PriceBar(
        code=str(row["code"]),
        trade_date=row["trade_date"],
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        preclose=Decimal(str(row["preclose"])),
    )


def build_derived_limit_events(
    daily_rows: Sequence[Mapping[str, Any]],
    *,
    source_id: str,
    config: StrategyConfig,
    derivation_version: str = DERIVATION_VERSION,
    corporate_action_status: str = "UNKNOWN",
    universe_members: set[str] | None = None,
) -> list[DerivedLimitUpEvent]:
    """Derive one core limit event per limit-close bar (frozen semantics)."""

    events: list[DerivedLimitUpEvent] = []
    for row in daily_rows:
        if row.get("close") is None or row.get("preclose") is None:
            continue
        bar = _row_bar(row)
        if not is_limit_close(bar, config):
            continue
        code = bar.code
        quality = (
            "OK"
            if universe_members is None or code in universe_members
            else "OUTSIDE_STRATEGY_UNIVERSE"
        )
        events.append(
            DerivedLimitUpEvent(
                code=code,
                trade_date=bar.trade_date,
                reference_price=bar.preclose,
                theoretical_limit_price=theoretical_limit_price(bar, config),
                is_limit_close=True,
                is_one_word=is_one_word_limit(bar, config),
                is_t_word=is_t_word_limit(bar, config),
                source_daily_hash=str(row.get("source_daily_hash") or row.get("selected_source_hash") or row.get("source_row_hash") or ""),
                source_snapshot_or_staging_id=source_id,
                derivation_version=derivation_version,
                corporate_action_status=corporate_action_status,
                quality_status=quality,
                price_profile="PRICE_ONLY",
                enrichment_profile="PRICE_ONLY",
            )
        )
    events.sort(key=lambda event: (event.code, event.trade_date))
    return events


def compose_enrichment(
    events: Sequence[DerivedLimitUpEvent],
    enrichment_rows: Sequence[Mapping[str, Any]],
) -> list[DerivedLimitUpEvent]:
    """Join legacy/external enrichment on (code, trade_date), never fabricate."""

    enrichment_by_key: dict[tuple[str, date], Mapping[str, Any]] = {
        (str(row["code"]), row["trade_date"]): row
        for row in enrichment_rows
    }
    composed: list[DerivedLimitUpEvent] = []
    for event in events:
        legacy = enrichment_by_key.get((event.code, event.trade_date))
        complete = (
            legacy is not None
            and legacy.get("first_seal_time") is not None
            and legacy.get("last_seal_time") is not None
            and legacy.get("open_count") is not None
            and legacy.get("consecutive_count") is not None
        )
        if not complete:
            composed.append(event)
            continue
        composed.append(
            DerivedLimitUpEvent(
                **{
                    **event.__dict__,
                    "first_seal_time": _as_time(legacy["first_seal_time"]),
                    "last_seal_time": _as_time(legacy["last_seal_time"]),
                    "open_count": int(legacy["open_count"]),
                    "consecutive_count": int(legacy["consecutive_count"]),
                    "seal_amount": None,
                    "industry": legacy.get("industry"),
                    "price_profile": "FULL",
                    "enrichment_profile": "FULL",
                }
            )
        )
    composed.sort(key=lambda event: (event.code, event.trade_date))
    return composed


def _as_time(value: Any) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value)[:8])
    except ValueError:
        return None


def derived_event_content_hash(events: Sequence[DerivedLimitUpEvent]) -> str:
    payload = [event.as_content_dict() for event in events]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def events_to_limit_up_records(
    events: Sequence[DerivedLimitUpEvent],
    *,
    fetched_at=None,
) -> list[LimitUpRecord]:
    """Materialize derived events as strategy-pool LimitUpRecords.

    Used by the characterization/screen-regression harness only; production
    strategy continues to read the canonical pool unchanged.
    """

    from datetime import timezone

    fetched = fetched_at or datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
    records: list[LimitUpRecord] = []
    for event in events:
        records.append(
            LimitUpRecord(
                code=event.code,
                trade_date=event.trade_date,
                name=event.industry or event.code,
                limit_price=event.theoretical_limit_price,
                first_seal_time=event.first_seal_time,
                last_seal_time=event.last_seal_time,
                open_count=event.open_count,
                consecutive_count=event.consecutive_count,
                turnover_rate=None,
                float_market_cap=None,
                total_market_cap=None,
                industry=event.industry,
                source=event.source,
                fetched_at=fetched,
            )
        )
    return records


def write_derived_event_manifest(
    *,
    events: Sequence[DerivedLimitUpEvent],
    base_snapshot_id: str,
    daily_staging_run_id: str,
    daily_staging_hash: str,
    universe_contract_version: str,
    universe_hash: str,
    date_from: date,
    date_to: date,
    legacy_enrichment_source_hash: str | None,
    corporate_action_status_summary: Mapping[str, int],
    validation_results: Mapping[str, Any],
    path: Path,
) -> Path:
    """Write the staged DERIVED_LIMIT_EVENT manifest (audit, not promotion)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rows_by_date: dict[str, int] = {}
    for event in events:
        rows_by_date[event.trade_date.isoformat()] = (
            rows_by_date.get(event.trade_date.isoformat(), 0) + 1
        )
    payload = {
        "schema_version": "1",
        "derivation_version": DERIVATION_VERSION,
        "base_snapshot_id": base_snapshot_id,
        "daily_staging_run_id": daily_staging_run_id,
        "daily_staging_hash": daily_staging_hash,
        "universe_contract_version": universe_contract_version,
        "universe_hash": universe_hash,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "derived_event_row_n": len(events),
        "rows_by_date": rows_by_date,
        "legacy_enrichment_source_hash": legacy_enrichment_source_hash,
        "corporate_action_status_summary": dict(
            sorted(corporate_action_status_summary.items())
        ),
        "validation_results": validation_results,
        "content_hash": derived_event_content_hash(events),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path
