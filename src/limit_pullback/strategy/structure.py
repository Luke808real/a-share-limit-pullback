"""Limit-up anchors and order-independent price structure."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from limit_pullback.models.config import StrategyConfig
from limit_pullback.models.enums import ScoreProfile
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.models.signal import (
    AnchorSnapshot,
    ResistanceCandidateSnapshot,
    ResistanceClusterSnapshot,
)
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
        if (
            ordered[index].trade_status
            and ordered[index].is_st is not True
            and is_limit_close(ordered[index], config)
        )
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
        low = min(values)
        high = max(values)
        arithmetic_mean = sum(values, Decimal("0")) / Decimal(len(values))
        center = min(max(arithmetic_mean, low), high)
        clusters.append(
            PriceCluster(
                low=low,
                high=high,
                center=center,
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
        if (
            cluster.center
            <= current_close
            * (ONE + config.support.max_above_reference_close)
        )
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

    def append_highest(
        source_prefix: str,
        values: Sequence[DailyBar],
    ) -> None:
        if not values:
            return
        selected = max(
            values,
            key=lambda bar: (bar.high, bar.trade_date),
        )
        candidates.append(
            PriceLevelCandidate(
                source=f"{source_prefix}:{selected.trade_date.isoformat()}",
                value=selected.high,
            )
        )

    left = pre_anchor[-config.resistance.left_high_lookback_days :]
    append_highest("PRE_ANCHOR_LEFT_HIGH", left)
    recent = ordered[-config.resistance.recent_high_lookback_days :]
    append_highest("RECENT_HIGH_20", recent)
    long_recent = ordered[
        -config.resistance.long_recent_high_lookback_days :
    ]
    append_highest("RECENT_HIGH_60", long_recent)
    first_window = post_anchor[: config.resistance.first_post_anchor_window_days]
    append_highest("FIRST_POST_ANCHOR_HIGH", first_window)

    dense_window = tuple(long_recent)
    for index in range(1, len(dense_window) - 1):
        previous_bar = dense_window[index - 1]
        bar = dense_window[index]
        following_bar = dense_window[index + 1]
        if (
            bar.high >= previous_bar.high
            and bar.high >= following_bar.high
            and (
                bar.high > previous_bar.high
                or bar.high > following_bar.high
            )
        ):
            candidates.append(
                PriceLevelCandidate(
                    source=f"DENSE_SWING_HIGH:{bar.trade_date.isoformat()}",
                    value=bar.high,
                )
            )
    return tuple(candidates)


def select_resistance_levels(
    candidates: Sequence[PriceLevelCandidate],
    *,
    anchor_price: Decimal,
    support: PriceCluster,
    reference_close: Decimal,
    expected_b2_trigger: Decimal,
    config: StrategyConfig,
) -> tuple[
    PriceCluster | None,
    PriceCluster | None,
    tuple[ResistanceCandidateSnapshot, ...],
    Decimal,
]:
    """Select immediate and target resistance with deterministic exclusions."""

    anchor_reference = PriceLevelCandidate(
        source="ANCHOR_PRICE_REFERENCE",
        value=anchor_price,
    )
    support_references = (
        PriceLevelCandidate(
            source="SUPPORT_LOW_REFERENCE",
            value=support.low,
        ),
        PriceLevelCandidate(
            source="SUPPORT_HIGH_REFERENCE",
            value=support.high,
        ),
    )
    clusters = cluster_price_candidates(
        (*candidates, anchor_reference, *support_references),
        config.resistance.cluster_distance,
    )

    def excluded_reason(cluster: PriceCluster) -> str | None:
        sources = set(cluster.sources)
        if "ANCHOR_PRICE_REFERENCE" in sources:
            return "ANCHOR_CLUSTER_OVERLAP"
        if sources & {"SUPPORT_LOW_REFERENCE", "SUPPORT_HIGH_REFERENCE"}:
            return "SUPPORT_CLUSTER_OVERLAP"
        if cluster.low <= reference_close:
            return "NOT_ABOVE_REFERENCE_PRICE"
        return None

    valid_clusters = tuple(
        cluster
        for cluster in clusters
        if excluded_reason(cluster) is None
    )
    immediate = (
        min(
            valid_clusters,
            key=lambda cluster: (
                cluster.low,
                -len(cluster.sources),
                cluster.center,
            ),
        )
        if valid_clusters
        else None
    )
    immediate_is_b2_platform = (
        immediate is not None
        and immediate.low
        <= expected_b2_trigger * (ONE + config.resistance.cluster_distance)
        and immediate.high
        >= expected_b2_trigger * (ONE - config.resistance.cluster_distance)
    )
    target_clusters = tuple(
        cluster
        for cluster in valid_clusters
        if (
            cluster.low > expected_b2_trigger
            and not (immediate_is_b2_platform and cluster == immediate)
        )
    )
    target = (
        min(
            target_clusters,
            key=lambda cluster: (
                cluster.low,
                -len(cluster.sources),
                cluster.center,
            ),
        )
        if target_clusters
        else None
    )

    audit: list[ResistanceCandidateSnapshot] = []
    for candidate in sorted(candidates, key=lambda item: (item.value, item.source)):
        cluster = next(
            cluster
            for cluster in clusters
            if (
                candidate.source in cluster.sources
                and cluster.low <= candidate.value <= cluster.high
            )
        )
        reason = excluded_reason(cluster)
        selected_reason: str | None = None
        if cluster == immediate and cluster == target:
            selected_reason = "SELECTED_IMMEDIATE_AND_TARGET_S1"
        elif cluster == immediate:
            selected_reason = "SELECTED_IMMEDIATE_RESISTANCE"
        elif cluster == target:
            selected_reason = "SELECTED_TARGET_S1"

        if (
            reason is None
            and immediate_is_b2_platform
            and cluster == immediate
        ):
            reason = "EXPECTED_B2_PLATFORM_CLUSTER"
        elif reason is None and cluster.low <= expected_b2_trigger:
            reason = "NOT_ABOVE_EXPECTED_B2_TRIGGER"
        elif (
            reason is None
            and target is not None
            and cluster.low > target.low
        ):
            reason = "HIGHER_THAN_NEAREST_VALID_TARGET"

        audit.append(
            ResistanceCandidateSnapshot(
                source=candidate.source,
                price=candidate.value,
                cluster=ResistanceClusterSnapshot(
                    low=cluster.low,
                    high=cluster.high,
                    center=cluster.center,
                    sources=cluster.sources,
                ),
                excluded_reason=reason,
                selected_reason=selected_reason,
            )
        )
    return immediate, target, tuple(audit), expected_b2_trigger
