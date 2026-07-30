"""Limit-up anchors and order-independent price structure."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import ScoreProfile
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.signal import AnchorSnapshot
from limit_pullback.models.strategy import (
    AnchorEvaluation,
    IndicatorPoint,
    PriceCluster,
    PriceLevelCandidate,
)


ONE = Decimal("1")


def theoretical_limit_price(bar: DailyBar, config: StrategyConfig) -> Decimal:
    tick = config.anchor.price_tick
    ticks = (
        bar.preclose * (ONE + config.anchor.limit_rate) / tick
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (ticks * tick).quantize(tick, rounding=ROUND_HALF_UP)


def _at_price(value: Decimal, target: Decimal, tolerance: Decimal) -> bool:
    return abs(value - target) <= tolerance


def is_limit_close(bar: DailyBar, config: StrategyConfig) -> bool:
    return _at_price(
        bar.close,
        theoretical_limit_price(bar, config),
        config.anchor.limit_price_tolerance,
    )


def is_one_word_limit(bar: DailyBar, config: StrategyConfig) -> bool:
    limit_price = theoretical_limit_price(bar, config)
    tolerance = config.anchor.limit_price_tolerance
    return all(
        _at_price(value, limit_price, tolerance)
        for value in (bar.open, bar.high, bar.low, bar.close)
    )


def is_t_word_limit(bar: DailyBar, config: StrategyConfig) -> bool:
    limit_price = theoretical_limit_price(bar, config)
    tolerance = config.anchor.limit_price_tolerance
    return (
        _at_price(bar.open, limit_price, tolerance)
        and _at_price(bar.high, limit_price, tolerance)
        and _at_price(bar.close, limit_price, tolerance)
        and bar.low < limit_price - tolerance
    )


def _pool_record_is_full(record: LimitUpRecord | None) -> bool:
    return (
        record is not None
        and record.first_seal_time is not None
        and record.last_seal_time is not None
        and record.open_count is not None
        and record.consecutive_count is not None
    )


def detect_anchor(
    bars: Sequence[DailyBar],
    as_of: date,
    config: StrategyConfig,
    limit_pool: Sequence[LimitUpRecord] = (),
) -> AnchorEvaluation | None:
    ordered = tuple(sorted(
        (bar for bar in bars if bar.trade_date <= as_of),
        key=lambda bar: bar.trade_date,
    ))
    if not ordered:
        return None
    pool_by_key = {
        (record.trade_date, record.code): record
        for record in limit_pool
        if record.trade_date <= as_of
    }
    start = max(0, len(ordered) - config.anchor.lookback_trade_days)
    recent_limit_indices = tuple(
        index
        for index in range(start, len(ordered))
        if is_limit_close(ordered[index], config)
    )
    if not recent_limit_indices:
        return None

    # A later limit-up changes the setup context even when that later bar is
    # itself an invalid anchor (for example a second board or one-word board).
    for index in (recent_limit_indices[-1],):
        bar = ordered[index]
        limit_price = theoretical_limit_price(bar, config)
        one_word = is_one_word_limit(bar, config)
        t_word = is_t_word_limit(bar, config)
        if not is_limit_close(bar, config) or one_word or t_word:
            continue
        if (
            config.anchor.require_positive_volume and bar.volume <= 0
        ) or (
            config.anchor.require_positive_amount and bar.amount <= 0
        ):
            continue

        recent_start = max(0, index - config.anchor.recent_limit_window + 1)
        recent_indices = tuple(
            candidate_index
            for candidate_index in range(recent_start, index + 1)
            if is_limit_close(ordered[candidate_index], config)
        )
        recent_count = len(recent_indices)
        if not (
            config.anchor.recent_limit_count_min
            <= recent_count
            <= config.anchor.recent_limit_count_max
        ):
            continue
        non_consecutive = all(
            right - left > 1
            for left, right in zip(recent_indices, recent_indices[1:])
        )
        if config.anchor.require_non_consecutive and not non_consecutive:
            continue

        inferred_first_board = index > 0 and not is_limit_close(
            ordered[index - 1], config
        )
        if config.anchor.require_first_board and not inferred_first_board:
            continue

        record = pool_by_key.get((bar.trade_date, bar.code))
        full = _pool_record_is_full(record)
        profile = ScoreProfile.FULL if full else ScoreProfile.PRICE_ONLY
        seal_before_cutoff: bool | None = None
        if full:
            assert record is not None and record.first_seal_time is not None
            if record.consecutive_count != 1:
                continue
            seal_before_cutoff = (
                record.first_seal_time <= config.anchor.first_seal_cutoff
            )
            if not seal_before_cutoff:
                continue

        return AnchorEvaluation(
            snapshot=AnchorSnapshot(
                anchor_date=bar.trade_date,
                anchor_price=limit_price,
                frozen_as_of=bar.trade_date,
                source=profile.value,
            ),
            profile=profile,
            limit_price=limit_price,
            is_limit_close=True,
            is_one_word=one_word,
            is_t_word=t_word,
            is_first_board=inferred_first_board,
            recent_limit_count=recent_count,
            recent_limits_non_consecutive=non_consecutive,
            seal_before_cutoff=seal_before_cutoff,
            pool_record=record if full else None,
        )
    return None


def cluster_price_candidates(
    candidates: Sequence[PriceLevelCandidate],
    distance: Decimal,
) -> tuple[PriceCluster, ...]:
    """Complete-link-style clustering, deterministic for every input order."""

    ordered = tuple(sorted(candidates, key=lambda item: (item.value, item.source)))
    if not ordered:
        return ()
    groups: list[list[PriceLevelCandidate]] = []
    current: list[PriceLevelCandidate] = []
    cluster_low: Decimal | None = None
    for candidate in ordered:
        if not current:
            current = [candidate]
            cluster_low = candidate.value
            continue
        assert cluster_low is not None
        if candidate.value / cluster_low - ONE <= distance:
            current.append(candidate)
        else:
            groups.append(current)
            current = [candidate]
            cluster_low = candidate.value
    groups.append(current)

    clusters = []
    for group in groups:
        values = tuple(item.value for item in group)
        clusters.append(
            PriceCluster(
                low=min(values),
                high=max(values),
                center=sum(values, Decimal("0")) / Decimal(len(values)),
                sources=tuple(sorted({item.source for item in group})),
            )
        )
    return tuple(clusters)


def generate_support_candidates(
    bars: Sequence[DailyBar],
    indicators: Sequence[IndicatorPoint],
    anchor: AnchorEvaluation,
    as_of: date,
    config: StrategyConfig,
) -> tuple[PriceLevelCandidate, ...]:
    ordered = tuple(sorted(
        (bar for bar in bars if bar.trade_date <= as_of),
        key=lambda bar: bar.trade_date,
    ))
    candidates = [
        PriceLevelCandidate(source="ANCHOR_PRICE", value=anchor.snapshot.anchor_price)
    ]
    pre_anchor = tuple(
        bar for bar in ordered if bar.trade_date < anchor.snapshot.anchor_date
    )[-config.support.platform_lookback_days :]
    if pre_anchor:
        candidates.append(
            PriceLevelCandidate(
                source="PLATFORM_HIGH_20",
                value=max(bar.high for bar in pre_anchor),
            )
        )
    current_indicator = next(
        (point for point in reversed(indicators) if point.trade_date <= as_of),
        None,
    )
    if current_indicator is not None:
        for window in config.support.moving_average_sources:
            value = current_indicator.raw_equivalent_mas.get(window)
            if value is not None:
                candidates.append(
                    PriceLevelCandidate(source=f"MA{window}", value=value)
                )
    return tuple(candidates)


def select_support_cluster(
    clusters: Sequence[PriceCluster],
    current_close: Decimal,
    config: StrategyConfig,
) -> PriceCluster | None:
    nearby = tuple(
        cluster
        for cluster in clusters
        if cluster.low <= current_close * (ONE + config.support.cluster_distance)
    )
    if not nearby:
        return None

    def rank(cluster: PriceCluster) -> tuple[Decimal, int, int, Decimal]:
        key_source = int(
            "ANCHOR_PRICE" in cluster.sources or "MA10" in cluster.sources
        )
        return (
            abs(current_close - cluster.center) / current_close,
            -len(cluster.sources),
            -key_source,
            cluster.low,
        )

    return min(nearby, key=rank)


def generate_resistance_candidates(
    bars: Sequence[DailyBar],
    anchor: AnchorEvaluation,
    as_of: date,
    config: StrategyConfig,
) -> tuple[PriceLevelCandidate, ...]:
    ordered = tuple(sorted(
        (bar for bar in bars if bar.trade_date <= as_of),
        key=lambda bar: bar.trade_date,
    ))
    pre_anchor = tuple(
        bar for bar in ordered if bar.trade_date < anchor.snapshot.anchor_date
    )
    post_anchor = tuple(
        bar for bar in ordered if bar.trade_date > anchor.snapshot.anchor_date
    )
    candidates: list[PriceLevelCandidate] = []
    left = pre_anchor[-config.resistance.left_high_lookback_days :]
    if left:
        candidates.append(
            PriceLevelCandidate(
                source="LEFT_HIGH_60",
                value=max(bar.high for bar in left),
            )
        )
    recent = ordered[-config.resistance.recent_high_lookback_days :]
    if recent:
        candidates.append(
            PriceLevelCandidate(
                source="RECENT_HIGH_20",
                value=max(bar.high for bar in recent),
            )
        )
    first_window = post_anchor[: config.resistance.first_post_anchor_window_days]
    if first_window:
        candidates.append(
            PriceLevelCandidate(
                source="FIRST_POST_ANCHOR_HIGH",
                value=max(bar.high for bar in first_window),
            )
        )
    return tuple(candidates)


def select_resistance_cluster(
    clusters: Sequence[PriceCluster],
    current_close: Decimal,
) -> PriceCluster | None:
    overhead = tuple(cluster for cluster in clusters if cluster.low > current_close)
    if not overhead:
        return None
    return min(overhead, key=lambda cluster: (cluster.low, -len(cluster.sources)))
