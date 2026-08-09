"""Targeted Gate 2A population-generator contract tests."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))

import r9_population_forensics_v01 as forensic  # noqa: E402
import r9_population_generator_v01 as generator  # noqa: E402
from limit_pullback.models.enums import DataQuality, SetupStage  # noqa: E402
from limit_pullback.strategy.engine import make_setup_id  # noqa: E402


pytestmark = pytest.mark.cloud_ci


CORRECTED_EPISODES_SHA256 = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
FIXED_THREE_WEEK_P0_SHA256 = "35b09cc262377db5df891a4478ccead95fe44fc6ce7e12080fe713ed28e9a473"
FIXED_THREE_WEEK_P1_SHA256 = "276576fa752a66ed98880ae39a93c9c598cd2f77e3e747edf2a5551cf440544d"


def _hash(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _input(
    *,
    symbol: str = "600000",
    state_as_of: date = date(2026, 8, 10),
    anchor_date: date = date(2026, 8, 3),
    anchor_price: Decimal = Decimal("11.00"),
    setup_stage: SetupStage | str = SetupStage.B1_READY,
    invalid_price: Decimal | None = Decimal("10.00"),
    s1_price: Decimal | None = Decimal("12.00"),
    data_quality: DataQuality | str = DataQuality.OK,
    price_tick: Decimal = Decimal("0.01"),
) -> generator.DailySetupInput:
    normalized = str(symbol).zfill(6)
    return generator.DailySetupInput(
        setup_id=make_setup_id(normalized, anchor_date, anchor_price, price_tick),
        symbol=normalized,
        state_as_of=state_as_of,
        anchor_date=anchor_date,
        anchor_price=anchor_price,
        setup_stage=setup_stage,
        invalid_price=invalid_price,
        s1_price=s1_price,
        data_quality=data_quality,
        price_tick=price_tick,
    )


class _Source:
    def __init__(self, slices: dict[date, generator.DailyPITSlice]):
        self.slices = slices
        self.requests: list[date] = []

    def daily_slice(self, *, as_of: date) -> generator.DailyPITSlice:
        self.requests.append(as_of)
        return self.slices[as_of]


def _slice(
    as_of: date,
    *candidates: generator.DailySetupInput,
    seed: str | None = None,
) -> generator.DailyPITSlice:
    return generator.DailyPITSlice(
        as_of=as_of,
        daily_coverage_through=as_of,
        limit_pool_coverage_through=as_of,
        source_manifest_hash=_hash(seed or as_of.isoformat()),
        candidates=tuple(candidates),
    )


def _serialized(rows: tuple[generator.ProspectiveObservation, ...]) -> bytes:
    return json.dumps(
        [row.canonical_record() for row in rows],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_maturity_before_dedup_changes_historical_identity_but_not_p0_or_p1():
    d1, d2 = date(2026, 7, 20), date(2026, 7, 21)
    setup_id = "600000:20260701:1100"
    episodes = pd.DataFrame({
        "code": ["600000", "600000"],
        "setup_id": [setup_id, setup_id],
        "setup_stage": ["B1_READY", "B2_READY"],
        "signal_date": [d1, d2],
        "anchor_date": [date(2026, 7, 1), date(2026, 7, 1)],
        "anchor_price": [Decimal("11.00"), Decimal("11.00")],
        "invalid_price": [Decimal("10.00"), Decimal("10.00")],
        "s1_price": [Decimal("12.00"), Decimal("12.00")],
        "data_quality": ["OK", "OK"],
        "future_sessions_available": [2, 3],
    })
    p0 = forensic.p0_raw_pit_observations(episodes)
    p1 = forensic.p1_prospective_first_observation(p0)
    historical = forensic.historical_maturity_then_first(episodes)
    assert list(p0["candidate_date"]) == [d1, d2]
    assert list(p1["candidate_date"]) == [d1]
    assert list(historical["candidate_date"]) == [d2]

    changed = episodes.copy()
    changed.loc[0, "future_sessions_available"] = 3
    pd.testing.assert_frame_equal(forensic.p0_raw_pit_observations(changed), p0)
    pd.testing.assert_frame_equal(
        forensic.p1_prospective_first_observation(
            forensic.p0_raw_pit_observations(changed)
        ),
        p1,
    )
    assert list(forensic.historical_maturity_then_first(changed)["candidate_date"]) == [d1]


def test_generator_uses_only_the_requested_daily_slice_and_future_rows_are_irrelevant():
    as_of = date(2026, 8, 10)
    eligible = _input()
    original = _Source({
        as_of - timedelta(days=2): _slice(as_of - timedelta(days=2), seed="d-2"),
        as_of - timedelta(days=1): _slice(as_of - timedelta(days=1), seed="d-1"),
        as_of: _slice(as_of, eligible, seed="prefix-through-d"),
        as_of + timedelta(days=1): _slice(
            as_of + timedelta(days=1), _input(symbol="600001"), seed="d+1-original",
        ),
        as_of + timedelta(days=2): _slice(
            as_of + timedelta(days=2), _input(symbol="600002"), seed="d+2-original",
        ),
    })
    before = generator.generate_setups(as_of=as_of, daily_source=original)
    assert original.requests == [as_of]

    changed = _Source({
        as_of - timedelta(days=2): original.slices[as_of - timedelta(days=2)],
        as_of - timedelta(days=1): original.slices[as_of - timedelta(days=1)],
        as_of: original.slices[as_of],
        as_of + timedelta(days=1): _slice(as_of + timedelta(days=1), seed="deleted-d+1"),
        as_of + timedelta(days=2): _slice(
            as_of + timedelta(days=2), _input(symbol="000001", anchor_price=Decimal("8.88")),
            seed="modified-d+2",
        ),
    })
    after = generator.generate_setups(as_of=as_of, daily_source=changed)
    assert changed.requests == [as_of]
    assert _serialized(before) == _serialized(after)

    wrong_session = _Source({
        as_of: _slice(as_of + timedelta(days=1), eligible, seed="wrong-session"),
    })
    with pytest.raises(generator.PopulationGeneratorBlocked, match="different as_of"):
        generator.generate_setups(as_of=as_of, daily_source=wrong_session)


def test_candidate_state_anchor_and_source_coverage_cannot_be_after_as_of():
    as_of = date(2026, 8, 10)
    future_anchor = _input(anchor_date=as_of + timedelta(days=1), state_as_of=as_of)
    with pytest.raises(generator.PopulationGeneratorBlocked, match="anchor date cannot be after as_of"):
        generator.generate_setups(
            as_of=as_of,
            daily_source=_Source({as_of: _slice(as_of, future_anchor)}),
        )
    stale = _input(state_as_of=as_of - timedelta(days=1))
    with pytest.raises(generator.PopulationGeneratorBlocked, match="state was not computed at as_of"):
        generator.generate_setups(
            as_of=as_of,
            daily_source=_Source({as_of: _slice(as_of, stale)}),
        )
    incomplete_coverage = generator.DailyPITSlice(
        as_of=as_of,
        daily_coverage_through=as_of - timedelta(days=1),
        limit_pool_coverage_through=as_of,
        source_manifest_hash=_hash("incomplete-coverage"),
        candidates=(_input(state_as_of=as_of),),
    )
    with pytest.raises(generator.PopulationGeneratorBlocked, match="coverage does not reach as_of"):
        generator.generate_setups(
            as_of=as_of,
            daily_source=_Source({as_of: incomplete_coverage}),
        )
    incomplete_pool_coverage = replace(
        incomplete_coverage,
        daily_coverage_through=as_of,
        limit_pool_coverage_through=as_of - timedelta(days=1),
    )
    with pytest.raises(generator.PopulationGeneratorBlocked, match="limit-pool coverage does not reach as_of"):
        generator.generate_setups(
            as_of=as_of,
            daily_source=_Source({as_of: incomplete_pool_coverage}),
        )


def test_generator_has_no_outcome_or_persistence_dependency():
    source = Path(generator.__file__).read_text()
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    prohibited_import_fragments = (
        "outcome",
        "success_control",
        "trade_plan",
        "screen.generation",
        "replay",
        "pandas",
        "pyarrow",
    )
    assert not any(
        fragment in module
        for module in imported
        for fragment in prohibited_import_fragments
    )
    assert "future_sessions_available" not in source
    assert "event_date" not in source
    assert "success_control_cases" not in source
    io_call_names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not io_call_names & {"open", "read_text", "read_bytes", "read_parquet", "write_text", "write_bytes"}


def test_setup_and_observation_ids_are_authoritative_and_deterministic():
    as_of = date(2026, 8, 10)
    candidate = _input()
    rows = generator.generate_setups(
        as_of=as_of,
        daily_source=_Source({as_of: _slice(as_of, candidate)}),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.setup_id == make_setup_id("600000", date(2026, 8, 3), Decimal("11.00"))
    assert row.observation_id == f"{row.setup_id}:20260810"
    assert tuple(key for key in generator.OUTPUT_COLUMNS if key != "price_tick") == (
        "setup_id", "symbol", "anchor_date", "anchor_price", "candidate_date",
        "as_of", "generator_version", "source_manifest_hash",
    )

    changed_anchor = replace(candidate, anchor_price=Decimal("11.01"))
    with pytest.raises(generator.PopulationGeneratorBlocked, match="authoritative engine key"):
        generator.generate_setups(
            as_of=as_of,
            daily_source=_Source({as_of: _slice(as_of, changed_anchor)}),
        )


def test_multi_day_observations_keep_first_eligible_row_immutable():
    d1, d2 = date(2026, 8, 10), date(2026, 8, 11)
    candidate = _input()
    source = _Source({
        d1: _slice(d1, candidate, seed="prefix-d1"),
        d2: _slice(d2, replace(candidate, state_as_of=d2), seed="prefix-d2"),
    })
    views = generator.bounded_replay(as_of_dates=(d1, d2), daily_source=source)
    assert [row.candidate_date for row in views.raw_pit_observations] == [d1, d2]
    assert [row.candidate_date for row in views.prospective_first_observations] == [d1]
    first, later = views.raw_pit_observations
    assert generator.append_first_eligible_observation({first.setup_id: first}, later) == "PRESERVE_FIRST"
    assert generator.append_first_eligible_observation({first.setup_id: first}, first) == "ALREADY_RECORDED"
    with pytest.raises(generator.PopulationGeneratorBlocked, match="payload drift"):
        generator.append_first_eligible_observation(
            {first.setup_id: first}, replace(first, source_manifest_hash=_hash("drift")),
        )
    earlier = replace(first, candidate_date=d1 - timedelta(days=1), as_of=d1 - timedelta(days=1))
    with pytest.raises(generator.PopulationGeneratorBlocked, match="FIRST_ELIGIBLE_OBSERVATION_DRIFT"):
        generator.append_first_eligible_observation({first.setup_id: first}, earlier)


def test_activation_is_not_a_population_filter_and_only_v01a_pit_fields_filter_rows():
    as_of = date(2026, 8, 10)
    candidates = (
        _input(),
        _input(symbol="600001", setup_stage=SetupStage.NORMAL),
        _input(symbol="600002", invalid_price=None),
        _input(symbol="600003", s1_price=None),
        _input(symbol="600004", data_quality=DataQuality.UNUSABLE),
    )
    rows = generator.generate_setups(
        as_of=as_of,
        daily_source=_Source({as_of: _slice(as_of, *candidates)}),
    )
    assert generator.ACTIVATION_REQUIRED_FOR_POPULATION is False
    assert [row.symbol for row in rows] == ["600000"]
    assert all("activation" not in row.canonical_record() for row in rows)


def test_bounded_replay_is_deterministic_and_rejects_duplicate_daily_setup():
    d1, d2 = date(2026, 8, 10), date(2026, 8, 11)
    first, second = _input(symbol="600000"), _input(symbol="600001")
    source_a = _Source({
        d1: _slice(d1, second, first, seed="d1"),
        d2: _slice(d2, replace(first, state_as_of=d2), seed="d2"),
    })
    source_b = _Source({
        d1: _slice(d1, first, second, seed="d1"),
        d2: _slice(d2, replace(first, state_as_of=d2), seed="d2"),
    })
    replay_a = generator.bounded_replay(as_of_dates=(d1, d2), daily_source=source_a)
    replay_b = generator.bounded_replay(as_of_dates=(d1, d2), daily_source=source_b)
    assert replay_a.raw_pit_hash == replay_b.raw_pit_hash
    assert replay_a.prospective_first_hash == replay_b.prospective_first_hash
    with pytest.raises(generator.PopulationGeneratorBlocked, match="strict and unique"):
        generator.bounded_replay(as_of_dates=(d2, d1), daily_source=source_a)
    duplicate = _Source({d1: _slice(d1, first, first)})
    with pytest.raises(generator.PopulationGeneratorBlocked, match="duplicate daily setup"):
        generator.generate_setups(as_of=d1, daily_source=duplicate)


class _FrozenEpisodesDailySource:
    """Read-only bounded fixture that exposes only one historical date at a time."""

    columns = [
        "code", "setup_id", "setup_stage", "signal_date", "anchor_date",
        "anchor_price", "invalid_price", "s1_price", "data_quality",
    ]

    def __init__(self, episodes_path: Path):
        self.episodes_path = episodes_path

    def daily_slice(self, *, as_of: date) -> generator.DailyPITSlice:
        cutoff = as_of.isoformat()
        prefix = pd.read_parquet(
            self.episodes_path,
            columns=self.columns,
            filters=[("signal_date", "<=", cutoff)],
        )
        daily = prefix[pd.to_datetime(prefix["signal_date"]).dt.date == as_of].copy()
        canonical_prefix = (
            prefix.assign(
                code=prefix["code"].astype(str).str.zfill(6),
                signal_date=pd.to_datetime(prefix["signal_date"]).dt.strftime("%Y-%m-%d"),
                anchor_date=pd.to_datetime(prefix["anchor_date"]).dt.strftime("%Y-%m-%d"),
            )
            .sort_values(["setup_id", "signal_date", "code"], kind="mergesort")
            .to_csv(index=False, lineterminator="\n")
        )
        candidates = tuple(
            generator.DailySetupInput(
                setup_id=str(row.setup_id),
                symbol=str(row.code).zfill(6),
                state_as_of=as_of,
                anchor_date=pd.Timestamp(row.anchor_date).date(),
                anchor_price=Decimal(str(row.anchor_price)),
                setup_stage=str(row.setup_stage),
                invalid_price=(None if pd.isna(row.invalid_price) else Decimal(str(row.invalid_price))),
                s1_price=(None if pd.isna(row.s1_price) else Decimal(str(row.s1_price))),
                data_quality=str(row.data_quality),
            )
            for row in daily.itertuples(index=False)
        )
        return generator.DailyPITSlice(
            as_of=as_of,
            daily_coverage_through=as_of,
            limit_pool_coverage_through=as_of,
            source_manifest_hash=hashlib.sha256(canonical_prefix.encode("utf-8")).hexdigest(),
            candidates=candidates,
        )


@pytest.mark.local_data
def test_fixed_three_week_local_replay_is_read_only_and_deterministic():
    episodes_path = (
        REPO_ROOT.parent / "V flash" / "data" / "outcome-study"
        / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
        / "corrected-b2-trigger-outcome"
        / "episodes.parquet"
    )
    if not episodes_path.exists():
        pytest.skip("local frozen episodes artifact is unavailable")
    with episodes_path.open("rb") as handle:
        assert hashlib.file_digest(handle, "sha256").hexdigest() == CORRECTED_EPISODES_SHA256
    source = _FrozenEpisodesDailySource(episodes_path)
    dates = forensic.fixed_three_week_dates()
    first = generator.bounded_replay(as_of_dates=dates, daily_source=source)
    second = generator.bounded_replay(as_of_dates=dates, daily_source=source)
    assert (len(first.raw_pit_observations), len(first.prospective_first_observations)) == (330, 216)
    assert first.raw_pit_hash == second.raw_pit_hash
    assert first.prospective_first_hash == second.prospective_first_hash
    assert first.raw_pit_hash == FIXED_THREE_WEEK_P0_SHA256
    assert first.prospective_first_hash == FIXED_THREE_WEEK_P1_SHA256
    assert all(row.candidate_date == row.as_of for row in first.raw_pit_observations)
