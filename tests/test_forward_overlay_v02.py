from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from limit_pullback.forward_overlay_v02 import (
    context_quality_v02,
    entry_timing_v02,
    human_attention,
    price_volume_interpretation,
    support_class_v02,
)


def test_support_class_v02_distinguishes_pierce_from_close_break():
    pierce, severity = support_class_v02(
        low=Decimal("9.40"),
        close=Decimal("9.60"),
        support_low=Decimal("9.50"),
        invalid=Decimal("9.45"),
    )
    assert pierce == "INTRADAY_PIERCE_RECOVERED"
    assert severity == "SOFT"

    close_break, severity2 = support_class_v02(
        low=Decimal("9.30"),
        close=Decimal("9.47"),
        support_low=Decimal("9.50"),
        invalid=Decimal("9.45"),
    )
    assert close_break == "CLOSE_BELOW_SUPPORT"
    assert severity2 == "SERIOUS"

    invalid_break, severity3 = support_class_v02(
        low=Decimal("9.20"),
        close=Decimal("9.40"),
        support_low=Decimal("9.50"),
        invalid=Decimal("9.45"),
    )
    assert invalid_break == "INVALID_CLOSE_BREACH"
    assert severity3 == "SERIOUS"


def test_price_volume_interpretation_separates_washout_from_damage():
    washout = price_volume_interpretation(
        support_class="INTRADAY_PIERCE_RECOVERED",
        support_severity="SOFT",
        weekly_context="FAVORABLE",
        weekly_volume_ratio=Decimal("1.2"),
        weekly_return_4w=Decimal("0.05"),
        current_volume_ratio=Decimal("1.0"),
        had_bearish_bar=True,
        close_above_support=True,
        insufficient_evidence=False,
    )
    assert washout == "WASHOUT_POSSIBLE"

    damage = price_volume_interpretation(
        support_class="CLOSE_BELOW_SUPPORT",
        support_severity="SERIOUS",
        weekly_context="FAVORABLE",
        weekly_volume_ratio=Decimal("1.0"),
        weekly_return_4w=Decimal("0.05"),
        current_volume_ratio=Decimal("1.0"),
        had_bearish_bar=False,
        close_above_support=False,
        insufficient_evidence=False,
    )
    assert damage == "STRUCTURAL_DAMAGE"


def test_context_quality_low_confidence_sector_does_not_boost():
    quality, confidence = context_quality_v02(
        weekly_context="FAVORABLE",
        pv_interpretation="MIXED",
        sector_context="LEADING",
        sector_confidence="LOW",
        stock_vs_sector="LEADER",
    )
    assert quality == "MIXED"
    assert confidence == "MEDIUM"


def test_entry_timing_separated_from_context():
    timing = entry_timing_v02(
        execution_label="B2_READY",
        close=Decimal("8.80"),
        preferred_entry=Decimal("9.00"),
        trigger_price=Decimal("9.00"),
        buy_zone_low=Decimal("8.50"),
        buy_zone_high=Decimal("8.80"),
        invalid_price=Decimal("8.40"),
    )
    assert timing["entry_timing"] == "WAIT_TRIGGER"
    extended = entry_timing_v02(
        execution_label="B2_READY",
        close=Decimal("9.50"),
        preferred_entry=Decimal("9.00"),
        trigger_price=Decimal("9.00"),
        buy_zone_low=Decimal("8.50"),
        buy_zone_high=Decimal("8.80"),
        invalid_price=Decimal("8.40"),
    )
    assert extended["entry_timing"] == "POST_TRIGGER_EXTENDED"


def test_human_attention_policy():
    assert (
        human_attention(
            entry_timing="AT_TRIGGER",
            context_quality="FAVORABLE",
            support_severity="NONE",
            context_confidence="MEDIUM",
        )
        == "OBSERVE_NOW"
    )
    assert (
        human_attention(
            entry_timing="POST_TRIGGER_EXTENDED",
            context_quality="MIXED",
            support_severity="NONE",
            context_confidence="MEDIUM",
        )
        == "WAIT"
    )


def test_v02_frozen_source_hashes():
    manifest = json.loads(
        (
            Path("data/forward-paper/manual-first-plan-overlay-v02/manifest.json")
        ).read_text(encoding="utf-8")
    )
    assert manifest["source_plan_hash"] == "0d1bb2b92c8b96dea97644abc9565a53ca681274c623024212f7f622dfa3afbf"
    assert manifest["source_overlay_v01_hash"] == "d527aa1d1cc037a21f84810f74c804231c0c4a51560c42cfbce91bd52ea593e9"
    assert manifest["source_audit_v01_hash"] == "43407eed26c58b9ff84d0cba94d700525a41d783e3491a117d613244856f6b24"
