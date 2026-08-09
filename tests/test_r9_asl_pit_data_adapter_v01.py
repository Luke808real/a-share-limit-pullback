"""Cloud-safe and bounded local-data tests for the R9 ASL PIT adapter."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import hashlib
import os
from pathlib import Path
import sys
import tomllib

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))

import r9_asl_pit_data_adapter_v01 as adapter  # noqa: E402
import r9_population_generator_v01 as population  # noqa: E402
import r9_prospective_factor_producer_v01 as producer  # noqa: E402
from limit_pullback.models.enums import DataQuality, SetupStage  # noqa: E402
from limit_pullback.strategy.engine import make_setup_id  # noqa: E402


pytestmark = pytest.mark.cloud_ci

AS_OF = date(2026, 8, 10)
ANCHOR = date(2026, 8, 5)
HASH_A = hashlib.sha256(b"candidate-state").hexdigest()
HASH_B = hashlib.sha256(b"limit-pool").hexdigest()
HASH_C = hashlib.sha256(b"configuration").hexdigest()
PINNED_ASL_CHECKOUT = Path("/Users/luke808/AI/ashare-lake-r8-candidate")
KNOWN_ASL_ROOTS = (
    Path("/tmp/asl_phase1b_lake"),
    PINNED_ASL_CHECKOUT,
    Path("/Users/luke808/AI/asl-r8-5m-lake"),
)


class _FakeASLQuery:
    code_sha = adapter.ASL_CODE_SHA

    def __init__(self, daily: list[dict], adj: list[dict], *, code_sha: str | None = None):
        self.daily = daily
        self.adj = adj
        if code_sha is not None:
            self.code_sha = code_sha
        self.calls: list[tuple[str, dict[str, object]]] = []

    def load(self, dataset: str, **kwargs: object) -> object:
        self.calls.append((dataset, dict(kwargs)))
        if dataset == adapter.DAILY_DATASET:
            return list(self.daily)
        if dataset == adapter.ADJ_FACTOR_DATASET:
            return list(self.adj)
        raise AssertionError(dataset)


def _candidate(
    *,
    symbol: str = "600000",
    state_as_of: date = AS_OF,
    anchor_date: date = ANCHOR,
) -> population.DailySetupInput:
    anchor_price = Decimal("11.00") if symbol == "600000" else Decimal("12.00")
    return population.DailySetupInput(
        setup_id=make_setup_id(symbol, anchor_date, anchor_price, Decimal("0.01")),
        symbol=symbol,
        state_as_of=state_as_of,
        anchor_date=anchor_date,
        anchor_price=anchor_price,
        setup_stage=SetupStage.B1_READY,
        invalid_price=Decimal("10.00"),
        s1_price=Decimal("12.00"),
        data_quality=DataQuality.OK,
        price_tick=Decimal("0.01"),
    )


def _daily_rows(symbol: str = "600000.SH") -> list[dict]:
    closes = {
        1: "10.00",
        2: "10.10",
        3: "10.20",
        4: "10.30",
        5: "11.00",
        6: "10.90",
        7: "10.80",
        8: "10.70",
        9: "10.60",
        10: "10.50",
    }
    highs = {
        1: "10.10",
        2: "10.20",
        3: "10.30",
        4: "10.40",
        5: "12.00",
        6: "11.00",
        7: "10.95",
        8: "10.90",
        9: "10.80",
        10: "10.70",
    }
    lows = {
        1: "9.80",
        2: "9.90",
        3: "10.00",
        4: "10.10",
        5: "10.50",
        6: "10.60",
        7: "10.50",
        8: "10.40",
        9: "10.30",
        10: "10.20",
    }
    volumes = {day: str(220 - day * 10) for day in range(1, 11)}
    return [
        {
            "symbol": symbol,
            "trade_date": date(2026, 8, day),
            "open": closes[day],
            "high": highs[day],
            "low": lows[day],
            "close": closes[day],
            "volume": volumes[day],
            "amount": "1",
            "source": "fixture",
            "data_version": "fixture",
            "fetched_at": None,
        }
        for day in range(1, 11)
    ]


def _adj_rows(*, event_day: int = 1, factor: str = "1.0") -> list[dict]:
    return [
        {
            "symbol": "600000.SH",
            "trade_date": date(2026, 8, event_day),
            "adjust_type": "hfq",
            "factor": factor,
            "source": "fixture",
            "data_version": "fixture",
            "fetched_at": None,
        }
    ]


def _backend(
    *,
    daily: list[dict] | None = None,
    adj: list[dict] | None = None,
    code_sha: str | None = None,
) -> _FakeASLQuery:
    return _FakeASLQuery(
        _daily_rows() if daily is None else daily,
        _adj_rows() if adj is None else adj,
        code_sha=code_sha,
    )


def _build(
    backend: _FakeASLQuery,
    *,
    candidates: tuple[population.DailySetupInput, ...] = (_candidate(),),
    as_of: date = AS_OF,
    asl_code_sha: str = adapter.ASL_CODE_SHA,
) -> producer.PITFactorInput:
    return adapter.build_pit_factor_input(
        as_of=as_of,
        candidates=candidates,
        candidate_state_source_hash=HASH_A,
        limit_pool_source_hash=HASH_B,
        configuration_version_hash=HASH_C,
        query_backend=backend,
        asl_code_sha=asl_code_sha,
    )


def _candidate_asl_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    env_root = os.environ.get("R9_ASL_DATA_ROOT")
    if env_root:
        roots.append(Path(env_root).expanduser())
    config_path = PINNED_ASL_CHECKOUT / "configs" / "ashare-lake.toml"
    if config_path.exists():
        with config_path.open("rb") as handle:
            config = tomllib.load(handle)
        configured_root = config.get("data", {}).get("root")
        if configured_root:
            root = Path(str(configured_root)).expanduser()
            roots.append(root if root.is_absolute() else config_path.parent / root)
    roots.extend(KNOWN_ASL_ROOTS)
    return tuple(dict.fromkeys(root.resolve() for root in roots))


def _existing_asl_query_roots() -> tuple[Path, ...]:
    return tuple(
        root
        for root in _candidate_asl_roots()
        if (root / "curated" / "daily_bars").is_dir()
        and (root / "derived" / "adj_factors").is_dir()
    )


def test_query_is_lazy_symbol_bounded_and_uses_official_datasets_only():
    backend = _backend()
    _build(backend)
    assert [dataset for dataset, _ in backend.calls] == [
        adapter.DAILY_DATASET,
        adapter.ADJ_FACTOR_DATASET,
    ]
    for dataset, kwargs in backend.calls:
        assert kwargs["end"] == AS_OF
        assert kwargs["start"] is None
        assert kwargs["symbols"] == ["600000.SH"]
        assert kwargs["adjust"] is None
        assert kwargs["universe"] is None
    source = Path(adapter.__file__).read_text()
    assert "tushare" not in source.lower()
    assert "akshare" not in source.lower()
    assert "baostock" not in source.lower()
    assert "read_parquet" not in source.lower()
    assert "duckdb" not in source.lower()


def test_adapter_constructs_exact_pit_input_and_existing_producer_executes():
    backend = _backend()
    package = _build(backend)
    assert package.source_vintage == adapter.ASL_SOURCE_VINTAGE
    assert package.as_of == AS_OF
    assert package.daily_coverage_through == AS_OF
    assert package.factor_coverage_through == AS_OF
    assert package.gate2a_slice.source_manifest_hash == package.source_manifest_hash
    assert package.gate2a_observations[0].symbol == "600000"
    assert package.daily_bars[0].preclose is None
    assert package.daily_bars[1].preclose == Decimal("10.00")
    assert package.adjustment_factors[-1].adj_factor == Decimal("1.0")
    assert producer.produce_prospective_factor_bundles(package)


def test_zero_candidates_are_valid_and_make_no_asl_query():
    backend = _backend()
    package = _build(backend, candidates=())
    assert backend.calls == []
    assert package.gate2a_observations == ()
    assert package.daily_bars == ()
    assert package.adjustment_factors == ()
    assert producer.produce_prospective_factor_bundles(package) == ()


@pytest.mark.parametrize("dataset", [adapter.DAILY_DATASET, adapter.ADJ_FACTOR_DATASET])
def test_future_rows_are_blocked_for_both_asl_components(dataset: str):
    future = date(2026, 8, 11)
    backend = _backend()
    if dataset == adapter.DAILY_DATASET:
        backend.daily.append({**backend.daily[0], "trade_date": future})
    else:
        backend.adj.append({**backend.adj[0], "trade_date": future})
    with pytest.raises(adapter.ASLPITAdapterBlocked, match="BLOCKED_FUTURE_DATA"):
        _build(backend)


def test_candidate_state_must_be_computed_at_as_of_before_query():
    backend = _backend()
    with pytest.raises(
        adapter.ASLPITAdapterBlocked,
        match="BLOCKED_CANDIDATE_STATE_ASOF_MISMATCH",
    ):
        _build(backend, candidates=(_candidate(state_as_of=AS_OF - timedelta(days=1)),))
    assert backend.calls == []


def test_daily_coverage_missing_d_is_a_whole_call_block():
    backend = _backend(daily=[row for row in _daily_rows() if row["trade_date"] != AS_OF])
    with pytest.raises(adapter.ASLPITAdapterBlocked, match="BLOCKED_ASL_DAILY_COVERAGE"):
        _build(backend)


@pytest.mark.parametrize("missing", ["t0", "d", "predecessor"])
def test_required_t0_d_and_predecessor_rows_are_not_partially_dropped(missing: str):
    rows = _daily_rows()
    if missing == "t0":
        rows = [row for row in rows if row["trade_date"] != ANCHOR]
    elif missing == "d":
        rows = [row for row in rows if row["trade_date"] != AS_OF]
    else:
        rows = [row for row in rows if row["trade_date"] >= ANCHOR]
    with pytest.raises(adapter.ASLPITAdapterBlocked, match="BLOCKED_ASL_DAILY_COVERAGE"):
        _build(_backend(daily=rows))


def test_required_ca_factor_side_is_fail_closed_and_not_forward_filled():
    backend = _backend(adj=_adj_rows(event_day=6))
    with pytest.raises(
        adapter.ASLPITAdapterBlocked,
        match="BLOCKED_ASL_CA_FACTOR_SIDE_MISSING",
    ):
        _build(backend)


def test_sparse_hfq_event_is_aligned_backward_and_ca_event_reaches_producer():
    backend = _backend(adj=_adj_rows() + _adj_rows(event_day=6, factor="2.0"))
    package = _build(backend)
    factors = {row.trade_date: row.adj_factor for row in package.adjustment_factors}
    assert factors[date(2026, 8, 5)] == Decimal("1.0")
    assert factors[date(2026, 8, 6)] == Decimal("2.0")
    with pytest.raises(
        producer.ProspectiveFactorProducerBlocked,
        match="CORPORATE_ACTION_EVENT",
    ):
        producer.produce_prospective_factor_bundles(package)


def test_duplicate_daily_row_is_blocked():
    rows = _daily_rows()
    rows.append(dict(rows[0]))
    with pytest.raises(adapter.ASLPITAdapterBlocked, match="BLOCKED_ASL_DUPLICATE_ROW"):
        _build(_backend(daily=rows))


def test_asl_code_revision_mismatch_is_blocked():
    with pytest.raises(
        adapter.ASLPITAdapterBlocked,
        match="BLOCKED_ASL_CODE_REVISION_MISMATCH",
    ):
        _build(_backend(code_sha="0" * 40))
    with pytest.raises(
        adapter.ASLPITAdapterBlocked,
        match="BLOCKED_ASL_CODE_REVISION_MISMATCH",
    ):
        _build(_backend(), asl_code_sha="1" * 40)


def test_one_missing_candidate_fails_whole_call_without_partial_drop():
    candidates = (_candidate(), _candidate(symbol="000001"))
    with pytest.raises(adapter.ASLPITAdapterBlocked, match="symbol=000001"):
        _build(_backend(), candidates=candidates)


def test_manifest_hashes_are_the_existing_component_and_composite_hashes():
    package = _build(_backend())
    assert package.daily_bar_prefix_hash == producer.canonical_daily_bar_prefix_hash(
        package.daily_bars
    )
    assert package.adjustment_factor_prefix_hash == producer.canonical_adjustment_factor_prefix_hash(
        package.adjustment_factors
    )
    assert package.source_manifest_hash == producer.build_source_manifest_hash(
        as_of=AS_OF,
        daily_coverage_through=AS_OF,
        factor_coverage_through=AS_OF,
        candidate_state_source_hash=HASH_A,
        limit_pool_source_hash=HASH_B,
        daily_bar_prefix_hash=package.daily_bar_prefix_hash,
        adjustment_factor_prefix_hash=package.adjustment_factor_prefix_hash,
        configuration_version_hash=HASH_C,
        source_vintage=adapter.ASL_SOURCE_VINTAGE,
    )


@pytest.mark.parametrize(
    ("middle_close", "expected_d3_preclose"),
    [
        ("10.25", Decimal("10.25")),
        ("0", Decimal("10.00")),
        ("-1", Decimal("10.00")),
        (None, Decimal("10.00")),
    ],
)
def test_preclose_advances_only_on_positive_close(
    middle_close: str | None,
    expected_d3_preclose: Decimal,
):
    rows = _daily_rows()
    rows[1]["close"] = middle_close
    rows[2]["close"] = "10.50"
    package = _build(_backend(daily=rows))
    bars = {row.trade_date: row for row in package.daily_bars}
    assert bars[date(2026, 8, 2)].preclose == Decimal("10.00")
    assert bars[date(2026, 8, 3)].preclose == expected_d3_preclose


@pytest.mark.local_data
def test_bounded_real_asl_query_for_two_symbols_at_2026_08_07():
    """Run only with the pinned checkout and a curated/derived local lake."""

    roots = _existing_asl_query_roots()
    if not roots:
        pytest.skip(
            "shared ASL data layer unavailable: no known root exposes "
            "curated/daily_bars and derived/adj_factors"
        )
    data_root = roots[0]
    try:
        from ashare_lake import query
    except ImportError:
        pytest.skip("pinned ASL runtime is unavailable in this Python environment")

    class _RealASLQuery:
        code_sha = adapter.ASL_CODE_SHA

        def load(self, dataset: str, **kwargs: object) -> object:
            return query.load(dataset, **kwargs)

    as_of = date(2026, 8, 7)
    candidates = (
        _candidate(symbol="600000", state_as_of=as_of, anchor_date=date(2026, 8, 3)),
        _candidate(symbol="000001", state_as_of=as_of, anchor_date=date(2026, 8, 3)),
    )
    package = adapter.build_pit_factor_input(
        as_of=as_of,
        candidates=candidates,
        candidate_state_source_hash=HASH_A,
        limit_pool_source_hash=HASH_B,
        configuration_version_hash=HASH_C,
        query_backend=_RealASLQuery(),
        asl_data_root=data_root,
    )
    assert max(row.trade_date for row in package.daily_bars) <= as_of
    assert max(row.trade_date for row in package.adjustment_factors) <= as_of
    for symbol in ("600000", "000001"):
        previous: Decimal | None = None
        for row in package.daily_bars:
            if row.symbol != symbol:
                continue
            if previous is not None and row.close is not None:
                assert row.preclose == previous
            if row.close is not None:
                previous = row.close
    assert producer.produce_prospective_factor_bundles(package)
