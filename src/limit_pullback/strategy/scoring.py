"""Explainable FULL and PRICE_ONLY score construction."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import ScoreProfile, SetupStage
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.signal import ScoreBreakdown
from limit_pullback.models.strategy import (
    AnchorEvaluation,
    ConditionScore,
    IndicatorPoint,
    PatternEvaluation,
    PriceCluster,
)


ZERO = Decimal("0")
ONE = Decimal("1")


def _fractional_score(maximum: Decimal, fraction: Decimal) -> Decimal:
    return maximum * min(max(fraction, ZERO), ONE)


def build_score(
    *,
    config: StrategyConfig,
    profile: ScoreProfile,
    bars: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    current: DailyBar,
    anchor: AnchorEvaluation | None,
    support: PriceCluster | None,
    patterns: PatternEvaluation | None,
    b1_conditions: ConditionScore | None,
    b2_conditions: ConditionScore | None,
    setup_stage: SetupStage,
    limit_pool: Sequence[LimitUpRecord],
) -> ScoreBreakdown:
    profile_config = config.scoring.profiles[profile]
    maxima = profile_config.rule_max_scores
    indicator_by_date = {point.trade_date: point for point in indicators}
    bar_by_date = {bar.trade_date: bar for bar in bars}
    values: dict[str, Decimal | None] = {}
    positive: dict[str, str] = {}
    negative: dict[str, str] = {}

    def boolean_rule(
        rule_id: str,
        result: bool | None,
        good: str,
        bad: str,
    ) -> None:
        if rule_id not in maxima:
            return
        if result is None:
            values[rule_id] = None
        elif result:
            values[rule_id] = maxima[rule_id]
            positive[rule_id] = good
        else:
            values[rule_id] = ZERO
            negative[rule_id] = bad

    boolean_rule(
        "normal_liquidity",
        current.volume > 0 and current.amount > 0,
        "成交量和成交额有效",
        "成交量或成交额无效",
    )

    if anchor is None:
        for rule_id in maxima:
            values.setdefault(rule_id, None)
    else:
        anchor_bar = bar_by_date[anchor.snapshot.anchor_date]
        anchor_index = tuple(bars).index(anchor_bar)
        pre_anchor_indicator = (
            indicator_by_date[bars[anchor_index - 1].trade_date]
            if anchor_index > 0
            else None
        )
        anchor_indicator = indicator_by_date[anchor.snapshot.anchor_date]
        boolean_rule(
            "limit_close",
            anchor.is_limit_close,
            "锚点以涨停价收盘",
            "锚点未以涨停价收盘",
        )
        boolean_rule(
            "non_one_word",
            not anchor.is_one_word,
            "锚点不是一字板",
            "锚点为一字板",
        )
        boolean_rule(
            "non_t_board",
            not anchor.is_t_word,
            "锚点不是T字板",
            "锚点为T字板",
        )
        boolean_rule(
            "first_board",
            anchor.is_first_board,
            "价格序列确认首板",
            "前一交易日也涨停",
        )
        boolean_rule(
            "seal_before_cutoff",
            anchor.seal_before_cutoff,
            "首次封板不晚于配置截止时间",
            "首次封板晚于配置截止时间",
        )

        if "position_120" in maxima:
            position = (
                pre_anchor_indicator.position_120
                if pre_anchor_indicator is not None
                else None
            )
            if position is None:
                values["position_120"] = None
            else:
                thresholds = config.indicators.position_thresholds
                if position <= thresholds.high_score_max:
                    fraction = ONE
                elif position <= thresholds.medium_score_max:
                    fraction = Decimal("0.75")
                elif position <= thresholds.low_score_max:
                    fraction = Decimal("0.25")
                else:
                    fraction = ZERO
                values["position_120"] = _fractional_score(
                    maxima["position_120"], fraction
                )
                (
                    positive if fraction >= Decimal("0.75") else negative
                )["position_120"] = f"涨停前120日位置={position}"

        if "ma_compression" in maxima:
            compression = (
                pre_anchor_indicator.ma_compression
                if pre_anchor_indicator is not None
                else None
            )
            if compression is None:
                values["ma_compression"] = None
            else:
                thresholds = config.indicators.ma_compression_thresholds
                if compression <= thresholds.high_max:
                    fraction = ONE
                elif compression <= thresholds.good_max:
                    fraction = Decimal("0.75")
                elif compression <= thresholds.normal_max:
                    fraction = Decimal("0.40")
                else:
                    fraction = ZERO
                values["ma_compression"] = _fractional_score(
                    maxima["ma_compression"], fraction
                )
                (
                    positive if fraction >= Decimal("0.75") else negative
                )["ma_compression"] = f"涨停前均线粘合={compression}"

        ma_values = tuple(
            anchor_indicator.raw_equivalent_mas.get(window)
            for window in (5, 10, 20)
        )
        bullish_cross = (
            anchor_bar.close > max(value for value in ma_values if value is not None)
            and sum(
                anchor_bar.open < value
                for value in ma_values
                if value is not None
            ) >= 2
            if all(value is not None for value in ma_values)
            else None
        )
        boolean_rule(
            "bullish_cross_ma",
            bullish_cross,
            "涨停K线一阳穿多线",
            "未形成一阳穿多线",
        )

        if patterns is not None:
            air = patterns.air_refuel
            bearish = patterns.bearish_pullback

            def condition_result(
                score: ConditionScore,
                condition: str,
            ) -> bool | None:
                if condition in score.matched:
                    return True
                if condition in score.failed:
                    return False
                return None

            boolean_rule(
                "price_retention",
                condition_result(air, "post_anchor_close_floor"),
                "涨停后价格保持",
                "涨停后价格保持不足",
            )
            boolean_rule(
                "amplitude_contraction",
                condition_result(air, "amplitude_contraction"),
                "涨停后振幅收窄",
                "涨停后振幅未收窄",
            )
            volume_results = tuple(
                result
                for result in (
                    condition_result(air, "volume_contraction"),
                    condition_result(bearish, "volume_contraction"),
                )
                if result is not None
            )
            boolean_rule(
                "volume_contraction",
                any(volume_results) if volume_results else None,
                "回调成交量收缩",
                "回调成交量未收缩",
            )
            boolean_rule(
                "no_volume_break",
                condition_result(bearish, "no_volume_break"),
                "未出现放量破位",
                "出现放量破位",
            )
            boolean_rule(
                "stabilization",
                condition_result(bearish, "stabilization"),
                "当前K线出现止跌形态",
                "当前K线缺少止跌形态",
            )

        if support is None:
            for rule_id in (
                "support_sources",
                "support_key_source",
                "support_not_broken",
            ):
                if rule_id in maxima:
                    values[rule_id] = None
        else:
            if "support_sources" in maxima:
                fraction = min(
                    Decimal(len(support.sources)) / Decimal("3"),
                    ONE,
                )
                values["support_sources"] = _fractional_score(
                    maxima["support_sources"], fraction
                )
                (
                    positive if fraction >= Decimal("0.66") else negative
                )["support_sources"] = f"支撑簇来源数={len(support.sources)}"
            boolean_rule(
                "support_key_source",
                "ANCHOR_PRICE" in support.sources or "MA10" in support.sources,
                "支撑簇包含涨停价或MA10",
                "支撑簇缺少涨停价和MA10",
            )
            boolean_rule(
                "support_not_broken",
                current.close
                >= support.low * (ONE - config.support.invalid_buffer),
                "收盘守住支撑下沿",
                "收盘跌破支撑下沿",
            )

        boolean_rule(
            "b1_quality",
            (
                b1_conditions.match_ratio >= config.b1.minimum_condition_ratio
                if b1_conditions is not None and b1_conditions.available_count
                else None
            ),
            "B1条件达到多数阈值",
            "B1条件未达到多数阈值",
        )
        if "b2_quality" in maxima:
            if setup_stage is SetupStage.B2_CONFIRMED:
                values["b2_quality"] = maxima["b2_quality"]
                positive["b2_quality"] = "B2已使用预先冻结触发价确认"
            elif setup_stage is SetupStage.B2_READY:
                values["b2_quality"] = maxima["b2_quality"] * Decimal("0.50")
                positive["b2_quality"] = "B2触发价已冻结待确认"
            elif b2_conditions is None:
                values["b2_quality"] = None
            else:
                values["b2_quality"] = ZERO
                negative["b2_quality"] = "B2尚未就绪"

        if "industry_resonance" in maxima:
            record = anchor.pool_record
            if record is None or not record.industry:
                values["industry_resonance"] = None
            else:
                count = sum(
                    item.trade_date == anchor.snapshot.anchor_date
                    and item.industry == record.industry
                    for item in limit_pool
                )
                fraction = (
                    ONE if count >= 3
                    else Decimal("0.60") if count == 2
                    else Decimal("0.20")
                )
                values["industry_resonance"] = _fractional_score(
                    maxima["industry_resonance"], fraction
                )
                positive["industry_resonance"] = f"锚点日同行业涨停数={count}"

    component_scores: dict[str, Decimal] = {}
    component_max_scores: dict[str, Decimal] = {}
    unavailable: list[str] = []
    quality_flags: list[str] = []
    for rule_id, maximum in maxima.items():
        value = values.get(rule_id)
        if value is None:
            unavailable.append(rule_id)
            quality_flags.append(
                f"{config.quality.missing_score_flag_prefix}{rule_id}"
            )
        else:
            component_scores[rule_id] = value
            component_max_scores[rule_id] = maximum

    return ScoreBreakdown(
        profile=profile,
        profile_max_score=profile_config.profile_max_score,
        component_scores=component_scores,
        component_max_scores=component_max_scores,
        unavailable_rules=tuple(sorted(unavailable)),
        reasons={
            key: value for key, value in positive.items()
            if key in component_scores
        },
        risks={
            key: value for key, value in negative.items()
            if key in component_scores
        },
        quality_flags=tuple(sorted(quality_flags)),
    )
