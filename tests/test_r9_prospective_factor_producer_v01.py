"""Bounded PIT tests for the prospective R9 six-factor producer."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import inspect
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))

import extract_daily_factors_v01 as r2_formulas  # noqa: E402
import r5b_benchmark_execution_v01 as r5b  # noqa: E402
import r9_population_generator_v01 as population  # noqa: E402
import r9_prospective_factor_producer_v01 as producer  # noqa: E402
import r9_setup_accumulator_v01 as accumulator  # noqa: E402
from limit_pullback.models.enums import DataQuality, SetupStage  # noqa: E402
from limit_pullback.strategy.engine import make_setup_id  # noqa: E402


pytestmark = pytest.mark.cloud_ci

AS_OF = date(2026, 8, 10)
ANCHOR = date(2026, 8, 5)
SYMBOLS = ("600000",)


def _hash(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _candidate(symbol: str, anchor_date: date) -> population.DailySetupInput:
    anchor_price = Decimal("11.00") if symbol == "600000" else Decimal("12.00")
    return population.DailySetupInput(
        setup_id=make_setup_id(symbol, anchor_date, anchor_price, Decimal("0.01")),
        symbol=symbol,
        state_as_of=AS_OF,
        anchor_date=anchor_date,
        anchor_price=anchor_price,
        setup_stage=SetupStage.B1_READY,
        invalid_price=Decimal("10.00"),
        s1_price=Decimal("12.00"),
        data_quality=DataQuality.OK,
        price_tick=Decimal("0.01"),
    )


def _base_bars(symbol: str) -> tuple[producer.PITDailyBar, ...]:
    dates = tuple(date(2026, 8, day) for day in range(1, 11))
    closes = (
        Decimal("10.00"), Decimal("10.20"), Decimal("10.40"),
        Decimal("10.60"), Decimal("11.00"), Decimal("10.90"),
        Decimal("10.80"), Decimal("10.70"), Decimal("10.60"),
        Decimal("11.40"),
    )
    highs = (
        Decimal("10.20"), Decimal("10.40"), Decimal("10.60"),
        Decimal("10.80"), Decimal("11.10"), Decimal("11.00"),
        Decimal("10.90"), Decimal("10.80"), Decimal("10.70"),
        Decimal("11.60"),
    )
    lows = (
        Decimal("9.80"), Decimal("10.00"), Decimal("10.20"),
        Decimal("10.40"), Decimal("10.80"), Decimal("10.70"),
        Decimal("10.60"), Decimal("10.50"), Decimal("10.40"),
        Decimal("11.00"),
    )
    volumes = (100, 110, 120, 130, 140, 100, 90, 80, 100, 112)
    rows = []
    for i, trade_date in enumerate(dates):
        preclose = closes[i - 1] if i else Decimal("9.70")
        rows.append(producer.PITDailyBar(
            symbol=symbol,
            trade_date=trade_date,
            high=highs[i],
            low=lows[i],
            close=closes[i],
            preclose=preclose,
            volume=volumes[i],
        ))
    return tuple(rows)


def _base_adjustments(symbol: str) -> tuple[producer.PITAdjustmentFactor, ...]:
    return tuple(
        producer.PITAdjustmentFactor(symbol, date(2026, 8, day), Decimal("1"))
        for day in range(1, 11)
    )


class _SliceSource:
    def __init__(self, daily: population.DailyPITSlice):
        self.daily = daily

    def daily_slice(self, *, as_of: date) -> population.DailyPITSlice:
        assert as_of == self.daily.as_of
        return self.daily


def _package(
    *,
    anchor_date: date = ANCHOR,
    symbols: tuple[str, ...] = SYMBOLS,
    daily_bars: tuple[producer.PITDailyBar, ...] | None = None,
    adjustment_factors: tuple[producer.PITAdjustmentFactor, ...] | None = None,
    daily_coverage_through: date = AS_OF,
    factor_coverage_through: date = AS_OF,
) -> producer.PITFactorInput:
    if daily_bars is None:
        daily_bars = tuple(row for symbol in symbols for row in _base_bars(symbol))
    if adjustment_factors is None:
        adjustment_factors = tuple(
            row for symbol in symbols for row in _base_adjustments(symbol)
        )
    daily_hash = producer.canonical_daily_bar_prefix_hash(daily_bars)
    adjustment_hash = producer.canonical_adjustment_factor_prefix_hash(
        adjustment_factors
    )
    manifest = producer.build_source_manifest_hash(
        as_of=AS_OF,
        daily_coverage_through=daily_coverage_through,
        factor_coverage_through=factor_coverage_through,
        candidate_state_source_hash=_hash("candidate-state"),
        limit_pool_source_hash=_hash("limit-pool"),
        daily_bar_prefix_hash=daily_hash,
        adjustment_factor_prefix_hash=adjustment_hash,
        configuration_version_hash=_hash("configuration-v01"),
        source_vintage="synthetic-pit-v01",
    )
    candidates = tuple(_candidate(symbol, anchor_date) for symbol in symbols)
    daily = population.DailyPITSlice(
        as_of=AS_OF,
        daily_coverage_through=AS_OF,
        limit_pool_coverage_through=AS_OF,
        source_manifest_hash=manifest,
        candidates=candidates,
    )
    observations = population.generate_setups(
        as_of=AS_OF,
        daily_source=_SliceSource(daily),
    )
    return producer.PITFactorInput(
        as_of=AS_OF,
        daily_coverage_through=daily_coverage_through,
        factor_coverage_through=factor_coverage_through,
        candidate_state_source_hash=_hash("candidate-state"),
        limit_pool_source_hash=_hash("limit-pool"),
        daily_bar_prefix_hash=daily_hash,
        adjustment_factor_prefix_hash=adjustment_hash,
        configuration_version_hash=_hash("configuration-v01"),
        source_vintage="synthetic-pit-v01",
        source_manifest_hash=manifest,
        gate2a_slice=daily,
        gate2a_observations=observations,
        daily_bars=daily_bars,
        adjustment_factors=adjustment_factors,
    )


def _bundle(package: producer.PITFactorInput):
    bundles = producer.produce_prospective_factor_bundles(package)
    assert len(bundles) == len(package.gate2a_observations)
    return bundles[0]


def _replace_bar(
    rows: tuple[producer.PITDailyBar, ...],
    trade_date: date,
    **changes: object,
) -> tuple[producer.PITDailyBar, ...]:
    return tuple(
        replace(row, **changes) if row.trade_date == trade_date else row
        for row in rows
    )


def test_pit_manifest_binds_gate2a_and_all_components():
    package = _package()
    observation = package.gate2a_observations[0]
    bundle = _bundle(package)
    assert package.source_manifest_hash == package.gate2a_slice.source_manifest_hash
    assert observation.source_manifest_hash == package.source_manifest_hash
    assert bundle.source_manifest_hash == package.source_manifest_hash
    assert bundle.identity_key == (
        observation.setup_id,
        observation.candidate_date,
        observation.source_manifest_hash,
    )
    assert tuple(bundle.__dataclass_fields__) == (
        "setup_id", "candidate_date", "source_manifest_hash", "B4", "B5",
        "B6", "B7", "median_range_ratio", "quiet_days_n",
    )


@pytest.mark.parametrize(
    ("anchor_date", "expected"),
    [
        (date(2026, 8, 8), Decimal("1")),
        (date(2026, 8, 9), Decimal("0")),
        (date(2026, 8, 5), Decimal("1")),
        (date(2026, 8, 4), Decimal("0")),
    ],
)
def test_b4_uses_canonical_session_offset(anchor_date, expected):
    assert _bundle(_package(anchor_date=anchor_date)).B4 == expected


def test_b5_exact_boundary_is_signal():
    bars = _base_bars("600000")
    bars = _replace_bar(bars, AS_OF, close=Decimal("10.56"))
    assert _bundle(_package(daily_bars=bars)).B5 == Decimal("1")


def test_b6_exact_boundary_is_signal():
    bars = _base_bars("600000")
    bars = _replace_bar(bars, AS_OF, volume=Decimal("119.0"))
    assert _bundle(_package(daily_bars=bars)).B6 == Decimal("1")


def test_r5_ca_event_blocks_the_whole_daily_run():
    bars = _base_bars("600000")
    bars = _replace_bar(bars, AS_OF, preclose=Decimal("10.706"))
    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match="BLOCKED_PROSPECTIVE_FACTOR_UNAVAILABLE.*CA_EVENT_D",
    ):
        _bundle(_package(daily_bars=bars))


def test_b7_is_strictly_greater_than_reference_high():
    bars = _base_bars("600000")
    reference = max(row.high for row in bars if row.trade_date < ANCHOR)
    equal = _replace_bar(bars, AS_OF, close=reference)
    greater = _replace_bar(bars, AS_OF, close=reference + Decimal("0.0001"))
    assert _bundle(_package(daily_bars=equal)).B7 == Decimal("0")
    assert _bundle(_package(daily_bars=greater)).B7 == Decimal("1")


def test_r5_pure_signal_parity_and_binary_output():
    package = _package()
    bundle = _bundle(package)
    observation = package.gate2a_observations[0]
    bars = tuple(sorted(package.daily_bars, key=lambda row: row.trade_date))
    i0 = [row.trade_date for row in bars].index(observation.anchor_date)
    iD = [row.trade_date for row in bars].index(observation.candidate_date)
    t0, dbar = bars[i0], bars[iD]
    _, expected_b4 = r5b.b4_signal(pd.Series([iD - i0]))
    expected_b5 = r5b.b5_signal(float(t0.close), float(dbar.close))
    expected_b6 = r5b.b6_signal(float(t0.volume), float(dbar.volume))
    expected_b7 = r5b.b7_reference_high(
        np.array([float(row.high) for row in bars[:i0]])
    )
    assert bundle.B4 == Decimal(int(expected_b4.iloc[0]))
    assert bundle.B5 == Decimal(int(expected_b5))
    assert bundle.B6 == Decimal(int(expected_b6))
    assert bundle.B7 == Decimal(int(float(dbar.close) > expected_b7))
    assert all(
        getattr(bundle, field) in {Decimal("0"), Decimal("1")}
        for field in ("B4", "B5", "B6", "B7")
    )


@pytest.mark.parametrize(
    "anchor_date",
    [date(2026, 8, 5), date(2026, 8, 9), date(2026, 8, 7), date(2026, 8, 6)],
)
def test_r2_median_and_quiet_formula_parity(anchor_date):
    package = _package(anchor_date=anchor_date)
    bundle = _bundle(package)
    observation = package.gate2a_observations[0]
    bars = tuple(sorted(package.daily_bars, key=lambda row: row.trade_date))
    dates = [row.trade_date for row in bars]
    context = producer._r2_context(
        observation=observation,
        bars=bars,
        i0=dates.index(observation.anchor_date),
        iD=dates.index(observation.candidate_date),
        adjustments={"600000": {
            row.trade_date: Decimal(str(row.adj_factor))
            for row in package.adjustment_factors
        }},
    )
    assert bundle.median_range_ratio == (
        r2_formulas.f_median_range_ratio(context).value
    )
    assert bundle.quiet_days_n == r2_formulas.f_quiet_days_n(context).value


def test_r2_boundary_contraction_formula_parity():
    bars = list(_base_bars("600000"))
    t0 = bars[4]
    t0_range = (t0.high - t0.low) / t0.preclose
    boundary_low = Decimal("11.00") - t0_range * Decimal("11.00")
    bars = list(_replace_bar(
        tuple(bars),
        date(2026, 8, 6),
        high=Decimal("11.00"),
        low=boundary_low,
    ))
    package = _package(daily_bars=tuple(bars))
    bundle = _bundle(package)
    observation = package.gate2a_observations[0]
    ordered = tuple(sorted(package.daily_bars, key=lambda row: row.trade_date))
    dates = [row.trade_date for row in ordered]
    context = producer._r2_context(
        observation=observation,
        bars=ordered,
        i0=dates.index(observation.anchor_date),
        iD=dates.index(observation.candidate_date),
        adjustments={"600000": {
            row.trade_date: Decimal(str(row.adj_factor))
            for row in package.adjustment_factors
        }},
    )
    assert bundle.median_range_ratio == (
        r2_formulas.f_median_range_ratio(context).value
    )
    assert bundle.quiet_days_n == r2_formulas.f_quiet_days_n(context).value


def test_ca_event_and_unknown_fail_closed_without_population_drop():
    adjustments = list(_base_adjustments("600000"))
    adjustments[6] = replace(adjustments[6], adj_factor=Decimal("2"))
    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match="BLOCKED_PROSPECTIVE_FACTOR_UNAVAILABLE.*CORPORATE_ACTION_EVENT",
    ):
        _bundle(_package(adjustment_factors=tuple(adjustments)))

    missing = tuple(row for i, row in enumerate(_base_adjustments("600000")) if i != 6)
    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match="BLOCKED_PROSPECTIVE_FACTOR_UNAVAILABLE.*CORPORATE_ACTION_UNKNOWN",
    ):
        _bundle(_package(adjustment_factors=missing))


def test_missing_factor_fails_the_entire_daily_run():
    bars = tuple(
        row for row in _base_bars("600000") if row.trade_date != AS_OF
    ) + tuple(_base_bars("600001"))
    package = _package(symbols=("600000", "600001"), daily_bars=bars)
    missing_setup = package.gate2a_slice.candidates[0].setup_id
    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match=f"BLOCKED_PROSPECTIVE_FACTOR_UNAVAILABLE.*{missing_setup}",
    ):
        producer.produce_prospective_factor_bundles(package)


def test_gate2a_to_accumulator_integration_is_one_to_one_and_deterministic():
    package = _package(symbols=("600000", "600001"))
    bundles_a = producer.produce_prospective_factor_bundles(package)
    bundles_b = producer.produce_prospective_factor_bundles(package)
    assert bundles_a == bundles_b
    mapping = producer.factor_bundle_mapping(bundles_a)
    result = accumulator.accumulate_setup_ledger(
        as_of=AS_OF,
        daily_source=_SliceSource(package.gate2a_slice),
        factor_bundles=mapping,
    )
    assert len(result.rows) == len(package.gate2a_observations) == 2
    assert {
        row["source_manifest_hash"] for row in result.rows
    } == {package.source_manifest_hash}
    assert accumulator.serialize_setup_ledger_rows(result.rows) == (
        accumulator.serialize_setup_ledger_rows(tuple(reversed(result.rows)))
    )


def test_future_data_and_coverage_drift_are_blocked():
    package = _package()
    future_bar = producer.PITDailyBar(
        "600000", AS_OF + timedelta(days=1), 1, 1, 1, 1, 1,
    )
    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match="STATUS=BLOCKED_FUTURE_DATA",
    ):
        replace(package, daily_bars=package.daily_bars + (future_bar,))

    future_adj = producer.PITAdjustmentFactor(
        "600000", AS_OF + timedelta(days=1), Decimal("1"),
    )
    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match="STATUS=BLOCKED_FUTURE_DATA",
    ):
        replace(
            package,
            adjustment_factors=package.adjustment_factors + (future_adj,),
        )

    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match="STATUS=BLOCKED_FUTURE_DATA",
    ):
        replace(package, factor_coverage_through=AS_OF + timedelta(days=1))


def test_candidate_date_and_manifest_drift_fail_closed():
    package = _package()
    bad_observation = replace(
        package.gate2a_observations[0],
        candidate_date=AS_OF + timedelta(days=1),
    )
    bad_package = replace(package, gate2a_observations=(bad_observation,))
    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match="STATUS=BLOCKED_CANDIDATE_DATE_MISMATCH",
    ):
        producer.produce_prospective_factor_bundles(bad_package)

    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match="STATUS=BLOCKED_MANIFEST_MISMATCH",
    ):
        replace(package, source_manifest_hash=_hash("different-manifest"))

    changed_bars = _replace_bar(
        package.daily_bars,
        AS_OF,
        close=Decimal("11.41"),
    )
    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match="STATUS=BLOCKED_MANIFEST_MISMATCH",
    ):
        replace(package, daily_bars=changed_bars)


def test_producer_api_is_label_free_and_has_no_runtime_loader_dependency():
    source = Path(producer.__file__).read_text()
    for forbidden in (
        "SUCCESS",
        "FAILED",
        "outcome_3d",
        "outcome_5d",
        "CASE_SET",
    ):
        assert forbidden not in source
    assert "input_gate" not in source
    assert "load_cases" not in source
    assert "load_adj_factors" not in source
    assert "load_canonical" not in source
    assert "r9_setup_accumulator_v01" in inspect.getsource(producer)
