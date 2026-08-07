"""Phase-1A parity harness: LEGACY canonical vs ASL adapter (read-only).

Compares the frozen V Flash canonical daily contract against the ASL-backed
adapter output for a bounded sample.  Writes a JSON report.  Never writes
canonical data, never promotes anything, never touches ASL data.

Usage:
    PYTHONPATH=src python research/asl_phase1a/parity.py \
        --legacy-root "/Users/luke808/AI/V flash/data" \
        --legacy-snapshot snap-2026-08-06-e798f88ff67b.parquet \
        --asl-root /tmp/asl_phase1a_lake \
        --start 2026-05-28 --as-of 2026-08-06 \
        --codes 000001,600519,601318,000010,000524,000593,002963,605179,605198,300750 \
        --out research/asl_phase1a/parity_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pyarrow.parquet as pq

from limit_pullback.config import load_strategy_config
from limit_pullback.models.market import DailyBar
from limit_pullback.strategy.engine import evaluate_strategy
from limit_pullback.strategy.math import calculate_indicators
from limit_pullback.strategy.structure import (
    detect_anchor,
    is_limit_close,
    is_one_word_limit,
    is_t_word_limit,
    theoretical_limit_price,
)
from limit_pullback.warehouse.asl_adapter import load_asl_daily_slice

PRICE_ABS = Decimal("0.01")
PRICE_REL = Decimal("0.001")
VOLUME_REL = Decimal("0.005")
AMOUNT_REL = Decimal("0.005")
PCT_ABS = Decimal("0.05")
MA_REL = Decimal("0.001")

FIXED_FETCHED_AT = datetime(2026, 8, 6, 23, 59, 59, tzinfo=timezone.utc)


def _rel(a: Decimal, b: Decimal) -> Decimal:
    scale = max(abs(a), abs(b))
    if scale == 0:
        return Decimal("0")
    return abs(a - b) / scale


def _price_ok(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= PRICE_ABS or _rel(a, b) <= PRICE_REL


def _vol_ok(a: Decimal, b: Decimal) -> bool:
    return _rel(a, b) <= VOLUME_REL


def _to_bar(row: Mapping[str, Any]) -> DailyBar:
    return DailyBar(
        trade_date=row["trade_date"],
        code=str(row["code"]),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        preclose=Decimal(str(row["preclose"])),
        volume=Decimal(str(row["volume"])),
        amount=Decimal(str(row["amount"])),
        turnover_rate=(
            Decimal(str(row["turnover_rate"]))
            if row.get("turnover_rate") is not None
            else None
        ),
        pct_change=(
            Decimal(str(row["pct_change"]))
            if row.get("pct_change") is not None
            else None
        ),
        trade_status=bool(row.get("trade_status", True)),
        is_st=(
            bool(row["is_st"]) if row.get("is_st") is not None else None
        ),
        source="PARITY",
        fetched_at=FIXED_FETCHED_AT,
    )


def _read_legacy(
    legacy_root: Path, snapshot: str, codes: set[str], start: date, as_of: date
) -> dict[str, list[dict[str, Any]]]:
    path = legacy_root / "canonical" / "daily_bars" / snapshot
    if not path.exists():
        raise FileNotFoundError(f"legacy snapshot not found: {path}")
    table = pq.ParquetFile(path).read()
    rows_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in table.to_pylist():
        code = str(row["code"])
        if code not in codes:
            continue
        if row["reconciliation_status"] != "CONFIRMED":
            continue
        if not (start <= row["trade_date"] <= as_of):
            continue
        rows_by_code.setdefault(code, []).append(row)
    for rows in rows_by_code.values():
        rows.sort(key=lambda row: row["trade_date"])
    return rows_by_code


def _compare_field_pair(
    legacy: Mapping[str, Any],
    adapter: Mapping[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in ("open", "high", "low", "close", "preclose"):
        lv = Decimal(str(legacy[field]))
        av = Decimal(str(adapter[field]))
        out[field] = {
            "legacy": str(lv),
            "adapter": str(av),
            "abs_diff": str(abs(lv - av)),
            "rel_diff": str(_rel(lv, av)),
            "ok": _price_ok(lv, av),
        }
    for field in ("volume", "amount"):
        lv = Decimal(str(legacy[field]))
        av = Decimal(str(adapter[field]))
        out[field] = {
            "legacy": str(lv),
            "adapter": str(av),
            "rel_diff": str(_rel(lv, av)),
            "ok": _vol_ok(lv, av),
        }
    return out


def _compare_code(
    code: str,
    legacy_rows: list[dict[str, Any]],
    adapter_rows: list[dict[str, Any]],
    adapter_by_date: Mapping[date, dict[str, Any]],
    config: Any,
    as_of: date,
    suspended_sessions: set[tuple[str, date]],
    warnings: list[str],
) -> dict[str, Any]:
    legacy_by_date = {row["trade_date"]: row for row in legacy_rows}
    all_sessions = sorted(set(legacy_by_date) | set(adapter_by_date))

    sessions: dict[str, list[str]] = {"BOTH": [], "LEGACY_ONLY": [], "ASL_ONLY": []}
    field_results: list[dict[str, Any]] = []
    preclose_exact = 0
    preclose_total = 0
    turnover_not_comparable = []
    structure_mismatches: list[dict[str, Any]] = []
    ma_compared = 0
    ma_fail = 0
    ma_hole_affected = 0
    ma_hole_fail = 0
    legacy_holes: list[str] = []

    # Identify legacy holes (sessions where ASL traded but legacy has no row).
    for day in all_sessions:
        has_legacy = day in legacy_by_date
        has_adapter = day in adapter_by_date
        if has_legacy and has_adapter:
            sessions["BOTH"].append(day.isoformat())
        elif has_legacy:
            sessions["LEGACY_ONLY"].append(day.isoformat())
        else:
            sessions["ASL_ONLY"].append(day.isoformat())
            if (code, day) in suspended_sessions:
                legacy_holes.append(f"{day.isoformat()}:ASL_SUSPENDED")
            else:
                legacy_holes.append(f"{day.isoformat()}:LEGACY_HOLE")

    for day in sessions["BOTH"]:
        d = date.fromisoformat(day)
        legacy = legacy_by_date[d]
        adapter = adapter_by_date[d]
        fields = _compare_field_pair(legacy, adapter)
        preclose_total += 1
        if Decimal(str(legacy["preclose"])) == Decimal(str(adapter["preclose"])):
            preclose_exact += 1

        # pct_change recomputed with the frozen rule on each side.
        def frozen_pct(row: Mapping[str, Any]) -> Decimal | None:
            pre = Decimal(str(row["preclose"]))
            if pre <= 0:
                return None
            return (
                (Decimal(str(row["close"])) - pre) / pre * Decimal("100")
            ).quantize(Decimal("0.0001"))

        lpct = frozen_pct(legacy)
        apct = frozen_pct(adapter)
        pct_ok = (
            lpct is not None
            and apct is not None
            and abs(lpct - apct) <= PCT_ABS
        )
        fields["pct_change_recomputed"] = {
            "legacy": str(lpct),
            "adapter": str(apct),
            "ok": pct_ok,
        }

        # Structure booleans (frozen V Flash functions on both sides).
        legacy_bar = _to_bar(legacy)
        adapter_bar = _to_bar(adapter)
        for name, fn in (
            ("limit_close", is_limit_close),
            ("one_word", is_one_word_limit),
            ("t_word", is_t_word_limit),
        ):
            lv = bool(fn(legacy_bar, config))
            av = bool(fn(adapter_bar, config))
            if lv != av:
                structure_mismatches.append(
                    {
                        "session": day,
                        "check": name,
                        "legacy": lv,
                        "adapter": av,
                        "theoretical_limit": str(
                            theoretical_limit_price(adapter_bar, config)
                        ),
                    }
                )

        if legacy.get("turnover_rate") is not None:
            turnover_not_comparable.append(
                {
                    "session": day,
                    "legacy_turnover_rate": str(legacy["turnover_rate"]),
                    "reason": "ASL has no PIT-safe per-stock turnover field",
                }
            )
        fields["status"] = {
            "legacy_is_st": (
                bool(legacy["is_st"]) if legacy.get("is_st") is not None else None
            ),
            "adapter_is_st": adapter["is_st"],
            "legacy_trade_status": bool(legacy.get("trade_status", True)),
            "adapter_trade_status": adapter["trade_status"],
            "ok": (
                bool(legacy.get("trade_status", True)) == adapter["trade_status"]
                and (
                    legacy.get("is_st") is None
                    or bool(legacy["is_st"]) == adapter["is_st"]
                )
            ),
        }
        field_results.append({"session": day, "fields": fields})

    # MA5/10/20 via the frozen indicator chain on both sides.
    try:
        legacy_bars = [_to_bar(row) for row in legacy_rows]
        adapter_bars = [_to_bar(row) for row in adapter_rows]
        legacy_inds = calculate_indicators(legacy_bars, config.indicators, as_of)
        adapter_inds = calculate_indicators(adapter_bars, config.indicators, as_of)
        legacy_ma = {
            point.trade_date: point.raw_equivalent_mas for point in legacy_inds
        }
        adapter_ma = {
            point.trade_date: point.raw_equivalent_mas for point in adapter_inds
        }
        ma_report: dict[str, Any] = {}
        for d in sorted(set(legacy_ma) & set(adapter_ma)):
            if d not in legacy_by_date or d not in adapter_by_date:
                continue
            # Sessions in the MA window where legacy has no row change the
            # chain: such comparisons are hole-affected, not failures.
            window = [
                day
                for day in all_sessions
                if day <= d
                and day in (set(legacy_by_date) | set(adapter_by_date))
                and day not in legacy_by_date
            ]
            hole_affected = bool(window)
            for window_size in (5, 10, 20):
                lm = legacy_ma[d].get(window_size)
                am = adapter_ma[d].get(window_size)
                if lm is None or am is None:
                    continue
                ma_compared += 1
                ok = _rel(lm, am) <= MA_REL
                if hole_affected:
                    ma_hole_affected += 1
                    if not ok:
                        ma_hole_fail += 1
                else:
                    if not ok:
                        ma_fail += 1
                        ma_report[f"{d}:ma{window_size}"] = {
                            "legacy": str(lm),
                            "adapter": str(am),
                            "rel_diff": str(_rel(lm, am)),
                        }
    except Exception as exc:  # noqa: BLE001 — report, do not abort parity
        warnings.append(f"{code}: MA comparison failed: {exc}")
        ma_report = {"error": str(exc)}

    # Anchor + stage via frozen functions on each side (no pool enrichment).
    anchor_report: dict[str, Any] = {}
    stage_report: dict[str, Any] = {}
    try:
        legacy_anchor = detect_anchor(
            [_to_bar(row) for row in legacy_rows], as_of, config
        )
        adapter_anchor = detect_anchor(
            [_to_bar(row) for row in adapter_rows], as_of, config
        )
        anchor_report = {
            "legacy": (
                {
                    "anchor_date": legacy_anchor.snapshot.anchor_date.isoformat(),
                    "anchor_price": str(legacy_anchor.snapshot.anchor_price),
                }
                if legacy_anchor is not None
                else None
            ),
            "adapter": (
                {
                    "anchor_date": adapter_anchor.snapshot.anchor_date.isoformat(),
                    "anchor_price": str(adapter_anchor.snapshot.anchor_price),
                }
                if adapter_anchor is not None
                else None
            ),
        }
        if legacy_anchor is None and adapter_anchor is None:
            anchor_report["match"] = True
        elif (legacy_anchor is None) != (adapter_anchor is None):
            anchor_report["match"] = False
        else:
            anchor_report["match"] = (
                legacy_anchor.snapshot.anchor_date
                == adapter_anchor.snapshot.anchor_date
                and legacy_anchor.snapshot.anchor_price
                == adapter_anchor.snapshot.anchor_price
            )
        if not anchor_report["match"] and legacy_holes:
            anchor_report["hole_affected"] = True

        latest = max(
            (
                day
                for day in all_sessions
                if day in legacy_by_date and day in adapter_by_date
            ),
            default=None,
        )
        if latest is not None:
            legacy_signal = evaluate_strategy(
                bars=[_to_bar(row) for row in legacy_rows],
                as_of=latest,
                config=config,
                generated_at=FIXED_FETCHED_AT,
            )
            adapter_signal = evaluate_strategy(
                bars=[_to_bar(row) for row in adapter_rows],
                as_of=latest,
                config=config,
                generated_at=FIXED_FETCHED_AT,
            )
            stage_report = {
                "as_of": latest.isoformat(),
                "legacy": legacy_signal.setup_stage.value,
                "adapter": adapter_signal.setup_stage.value,
                "match": legacy_signal.setup_stage == adapter_signal.setup_stage,
            }
    except Exception as exc:  # noqa: BLE001 — report, do not abort parity
        warnings.append(f"{code}: anchor/stage comparison failed: {exc}")

    return {
        "code": code,
        "sessions": sessions,
        "field_comparisons": {
            "rows": field_results,
            "preclose_exact": preclose_exact,
            "preclose_total": preclose_total,
        },
        "structure_mismatches": structure_mismatches,
        "ma": {
            "compared": ma_compared,
            "fail": ma_fail,
            "hole_affected": ma_hole_affected,
            "hole_affected_fail": ma_hole_fail,
            "details": ma_report,
        },
        "anchor": anchor_report,
        "stage": stage_report,
        "turnover_not_comparable": turnover_not_comparable,
        "legacy_holes": legacy_holes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-root", required=True, type=Path)
    parser.add_argument("--legacy-snapshot", required=True)
    parser.add_argument("--asl-root", required=True, type=Path)
    parser.add_argument("--start", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--codes", required=True)
    parser.add_argument("--config", default="config/strategy.yaml", type=Path)
    parser.add_argument("--out", default="research/asl_phase1a/parity_report.json", type=Path)
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start)
    as_of = date.fromisoformat(args.as_of)
    codes = tuple(sorted({str(code).zfill(6) for code in args.codes.split(",")}))
    config = load_strategy_config(args.config)

    legacy = _read_legacy(args.legacy_root, args.legacy_snapshot, set(codes), start, as_of)
    slice_ = load_asl_daily_slice(
        args.asl_root,
        as_of=as_of,
        start=start,
        codes=codes,
    )

    adapter_by_code: dict[str, dict[date, dict[str, Any]]] = {}
    adapter_fail_closed: list[dict[str, Any]] = []
    for row in slice_.rows:
        if row.row_status != "VALID_ROW":
            adapter_fail_closed.append(
                {
                    "code": row.code,
                    "trade_date": row.trade_date.isoformat(),
                    "row_status": row.row_status,
                    "reason": row.reason,
                }
            )
            continue
        adapter_by_code.setdefault(row.code, {})[row.trade_date] = {
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "preclose": row.preclose,
            "volume": row.volume,
            "amount": row.amount,
            "pct_change": row.pct_change,
            "trade_status": row.trade_status,
            "is_st": row.is_st,
            "code": row.code,
            "trade_date": row.trade_date,
        }
    adapter_rows_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in slice_.rows:
        if row.row_status != "VALID_ROW":
            continue
        adapter_rows_by_code.setdefault(row.code, []).append(
            {
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "preclose": row.preclose,
                "volume": row.volume,
                "amount": row.amount,
                "pct_change": row.pct_change,
                "trade_status": row.trade_status,
                "is_st": row.is_st,
                "code": row.code,
                "trade_date": row.trade_date,
            }
        )

    suspended_sessions = set(slice_.suspended_sessions)
    warnings: list[str] = list(slice_.warnings)
    results: list[dict[str, Any]] = []
    for code in codes:
        if code in slice_.excluded_codes:
            results.append(
                {
                    "code": code,
                    "excluded": "OUTSIDE_FROZEN_UNIVERSE",
                    "note": "ASL rows exist but the frozen universe contract excludes this prefix",
                }
            )
            continue
        if code not in legacy:
            warnings.append(f"{code}: no legacy CONFIRMED rows in window")
            continue
        results.append(
            _compare_code(
                code,
                legacy[code],
                adapter_rows_by_code.get(code, []),
                adapter_by_code.get(code, {}),
                config,
                as_of,
                suspended_sessions,
                warnings,
            )
        )

    report = {
        "contract": "VFLASH_ASL_PHASE1A_PARITY",
        "asl_revision": slice_.asl_revision,
        "asl_root": str(args.asl_root),
        "legacy_root": str(args.legacy_root),
        "legacy_snapshot": args.legacy_snapshot,
        "window": {"start": start.isoformat(), "as_of": as_of.isoformat()},
        "codes": list(codes),
        "status_coverage": {
            "mode": slice_.status_coverage.mode,
            "status_rows_in_window": slice_.status_coverage.status_rows_in_window,
            "sessions_with_status_row": slice_.status_coverage.sessions_with_status_row,
            "sessions_without_status_row": slice_.status_coverage.sessions_without_status_row,
        },
        "suspended_sessions": [
            f"{code}:{day.isoformat()}" for code, day in slice_.suspended_sessions
        ],
        "adapter_fail_closed_rows": adapter_fail_closed,
        "adapter_fail_closed_count": len(adapter_fail_closed),
        "results": results,
        "warnings": warnings,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    total_rows = sum(len(r["field_comparisons"]["rows"]) for r in results if "field_comparisons" in r)
    preclose_exact = sum(r["field_comparisons"]["preclose_exact"] for r in results if "field_comparisons" in r)
    mismatches = [
        (r["code"], m) for r in results if "structure_mismatches" in r for m in r["structure_mismatches"]
    ]
    ma_fail = sum(r["ma"]["fail"] for r in results if "ma" in r)
    stage_mismatch = [r["code"] for r in results if "stage" in r and r["stage"] and not r["stage"]["match"]]
    anchor_mismatch = [r["code"] for r in results if "anchor" in r and r["anchor"].get("match") is False]

    print(json.dumps({
        "codes": len(results),
        "compared_rows": total_rows,
        "preclose_exact": f"{preclose_exact}/{total_rows}",
        "structure_mismatches": len(mismatches),
        "ma_fail": ma_fail,
        "anchor_mismatch": anchor_mismatch,
        "stage_mismatch": stage_mismatch,
        "warnings": len(warnings),
        "report": str(args.out),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
