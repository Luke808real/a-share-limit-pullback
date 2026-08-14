"""B2_CONFIRMATION_V01 — confirmation layer over the frozen B1/B2 lifecycle.

The frozen state machine remains the single source of truth for
``setup_stage``. This module only adds a deterministic, PIT-safe confirmation
score, level label, diagnostics, and two explicit rankings on top of it.

All thresholds in ``B2ConfirmationConfig`` are V01 hypotheses, centralized in
one place so they can be re-validated against historical success/control cases
and forward paper records later.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from limit_pullback.models.b2_confirmation import (
    B1SetupRankRow,
    B2ConfirmationEvaluation,
    B2ConfirmationFeatures,
    B2LaunchRankRow,
    IntradayBar,
)
from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import (
    B2ConfirmationLevel,
    ScoreProfile,
    SetupStage,
    VwapSource,
)
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.signal import ScoreBreakdown, StrategySignal
from limit_pullback.models.strategy import (
    AnchorEvaluation,
    ConditionScore,
    IndicatorPoint,
    PriceCluster,
)
from limit_pullback.strategy.structure import is_limit_close


ZERO = Decimal("0")
ONE = Decimal("1")
SCORE_QUANTUM = Decimal("0.01")
PCT_QUANTUM = Decimal("0.01")

# Piecewise score buckets for the day-return zone (V01 hypothesis).
RETURN_WEAK_MAX_PCT = Decimal("1.5")
RETURN_IMPROVING_MAX_PCT = Decimal("2.5")
RETURN_STRONG_MAX_PCT = Decimal("7.0")
RETURN_EXTENDED_MAX_PCT = Decimal("9.0")

# Intraday attack score buckets (V01 hypothesis).
ATTACK_WEAK_MAX_PCT = Decimal("2.0")
ATTACK_MODERATE_MAX_PCT = Decimal("4.0")

# Pullback-volume ratio score buckets (V01 hypothesis).
VOLUME_GOOD_MAX = Decimal("0.80")
VOLUME_OK_MAX = Decimal("1.00")
VOLUME_HEAVY_MAX = Decimal("1.30")
VOLUME_DISTRIBUTION_MAX = Decimal("1.50")

ANCHOR_SCORE_RULES = (
    "limit_close",
    "non_one_word",
    "non_t_board",
    "first_board",
    "seal_before_cutoff",
    "normal_liquidity",
    "position_120",
    "ma_compression",
    "bullish_cross_ma",
)

B1_RANK_STAGES = frozenset(
    {SetupStage.WATCH_PULLBACK, SetupStage.B1_READY}
)
B2_RANK_STAGES = frozenset({SetupStage.B2_READY, SetupStage.B2_CONFIRMED})


def _quantize(value: Decimal, quantum: Decimal = SCORE_QUANTUM) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _pct(ratio: Decimal) -> Decimal:
    return _quantize(ratio * Decimal("100"), PCT_QUANTUM)


def compute_vwap(
    intraday_bars: Sequence[IntradayBar],
    *,
    code: str,
    as_of: date,
) -> tuple[Decimal | None, VwapSource]:
    """PIT-safe intraday VWAP: sum(amount) / sum(volume in shares)."""

    future = tuple(bar for bar in intraday_bars if bar.trade_date > as_of)
    if future:
        raise ValueError("intraday bars after as_of are forbidden (lookahead)")
    day_bars = tuple(
        bar
        for bar in intraday_bars
        if bar.trade_date == as_of and bar.code == code
    )
    if not day_bars:
        return None, VwapSource.UNKNOWN
    if any(
        bar.volume_unit == "UNKNOWN" or bar.amount_unit == "UNKNOWN"
        for bar in day_bars
    ):
        return None, VwapSource.UNKNOWN
    volume_shares = sum(
        bar.volume * (Decimal("100") if bar.volume_unit == "LOTS" else ONE)
        for bar in day_bars
    )
    amount = sum(bar.amount for bar in day_bars)
    if volume_shares <= ZERO or amount < ZERO:
        return None, VwapSource.UNKNOWN
    return _quantize(amount / volume_shares, PCT_QUANTUM), (
        VwapSource.INTRADAY_AMOUNT_VOLUME
    )


def _rolling_raw_ma(
    bars: Sequence[DailyBar],
    index: int,
    window: int,
) -> Decimal | None:
    if index + 1 < window:
        return None
    values = tuple(bars[position].close for position in range(index - window + 1, index + 1))
    return sum(values, ZERO) / Decimal(window)


def _t0_quality(anchor: AnchorEvaluation) -> str:
    if (
        anchor.profile is ScoreProfile.FULL
        and anchor.seal_before_cutoff is True
        and anchor.is_first_board
        and anchor.recent_limit_count == 1
    ):
        return "A"
    if anchor.profile is ScoreProfile.FULL and anchor.is_first_board:
        return "B"
    if (
        anchor.profile is ScoreProfile.PRICE_ONLY
        and anchor.is_first_board
        and anchor.recent_limit_count <= 2
    ):
        return "C"
    return "D"


def compute_features(
    *,
    ordered: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    as_of: date,
    config: StrategyConfig,
    anchor: AnchorEvaluation,
    limit_pool: Sequence[LimitUpRecord],
    intraday_bars: Sequence[IntradayBar] = (),
) -> B2ConfirmationFeatures:
    """Build the PIT feature snapshot for session D."""

    if not ordered or ordered[-1].trade_date != as_of:
        raise ValueError("bars must contain an observation exactly on as_of")
    if any(bar.trade_date > as_of for bar in ordered):
        raise ValueError("daily bars after as_of are forbidden (lookahead)")
    if len(indicators) != len(ordered):
        raise ValueError("indicators must be aligned with ordered bars")
    current = ordered[-1]
    anchor_index = next(
        index
        for index, bar in enumerate(ordered)
        if bar.trade_date == anchor.snapshot.anchor_date
    )
    current_indicator = indicators[-1]

    day_return_ratio = (
        current.close / current.preclose - ONE
        if current.preclose > ZERO
        else None
    )
    intraday_max_ratio = (
        current.high / current.preclose - ONE
        if current.preclose > ZERO
        else None
    )
    day_return_pct = _pct(day_return_ratio) if day_return_ratio is not None else None
    intraday_max_return_pct = (
        _pct(intraday_max_ratio) if intraday_max_ratio is not None else None
    )
    b2_return_zone = (
        config.b2_confirmation.day_return_strong_min
        <= day_return_ratio
        < config.b2_confirmation.day_return_extended_min
        if day_return_ratio is not None
        else None
    )
    b2_intraday_attack = (
        intraday_max_ratio >= config.b2_confirmation.intraday_attack_min
        if intraday_max_ratio is not None
        else None
    )

    vwap, vwap_source = compute_vwap(
        intraday_bars,
        code=current.code,
        as_of=as_of,
    )
    close_above_vwap = (
        current.close > vwap if vwap is not None else None
    )
    close_to_vwap_pct = (
        _pct(current.close / vwap - ONE) if vwap is not None else None
    )

    ma5 = current_indicator.raw_equivalent_mas.get(5)
    ma10 = current_indicator.raw_equivalent_mas.get(10)
    ma20 = current_indicator.raw_equivalent_mas.get(20)
    close_above_ma5 = current.close > ma5 if ma5 is not None else None
    ma5_gt_ma10 = ma5 > ma10 if ma5 is not None and ma10 is not None else None
    ma5_gt_ma20 = ma5 > ma20 if ma5 is not None and ma20 is not None else None
    short_ma_bullish = (
        close_above_ma5 is True
        and ma5_gt_ma10 is True
        and ma5_gt_ma20 is True
    )

    turnover_rate = current.turnover_rate
    turnover_active = (
        turnover_rate >= config.b2_confirmation.turnover_active_min
        if turnover_rate is not None
        else None
    )

    washout_lookback = config.b2_confirmation.washout_lookback_days
    tail_bars = tuple(ordered[-washout_lookback:])
    tail_indicators = tuple(indicators[-washout_lookback:])
    tail_start = len(ordered) - len(tail_bars)
    touched_windows: dict[int, bool] = {5: False, 10: False, 18: False}
    depths: list[Decimal] = []
    for offset, (bar, indicator) in enumerate(zip(tail_bars, tail_indicators, strict=True)):
        index = tail_start + offset
        ma_lookup = {
            5: indicator.raw_equivalent_mas.get(5),
            10: indicator.raw_equivalent_mas.get(10),
            18: _rolling_raw_ma(ordered, index, 18),
        }
        for window, value in ma_lookup.items():
            if value is None:
                continue
            if bar.low <= value:
                touched_windows[window] = True
                depth = (value - bar.low) / value
                if depth > ZERO:
                    depths.append(depth)
    washout_depth = max(depths) if depths else ZERO
    washout_depth_score = _quantize(
        min(
            washout_depth / config.b2_confirmation.washout_depth_scale,
            ONE,
        )
    )

    limit_lookback = config.b2_confirmation.limit_up_lookback_days
    limit_up_count_7d = sum(
        is_limit_close(bar, config) for bar in ordered[-limit_lookback:]
    )
    prev_day_not_limit_up = (
        not is_limit_close(ordered[-2], config)
        if len(ordered) >= 2
        else None
    )
    return_20d_pct = (
        _pct(current.close / ordered[-21].close - ONE)
        if len(ordered) >= 21
        else None
    )

    pool_by_key = {
        (record.trade_date, record.code): record for record in limit_pool
    }
    market_cap_source_date: date | None = None
    market_cap: Decimal | None = None
    for candidate_date in (as_of, anchor.snapshot.anchor_date):
        record = pool_by_key.get((candidate_date, current.code))
        if record is not None and record.float_market_cap is not None:
            market_cap = record.float_market_cap
            market_cap_source_date = candidate_date
            break

    pullback_bars = tuple(ordered[anchor_index + 1 : -1])
    average_pullback_volume = (
        sum((bar.volume for bar in pullback_bars), ZERO)
        / Decimal(len(pullback_bars))
        if pullback_bars
        else None
    )
    pullback_volume_ratio = (
        current.volume / average_pullback_volume
        if average_pullback_volume is not None and average_pullback_volume > ZERO
        else None
    )

    return B2ConfirmationFeatures(
        trade_date=as_of,
        code=current.code,
        t0_date=anchor.snapshot.anchor_date,
        t0_quality=_t0_quality(anchor),
        days_after_anchor=len(ordered) - 1 - anchor_index,
        day_return_pct=day_return_pct,
        intraday_max_return_pct=intraday_max_return_pct,
        b2_return_zone=b2_return_zone,
        b2_intraday_attack=b2_intraday_attack,
        vwap=vwap,
        vwap_source=vwap_source,
        close_above_vwap=close_above_vwap,
        close_to_vwap_pct=close_to_vwap_pct,
        close_above_ma5=close_above_ma5,
        ma5_gt_ma10=ma5_gt_ma10,
        ma5_gt_ma20=ma5_gt_ma20,
        short_ma_bullish=short_ma_bullish,
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        turnover_rate=turnover_rate,
        turnover_active=turnover_active,
        touched_below_ma5_7d=touched_windows[5],
        touched_below_ma10_7d=touched_windows[10],
        touched_below_ma18_7d=touched_windows[18],
        washout_depth_score=washout_depth_score,
        limit_up_count_7d=limit_up_count_7d,
        prev_day_not_limit_up=prev_day_not_limit_up,
        return_20d_pct=return_20d_pct,
        circulating_market_cap=(
            _quantize(market_cap, PCT_QUANTUM)
            if market_cap is not None
            else None
        ),
        market_cap_source_date=market_cap_source_date,
        pullback_volume_ratio=(
            _quantize(pullback_volume_ratio, PCT_QUANTUM)
            if pullback_volume_ratio is not None
            else None
        ),
    )


def _structure_components(
    *,
    config: StrategyConfig,
    score: ScoreBreakdown,
    features: B2ConfirmationFeatures,
    b1_conditions: ConditionScore | None,
    support: PriceCluster | None,
    current: DailyBar,
) -> tuple[
    dict[str, Decimal],
    dict[str, Decimal],
    tuple[str, ...],
    tuple[str, ...],
]:
    maxima = config.b2_confirmation.structure_max
    values: dict[str, Decimal] = {}
    missing: list[str] = []
    reasons: list[str] = []

    anchor_max = ZERO
    anchor_available = ZERO
    for rule_id in ANCHOR_SCORE_RULES:
        if rule_id in score.component_scores:
            anchor_available += score.component_scores[rule_id]
            anchor_max += score.component_max_scores[rule_id]
    fraction = anchor_available / anchor_max if anchor_max > ZERO else ZERO
    values["t0_quality"] = _quantize(maxima["t0_quality"] * fraction)
    if anchor_max == ZERO:
        missing.append("t0_quality")
    elif fraction >= Decimal("0.75"):
        reasons.append("T0_QUALITY_STRONG")
    elif fraction < Decimal("0.40"):
        reasons.append("T0_QUALITY_WEAK")

    ratio = features.pullback_volume_ratio
    if ratio is None:
        volume_fraction = ZERO
        if b1_conditions is not None:
            if "recent_volume_contraction" in b1_conditions.matched:
                volume_fraction += Decimal("0.7")
            if "anchor_volume_contraction" in b1_conditions.matched:
                volume_fraction += Decimal("0.3")
    elif ratio <= VOLUME_GOOD_MAX:
        volume_fraction = ONE
        reasons.append("PULLBACK_VOLUME_GOOD")
    elif ratio <= VOLUME_OK_MAX:
        volume_fraction = Decimal("0.80")
    elif ratio <= VOLUME_HEAVY_MAX:
        volume_fraction = Decimal("0.50")
    elif ratio <= VOLUME_DISTRIBUTION_MAX:
        volume_fraction = Decimal("0.20")
    else:
        volume_fraction = ZERO
    values["pullback_volume"] = _quantize(
        maxima["pullback_volume"] * volume_fraction
    )

    if support is None:
        values["support_pullback"] = ZERO
    else:
        support_score = Decimal("5")
        if current.close >= support.low * (
            ONE - config.support.invalid_buffer
        ):
            support_score += Decimal("3")
            reasons.append("SUPPORT_HOLD")
        if len(support.sources) >= 2:
            support_score += Decimal("2")
            reasons.append("SUPPORT_MULTI_SOURCE")
        values["support_pullback"] = _quantize(
            min(support_score, maxima["support_pullback"])
        )

    b1_fraction = (
        b1_conditions.match_ratio
        if b1_conditions is not None and b1_conditions.available_count > 0
        else ZERO
    )
    values["b1_structure"] = _quantize(
        maxima["b1_structure"] * b1_fraction
    )
    if b1_fraction >= Decimal("0.6"):
        reasons.append("B1_STRUCTURE_OK")
    elif b1_conditions is None:
        missing.append("b1_structure")

    return values, maxima, tuple(sorted(set(reasons))), tuple(sorted(set(missing)))


def _launch_components(
    *,
    config: StrategyConfig,
    features: B2ConfirmationFeatures,
) -> tuple[
    dict[str, Decimal],
    dict[str, Decimal],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    maxima = config.b2_confirmation.launch_max
    values: dict[str, Decimal] = {}
    missing: list[str] = []
    reasons: list[str] = []
    risks: list[str] = []

    day_return = features.day_return_pct
    if day_return is None:
        values["day_return_zone"] = ZERO
        missing.append("day_return_zone")
    elif day_return < ZERO:
        values["day_return_zone"] = ZERO
        risks.append("DAY_RETURN_NEGATIVE")
    elif day_return < RETURN_WEAK_MAX_PCT:
        values["day_return_zone"] = _quantize(Decimal("3"))
        risks.append("DAY_RETURN_WEAK")
    elif day_return < RETURN_IMPROVING_MAX_PCT:
        values["day_return_zone"] = _quantize(Decimal("6"))
        reasons.append("RETURN_IMPROVING")
    elif day_return < RETURN_STRONG_MAX_PCT:
        values["day_return_zone"] = maxima["day_return_zone"]
        reasons.append("RETURN_ZONE_OK")
    elif day_return < RETURN_EXTENDED_MAX_PCT:
        values["day_return_zone"] = _quantize(Decimal("6"))
        reasons.append("RETURN_STRONG_BUT_EXTENDED")
        risks.append("RETURN_TOO_EXTENDED")
    else:
        values["day_return_zone"] = _quantize(Decimal("4"))
        reasons.append("RETURN_NEAR_LIMIT")
        risks.append("RETURN_NEAR_LIMIT_POOR_RR")

    intraday_max = features.intraday_max_return_pct
    if intraday_max is None:
        values["intraday_attack"] = ZERO
        missing.append("intraday_attack")
    elif intraday_max < ATTACK_WEAK_MAX_PCT:
        values["intraday_attack"] = ZERO
        risks.append("NO_INTRADAY_ATTACK")
    elif intraday_max < ATTACK_MODERATE_MAX_PCT:
        values["intraday_attack"] = _quantize(Decimal("4"))
    else:
        values["intraday_attack"] = maxima["intraday_attack"]
        reasons.append("INTRADAY_ATTACK_OK")

    if features.close_above_vwap is None:
        values["close_above_vwap"] = ZERO
        missing.append("close_above_vwap")
        risks.append("VWAP_UNAVAILABLE")
    elif features.close_above_vwap:
        values["close_above_vwap"] = maxima["close_above_vwap"]
        reasons.append("CLOSE_ABOVE_VWAP")
    else:
        values["close_above_vwap"] = ZERO
        risks.append("CLOSE_BELOW_VWAP")

    if features.close_above_ma5 is None:
        values["close_above_ma5"] = ZERO
        missing.append("close_above_ma5")
    elif features.close_above_ma5:
        values["close_above_ma5"] = maxima["close_above_ma5"]
        reasons.append("CLOSE_ABOVE_MA5")
    else:
        values["close_above_ma5"] = ZERO
        risks.append("CLOSE_BELOW_MA5")

    if features.ma5_gt_ma10 is None:
        values["ma5_gt_ma10"] = ZERO
        missing.append("ma5_gt_ma10")
    elif features.ma5_gt_ma10:
        values["ma5_gt_ma10"] = maxima["ma5_gt_ma10"]
        reasons.append("MA5_GT_MA10")
    else:
        values["ma5_gt_ma10"] = ZERO

    if features.ma5_gt_ma20 is None:
        values["ma5_gt_ma20"] = ZERO
        missing.append("ma5_gt_ma20")
    elif features.ma5_gt_ma20:
        values["ma5_gt_ma20"] = maxima["ma5_gt_ma20"]
        reasons.append("MA5_GT_MA20")
    else:
        values["ma5_gt_ma20"] = ZERO
        risks.append("MA5_NOT_GT_MA20")

    if features.turnover_active is None:
        values["turnover_active"] = ZERO
        missing.append("turnover_active")
        risks.append("TURNOVER_UNAVAILABLE")
    elif features.turnover_active:
        values["turnover_active"] = maxima["turnover_active"]
        reasons.append("TURNOVER_ACTIVE")
    else:
        rate = features.turnover_rate
        if rate is not None and rate >= Decimal("3"):
            values["turnover_active"] = _quantize(Decimal("3"))
            risks.append("TURNOVER_MODERATE")
        else:
            values["turnover_active"] = _quantize(Decimal("1"))
            risks.append("TURNOVER_LOW")

    washout = any(
        (
            features.touched_below_ma5_7d is True,
            features.touched_below_ma10_7d is True,
            features.touched_below_ma18_7d is True,
        )
    )
    values["washout_ma_touch"] = (
        maxima["washout_ma_touch"] if washout else ZERO
    )
    if washout:
        reasons.append("WASHOUT_MA_TOUCH")

    if features.prev_day_not_limit_up is None:
        values["prev_day_not_limit_up"] = ZERO
        missing.append("prev_day_not_limit_up")
    elif features.prev_day_not_limit_up:
        values["prev_day_not_limit_up"] = maxima["prev_day_not_limit_up"]
        reasons.append("PREV_DAY_NOT_LIMIT_UP")
    else:
        values["prev_day_not_limit_up"] = ZERO
        risks.append("PREV_DAY_LIMIT_UP")

    return (
        values,
        maxima,
        tuple(sorted(set(reasons))),
        tuple(sorted(set(risks))),
        tuple(sorted(set(missing))),
    )


def _level_from_score(
    normalized: Decimal,
    config: StrategyConfig,
) -> B2ConfirmationLevel:
    thresholds = config.b2_confirmation
    if normalized < thresholds.level_weak_min:
        return B2ConfirmationLevel.NONE
    if normalized < thresholds.level_candidate_min:
        return B2ConfirmationLevel.WEAK
    if normalized < thresholds.level_confirmed_min:
        return B2ConfirmationLevel.CANDIDATE
    if normalized < thresholds.level_strong_min:
        return B2ConfirmationLevel.CONFIRMED
    return B2ConfirmationLevel.STRONG_CONFIRMED


def evaluate_b2_confirmation(
    *,
    ordered: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    as_of: date,
    config: StrategyConfig,
    anchor: AnchorEvaluation,
    setup_stage: SetupStage,
    score: ScoreBreakdown,
    b1_conditions: ConditionScore | None,
    support: PriceCluster | None,
    invalid_price: Decimal | None,
    invalidation_reasons: Sequence[str],
    limit_pool: Sequence[LimitUpRecord],
    intraday_bars: Sequence[IntradayBar] = (),
) -> B2ConfirmationEvaluation:
    features = compute_features(
        ordered=ordered,
        indicators=indicators,
        as_of=as_of,
        config=config,
        anchor=anchor,
        limit_pool=limit_pool,
        intraday_bars=intraday_bars,
    )
    current = ordered[-1]

    structure_values, structure_max, structure_reasons, structure_missing = (
        _structure_components(
            config=config,
            score=score,
            features=features,
            b1_conditions=b1_conditions,
            support=support,
            current=current,
        )
    )
    launch_values, launch_max, launch_reasons, launch_risks, launch_missing = (
        _launch_components(config=config, features=features)
    )
    missing = tuple(sorted(set(structure_missing) | set(launch_missing)))
    available_max = sum(
        value
        for key, value in (
            *structure_max.items(),
            *launch_max.items(),
        )
        if key not in missing
    )
    structure_score = sum(structure_values.values(), ZERO)
    launch_score = sum(launch_values.values(), ZERO)
    b2_confirm_score = structure_score + launch_score
    normalized = (
        _quantize(b2_confirm_score / available_max * Decimal("100"))
        if available_max > ZERO
        else ZERO
    )

    volume_ratio = features.pullback_volume_ratio
    current_indicator = indicators[-1]
    hard_fail_reason: str | None = None
    if setup_stage is SetupStage.INVALID or invalidation_reasons:
        hard_fail_reason = "STRUCTURE_INVALIDATED"
    elif invalid_price is not None and current.close <= invalid_price:
        hard_fail_reason = "CLOSED_BELOW_INVALID_PRICE"
    elif (
        volume_ratio is not None
        and volume_ratio >= VOLUME_DISTRIBUTION_MAX
        and current.close < current.open
        and current_indicator.kline.is_long_bearish
    ):
        hard_fail_reason = "VOLUME_DISTRIBUTION"

    raw_level = (
        B2ConfirmationLevel.NONE
        if hard_fail_reason is not None
        else _level_from_score(b2_confirm_score, config)
    )
    # Close > VWAP is a strong-confirmation prerequisite: without a confirmed
    # close above VWAP the best possible level is CONFIRMED, never STRONG.
    if (
        raw_level is B2ConfirmationLevel.STRONG_CONFIRMED
        and features.close_above_vwap is not True
    ):
        level = B2ConfirmationLevel.CONFIRMED
    else:
        level = raw_level
    reasons = tuple(
        sorted(set((*structure_reasons, *launch_reasons)))
    )
    risks = tuple(
        sorted(
            set(
                launch_risks
                + (("STRUCTURE_FAIL",) if hard_fail_reason is not None else ())
            )
        )
    )
    if not reasons:
        reasons = ("STRUCTURE_EVALUATED",)

    return B2ConfirmationEvaluation(
        trade_date=as_of,
        code=current.code,
        setup_stage=setup_stage,
        features=features,
        structure_score=_quantize(structure_score),
        launch_score=_quantize(launch_score),
        b2_confirm_score=_quantize(b2_confirm_score),
        available_max_score=_quantize(available_max),
        normalized_score=normalized,
        level=level,
        hard_fail=hard_fail_reason is not None,
        hard_fail_reason=hard_fail_reason,
        reasons=reasons,
        risks=risks,
        structure_components={
            key: _quantize(value) for key, value in structure_values.items()
        },
        launch_components={
            key: _quantize(value) for key, value in launch_values.items()
        },
        missing_components=missing,
    )


def rank_b1_setup(
    signals: Sequence[StrategySignal],
    names: Mapping[str, str] | None = None,
) -> tuple[B1SetupRankRow, ...]:
    """B1 latent ranking, deterministic; no filesystem/insertion order."""

    names = names or {}
    rows: list[B1SetupRankRow] = []
    for signal in signals:
        if signal.anchor is None or signal.setup_stage not in B1_RANK_STAGES:
            continue
        features = (
            signal.b2_confirmation.features
            if signal.b2_confirmation is not None
            else None
        )
        support = signal.support
        rows.append(
            B1SetupRankRow(
                code=signal.code,
                name=names.get(signal.code, ""),
                t0_date=signal.anchor.anchor_date,
                t0_quality=(
                    features.t0_quality
                    if features is not None
                    else "D"
                ),
                pullback_days=(
                    features.days_after_anchor if features is not None else 0
                ),
                b1_zone_low=support.support_low if support is not None else None,
                b1_zone_high=support.support_high if support is not None else None,
                support_low=support.support_low if support is not None else None,
                support_high=support.support_high if support is not None else None,
                pullback_volume_ratio=(
                    features.pullback_volume_ratio
                    if features is not None
                    else None
                ),
                b1_score=signal.setup_quality_score,
                current_stage=signal.setup_stage,
            )
        )
    rows.sort(
        key=lambda row: (
            -row.b1_score,
            row.pullback_volume_ratio
            if row.pullback_volume_ratio is not None
            else Decimal("inf"),
            row.pullback_days,
            row.code,
        )
    )
    return tuple(rows)


def rank_b2_launch(
    signals: Sequence[StrategySignal],
    names: Mapping[str, str] | None = None,
) -> tuple[B2LaunchRankRow, ...]:
    """B2 launch ranking; hard-failed structures are excluded."""

    names = names or {}
    t0_rank = {"A": 0, "B": 1, "C": 2, "D": 3}
    rows: list[B2LaunchRankRow] = []
    for signal in signals:
        evaluation = signal.b2_confirmation
        if (
            evaluation is None
            or evaluation.hard_fail
            or signal.setup_stage not in B2_RANK_STAGES
        ):
            continue
        features = evaluation.features
        rows.append(
            B2LaunchRankRow(
                code=signal.code,
                name=names.get(signal.code, ""),
                t0_date=features.t0_date,
                t0_quality=features.t0_quality,
                pullback_days=features.days_after_anchor,
                day_return_pct=features.day_return_pct,
                intraday_max_return_pct=features.intraday_max_return_pct,
                close_above_vwap=features.close_above_vwap,
                turnover_rate=features.turnover_rate,
                ma5=features.ma5,
                ma10=features.ma10,
                ma20=features.ma20,
                pullback_volume_ratio=features.pullback_volume_ratio,
                b2_confirm_score=evaluation.b2_confirm_score,
                structure_score=evaluation.structure_score,
                b2_confirm_level=evaluation.level,
                current_stage=signal.setup_stage,
            )
        )
    rows.sort(
        key=lambda row: (
            -row.b2_confirm_score,
            -row.structure_score,
            t0_rank[row.t0_quality],
            row.pullback_volume_ratio
            if row.pullback_volume_ratio is not None
            else Decimal("inf"),
            row.code,
        )
    )
    return tuple(rows)
