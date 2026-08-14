from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
import yaml

from limit_pullback.config import load_strategy_config
from limit_pullback.models.b2_confirmation import IntradayBar
from limit_pullback.models.enums import (
    B2ConfirmationLevel,
    SetupStage,
    VwapSource,
)
from limit_pullback.models.signal import StrategySignal
from limit_pullback.strategy.b2_confirmation import (
    compute_vwap,
    rank_b1_setup,
    rank_b2_launch,
)
from limit_pullback.strategy.engine import evaluate_strategy
from tests.synthetic_data import (
    TZ_SHANGHAI,
    append_b2_ready_bar,
    append_pullback_bars,
    base_setup_bars,
    business_dates,
    full_limit_pool,
    make_bar,
)


GENERATED_AT = datetime(2024, 1, 1, 16, 0, tzinfo=TZ_SHANGHAI)


def _eval(bars, config, pool, previous=None, intraday=()):
    return evaluate_strategy(
        bars=bars,
        as_of=bars[-1].trade_date,
        config=config,
        generated_at=GENERATED_AT,
        limit_pool=pool,
        previous_signal=previous,
        intraday_bars=intraday,
    )


def _progression(config):
    bars = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(bars)
    b1 = _eval(bars, config, pool)
    assert b1.setup_stage is SetupStage.B1_READY
    append_b2_ready_bar(bars)
    ready = _eval(bars, config, pool, previous=b1)
    assert ready.setup_stage is SetupStage.B2_READY
    return bars, pool, b1, ready


def _next_date(bars):
    return business_dates(bars[-1].trade_date + timedelta(days=1), 1)[0]


def _append_bar(
    bars,
    *,
    open_price,
    high,
    low,
    close,
    preclose,
    volume,
    turnover="3",
):
    trade_date = _next_date(bars)
    bar = make_bar(
        trade_date,
        open_price=open_price,
        high=high,
        low=low,
        close=close,
        preclose=preclose,
        volume=volume,
    ).model_copy(update={"turnover_rate": Decimal(turnover)})
    bars.append(bar)
    return bar


def _intraday_vwap(trade_date, code, vwap: str):
    vwap_value = Decimal(vwap)
    return (
        IntradayBar(
            trade_date=trade_date,
            code=code,
            time=time(10, 0),
            price=vwap_value - Decimal("0.10"),
            volume=Decimal("1000"),
            amount=(vwap_value - Decimal("0.10")) * Decimal("1000"),
        ),
        IntradayBar(
            trade_date=trade_date,
            code=code,
            time=time(14, 30),
            price=vwap_value + Decimal("0.10"),
            volume=Decimal("1000"),
            amount=(vwap_value + Decimal("0.10")) * Decimal("1000"),
        ),
    )


@pytest.fixture
def config(project_root):
    return load_strategy_config(project_root / "config" / "strategy.yaml")


def _load_signal_case(project_root, key: str) -> dict:
    path = project_root / "tests" / "fixtures" / "signal_cases.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload[key]


def test_vwap_normal_close_above(config):
    bars, pool, b1, ready = _progression(config)
    bar = _append_bar(
        bars,
        open_price="11.05",
        high="11.65",
        low="10.95",
        close="11.45",
        preclose="10.99",
        volume="500",
        turnover="8",
    )
    intraday = _intraday_vwap(bar.trade_date, bar.code, "11.30")
    confirmed = _eval(bars, config, pool, previous=ready, intraday=intraday)
    features = confirmed.b2_confirmation.features
    assert features.vwap_source is VwapSource.INTRADAY_AMOUNT_VOLUME
    assert features.close_above_vwap is True
    assert features.close_to_vwap_pct > 0


def test_vwap_close_below():
    trade_date = date(2024, 1, 10)
    code = "600000"
    vwap, source = compute_vwap(
        _intraday_vwap(trade_date, code, "11.50"),
        code=code,
        as_of=trade_date,
    )
    assert source is VwapSource.INTRADAY_AMOUNT_VOLUME
    assert vwap == Decimal("11.50")


def test_vwap_lots_unit_converted():
    trade_date = date(2024, 1, 10)
    code = "600000"
    bars = (
        IntradayBar(
            trade_date=trade_date,
            code=code,
            time=time(10, 0),
            price=Decimal("10.00"),
            volume=Decimal("100"),
            amount=Decimal("100000"),
            volume_unit="LOTS",
        ),
    )
    vwap, source = compute_vwap(bars, code=code, as_of=trade_date)
    # 100 lots = 10,000 shares; amount 100,000 -> vwap 10.00
    assert source is VwapSource.INTRADAY_AMOUNT_VOLUME
    assert vwap == Decimal("10.00")


def test_vwap_missing_is_unknown_not_false():
    trade_date = date(2024, 1, 10)
    vwap, source = compute_vwap((), code="600000", as_of=trade_date)
    assert vwap is None
    assert source is VwapSource.UNKNOWN


