"""MAINLINE PULLBACK OBSERVATION OVERLAY v0.2 - CORRECTED.

Corrects v0.1's point-in-time support bug and separates context quality from
entry timing.  Research-only; never modifies production strategy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")
ONE = Decimal("1")


def support_class_v02(
    *,
    low: Decimal,
    close: Decimal,
    support_low: Decimal,
    invalid: Decimal,
) -> tuple[str, str]:
    """Classify only the current plan-date bar against its own frozen support."""

    if close <= invalid:
        return "INVALID_CLOSE_BREACH", "SERIOUS"
    if close < support_low:
        return "CLOSE_BELOW_SUPPORT", "SERIOUS"
    if low < support_low or low <= invalid:
        return "INTRADAY_PIERCE_RECOVERED", "SOFT"
    return "SUPPORT_HELD", "NONE"


def price_volume_interpretation(
    *,
    support_class: str,
    support_severity: str,
    weekly_context: str,
    weekly_volume_ratio: Decimal | None,
    weekly_return_4w: Decimal | None,
    current_volume_ratio: Decimal | None,
    had_bearish_bar: bool,
    close_above_support: bool,
    insufficient_evidence: bool,
) -> str:
    """Interpret price-volume facts without treating one bar as distribution."""

    if insufficient_evidence:
        return "INSUFFICIENT_EVIDENCE"
    if support_severity == "SERIOUS":
        return "STRUCTURAL_DAMAGE"
    if (
        weekly_context == "UNFAVORABLE"
        and weekly_volume_ratio is not None
        and weekly_volume_ratio > Decimal("2")
        and (weekly_return_4w or ZERO) < ZERO
    ):
        return "DISTRIBUTION_RISK"
    if had_bearish_bar and close_above_support:
        return "WASHOUT_POSSIBLE"
    if current_volume_ratio is not None and current_volume_ratio < Decimal("0.8"):
        return "HEALTHY_CONTRACTION"
    return "MIXED"


def context_quality_v02(
    *,
    weekly_context: str,
    pv_interpretation: str,
    sector_context: str,
    sector_confidence: str,
    stock_vs_sector: str,
) -> tuple[str, str]:
    """Context quality; sector proxy is LOW confidence and cannot alone decide."""

    if pv_interpretation in {"STRUCTURAL_DAMAGE", "DISTRIBUTION_RISK"}:
        return "UNFAVORABLE", "HIGH"
    if weekly_context == "UNFAVORABLE":
        return "UNFAVORABLE", "HIGH"
    if pv_interpretation == "INSUFFICIENT_EVIDENCE" and weekly_context == "UNKNOWN":
        return "UNKNOWN", "LOW"

    sector_boost = (
        sector_confidence == "HIGH"
        and sector_context in {"LEADING", "IMPROVING"}
    )
    if weekly_context == "FAVORABLE" and pv_interpretation in {
        "HEALTHY_CONTRACTION",
        "WASHOUT_POSSIBLE",
    }:
        quality = "FAVORABLE"
    elif weekly_context == "FAVORABLE" and pv_interpretation == "MIXED":
        quality = "MIXED"
    elif weekly_context in {"FAVORABLE", "NEUTRAL"} and pv_interpretation in {
        "HEALTHY_CONTRACTION",
        "WASHOUT_POSSIBLE",
        "MIXED",
    }:
        quality = "MIXED"
    else:
        quality = "MIXED"

    if sector_boost and quality == "MIXED":
        quality = "FAVORABLE"
    confidence = "HIGH"
    if sector_confidence != "HIGH" or sector_context == "UNKNOWN":
        confidence = "MEDIUM"
    if weekly_context == "UNKNOWN":
        confidence = "LOW"
    return quality, confidence


def entry_timing_v02(
    *,
    execution_label: str,
    close: Decimal,
    preferred_entry: Decimal | None,
    trigger_price: Decimal | None,
    buy_zone_low: Decimal | None,
    buy_zone_high: Decimal | None,
    invalid_price: Decimal | None,
) -> dict[str, Any]:
    """Entry timing only; no threshold search, distances are descriptive."""

    result: dict[str, Any] = {
        "entry_timing": "UNKNOWN",
        "distance_to_preferred_pct": None,
        "distance_to_buy_zone_pct": None,
        "distance_to_trigger_pct": None,
        "distance_to_invalid_pct": None,
        "descriptive_only_extended": False,
    }
    if invalid_price is not None and invalid_price > 0:
        result["distance_to_invalid_pct"] = close / invalid_price - ONE
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
    if invalid_price is not None and close <= invalid_price:
        result["entry_timing"] = "INVALID"
        return result

    if execution_label == "B1_READY":
        if buy_zone_low is not None and buy_zone_high is not None:
            result["entry_timing"] = (
                "READY_AT_BUY_ZONE"
                if buy_zone_low <= close <= buy_zone_high
                else "WAIT_PULLBACK"
            )
        elif preferred_entry is not None:
            result["entry_timing"] = (
                "READY_AT_BUY_ZONE"
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
        result["entry_timing"] = "AT_TRIGGER"
    else:
        result["entry_timing"] = (
            "POST_TRIGGER_EXTENDED"
            if execution_label == "B2_READY"
            else "CONFIRMED_EXTENDED"
        )
        result["descriptive_only_extended"] = True
    return result


def human_attention(
    *,
    entry_timing: str,
    context_quality: str,
    support_severity: str,
    context_confidence: str,
) -> str:
    if (
        entry_timing in {"READY_AT_BUY_ZONE", "AT_TRIGGER", "WAIT_TRIGGER"}
        and context_quality != "UNFAVORABLE"
        and support_severity != "SERIOUS"
    ):
        return "OBSERVE_NOW"
    if context_quality == "UNFAVORABLE" or support_severity == "SERIOUS":
        return "DIAGNOSTIC"
    if entry_timing in {
        "WAIT_PULLBACK",
        "POST_TRIGGER",
        "POST_TRIGGER_EXTENDED",
        "CONFIRMED_EXTENDED",
        "INVALID",
    } or context_confidence == "LOW":
        return "WAIT"
    return "DIAGNOSTIC"


def overlay_v02_payload_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    import hashlib
    import json

    normalized = []
    for row in rows:
        item = dict(row)
        for key, value in item.items():
            if isinstance(value, Decimal):
                item[key] = str(value)
            elif hasattr(value, "isoformat"):
                item[key] = value.isoformat()
        normalized.append(item)
    normalized.sort(key=lambda item: item["code"])
    payload = {"overlay_version": "MAINLINE_CONTEXT_V0_2_CORRECTED", "rows": normalized}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
