"""MAINLINE PULLBACK OBSERVATION REVIEW v0.1 (read-only overlay).

This module adds a human observation layer on top of the frozen forward plan.
It never modifies strategy semantics, scores, thresholds, or the original
forward-plan artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

ZERO = Decimal("0")
ONE = Decimal("1")
CUTOFF = date(2026, 7, 31)
DECLARED_NEXT = date(2026, 8, 3)
OVERLAY_VERSION = "MAINLINE_PULLBACK_OBSERVATION_V0_1"

SEVERE_PV = {
    "SUPPORT_BREAK_WARNING",
    "HIGH_VOLUME_BEARISH_WARNING",
    "HIGH_VOLUME_STALL_WARNING",
}


def _pct(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.0001")))


def _ratio(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.0001")))


def _iso_week(value: date) -> tuple[int, int]:
    iso = value.isocalendar()
    return iso[0], iso[1]


def build_weekly_bars(
    daily_rows: Sequence[Mapping[str, Any]],
    cutoff: date,
) -> list[dict[str, Any]]:
    rows = [row for row in daily_rows if row["trade_date"] <= cutoff]
    rows.sort(key=lambda row: row["trade_date"])
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_iso_week(row["trade_date"]), []).append(row)
    weekly: list[dict[str, Any]] = []
    for week_key in sorted(grouped):
        bars = grouped[week_key]
        weekly.append(
            {
                "week": week_key,
                "week_end": bars[-1]["trade_date"],
                "open": bars[0]["open"],
                "high": max(bar["high"] for bar in bars),
                "low": min(bar["low"] for bar in bars),
                "close": bars[-1]["close"],
                "volume": sum((bar["volume"] or ZERO) for bar in bars),
                "amount": sum((bar["amount"] or ZERO) for bar in bars),
            }
        )
    return weekly


def weekly_metrics(weekly_bars: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not weekly_bars:
        return {"weekly_position_52w": None, "weekly_context": "UNKNOWN", "reasons": ["NO_WEEKLY_DATA"]}
    bars = list(weekly_bars[-52:])
    current = bars[-1]
    high_52 = max(bar["high"] for bar in bars)
    low_52 = min(bar["low"] for bar in bars)
    position = (
        (current["close"] - low_52) / (high_52 - low_52)
        if high_52 > low_52
        else None
    )
    closes = [bar["close"] for bar in bars]
    def ret(weeks: int) -> Decimal | None:
        if len(closes) <= weeks:
            return None
        base = closes[-1 - weeks]
        if base == 0:
            return None
        return closes[-1] / base - ONE
    ma10 = mean(closes[-10:]) if len(closes) >= 10 else None
    ma20 = mean(closes[-20:]) if len(closes) >= 20 else None
    ma10_prev = mean(closes[-14:-4]) if len(closes) >= 14 else None
    if ma10 is not None and ma10_prev is not None:
        ma10_direction = "UP" if ma10 > ma10_prev else ("DOWN" if ma10 < ma10_prev else "FLAT")
    else:
        ma10_direction = "UNKNOWN"
    last4_highs = [bar["high"] for bar in bars[-4:]]
    last4_lows = [bar["low"] for bar in bars[-4:]]
    higher_highs = all(
        last4_highs[index] > last4_highs[index - 1]
        for index in range(1, len(last4_highs))
    )
    higher_lows = all(
        last4_lows[index] > last4_lows[index - 1]
        for index in range(1, len(last4_lows))
    )
    prior8_volumes = [bar["volume"] for bar in bars[-9:-1] if (bar["volume"] or ZERO) > 0]
    volume_ratio = (
        current["volume"] / median(prior8_volumes)
        if prior8_volumes and median(prior8_volumes) > 0
        else None
    )
    return {
        "current_week_close": current["close"],
        "52w_high": high_52,
        "52w_low": low_52,
        "weekly_position_52w": position,
        "return_4w": ret(4),
        "return_12w": ret(12),
        "ma10_week": ma10,
        "ma20_week": ma20,
        "ma10_direction": ma10_direction,
        "higher_highs": higher_highs,
        "higher_lows": higher_lows,
        "weekly_volume_ratio": volume_ratio,
        "weekly_bars_count": len(bars),
    }


def classify_weekly_context(metrics: Mapping[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    position = metrics.get("weekly_position_52w")
    ret4 = metrics.get("return_4w")
    ret12 = metrics.get("return_12w")
    volume_ratio = metrics.get("weekly_volume_ratio")
    high = metrics.get("52w_high")
    current = metrics.get("current_week_close")
    if position is None:
        return "UNKNOWN", ["WEEKLY_POSITION_UNKNOWN"]
    if (
        volume_ratio is not None
        and volume_ratio > Decimal("2")
        and (ret4 or ZERO) < Decimal("0.02")
    ):
        reasons.append("HIGH_VOLUME_STALL")
    if high and current and high > 0 and current >= high * Decimal("0.98"):
        reasons.append("NEAR_52W_HIGH")
    if (ret4 or ZERO) > Decimal("0.30") and position > Decimal("0.85"):
        reasons.append("HIGH_POSITION_RAPID_RUN")
    if reasons:
        return "UNFAVORABLE", reasons
    if position <= Decimal("0.35") and (ret12 or ZERO) < Decimal("0.15"):
        return "FAVORABLE", ["LOW_BASE_OR_EARLY_LIFT"]
    if Decimal("0.35") < position < Decimal("0.80") and (ret4 or ZERO) > Decimal("-0.10"):
        return "FAVORABLE", ["MID_RANGE_REACCUMULATION"]
    return "NEUTRAL", ["MID_RANGE_CONTEXT"]


def daily_pv_metrics(
    daily_rows: Sequence[Mapping[str, Any]],
    *,
    anchor_date: date | None,
    invalid_price: Decimal | None,
    support_low: Decimal | None,
    cutoff: date,
) -> dict[str, Any]:
    rows = [row for row in daily_rows if row["trade_date"] <= cutoff]
    rows.sort(key=lambda row: row["trade_date"])
    recent = rows[-15:]
    result: dict[str, Any] = {"recent_days": len(recent)}
    if len(recent) < 5:
        result["pv_context"] = "INSUFFICIENT_EVIDENCE"
        result["reasons"] = ["INSUFFICIENT_EVIDENCE"]
        return result
    volumes = [Decimal(row["volume"]) for row in recent]
    closes = [Decimal(row["close"]) for row in recent]
    prior5 = mean(volumes[-6:-1]) if len(volumes) >= 6 else mean(volumes[:-1])
    result["volume_ratio_5d"] = volumes[-1] / prior5 if prior5 > 0 else None
    anchor_row = next((row for row in rows if row["trade_date"] == anchor_date), None)
    anchor_volume: Decimal | None = None
    anchor_ratio: Decimal | None = None
    if anchor_row is not None:
        anchor_index = rows.index(anchor_row)
        prior = rows[max(0, anchor_index - 5):anchor_index]
        prior_vol = mean([Decimal(row["volume"]) for row in prior]) if prior else None
        anchor_volume = Decimal(anchor_row["volume"])
        anchor_ratio = anchor_volume / prior_vol if prior_vol and prior_vol > 0 else None
    pullback = rows[(rows.index(anchor_row) + 1 if anchor_row else 0):]
    pullback_vol = median([Decimal(row["volume"]) for row in pullback]) if pullback else None
    pullback_ratio = (
        pullback_vol / anchor_volume
        if pullback_vol is not None and anchor_volume
        else None
    )
    result["anchor_volume_ratio"] = anchor_ratio
    result["pullback_volume_ratio"] = pullback_ratio
    result["latest_3d_volume_trend"] = (
        mean(volumes[-3:]) / mean(volumes[-6:-3])
        if len(volumes) >= 6 and mean(volumes[-6:-3]) > 0
        else None
    )
    result["latest_3d_price_trend"] = (
        closes[-1] / closes[-4] - ONE if len(closes) >= 4 else None
    )
    reasons: list[str] = []
    last3 = recent[-3:]
    prior5_vol = mean(volumes[-6:-1]) if len(volumes) >= 6 else mean(volumes[:-1])
    for row in last3:
        volume = Decimal(row["volume"])
        close = Decimal(row["close"])
        open_price = Decimal(row["open"])
        high = Decimal(row["high"])
        low = Decimal(row["low"])
        row_index = recent.index(row)
        prev_close = closes[row_index - 1] if row_index > 0 else None
        if volume > prior5_vol * Decimal("1.5"):
            if close < open_price and (prev_close is None or close < prev_close):
                reasons.append("HIGH_VOLUME_BEARISH_WARNING")
            if abs(close / open_price - ONE) < Decimal("0.01"):
                reasons.append("HIGH_VOLUME_STALL_WARNING")
        if (
            prev_close is not None
            and close > prev_close
            and volume < prior5_vol * Decimal("0.7")
        ):
            reasons.append("PRICE_UP_VOLUME_DOWN_WARNING")
        body_range = high - min(open_price, close)
        if high > low and (high - max(open_price, close)) / (high - low) > Decimal("0.5"):
            reasons.append("LONG_UPPER_SHADOW")
        if invalid_price is not None and low <= invalid_price:
            reasons.append("SUPPORT_BREAK_WARNING")
        if support_low is not None and close < support_low:
            reasons.append("SUPPORT_BREAK_WARNING")
    result["reasons"] = sorted(set(reasons))
    if any(reason in SEVERE_PV for reason in reasons):
        result["pv_context"] = "WARNING"
    elif anchor_ratio is not None and anchor_ratio > Decimal("1.2") and (
        pullback_ratio is None or pullback_ratio < Decimal("0.8")
    ):
        result["pv_context"] = "CONFIRMED"
        if not reasons:
            result["reasons"] = ["ATTACK_CONFIRMED", "PULLBACK_VOLUME_CONTRACTED"]
    elif "PRICE_UP_VOLUME_DOWN_WARNING" in reasons:
        result["pv_context"] = "WARNING"
    else:
        result["pv_context"] = "MIXED"
    return result


def sector_context_from_metrics(metrics: Mapping[str, Any]) -> str:
    if not metrics.get("has_mapping") or (metrics.get("member_count") or 0) < 3:
        return "UNKNOWN"
    rel5 = metrics.get("relative_5d")
    rel10 = metrics.get("relative_10d")
    rel20 = metrics.get("relative_20d")
    breadth = metrics.get("breadth_5d")
    if (
        rel5 is not None
        and rel10 is not None
        and rel20 is not None
        and rel5 > 0
        and rel10 > 0
        and rel20 > 0
        and (breadth or 0) >= Decimal("0.5")
    ):
        return "LEADING"
    if rel5 is not None and rel10 is not None and (rel5 > 0 and rel10 > 0):
        return "IMPROVING"
    if (
        rel5 is not None
        and rel10 is not None
        and rel20 is not None
        and rel5 < 0
        and rel10 < 0
        and rel20 < 0
    ):
        return "WEAK"
    return "MIXED"


def classify_stock_vs_sector(
    stock: Mapping[str, Any],
    sector: Mapping[str, Any] | None,
) -> tuple[str, bool]:
    if sector is None or not sector.get("has_mapping"):
        return "UNKNOWN", False
    wins = 0
    losses = 0
    for horizon in ("5d", "10d", "20d"):
        stock_ret = stock.get(f"stock_return_{horizon}")
        sector_ret = sector.get(f"return_{horizon}")
        if stock_ret is not None and sector_ret is not None:
            if stock_ret > sector_ret:
                wins += 1
            elif stock_ret < sector_ret:
                losses += 1
    label = "LEADER" if wins >= 2 else ("LAGGARD" if losses >= 2 else "IN_LINE")
    isolated = (
        sector.get("context") == "WEAK"
        and (stock.get("stock_return_5d") or ZERO) > (sector.get("return_5d") or ZERO) + Decimal("0.05")
    )
    return label, isolated


def human_priority(
    *,
    weekly_context: str,
    sector_context: str,
    pv_context: str,
    pv_reasons: Sequence[str],
    stock_vs_sector: str,
    isolated_strength: bool,
) -> tuple[str, list[str]]:
    severe = any(reason in SEVERE_PV for reason in pv_reasons)
    if (
        weekly_context != "UNFAVORABLE"
        and sector_context in {"LEADING", "IMPROVING"}
        and pv_context in {"CONFIRMED", "MIXED"}
        and not severe
        and stock_vs_sector != "LAGGARD"
        and not isolated_strength
    ):
        return "A", ["WEEKLY_SECTOR_PV_ALIGNED"]
    if (
        weekly_context != "UNFAVORABLE"
        and sector_context not in {"WEAK"}
        and pv_context not in {"WARNING", "INSUFFICIENT_EVIDENCE"}
        and not severe
    ):
        return "B", ["PARTIAL_ALIGNMENT"]
    return "C", ["WEEKLY_SECTOR_OR_PV_RISK"]


def load_sector_mapping(pool_path: Path) -> dict[str, str]:
    table = pq.read_table(pool_path, columns=["code", "industry"])
    mapping: dict[str, str] = {}
    for code, industry in zip(
        table.column("code").to_pylist(),
        table.column("industry").to_pylist(),
    ):
        if industry:
            mapping[str(code)] = str(industry)
    return mapping


def _load_market_and_candidates(
    daily_path: Path,
    candidate_codes: set[str],
    sector_mapping: Mapping[str, str],
    cutoff: date,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    recent: dict[str, deque[tuple[date, Decimal]]] = {}
    volumes: dict[str, deque[tuple[date, Decimal]]] = {}
    candidate_bars: dict[str, list[dict[str, Any]]] = {code: [] for code in candidate_codes}
    pf = pq.ParquetFile(daily_path)
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
    for batch in pf.iter_batches(columns=columns, batch_size=8192, use_threads=False):
        for row in batch.to_pylist():
            if row["reconciliation_status"] != "CONFIRMED":
                continue
            code = str(row["code"])
            trade_date = row["trade_date"]
            if trade_date > cutoff:
                continue
            if code in candidate_bars:
                candidate_bars[code].append(row)
            recent.setdefault(code, deque(maxlen=21)).append(
                (trade_date, Decimal(row["close"]))
            )
            volumes.setdefault(code, deque(maxlen=25)).append(
                (trade_date, Decimal(row["volume"]))
            )

    per_code: dict[str, dict[str, Any]] = {}
    for code, values in recent.items():
        if len(values) < 6:
            continue
        closes = [close for _, close in values]
        close_now = closes[-1]
        ret5 = closes[-1] / closes[-6] - ONE if closes[-6] else None
        ret10 = closes[-1] / closes[-11] - ONE if len(closes) >= 11 and closes[-11] else None
        ret20 = closes[-1] / closes[-21] - ONE if len(closes) >= 21 and closes[-21] else None
        ma20 = mean(closes[-20:]) if len(closes) >= 20 else None
        vol_values = [volume for _, volume in volumes.get(code, ())]
        vol5 = sum(vol_values[-5:]) if vol_values else ZERO
        vol_prior = sum(vol_values[-25:-5]) if len(vol_values) >= 25 else None
        per_code[code] = {
            "ret5": ret5,
            "ret10": ret10,
            "ret20": ret20,
            "close": close_now,
            "ma20": ma20,
            "advancing": ret5 is not None and ret5 > 0,
            "above_ma20": ma20 is not None and close_now > ma20,
            "vol5": vol5,
            "vol_prior": vol_prior,
        }

    market_returns = [row["ret5"] for row in per_code.values() if row["ret5"] is not None]
    market_ret10 = [row["ret10"] for row in per_code.values() if row["ret10"] is not None]
    advancing = sum(1 for row in per_code.values() if row["advancing"])
    total = len(per_code)
    market_metrics = {
        "market_return_5d": median(market_returns) if market_returns else None,
        "market_return_10d": median(market_ret10) if market_ret10 else None,
        "advancing_share": advancing / total if total else None,
        "total_codes": total,
    }
    if (market_metrics["market_return_5d"] or ZERO) > 0 and (
        market_metrics["market_return_10d"] or ZERO
    ) > 0 and (market_metrics["advancing_share"] or ZERO) > Decimal("0.5"):
        market_metrics["market_context"] = "RISK_ON"
    elif (market_metrics["market_return_5d"] or ZERO) < 0 and (
        market_metrics["market_return_10d"] or ZERO
    ) < 0:
        market_metrics["market_context"] = "RISK_OFF"
    else:
        market_metrics["market_context"] = "NEUTRAL"

    sectors: dict[str, dict[str, Any]] = {}
    for code, metrics in per_code.items():
        sector = sector_mapping.get(code)
        if not sector:
            continue
        target = sectors.setdefault(
            sector,
            {
                "returns_5d": [],
                "returns_10d": [],
                "returns_20d": [],
                "advancing": 0,
                "above_ma20": 0,
                "member_count": 0,
                "vol5": ZERO,
                "vol_prior": ZERO,
            },
        )
        target["member_count"] += 1
        if metrics["ret5"] is not None:
            target["returns_5d"].append(metrics["ret5"])
        if metrics["ret10"] is not None:
            target["returns_10d"].append(metrics["ret10"])
        if metrics["ret20"] is not None:
            target["returns_20d"].append(metrics["ret20"])
        if metrics["advancing"]:
            target["advancing"] += 1
        if metrics["above_ma20"]:
            target["above_ma20"] += 1
        target["vol5"] += metrics["vol5"]
        if metrics["vol_prior"] is not None:
            target["vol_prior"] += metrics["vol_prior"]
    for name, target in sectors.items():
        target["return_5d"] = median(target["returns_5d"]) if target["returns_5d"] else None
        target["return_10d"] = median(target["returns_10d"]) if target["returns_10d"] else None
        target["return_20d"] = median(target["returns_20d"]) if target["returns_20d"] else None
        target["breadth_5d"] = (
            Decimal(target["advancing"]) / Decimal(target["member_count"])
            if target["member_count"]
            else None
        )
        target["above_ma20_share"] = (
            Decimal(target["above_ma20"]) / Decimal(target["member_count"])
            if target["member_count"]
            else None
        )
        target["volume_ratio"] = (
            target["vol5"] / target["vol_prior"] if target["vol_prior"] and target["vol_prior"] > 0 else None
        )
        target["relative_5d"] = (
            target["return_5d"] - market_metrics["market_return_5d"]
            if target["return_5d"] is not None and market_metrics["market_return_5d"] is not None
            else None
        )
        target["relative_10d"] = (
            target["return_10d"] - market_metrics["market_return_10d"]
            if target["return_10d"] is not None and market_metrics["market_return_10d"] is not None
            else None
        )
        target["relative_20d"] = (
            target["return_20d"] - market_metrics["market_return_5d"]
            if target["return_20d"] is not None and market_metrics["market_return_5d"] is not None
            else None
        )
        target["has_mapping"] = True
        target["context"] = sector_context_from_metrics(target)
    return candidate_bars, market_metrics, sectors


def _overlay_payload_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    normalized = []
    for row in rows:
        item = dict(row)
        for key, value in item.items():
            if isinstance(value, Decimal):
                item[key] = str(value)
            elif isinstance(value, date):
                item[key] = value.isoformat()
        normalized.append(item)
    normalized.sort(key=lambda item: item["code"])
    payload = {
        "overlay_version": OVERLAY_VERSION,
        "data_cutoff": CUTOFF.isoformat(),
        "rows": normalized,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_overlay(
    *,
    plan_dir: Path,
    output_dir: Path,
    daily_path: Path,
    pool_path: Path,
    source_plan_hash: str,
) -> dict[str, Any]:
    plan_table = pq.read_table(plan_dir / "full_candidates.parquet")
    plan_rows = plan_table.to_pylist()
    sector_mapping = load_sector_mapping(pool_path)
    candidate_bars, market_metrics, sectors = _load_market_and_candidates(
        daily_path,
        {str(row["code"]) for row in plan_rows},
        sector_mapping,
        CUTOFF,
    )
    overlay_rows: list[dict[str, Any]] = []
    for plan in plan_rows:
        code = str(plan["code"])
        bars = candidate_bars.get(code, [])
        weekly = weekly_metrics(build_weekly_bars(bars, CUTOFF))
        weekly_context, weekly_reasons = classify_weekly_context(weekly)
        anchor_date = plan.get("anchor_date")
        invalid_price = (
            Decimal(str(plan["invalid_price"]))
            if plan.get("invalid_price") is not None
            else None
        )
        support_low = (
            Decimal(str(plan["support_low"]))
            if plan.get("support_low") is not None
            else None
        )
        pv = daily_pv_metrics(
            bars,
            anchor_date=anchor_date,
            invalid_price=invalid_price,
            support_low=support_low,
            cutoff=CUTOFF,
        )
        pv_context = pv.get("pv_context", "INSUFFICIENT_EVIDENCE")
        pv_reasons = pv.get("reasons", [])
        sector_name = sector_mapping.get(code)
        sector = sectors.get(sector_name) if sector_name else None
        if sector is None:
            sector = {
                "has_mapping": False,
                "member_count": 0,
                "return_5d": None,
                "return_10d": None,
                "return_20d": None,
                "relative_5d": None,
                "relative_10d": None,
                "relative_20d": None,
                "breadth_5d": None,
                "context": "UNKNOWN",
            }
        stock_returns = {
            "stock_return_5d": (
                (Decimal(bars[-1]["close"]) / Decimal(bars[-6]["close"]) - ONE)
                if len(bars) >= 6 and Decimal(bars[-6]["close"]) > 0
                else None
            ),
            "stock_return_10d": (
                (Decimal(bars[-1]["close"]) / Decimal(bars[-11]["close"]) - ONE)
                if len(bars) >= 11 and Decimal(bars[-11]["close"]) > 0
                else None
            ),
            "stock_return_20d": (
                (Decimal(bars[-1]["close"]) / Decimal(bars[-21]["close"]) - ONE)
                if len(bars) >= 21 and Decimal(bars[-21]["close"]) > 0
                else None
            ),
        }
        stock_vs_sector, isolated = classify_stock_vs_sector(
            {**stock_returns, **sector},
            sector,
        )
        priority, priority_reasons = human_priority(
            weekly_context=weekly_context,
            sector_context=sector.get("context", "UNKNOWN"),
            pv_context=pv_context,
            pv_reasons=pv_reasons,
            stock_vs_sector=stock_vs_sector,
            isolated_strength=isolated,
        )
        overlay_rows.append(
            {
                "code": code,
                "name": plan.get("name"),
                "execution_label": plan.get("execution_label"),
                "original_rank": plan.get("existing_rank"),
                "is_entry_candidate": plan.get("is_entry_candidate"),
                "current_close": plan.get("current_close"),
                "preferred_entry": plan.get("preferred_entry"),
                "trigger_price": plan.get("trigger_price"),
                "buy_zone_low": plan.get("buy_zone_low"),
                "buy_zone_high": plan.get("buy_zone_high"),
                "invalid_price": plan.get("invalid_price"),
                "s1_price": plan.get("s1_price"),
                "setup_quality_score": plan.get("setup_quality_score"),
                "entry_quality_score": plan.get("entry_quality_score"),
                "entry_room_state": plan.get("entry_room_state"),
                "weekly_context": weekly_context,
                "weekly_reasons": weekly_reasons,
                "weekly_position_52w": weekly.get("weekly_position_52w"),
                "return_4w": weekly.get("return_4w"),
                "return_12w": weekly.get("return_12w"),
                "pv_context": pv_context,
                "pv_reasons": pv_reasons,
                "anchor_volume_ratio": pv.get("anchor_volume_ratio"),
                "pullback_volume_ratio": pv.get("pullback_volume_ratio"),
                "sector_name": sector_name,
                "sector_context": sector.get("context", "UNKNOWN"),
                "sector_member_count": sector.get("member_count", 0),
                "sector_relative_5d": sector.get("relative_5d"),
                "sector_relative_10d": sector.get("relative_10d"),
                "sector_relative_20d": sector.get("relative_20d"),
                "sector_breadth_5d": sector.get("breadth_5d"),
                "stock_return_5d": stock_returns["stock_return_5d"],
                "stock_return_10d": stock_returns["stock_return_10d"],
                "stock_return_20d": stock_returns["stock_return_20d"],
                "stock_vs_sector": stock_vs_sector,
                "isolated_strength_warning": isolated,
                "human_priority": priority,
                "priority_reasons": priority_reasons,
            }
        )

    payload_hash = _overlay_payload_hash(overlay_rows)
    manifest = {
        "source_forward_plan_hash": source_plan_hash,
        "data_cutoff": CUTOFF.isoformat(),
        "declared_next_trade_date": DECLARED_NEXT.isoformat(),
        "overlay_version": OVERLAY_VERSION,
        "strategy_changed": False,
        "future_data_used": False,
        "payload_sha256": payload_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "overlay_rows": overlay_rows,
        "market_metrics": market_metrics,
        "sectors": sectors,
        "manifest": manifest,
        "payload_hash": payload_hash,
    }
