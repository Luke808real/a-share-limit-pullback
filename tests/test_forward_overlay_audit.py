from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from limit_pullback.forward_overlay_audit import (
    classify_support_warning,
    context_quality,
    entry_timing,
    sector_proxy_label,
)


def test_support_warning_classification_distinguishes_pierce_from_close_break():
    recovered = classify_support_warning(
        low=Decimal("9.40"),
        close=Decimal("9.60"),
        support_low=Decimal("9.50"),
        invalid=Decimal("9.45"),
    )
    assert "INTRADAY_PIERCE_RECOVERED" in recovered
    assert "CLOSE_BELOW_SUPPORT" not in recovered
    assert "INVALID_INTRADAY_PIERCE" in recovered

    close_break = classify_support_warning(
        low=Decimal("9.30"),
        close=Decimal("9.40"),
        support_low=Decimal("9.50"),
        invalid=Decimal("9.45"),
    )
    assert "CLOSE_BELOW_SUPPORT" in close_break
    assert "INVALID_CLOSE_BREACH" in close_break


def test_context_quality_is_independent_of_entry_distance():
    good = context_quality(
        weekly_context="FAVORABLE",
        sector_context="LEADING",
        pv_context="CONFIRMED",
        stock_vs_sector="LEADER",
        isolated_strength_warning=False,
    )
    assert good == "FAVORABLE"

    timing_close = entry_timing(
        execution_label="B2_READY",
        close=Decimal("9.50"),
        preferred_entry=Decimal("9.00"),
        trigger_price=Decimal("9.00"),
        buy_zone_low=Decimal("8.50"),
        buy_zone_high=Decimal("8.80"),
        invalid_price=Decimal("8.40"),
    )
    assert timing_close["entry_timing"] == "EXTENDED"
    timing_far = entry_timing(
        execution_label="B2_READY",
        close=Decimal("8.80"),
        preferred_entry=Decimal("9.00"),
        trigger_price=Decimal("9.00"),
        buy_zone_low=Decimal("8.50"),
        buy_zone_high=Decimal("8.80"),
        invalid_price=Decimal("8.40"),
    )
    assert timing_far["entry_timing"] == "WAIT_TRIGGER"


def test_sector_proxy_is_low_confidence_for_pool_source():
    label = sector_proxy_label(
        source="LIMIT_UP_POOL_INDUSTRY",
        coverage=64,
        total=78,
        member_count=5,
    )
    assert label == {
        "label": "LIMIT_UP_POOL_SECTOR_PROXY",
        "confidence": "LOW_CONFIDENCE_PROXY",
    }


def test_frozen_artifacts_unchanged():
    plan_manifest = json.loads(
        (
            Path("data/forward-paper/manual-first-plan/manifest.json")
        ).read_text(encoding="utf-8")
    )
    overlay_manifest = json.loads(
        (
            Path("data/forward-paper/manual-first-plan-overlay/manifest.json")
        ).read_text(encoding="utf-8")
    )
    assert plan_manifest["payload_sha256"] == "0d1bb2b92c8b96dea97644abc9565a53ca681274c623024212f7f622dfa3afbf"
    assert overlay_manifest["payload_sha256"] == "d527aa1d1cc037a21f84810f74c804231c0c4a51560c42cfbce91bd52ea593e9"