def test_vwap_invalid_volume_is_unknown():
    trade_date = date(2024, 1, 10)
    bars = (
        IntradayBar(
            trade_date=trade_date,
            code="600000",
            time=time(10, 0),
            price=Decimal("10.00"),
            volume=Decimal("0"),
            amount=Decimal("0"),
        ),
    )
    vwap, source = compute_vwap(bars, code="600000", as_of=trade_date)
    assert vwap is None
    assert source is VwapSource.UNKNOWN


def test_vwap_future_bar_forbidden():
    trade_date = date(2024, 1, 10)
    bars = (
        IntradayBar(
            trade_date=date(2024, 1, 11),
            code="600000",
            time=time(10, 0),
            price=Decimal("10.00"),
            volume=Decimal("1000"),
            amount=Decimal("10000"),
        ),
    )
    with pytest.raises(ValueError, match="lookahead"):
        compute_vwap(bars, code="600000", as_of=trade_date)


def test_case_a_strong_confirmation(config):
    bars, pool, b1, ready = _progression(config)
    bar = _append_bar(
        bars,
        open_price="11.05",
        high="11.65",
        low="10.95",
        close="11.45",
        preclose="10.99",
        volume="500",
        turnover="8",
    )
    intraday = _intraday_vwap(bar.trade_date, bar.code, "11.30")
    confirmed = _eval(bars, config, pool, previous=ready, intraday=intraday)
    assert confirmed.setup_stage is SetupStage.B2_CONFIRMED
    evaluation = confirmed.b2_confirmation
    assert evaluation is not None
    assert evaluation.hard_fail is False
    assert evaluation.level is B2ConfirmationLevel.STRONG_CONFIRMED
    assert evaluation.b2_confirm_score >= Decimal("75")
    assert "RETURN_ZONE_OK" in evaluation.reasons
    assert "CLOSE_ABOVE_VWAP" in evaluation.reasons
    assert "TURNOVER_ACTIVE" in evaluation.reasons


def test_case_b_volume_distribution_never_confirmed(config):
    bars, pool, b1, ready = _progression(config)
    _append_bar(
        bars,
        open_price="11.20",
        high="11.35",
        low="10.55",
        close="10.60",
        preclose="10.99",
        volume="2000",
        turnover="8",
    )
    bad = _eval(bars, config, pool, previous=ready)
    evaluation = bad.b2_confirmation
    assert evaluation.hard_fail is True
    assert evaluation.level is B2ConfirmationLevel.NONE
    assert evaluation.hard_fail_reason in {
        "STRUCTURE_INVALIDATED",
        "VOLUME_DISTRIBUTION",
    }
    b2_rows = rank_b2_launch((ready, bad))
    assert all(row.current_stage is not SetupStage.INVALID for row in b2_rows)


def test_case_c_pretty_b1_no_attack_stays_b1(config):
    bars, pool, b1, _ = _progression(config)
    assert b1.setup_stage is SetupStage.B1_READY
    evaluation = b1.b2_confirmation
    assert evaluation.features.day_return_pct < Decimal("1.5")
    assert evaluation.features.b2_intraday_attack is False
    assert evaluation.level not in {
        B2ConfirmationLevel.CONFIRMED,
        B2ConfirmationLevel.STRONG_CONFIRMED,
    }
    assert b1.code not in {row.code for row in rank_b2_launch((b1,))}


def test_case_d_close_below_vwap_downgraded(config):
    bars, pool, b1, ready = _progression(config)
    bar = _append_bar(
        bars,
        open_price="11.15",
        high="11.60",
        low="11.00",
        close="11.30",
        preclose="10.99",
        volume="500",
        turnover="8",
    )
    intraday = _intraday_vwap(bar.trade_date, bar.code, "11.45")
    signal = _eval(bars, config, pool, previous=ready, intraday=intraday)
    evaluation = signal.b2_confirmation
    assert evaluation.features.close_above_vwap is False
    assert "CLOSE_BELOW_VWAP" in evaluation.risks
    assert evaluation.level is not B2ConfirmationLevel.STRONG_CONFIRMED


def test_case_e_extended_return_has_chasing_risk(config):
    bars, pool, b1, ready = _progression(config)
    bar = _append_bar(
        bars,
        open_price="11.20",
        high="12.00",
        low="11.00",
        close="11.92",
        preclose="10.99",
        volume="500",
        turnover="8",
    )
    intraday = _intraday_vwap(bar.trade_date, bar.code, "11.60")
    signal = _eval(bars, config, pool, previous=ready, intraday=intraday)
    evaluation = signal.b2_confirmation
    assert evaluation.features.day_return_pct >= Decimal("7")
    assert evaluation.launch_components["day_return_zone"] == Decimal("6")
    assert "RETURN_TOO_EXTENDED" in evaluation.risks


