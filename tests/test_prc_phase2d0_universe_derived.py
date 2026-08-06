"""PR-C offline tests: PHASE2D0_UNIVERSE_V1, coverage, derived limit events."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from limit_pullback.config import load_strategy_config
from limit_pullback.coverage import (
    CONFIRMED_TRADED_BAR,
    DATA_MISSING_UNEXPLAINED,
    VERIFIED_NO_TRADE,
    classify_daily_coverage,
)
from limit_pullback.derived_limit_event import (
    build_derived_limit_events,
    compose_enrichment,
)
from limit_pullback.models.market import LimitUpRecord
from limit_pullback.strategy.structure import detect_anchor
from limit_pullback.universe import (
    PHASE2D0_UNIVERSE_CONTRACT_VERSION,
    declared_config_universe_members,
    phase2d0_universe_members,
)
from tests.synthetic_data import base_setup_bars


@pytest.fixture
def config(project_root):
    return load_strategy_config(project_root / "config" / "strategy.yaml")


def _limit_row(
    *,
    code: str = "000001",
    day: date,
    close: str,
    preclose: str,
    open_price: str = "11.00",
    high: str = "11.00",
    low: str = "10.90",
    hash_value: str = "h1",
) -> dict:
    return {
        "code": code,
        "trade_date": day,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "preclose": preclose,
        "volume": "1000",
        "amount": "11000",
        "source_daily_hash": hash_value,
    }


def test_phase2d0_universe_mainboard_only():
    members = phase2d0_universe_members(
        ["000001", "600000", "002594", "300750", "688981", "830799"]
    )
    assert members == ("000001", "002594", "600000")
    assert "300750" not in members
    assert "688981" not in members


def test_phase2d0_universe_includes_legacy_st_member():
    # ST exclusion was declared in config but never enforced at membership.
    assert "000010" in phase2d0_universe_members(["000010"])
    rows_by_code = {
        "000010": [{"trade_date": date(2026, 7, 31), "is_st": True}],
    }
    declared = declared_config_universe_members(
        members=["000010"],
        rows_by_code=rows_by_code,
        as_of=date(2026, 7, 31),
    )
    assert declared == ()


def test_phase2d0_universe_includes_legacy_under120_member():
    assert "001220" in phase2d0_universe_members(["001220"])
    rows_by_code = {
        "001220": [
            {
                "trade_date": date(2026, 1, 5) + timedelta(days=index),
                "is_st": False,
            }
            for index in range(86)
        ]
    }
    declared = declared_config_universe_members(
        members=["001220"],
        rows_by_code=rows_by_code,
        as_of=date(2026, 7, 31),
    )
    assert declared == ()


def test_phase2d0_universe_membership_not_active_day_filter():
    assert "000756" in phase2d0_universe_members(["000756"])
    rows_by_code = {
        "000756": [{"trade_date": date(2026, 7, 30), "is_st": False}],
    }
    declared = declared_config_universe_members(
        members=["000756"],
        rows_by_code=rows_by_code,
        as_of=date(2026, 7, 31),
    )
    assert declared == ()


def test_declared_config_universe_is_audit_only():
    members = ["000010", "001220", "000756", "600000"]
    rows_by_code = {
        "000010": [{"trade_date": date(2026, 7, 31), "is_st": True}],
        "001220": [
            {"trade_date": date(2026, 7, 1) + timedelta(days=index), "is_st": False}
            for index in range(30)
        ],
        "000756": [{"trade_date": date(2026, 7, 30), "is_st": False}],
        "600000": [
            {
                "trade_date": date(2026, 7, 31) - timedelta(days=119 - index),
                "is_st": False,
            }
            for index in range(120)
        ],
    }
    declared = declared_config_universe_members(
        members=members,
        rows_by_code=rows_by_code,
        as_of=date(2026, 7, 31),
    )
    assert declared == ("600000",)
    # Screen membership stays the phase-2d0 legacy-compatible set.
    assert phase2d0_universe_members(members) == (
        "000010",
        "000756",
        "001220",
        "600000",
    )


def test_chinext_excluded():
    assert phase2d0_universe_members(["300750", "301234"]) == ()


def test_star_excluded():
    assert phase2d0_universe_members(["688981", "689009"]) == ()


def test_strict_future_change_guard_phase2d0_membership():
    """Mutation guard: adding config gates to V1 membership must break."""

    sample = ["000010", "001220", "000756", "600000"]
    contract = phase2d0_universe_members(sample)
    # A future buggy implementation that applies exclude_st would drop 000010.
    buggy = tuple(code for code in contract if code != "000010")
    assert buggy != contract
    # And applying every declared gate would drop three members.
    assert PHASE2D0_UNIVERSE_CONTRACT_VERSION == "PHASE2D0_UNIVERSE_V1"


def _audit(
    *,
    members,
    staged_rows,
    verified=(),
    day=date(2026, 8, 3),
):
    return classify_daily_coverage(
        contract_version=PHASE2D0_UNIVERSE_CONTRACT_VERSION,
        as_of=day,
        universe_members=members,
        staged_rows=staged_rows,
        verified_no_trade=verified,
    )


def test_verified_no_trade_does_not_create_synthetic_bar():
    audit = _audit(
        members=["600000", "600530"],
        staged_rows=[{"code": "600000", "trade_date": date(2026, 8, 3), "close": 11}],
        verified=[("600530", date(2026, 8, 3))],
    )
    assert audit.traded == (("600000", date(2026, 8, 3)),)
    assert audit.verified_no_trade == (("600530", date(2026, 8, 3)),)
    assert audit.unexplained_n == 0
    assert audit.ready is True


def test_verified_no_trade_does_not_block_data_readiness():
    audit = _audit(
        members=["600530"],
        staged_rows=[],
        verified=[("600530", date(2026, 8, 3))],
    )
    assert audit.ready is True


def test_unexplained_missing_blocks_data_readiness():
    audit = _audit(
        members=["600530"],
        staged_rows=[],
        verified=[],
    )
    assert audit.unexplained_n == 1
    assert audit.ready is False


def test_both_provider_missing_requires_independent_classification():
    staged = [
        {
            "code": "603221",
            "trade_date": date(2026, 8, 3),
            "close": None,
            "reconciliation_status": "INCOMPLETE",
        }
    ]
    audit = _audit(members=["603221"], staged_rows=staged, verified=[])
    assert audit.unexplained_missing == (("603221", date(2026, 8, 3)),)
    verified_audit = _audit(
        members=["603221"],
        staged_rows=staged,
        verified=[("603221", date(2026, 8, 3))],
    )
    assert verified_audit.ready is True


def _pool_record(
    *,
    code="600000",
    day,
    complete: bool,
) -> LimitUpRecord:
    return LimitUpRecord(
        trade_date=day,
        code=code,
        name="测试",
        limit_price=Decimal("11.00"),
        first_seal_time=time(9, 30) if complete else None,
        last_seal_time=time(14, 0) if complete else None,
        open_count=0 if complete else None,
        consecutive_count=1 if complete else None,
        source="TEST",
        fetched_at=datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc),
    )


def test_no_pool_record_still_price_only_anchor(config):
    bars = base_setup_bars()
    anchor = detect_anchor(bars, bars[-1].trade_date, config, limit_pool=())
    assert anchor is not None
    assert anchor.profile.value == "PRICE_ONLY"


def test_incomplete_pool_record_still_price_only(config):
    bars = base_setup_bars()
    day = bars[-1].trade_date
    anchor = detect_anchor(
        bars,
        day,
        config,
        limit_pool=[_pool_record(day=day, complete=False)],
    )
    assert anchor is not None
    assert anchor.profile.value == "PRICE_ONLY"


def test_complete_enrichment_full_profile(config):
    bars = base_setup_bars()
    day = bars[-1].trade_date
    anchor = detect_anchor(
        bars,
        day,
        config,
        limit_pool=[_pool_record(day=day, complete=True)],
    )
    assert anchor is not None
    assert anchor.profile.value == "FULL"


def test_no_fake_enrichment(config):
    day = date(2026, 8, 5)
    events = build_derived_limit_events(
        [
            _limit_row(
                day=day,
                close="11.00",
                preclose="10.00",
                open_price="11.00",
                high="11.00",
                low="11.00",
            )
        ],
        source_id="staging-test",
        config=config,
    )
    assert len(events) == 1
    event = events[0]
    assert event.is_one_word is True
    assert event.first_seal_time is None
    assert event.last_seal_time is None
    assert event.open_count is None
    assert event.consecutive_count is None
    assert event.price_profile == "PRICE_ONLY"


def test_derived_event_matches_frozen_is_limit_close(config):
    day = date(2026, 8, 5)
    rows = [
        _limit_row(day=day, close="11.00", preclose="10.00", hash_value="h-limit"),
        _limit_row(day=day, close="10.50", preclose="10.00", hash_value="h-not"),
    ]
    events = build_derived_limit_events(rows, source_id="s", config=config)
    assert [event.code for event in events] == ["000001"]
    assert events[0].source_daily_hash == "h-limit"


def test_one_word_semantics_exact(config):
    day = date(2026, 8, 5)
    row = _limit_row(
        day=day,
        close="11.00",
        preclose="10.00",
        open_price="11.00",
        high="11.00",
        low="11.00",
    )
    events = build_derived_limit_events([row], source_id="s", config=config)
    assert events[0].is_one_word is True
    assert events[0].is_t_word is False


def test_t_word_semantics_exact(config):
    day = date(2026, 8, 5)
    row = _limit_row(
        day=day,
        close="11.00",
        preclose="10.00",
        open_price="11.00",
        high="11.00",
        low="10.90",
    )
    events = build_derived_limit_events([row], source_id="s", config=config)
    assert events[0].is_t_word is True
    assert events[0].is_one_word is False


def test_missing_enrichment_preserves_price_only(config):
    day = date(2026, 8, 5)
    events = build_derived_limit_events(
        [_limit_row(day=day, close="11.00", preclose="10.00")],
        source_id="s",
        config=config,
    )
    composed = compose_enrichment(events, [])
    assert composed[0].price_profile == "PRICE_ONLY"
    assert composed[0].first_seal_time is None


def test_complete_enrichment_preserves_full(config):
    day = date(2026, 8, 5)
    events = build_derived_limit_events(
        [_limit_row(day=day, close="11.00", preclose="10.00")],
        source_id="s",
        config=config,
    )
    composed = compose_enrichment(
        events,
        [
            {
                "code": "000001",
                "trade_date": day,
                "first_seal_time": "09:25:00",
                "last_seal_time": "09:25:00",
                "open_count": 0,
                "consecutive_count": 1,
                "industry": "银行",
            }
        ],
    )
    assert composed[0].price_profile == "FULL"
    assert composed[0].enrichment_profile == "FULL"
    assert composed[0].first_seal_time == time(9, 25)
    assert composed[0].open_count == 0
    assert composed[0].consecutive_count == 1


def test_legacy_full_profile_preserved(config):
    day = date(2026, 7, 14)
    events = build_derived_limit_events(
        [_limit_row(code="000008", day=day, close="2.60", preclose="2.36")],
        source_id="b5f",
        config=config,
    )
    composed = compose_enrichment(
        events,
        [
            {
                "code": "000008",
                "trade_date": day,
                "first_seal_time": "09:25:00",
                "last_seal_time": "09:25:00",
                "open_count": 0,
                "consecutive_count": 1,
                "industry": "轨交设备",
            }
        ],
    )
    assert composed[0].price_profile == "FULL"


def test_derived_event_no_false_positive(config):
    day = date(2026, 8, 5)
    events = build_derived_limit_events(
        [_limit_row(day=day, close="10.50", preclose="10.00")],
        source_id="s",
        config=config,
    )
    assert events == []


def test_every_formal_limit_close_has_event(config):
    day = date(2026, 8, 5)
    rows = [
        _limit_row(code="600000", day=day, close="11.00", preclose="10.00"),
        _limit_row(code="000001", day=day, close="11.00", preclose="10.00"),
    ]
    events = build_derived_limit_events(
        rows,
        source_id="s",
        config=config,
        universe_members={"600000", "000001"},
    )
    assert len(events) == 2
    assert all(event.quality_status == "OK" for event in events)
