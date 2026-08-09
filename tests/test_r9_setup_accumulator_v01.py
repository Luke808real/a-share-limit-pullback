"""Synthetic tests for the minimal prospective R9 setup accumulator."""

from __future__ import annotations

import csv
from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))

import r9_population_generator_v01 as population  # noqa: E402
import r9_protocol_v02 as protocol  # noqa: E402
import r9_setup_accumulator_v01 as accumulator  # noqa: E402
from limit_pullback.models.enums import DataQuality, SetupStage  # noqa: E402
from limit_pullback.strategy.engine import make_setup_id  # noqa: E402


pytestmark = pytest.mark.cloud_ci


def _hash(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _candidate(
    as_of: date,
    *,
    stage: SetupStage = SetupStage.B1_READY,
) -> population.DailySetupInput:
    anchor_date = date(2026, 8, 3)
    anchor_price = Decimal("11.00")
    price_tick = Decimal("0.01")
    return population.DailySetupInput(
        setup_id=make_setup_id("600000", anchor_date, anchor_price, price_tick),
        symbol="600000",
        state_as_of=as_of,
        anchor_date=anchor_date,
        anchor_price=anchor_price,
        setup_stage=stage,
        invalid_price=Decimal("10.00"),
        s1_price=Decimal("12.00"),
        data_quality=DataQuality.OK,
        price_tick=price_tick,
    )


class _Source:
    def __init__(self, daily: population.DailyPITSlice):
        self.daily = daily
        self.requests: list[date] = []

    def daily_slice(self, *, as_of: date) -> population.DailyPITSlice:
        self.requests.append(as_of)
        return self.daily


def _inputs(
    as_of: date = date(2026, 8, 10),
    *,
    stage: SetupStage = SetupStage.B1_READY,
    factor_overrides: dict[str, Decimal | int | float] | None = None,
):
    candidate = _candidate(as_of, stage=stage)
    source_manifest_hash = _hash(f"manifest:{as_of.isoformat()}:{stage.value}")
    daily = population.DailyPITSlice(
        as_of=as_of,
        daily_coverage_through=as_of,
        limit_pool_coverage_through=as_of,
        source_manifest_hash=source_manifest_hash,
        candidates=(candidate,),
    )
    factors: dict[str, Decimal | int | float] = {
        "B4": 1,
        "B5": 0,
        "B6": 1,
        "B7": 0,
        "median_range_ratio": Decimal("0.40"),
        "quiet_days_n": 2,
    }
    factors.update(factor_overrides or {})
    bundle = accumulator.ProspectiveFactorBundle(
        setup_id=candidate.setup_id,
        candidate_date=as_of,
        source_manifest_hash=source_manifest_hash,
        **factors,
    )
    return candidate, bundle, _Source(daily)


def _run(
    as_of: date = date(2026, 8, 10),
    *,
    stage: SetupStage = SetupStage.B1_READY,
    factor_overrides: dict[str, Decimal | int | float] | None = None,
):
    candidate, bundle, source = _inputs(
        as_of,
        stage=stage,
        factor_overrides=factor_overrides,
    )
    result = accumulator.accumulate_setup_ledger(
        as_of=as_of,
        daily_source=source,
        factor_bundles={bundle.identity_key: bundle},
    )
    return result, candidate, bundle, source


def test_synthetic_first_row_reuses_gate2a_and_all_frozen_scores():
    result, candidate, bundle, source = _run()
    assert source.requests == [date(2026, 8, 10)]
    assert result.status_by_observation == {
        f"{candidate.setup_id}:20260810": "APPEND",
    }
    assert len(result.rows) == 1
    row = result.rows[0]
    assert tuple(row) == protocol.SETUP_LEDGER_COLUMNS
    assert row["setup_id"] == candidate.setup_id
    assert row["candidate_date"] == date(2026, 8, 10)
    assert row["setup_status"] == "ACTIVE"
    assert row["activation_status"] == "PENDING"
    assert row["event_id"] is None
    values = {
        field: Decimal(str(getattr(bundle, field)))
        for field in accumulator.FACTOR_FIELDS
    }
    for model_id in ("M0", "M1", "M2"):
        assert Decimal(str(row[f"{model_id}_score"])) == protocol.frozen_daily_score(
            model_id,
            values,
        )


def test_b2_confirmed_initial_row_is_preobserved_activation():
    result, _, _, _ = _run(stage=SetupStage.B2_CONFIRMED)
    row = result.rows[0]
    assert row["activation_status"] == "PREOBSERVED_ACTIVATION"
    assert row["intraday_primary_eligible"] is False
    assert row["intraday_ineligible_reason"] == "PREOBSERVED_ACTIVATION"
    assert row["event_id"] is None


def test_ttl_end_and_after_expiry_lifecycle_are_frozen():
    ttl_end, _, _, _ = _run(as_of=date(2026, 8, 12))
    assert ttl_end.rows[0]["activation_status"] == "NO_ACTIVATION_WITHIN_TTL"
    assert ttl_end.rows[0]["setup_status"] == "NO_ACTIVATION_WITHIN_TTL"
    assert ttl_end.rows[0]["event_id"] is None

    after_expiry, _, _, _ = _run(as_of=date(2026, 8, 13))
    assert after_expiry.rows[0]["activation_status"] == "NOT_ACTIVE_AFTER_ADMINISTRATIVE_EXPIRY"
    assert after_expiry.rows[0]["r9_active_population"] is False
    assert after_expiry.rows[0]["event_id"] is None


def test_pre_oos_candidate_is_rejected_before_serialization():
    with pytest.raises(protocol.ProtocolBlocked):
        _run(as_of=date(2026, 8, 9))


def test_first_observation_is_append_only_and_preserved():
    first, first_candidate, first_bundle, first_source = _run()
    first_observation = population.generate_setups(
        as_of=date(2026, 8, 10),
        daily_source=first_source,
    )[0]
    later_candidate, later_bundle, later_source = _inputs(date(2026, 8, 11))
    later = accumulator.accumulate_setup_ledger(
        as_of=date(2026, 8, 11),
        daily_source=later_source,
        factor_bundles={later_bundle.identity_key: later_bundle},
        existing_observations={first_candidate.setup_id: first_observation},
    )
    assert later.status_by_observation == {
        f"{later_candidate.setup_id}:20260811": "PRESERVE_FIRST",
    }
    assert later.rows == ()

    rerun = accumulator.accumulate_setup_ledger(
        as_of=date(2026, 8, 10),
        daily_source=first_source,
        factor_bundles={first_bundle.identity_key: first_bundle},
        existing_observations={first_candidate.setup_id: first_observation},
        existing_feature_hashes=dict(first.feature_hashes),
    )
    assert rerun.status_by_observation == {
        f"{first_candidate.setup_id}:20260810": "ALREADY_RECORDED",
    }
    assert rerun.rows == ()

    earlier_candidate, earlier_bundle, earlier_source = _inputs(date(2026, 8, 9))
    with pytest.raises(population.PopulationGeneratorBlocked, match="FIRST_ELIGIBLE_OBSERVATION_DRIFT"):
        accumulator.accumulate_setup_ledger(
            as_of=date(2026, 8, 9),
            daily_source=earlier_source,
            factor_bundles={earlier_bundle.identity_key: earlier_bundle},
            existing_observations={first_candidate.setup_id: first_observation},
        )


def test_feature_payload_drift_and_source_mismatch_fail_closed():
    first, candidate, bundle, _ = _run()
    _, changed_bundle, changed_source = _inputs(
        factor_overrides={"B4": 0},
    )
    with pytest.raises(accumulator.SetupAccumulatorBlocked, match="BLOCKED_FEATURE_DRIFT"):
        accumulator.accumulate_setup_ledger(
            as_of=date(2026, 8, 10),
            daily_source=changed_source,
            factor_bundles={changed_bundle.identity_key: changed_bundle},
            existing_feature_hashes=dict(first.feature_hashes),
        )

    wrong_manifest = _hash("wrong-factor-manifest")
    wrong_bundle = replace(bundle, source_manifest_hash=wrong_manifest)
    _, _, wrong_source = _inputs()
    with pytest.raises(
        accumulator.SetupAccumulatorBlocked,
        match="BLOCKED_SETUP_SOURCE_RECONCILIATION",
    ):
        accumulator.accumulate_setup_ledger(
            as_of=date(2026, 8, 10),
            daily_source=wrong_source,
            factor_bundles={wrong_bundle.identity_key: wrong_bundle},
        )


def test_schema_hash_and_atomic_publication_are_deterministic(tmp_path):
    result, _, _, _ = _run()
    payload_a = accumulator.serialize_setup_ledger_rows(result.rows)
    payload_b = accumulator.serialize_setup_ledger_rows(tuple(reversed(result.rows)))
    assert payload_a == payload_b
    assert hashlib.sha256(payload_a).hexdigest() == hashlib.sha256(payload_b).hexdigest()
    assert list(csv.reader(payload_a.decode("utf-8").splitlines()))[0] == list(
        protocol.SETUP_LEDGER_COLUMNS
    )
    parsed = list(csv.DictReader(payload_a.decode("utf-8").splitlines()))[0]
    assert parsed["event_id"] == ""
    assert all(
        parsed[field] in {"0", "1"}
        for field in accumulator.BENCHMARK_SIGNAL_FIELDS
    )

    destination = tmp_path / "r9_setup_ledger_v01.csv"
    digest = accumulator.publish_setup_ledger(destination, result.rows)
    assert digest == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert str(destination).startswith(str(tmp_path))
    with pytest.raises(protocol.ProtocolBlocked, match="append-only"):
        accumulator.publish_setup_ledger(destination, result.rows)


def test_v04_descendant_write_authority_is_real_and_outcome_blind():
    receipt = protocol.require_r9_accumulation_write_authority()
    assert receipt.tag == "r9-protocol-freeze-v04"
    source = Path(accumulator.__file__).read_text()
    assert "extract_daily_factors_v01" not in source
    assert "CASE_SET" not in source
    assert "SUCCESS" not in source
    assert "FAILED" not in source


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("B4", Decimal("0.25")),
        ("B5", Decimal("-1")),
        ("B6", Decimal("2")),
        ("B7", Decimal("0.5")),
        ("B4", float("nan")),
        ("B5", float("inf")),
        ("B6", float("-inf")),
    ],
)
def test_non_binary_benchmark_signals_fail_closed(field, value):
    with pytest.raises(
        accumulator.SetupAccumulatorBlocked,
        match="STATUS=BLOCKED_FACTOR_DOMAIN",
    ):
        _run(factor_overrides={field: value})


@pytest.mark.parametrize("field", accumulator.BENCHMARK_SIGNAL_FIELDS)
def test_boolean_benchmark_signals_fail_closed(field):
    with pytest.raises(
        accumulator.SetupAccumulatorBlocked,
        match="STATUS=BLOCKED_FACTOR_DOMAIN",
    ):
        _run(factor_overrides={field: True})


@pytest.mark.parametrize(
    "value",
    [0, 1, Decimal("0"), Decimal("1"), 0.0, 1.0],
)
def test_binary_benchmark_signal_representations_are_accepted(value):
    result, _, _, _ = _run(
        factor_overrides={
            field: value for field in accumulator.BENCHMARK_SIGNAL_FIELDS
        }
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert all(
        row[field] in {"0", "1"}
        for field in accumulator.BENCHMARK_SIGNAL_FIELDS
    )