def test_case_f_vwap_unavailable_is_not_fatal(config):
    bars, pool, b1, ready = _progression(config)
    _append_bar(
        bars,
        open_price="11.05",
        high="11.65",
        low="10.95",
        close="11.45",
        preclose="10.99",
        volume="500",
        turnover="8",
    )
    signal = _eval(bars, config, pool, previous=ready)
    evaluation = signal.b2_confirmation
    assert evaluation.features.vwap is None
    assert "VWAP_UNAVAILABLE" in evaluation.risks
    assert "close_above_vwap" in evaluation.missing_components
    assert evaluation.hard_fail is False


def test_case_g_prev_day_limit_up_is_not_ideal_second_launch(config):
    bars, pool, b1, ready = _progression(config)
    limit_date = _next_date(bars)
    bars.append(
        make_bar(
            limit_date,
            open_price="11.00",
            high="12.09",
            low="10.99",
            close="12.09",
            preclose="10.99",
            volume="900",
        )
    )
    limit_signal = _eval(bars, config, pool, previous=ready)
    next_date = _next_date(bars)
    bars.append(
        make_bar(
            next_date,
            open_price="12.05",
            high="12.30",
            low="11.95",
            close="12.20",
            preclose="12.09",
            volume="700",
        )
    )
    signal = _eval(bars, config, pool, previous=limit_signal)
    evaluation = signal.b2_confirmation
    assert evaluation.features.prev_day_not_limit_up is False
    assert "PREV_DAY_LIMIT_UP" in evaluation.risks


def test_engine_includes_b2_confirmation_only_for_anchored_non_anchor_days(
    config,
):
    bars = base_setup_bars()
    pool = full_limit_pool(bars)
    anchor_signal = _eval(bars, config, pool)
    assert anchor_signal.setup_stage is SetupStage.LIMIT_ANCHOR
    assert anchor_signal.b2_confirmation is None
    bars = append_pullback_bars(bars)
    b1 = _eval(bars, config, pool)
    assert b1.b2_confirmation is not None


def test_rankings_deterministic_and_hard_fail_excluded(config):
    bars, pool, b1, ready = _progression(config)
    good = _append_bar(
        bars,
        open_price="11.05",
        high="11.65",
        low="10.95",
        close="11.45",
        preclose="10.99",
        volume="500",
        turnover="8",
    )
    intraday = _intraday_vwap(good.trade_date, good.code, "11.30")
    confirmed = _eval(bars, config, pool, previous=ready, intraday=intraday)

    b1_rows = rank_b1_setup((b1, ready, confirmed))
    assert [row.code for row in b1_rows] == [b1.code]
    assert b1_rows[0].current_stage is SetupStage.B1_READY

    b2_rows = rank_b2_launch((ready, confirmed))
    assert [row.code for row in b2_rows] == [confirmed.code, ready.code]
    assert b2_rows[0].b2_confirm_level in {
        B2ConfirmationLevel.CONFIRMED,
        B2ConfirmationLevel.STRONG_CONFIRMED,
    }
    # Reversed input order must not change ranking.
    assert rank_b2_launch((confirmed, ready)) == b2_rows


def test_old_signal_without_b2_confirmation_still_readable(project_root):
    payload = _load_signal_case(project_root, "valid_b2_confirmed")
    signal = StrategySignal.model_validate(payload)
    assert signal.b2_confirmation is None
    assert signal.setup_stage is SetupStage.B2_CONFIRMED


def test_new_signal_roundtrip_preserves_b2_confirmation(config):
    bars, pool, b1, ready = _progression(config)
    bar = _append_bar(
        bars,
        open_price="11.05",
        high="11.65",
        low="10.95",
        close="11.45",
        preclose="10.99",
        volume="500",
        turnover="8",
    )
    intraday = _intraday_vwap(bar.trade_date, bar.code, "11.30")
    confirmed = _eval(bars, config, pool, previous=ready, intraday=intraday)
    payload = confirmed.model_dump(mode="json", exclude_computed_fields=True)
    restored = StrategySignal.model_validate(payload)
    assert restored.b2_confirmation is not None
    assert (
        restored.b2_confirmation.b2_confirm_score
        == confirmed.b2_confirmation.b2_confirm_score
    )


def test_evaluate_strategy_rejects_future_intraday_bars(config):
    bars = append_pullback_bars(base_setup_bars())
    pool = full_limit_pool(bars)
    future = (
        IntradayBar(
            trade_date=bars[-1].trade_date + timedelta(days=1),
            code="600000",
            time=time(10, 0),
            price=Decimal("11.00"),
            volume=Decimal("1000"),
            amount=Decimal("11000"),
        ),
    )
    with pytest.raises(ValueError, match="lookahead"):
        _eval(bars, config, pool, intraday=future)
