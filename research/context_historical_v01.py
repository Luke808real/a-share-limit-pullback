"""Historical Context Validation V0.1 (H1 weekly, H4 price/volume, JOINT).

Reads corrected frozen episodes and Phase 2D.1A execution-reality outcomes.
Never calls evaluate_strategy, replay, screen, or providers.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from statistics import mean, median

import pyarrow as pa
import pyarrow.parquet as pq

from limit_pullback.forward_overlay import (
    build_weekly_bars,
    classify_weekly_context,
    weekly_metrics,
)
from limit_pullback.forward_overlay_v02 import (
    price_volume_interpretation,
    support_class_v02,
)


ROOT = Path("/Users/luke808/AI/V flash")
EPISODES = ROOT / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet"
EXEC = ROOT / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/execution-reality/execution_episodes.parquet"
DAILY = ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"
OUT = ROOT / "data/outcome-study/context-historical-v01"


def dec(value: object) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def feature_for(episode: dict, bars: list[dict]) -> dict:
    if len(bars) < 6:
        return {"weekly_context": "UNKNOWN", "pv_interpretation": "INSUFFICIENT_EVIDENCE"}
    signal_date = episode["signal_date"]
    bars_up_to = [bar for bar in bars if bar["trade_date"] <= signal_date]
    if len(bars_up_to) < 6:
        return {"weekly_context": "UNKNOWN", "pv_interpretation": "INSUFFICIENT_EVIDENCE"}
    weekly = weekly_metrics(build_weekly_bars(bars_up_to, signal_date))
    weekly_context, _ = classify_weekly_context(weekly)
    support_low = dec(episode.get("support_low")) or Decimal("0")
    invalid = dec(episode.get("invalid_price")) or Decimal("0")
    current = bars_up_to[-1]
    support_class, support_severity = support_class_v02(
        low=dec(current["low"]),
        close=dec(current["close"]),
        support_low=support_low,
        invalid=invalid,
    )
    volumes = [dec(row["volume"]) for row in bars_up_to]
    prior5 = mean(volumes[-6:-1]) if len(volumes) >= 6 else None
    current_volume_ratio = volumes[-1] / prior5 if prior5 and prior5 > 0 else None
    anchor_date = episode.get("anchor_date")
    anchor_volume_ratio = None
    pullback_median = None
    pullback_ratio = None
    if anchor_date is not None:
        anchor_index = next(
            (i for i, row in enumerate(bars_up_to) if row["trade_date"] == anchor_date),
            None,
        )
        if anchor_index is not None:
            anchor_vol = volumes[anchor_index]
            prior = volumes[max(0, anchor_index - 5):anchor_index]
            prior_mean = mean(prior) if prior else None
            anchor_volume_ratio = (
                anchor_vol / prior_mean if prior_mean and prior_mean > 0 else None
            )
            pullback_rows = bars_up_to[anchor_index + 1:]
            pullback_median = (
                median([dec(row["volume"]) for row in pullback_rows])
                if pullback_rows
                else None
            )
            pullback_ratio = (
                pullback_median / anchor_vol
                if pullback_median is not None and anchor_vol
                else None
            )
    had_bearish = False
    for index in range(max(0, len(bars_up_to) - 3), len(bars_up_to)):
        row = bars_up_to[index]
        causal = volumes[max(0, index - 5):index]
        causal_base = mean(causal) if causal else None
        prev_close = dec(bars_up_to[index - 1]["close"]) if index > 0 else None
        if (
            causal_base
            and causal_base > 0
            and dec(row["volume"]) > causal_base * Decimal("1.5")
            and dec(row["close"]) < dec(row["open"])
            and (prev_close is None or dec(row["close"]) < prev_close)
        ):
            had_bearish = True
    high = dec(current["high"])
    low = dec(current["low"])
    close = dec(current["close"])
    open_price = dec(current["open"])
    upper_shadow = (
        (high - max(open_price, close)) / (high - low)
        if high and low and high > low
        else None
    )
    pv = price_volume_interpretation(
        support_class=support_class,
        support_severity=support_severity,
        weekly_context=weekly_context,
        weekly_volume_ratio=weekly.get("weekly_volume_ratio"),
        weekly_return_4w=weekly.get("return_4w"),
        current_volume_ratio=current_volume_ratio,
        had_bearish_bar=had_bearish,
        close_above_support=close >= support_low,
        insufficient_evidence=len(bars_up_to) < 6,
    )
    return {
        "weekly_position_52w": weekly.get("weekly_position_52w"),
        "weekly_return_4w": weekly.get("return_4w"),
        "weekly_return_12w": weekly.get("return_12w"),
        "weekly_ma10": weekly.get("ma10_week"),
        "weekly_ma20": weekly.get("ma20_week"),
        "weekly_ma10_direction": weekly.get("ma10_direction"),
        "weekly_volume_ratio": weekly.get("weekly_volume_ratio"),
        "higher_highs_4w": weekly.get("higher_highs"),
        "higher_lows_4w": weekly.get("higher_lows"),
        "weekly_context": weekly_context,
        "anchor_volume_ratio_vs_prior5": anchor_volume_ratio,
        "post_anchor_pullback_median_volume": pullback_median,
        "pullback_volume_ratio_vs_anchor": pullback_ratio,
        "current_volume_ratio": current_volume_ratio,
        "had_bearish_pullback_bar": had_bearish,
        "upper_shadow_fact": upper_shadow,
        "current_support_class": support_class,
        "current_support_severity": support_severity,
        "price_volume_interpretation": pv,
    }


def build_feature_rows() -> list[dict]:
    episodes = pq.read_table(EPISODES).to_pylist()
    exec_rows = pq.read_table(EXEC).to_pylist()
    for row in episodes:
        if isinstance(row["signal_date"], str):
            row["signal_date"] = date.fromisoformat(row["signal_date"])
        if row.get("anchor_date") is not None and isinstance(row["anchor_date"], str):
            row["anchor_date"] = date.fromisoformat(row["anchor_date"])
    for row in exec_rows:
        if isinstance(row["signal_date"], str):
            row["signal_date"] = date.fromisoformat(row["signal_date"])
    exec_by_key = {
        (str(row["code"]), str(row["setup_id"]), row["signal_date"]): row
        for row in exec_rows
    }
    episodes_by_code: dict[str, list[dict]] = defaultdict(list)
    for row in episodes:
        episodes_by_code[str(row["code"])].append(row)
    output: list[dict] = []
    pf = pq.ParquetFile(DAILY)
    columns = [
        "code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "reconciliation_status",
    ]
    current_code = None
    bars: list[dict] = []
    for batch in pf.iter_batches(columns=columns, batch_size=8192, use_threads=False):
        for row in batch.to_pylist():
            if row["reconciliation_status"] != "CONFIRMED":
                continue
            code = str(row["code"])
            if code != current_code:
                if current_code is not None and current_code in episodes_by_code:
                    for ep in sorted(
                        episodes_by_code[current_code],
                        key=lambda item: item["signal_date"],
                    ):
                        feats = feature_for(ep, bars)
                        key = (current_code, str(ep["setup_id"]), ep["signal_date"])
                        ex = exec_by_key.get(key)
                        output.append(
                            {
                                "code": current_code,
                                "setup_id": str(ep["setup_id"]),
                                "signal_date": ep["signal_date"],
                                "execution_label": ep["execution_label"],
                                "is_entry_candidate": bool(ep["is_entry_candidate"]),
                                **feats,
                                "conservative_net_execution_R_10bp": (
                                    ex.get("conservative_net_execution_R_10bp")
                                    if ex
                                    else None
                                ),
                                "gross_execution_R": (
                                    ex.get("gross_execution_R") if ex else None
                                ),
                                "conservative_gross_execution_R": (
                                    ex.get("conservative_gross_execution_R")
                                    if ex
                                    else None
                                ),
                                "strict_execution_status": (
                                    ex.get("strict_execution_status") if ex else None
                                ),
                                "conservative_execution_status": (
                                    ex.get("conservative_execution_status")
                                    if ex
                                    else None
                                ),
                                "fill_status": ep.get("fill_status"),
                                "r_multiple": ep.get("r_multiple"),
                            }
                        )
                current_code = code
                bars = []
            bars.append(row)
    if current_code is not None and current_code in episodes_by_code:
        for ep in sorted(
            episodes_by_code[current_code],
            key=lambda item: item["signal_date"],
        ):
            feats = feature_for(ep, bars)
            key = (current_code, str(ep["setup_id"]), ep["signal_date"])
            ex = exec_by_key.get(key)
            output.append(
                {
                    "code": current_code,
                    "setup_id": str(ep["setup_id"]),
                    "signal_date": ep["signal_date"],
                    "execution_label": ep["execution_label"],
                    "is_entry_candidate": bool(ep["is_entry_candidate"]),
                    **feats,
                    "conservative_net_execution_R_10bp": (
                        ex.get("conservative_net_execution_R_10bp") if ex else None
                    ),
                    "gross_execution_R": ex.get("gross_execution_R") if ex else None,
                    "conservative_gross_execution_R": (
                        ex.get("conservative_gross_execution_R") if ex else None
                    ),
                    "strict_execution_status": (
                        ex.get("strict_execution_status") if ex else None
                    ),
                    "conservative_execution_status": (
                        ex.get("conservative_execution_status") if ex else None
                    ),
                    "fill_status": ep.get("fill_status"),
                    "r_multiple": ep.get("r_multiple"),
                }
            )
    return output


def cohort_stats(rows: list[dict]) -> dict:
    filled = sum(1 for row in rows if row.get("fill_status") == "FILLED")
    resolved = [
        row
        for row in rows
        if row.get("conservative_execution_status") == "RESOLVED"
        and row.get("conservative_net_execution_R_10bp") is not None
    ]
    values = [Decimal(str(row["conservative_net_execution_R_10bp"])) for row in resolved]
    raw_values = [
        Decimal(str(row["conservative_gross_execution_R"]))
        for row in resolved
        if row.get("conservative_gross_execution_R") is not None
    ]
    strict_raw = [
        Decimal(str(row["gross_execution_R"]))
        for row in resolved
        if row.get("gross_execution_R") is not None
    ]
    def cap(values: list[Decimal], limit: int) -> Decimal | None:
        if not values:
            return None
        capped = [min(value, Decimal(limit)) if value > 0 else value for value in values]
        return sum(capped) / len(capped)
    return {
        "episodes": len(rows),
        "filled": filled,
        "resolved": len(resolved),
        "conservative_10bp_E_R": str(mean(values)) if values else None,
        "gross_conservative_E_R": str(mean(raw_values)) if raw_values else None,
        "gross_strict_E_R": str(mean(strict_raw)) if strict_raw else None,
        "cap5_10bp": str(cap(values, 5)) if values else None,
        "cap10_10bp": str(cap(values, 10)) if values else None,
    }


def yearly(rows: list[dict]) -> dict:
    out = {}
    for year in (2024, 2025, 2026):
        out[str(year)] = cohort_stats(
            [row for row in rows if row["signal_date"].year == year]
        )
    return out


def main() -> None:
    rows = build_feature_rows()
    OUT.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, OUT / "context_features_v01.parquet", compression="zstd")
    b1 = [
        row
        for row in rows
        if row["execution_label"] == "B1_READY" and row["is_entry_candidate"]
    ]
    h1_groups = {}
    for group in ("FAVORABLE", "NEUTRAL", "UNFAVORABLE", "UNKNOWN"):
        subset = [row for row in b1 if row["weekly_context"] == group]
        h1_groups[group] = {
            **cohort_stats(subset),
            "years": yearly(subset),
        }
    h1_groups["NON_FAVORABLE"] = cohort_stats(
        [row for row in b1 if row["weekly_context"] != "FAVORABLE"]
    )
    h4_groups = {}
    for group in (
        "HEALTHY_CONTRACTION",
        "WASHOUT_POSSIBLE",
        "MIXED",
        "DISTRIBUTION_RISK",
        "STRUCTURAL_DAMAGE",
        "INSUFFICIENT_EVIDENCE",
    ):
        subset = [row for row in b1 if row["price_volume_interpretation"] == group]
        h4_groups[group] = {
            **cohort_stats(subset),
            "years": yearly(subset),
        }
    joint = [
        row
        for row in b1
        if row["weekly_context"] == "FAVORABLE"
        and row["price_volume_interpretation"]
        in {"HEALTHY_CONTRACTION", "WASHOUT_POSSIBLE"}
    ]
    joint_stats = {**cohort_stats(joint), "years": yearly(joint)}
    results = {
        "episode_count": len(rows),
        "actionable_b1_count": len(b1),
        "evaluate_strategy_calls": 0,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "h1_weekly": h1_groups,
        "h4_price_volume": h4_groups,
        "joint_context_v01": joint_stats,
    }
    (OUT / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    (OUT / "manifest.json").write_text(
        json.dumps(
            {
                "source_episodes_sha256": results["source_episodes_sha256"],
                "data_cutoff": "2026-07-31",
                "future_data_used": False,
                "evaluate_strategy_calls": 0,
                "feature_contract_version": "HISTORICAL_CONTEXT_V0_1",
                "thresholds": {
                    "weekly_volume_ratio_gt_2_0": "UNVALIDATED_DESCRIPTIVE_THRESHOLD",
                    "volume_contraction_lt_0_8": "UNVALIDATED_DESCRIPTIVE_THRESHOLD",
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
