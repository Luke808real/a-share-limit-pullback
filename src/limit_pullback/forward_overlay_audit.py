"""MAINLINE CONTEXT AUDIT v0.1: read-only diagnostic helpers.

The audit never rewrites the frozen plan or overlay; it only classifies warning
semantics and separates context quality from entry timing for human review.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

ZERO = Decimal("0")
ONE = Decimal("1")


def classify_support_warning(
    *,
    low: Decimal,
    close: Decimal,
    support_low: Decimal,
    invalid: Decimal,
) -> list[str]:
    """Classify one bar against the frozen support snapshot (descriptive only)."""

    types: list[str] = []
    if low < invalid:
        types.append("INVALID_INTRADAY_PIERCE")
    if close < invalid:
        types.append("INVALID_CLOSE_BREACH")
    if close < support_low:
        types.append("CLOSE_BELOW_SUPPORT")
    if low < support_low and close >= support_low:
        types.append("INTRADAY_PIERCE_RECOVERED")
    if support_low > 0 and close >= support_low and (close - support_low) / support_low <= Decimal("0.01"):
        types.append("NEAR_SUPPORT_NO_BREAK")
    return types


def context_quality(
    *,
    weekly_context: str,
    sector_context: str,
    pv_context: str,
    stock_vs_sector: str,
    isolated_strength_warning: bool,
) -> str:
    """Context quality only; never mixes in entry distance."""

    if (
        weekly_context == "UNFAVORABLE"
        or sector_context == "WEAK"
        or pv_context == "WARNING"
        or isolated_strength_warning
    ):
        return "UNFAVORABLE"
    if sector_context == "UNKNOWN":
        return "UNKNOWN"
    if (
        weekly_context == "FAVORABLE"
        and sector_context in {"LEADING", "IMPROVING"}
        and pv_context in {"CONFIRMED", "MIXED"}
        and stock_vs_sector != "LAGGARD"
    ):
        return "FAVORABLE"
    return "MIXED"


def entry_timing(
    *,
    execution_label: str,
    close: Decimal,
    preferred_entry: Decimal | None,
    trigger_price: Decimal | None,
    buy_zone_low: Decimal | None,
    buy_zone_high: Decimal | None,
    invalid_price: Decimal | None,
) -> dict[str, Any]:
    """Geometric entry timing derived only from frozen plan + cutoff close."""

    result: dict[str, Any] = {
        "entry_timing": "UNKNOWN",
        "distance_to_preferred_pct": None,
        "distance_to_trigger_pct": None,
        "distance_to_buy_zone_pct": None,
        "descriptive_only_extended": False,
    }
    if invalid_price is not None and close <= invalid_price:
        result["entry_timing"] = "INVALID"
        return result
    if preferred_entry is not None and preferred_entry > 0:
        result["distance_to_preferred_pct"] = close / preferred_entry - ONE
    if trigger_price is not None and trigger_price > 0:
        result["distance_to_trigger_pct"] = close / trigger_price - ONE
    if buy_zone_low is not None and buy_zone_high is not None:
        if close < buy_zone_low:
            result["distance_to_buy_zone_pct"] = close / buy_zone_low - ONE
        elif close > buy_zone_high:
            result["distance_to_buy_zone_pct"] = close / buy_zone_high - ONE
        else:
            result["distance_to_buy_zone_pct"] = ZERO

    if execution_label == "B1_READY":
        if buy_zone_low is not None and buy_zone_high is not None:
            if buy_zone_low <= close <= buy_zone_high:
                result["entry_timing"] = "READY"
            else:
                result["entry_timing"] = "WAIT_PULLBACK"
        elif preferred_entry is not None:
            result["entry_timing"] = (
                "READY"
                if close <= preferred_entry
                else "WAIT_PULLBACK"
            )
        return result

    reference = trigger_price or preferred_entry
    if reference is None or reference <= 0:
        result["entry_timing"] = "WAIT_TRIGGER"
        return result
    distance = close / reference - ONE
    if close < reference:
        result["entry_timing"] = "WAIT_TRIGGER"
    elif distance <= Decimal("0.03"):
        result["entry_timing"] = "READY"
    else:
        result["entry_timing"] = "EXTENDED"
        result["descriptive_only_extended"] = True
    return result


def sector_proxy_label(
    *,
    source: str,
    coverage: int,
    total: int,
    member_count: int,
) -> dict[str, str]:
    if source != "LIMIT_UP_POOL_INDUSTRY":
        return {
            "label": "FULL_MARKET_OR_OTHER",
            "confidence": "UNKNOWN",
        }
    return {
        "label": "LIMIT_UP_POOL_SECTOR_PROXY",
        "confidence": (
            "LOW_CONFIDENCE_PROXY"
            if coverage < total or member_count < 10
            else "MEDIUM_CONFIDENCE_PROXY"
        ),
    }
