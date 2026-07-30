from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import yaml
from pydantic import ValidationError

from limit_pullback.models import (
    AnchorSnapshot,
    B2TriggerSnapshot,
    InvalidPriceSnapshot,
    ReviewGroup,
    S1Snapshot,
    ScoreBreakdown,
    ScoreProfile,
    SetupStage,
    StrategySignal,
    SupportSnapshot,
)


def load_cases(project_root):
    with (project_root / "tests" / "fixtures" / "signal_cases.yaml").open(
        encoding="utf-8"
    ) as stream:
        return yaml.safe_load(stream)


def test_valid_b2_confirmed_fixture(project_root):
    signal = StrategySignal.model_validate(load_cases(project_root)["valid_b2_confirmed"])

    assert signal.setup_stage is SetupStage.B2_CONFIRMED
    assert signal.score.available_score == Decimal("12")
    assert signal.score.available_max_score == Decimal("14")
    assert signal.score.normalized_score == Decimal("85.71")
    assert '"normalized_score":"85.71"' in signal.model_dump_json()


def test_valid_open_space_fixture(project_root):
    signal = StrategySignal.model_validate(load_cases(project_root)["valid_open_space"])

    assert signal.review_group is ReviewGroup.OPEN_SPACE
    assert signal.target_s1 is None
    assert signal.risk_reward_ratio is None


def test_normalized_score_cannot_be_supplied():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ScoreBreakdown.model_validate(
            {
                "profile": "FULL",
                "profile_max_score": "100",
                "component_scores": {"rule": "5"},
                "component_max_scores": {"rule": "10"},
                "normalized_score": "50.00",
            }
        )


def test_unavailable_rule_is_removed_and_flagged():
    score = ScoreBreakdown(
        profile=ScoreProfile.PRICE_ONLY,
        profile_max_score=Decimal("91"),
        component_scores={"limit_close": Decimal("6")},
        component_max_scores={"limit_close": Decimal("6")},
        unavailable_rules=("seal_before_cutoff",),
        quality_flags=("MISSING_SCORE_FIELD:seal_before_cutoff",),
    )

    assert score.available_max_score == Decimal("6")
    assert "seal_before_cutoff" not in score.component_scores


def test_unavailable_rule_cannot_form_negative_reason():
    with pytest.raises(ValidationError, match="cannot form negative reasons"):
        ScoreBreakdown(
            profile=ScoreProfile.PRICE_ONLY,
            profile_max_score=Decimal("91"),
            component_scores={"limit_close": Decimal("6")},
            component_max_scores={"limit_close": Decimal("6")},
            unavailable_rules=("seal_before_cutoff",),
            risks={"seal_before_cutoff": "缺失被错误视为风险"},
            quality_flags=("MISSING_SCORE_FIELD:seal_before_cutoff",),
        )


def test_b2_trigger_requires_future_eligibility():
    with pytest.raises(ValidationError, match="later than frozen_as_of"):
        B2TriggerSnapshot(
            trigger_price=Decimal("11.35"),
            frozen_as_of=date(2024, 1, 5),
            eligible_from=date(2024, 1, 5),
            sources=("PLATFORM_HIGH",),
        )


def test_b2_confirmed_rejects_same_day_freeze(project_root):
    payload = load_cases(project_root)["valid_b2_confirmed"]
    payload["b2_trigger"]["frozen_as_of"] = payload["trade_date"]
    payload["b2_trigger"]["eligible_from"] = date(2024, 1, 9)

    with pytest.raises(ValidationError, match="snapshots cannot be frozen after|frozen before"):
        StrategySignal.model_validate(payload)


def test_invalid_price_cannot_loosen(project_root):
    payload = load_cases(project_root)["valid_open_space"]
    payload["invalid_price"] = "10.50"
    payload["invalid_price_snapshot"]["invalid_price"] = "10.50"

    with pytest.raises(ValidationError, match="cannot loosen"):
        StrategySignal.model_validate(payload)


@pytest.mark.parametrize(
    "snapshot",
    (
        SupportSnapshot(
            support_low=Decimal("10.80"),
            support_high=Decimal("11.00"),
            support_center=Decimal("10.90"),
            sources=("ANCHOR_PRICE",),
            frozen_as_of=date(2024, 1, 5),
            eligible_from=date(2024, 1, 6),
            reference_close=Decimal("10.95"),
            max_above_reference_close=Decimal("0.002"),
        ),
        S1Snapshot(
            s1_low=Decimal("12"),
            s1_high=Decimal("12.10"),
            sources=("LEFT_HIGH_60",),
            frozen_as_of=date(2024, 1, 5),
            eligible_from=date(2024, 1, 6),
        ),
        InvalidPriceSnapshot(
            initial_invalid_price=Decimal("10.70"),
            invalid_price=Decimal("10.70"),
            frozen_as_of=date(2024, 1, 5),
            eligible_from=date(2024, 1, 6),
        ),
    ),
)
def test_structure_snapshots_require_future_eligibility(snapshot):
    with pytest.raises(ValidationError, match="later than frozen_as_of"):
        snapshot.model_copy(
            update={"eligible_from": snapshot.frozen_as_of}
        ).__class__.model_validate(
            snapshot.model_dump()
            | {"eligible_from": snapshot.frozen_as_of}
        )


def test_support_snapshot_rejects_level_materially_above_close():
    with pytest.raises(ValidationError, match="too far above"):
        SupportSnapshot(
            support_low=Decimal("16.90"),
            support_high=Decimal("17.04"),
            support_center=Decimal("16.97"),
            sources=("PLATFORM_HIGH_20",),
            frozen_as_of=date(2026, 7, 24),
            eligible_from=date(2026, 7, 25),
            reference_close=Decimal("16.57"),
            max_above_reference_close=Decimal("0.002"),
        )


def test_open_space_cannot_contain_risk_reward(project_root):
    payload = load_cases(project_root)["valid_open_space"]
    payload["risk_reward_ratio"] = "1.50"

    with pytest.raises(ValidationError, match="must be null"):
        StrategySignal.model_validate(payload)


def test_runtime_datetime_requires_explicit_timezone(project_root):
    payload = load_cases(project_root)["valid_open_space"]
    payload["generated_at"] = datetime(2024, 1, 5, 16, 10)

    with pytest.raises(ValidationError, match="explicit timezone"):
        StrategySignal.model_validate(payload)


def test_snapshot_is_immutable():
    snapshot = AnchorSnapshot(
        anchor_date=date(2024, 1, 3),
        anchor_price=Decimal("11"),
        frozen_as_of=date(2024, 1, 3),
        source="SYNTHETIC",
    )

    with pytest.raises(ValidationError, match="frozen"):
        snapshot.anchor_price = Decimal("12")


def test_signal_rejects_float(project_root):
    payload = load_cases(project_root)["valid_open_space"]
    payload["initial_invalid_price"] = 10.69

    with pytest.raises(TypeError, match="float is forbidden"):
        StrategySignal.model_validate(payload)


def test_generated_at_accepts_timezone_aware_datetime(project_root):
    payload = load_cases(project_root)["valid_open_space"]
    payload["generated_at"] = datetime(2024, 1, 5, 8, 10, tzinfo=timezone.utc)

    assert StrategySignal.model_validate(payload).generated_at.utcoffset() is not None


def test_is_entry_candidate_cannot_be_supplied_by_caller(project_root):
    payload = load_cases(project_root)["valid_open_space"]
    payload["is_entry_candidate"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StrategySignal.model_validate(payload)
