"""Phase-1A parity gate: LEGACY canonical vs ASL adapter (read-only).

Compares the frozen V Flash canonical daily contract against the ASL-backed
adapter output for a bounded sample and returns a hard gate:

    PASS             exit 0
    BLOCKED_PARITY   exit 2   (comparison failures: OHLC/volume/amount/
                               preclose/pct/structure/clean-MA/anchor/stage)
    BLOCKED_DATA     exit 3   (adapter contract violations or missing input)

Legacy-hole completeness deltas and status semantic deltas are reported but
non-fatal (they are data-quality observations, not adapter failures).

The latest-date setup-stage comparison is a SMOKE CHECK only, never full
episode parity (timeline-level episode parity is Phase-1B work).

Outputs:
* compact deterministic summary  -> research/asl_phase1a/parity_summary.json
* full row-level report          -> research/asl_phase1a/artifacts/
                                    parity_report_full.json (gitignored)

Usage:
    PYTHONPATH=src python research/asl_phase1a/parity.py \
        --legacy-root "/Users/luke808/AI/V flash/data" \
        --legacy-snapshot snap-2026-08-06-e798f88ff67b.parquet \
        --asl-root /tmp/asl_phase1a_lake \
        --start 2026-05-28 --as-of 2026-08-06 \
        --codes 000001,600519,601318,000010,000524,000593,002963,605179,605198,000037,300750
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

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
from limit_pullback.warehouse.asl_adapter import (
    AslAdapterError,
    load_asl_daily_slice,
)

PRICE_ABS = Decimal("0.01")
PRICE_REL = Decimal("0.001")
VOLUME_REL = Decimal("0.005")
AMOUNT_REL = Decimal("0.005")
PCT_ABS = Decimal("0.05")
MA_REL = Decimal("0.001")

GATE_PASS = "PASS"
GATE_BLOCKED_PARITY = "BLOCKED_PARITY"
GATE_BLOCKED_DATA = "BLOCKED_DATA"

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
        turnover_rate=None,
        pct_change=None,
        trade_status=bool(row.get("trade_status", True)),
        is_st=(
            bool(row["is_st"]) if row.get("is_st") is not None else None
        ),
        source="PARITY",
        fetched_at=FIXED_FETCHED_AT,
    )


def last_n_bar_dates(
    sorted_dates: Sequence[date], as_of: date, n: int
) -> tuple[date, ...] | None:
    """The exact last *n* bar dates at or before *as_of*, or None if fewer."""

    eligible = [day for day in sorted_dates if day <= as_of]
    if len(eligible) < n:
        return None
    return tuple(eligible[-n:])


def classify_ma_window(
    legacy_dates: Sequence[date],
    adapter_dates: Sequence[date],
    as_of: date,
    n: int,
) -> str:
    """CLEAN when both sides' last-N bar-date sequences are identical.

    Otherwise HOLE_AFFECTED_MA{n} (or INSUFFICIENT when a side cannot form
    the window).  A hole older than the active N-bar window never
    contaminates the current comparison.
    """

    legacy_window = last_n_bar_dates(legacy_dates, as_of, n)
    adapter_window = last_n_bar_dates(adapter_dates, as_of, n)
    if legacy_window is None or adapter_window is None:
        return "INSUFFICIENT"
    if legacy_window == adapter_window:
        return "CLEAN"
    return f"HOLE_AFFECTED_MA{n}"


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frozen_pct(row: Mapping[str, Any]) -> Decimal | None:
    preclose = Decimal(str(row["preclose"]))
    if preclose <= 0:
        return None
    return (
        (Decimal(str(row["close"])) - preclose) / preclose * Decimal("100")
    ).quantize(Decimal("0.0001"))


def _compare_code(
    code: str,
    legacy_rows: list[dict[str, Any]],
    adapter_rows: list[dict[str, Any]],
    adapter_by_date: Mapping[date, dict[str, Any]],
    config: Any,
    as_of: date,
    suspended_sessions: set[tuple[str, date]],
    hard_failures: list[str],
) -> dict[str, Any]:
    legacy_by_date = {row["trade_date"]: row for row in legacy_rows}
    all_sessions = sorted(set(legacy_by_date) | set(adapter_by_date))

    sessions: dict[str, list[str]] = {"BOTH": [], "LEGACY_ONLY": [], "ASL_ONLY": []}
    field_results: list[dict[str, Any]] = []
    preclose_exact = 0
    preclose_total = 0
    turnover_not_comparable = []
    structure_mismatches: list[dict[str, Any]] = []
    status_deltas = {
        "EXACT_STATUS_MATCH": 0,
        "LEGACY_UNKNOWN_TO_ASL_TRUE": 0,
        "LEGACY_UNKNOWN_TO_ASL_FALSE": 0,
        "TRUE_STATUS_CONFLICT": 0,
    }
    ma_windows = {
        "MA5": {"CLEAN": 0, "CLEAN_MISMATCH": 0, "HOLE_AFFECTED": 0},
        "MA10": {"CLEAN": 0, "CLEAN_MISMATCH": 0, "HOLE_AFFECTED": 0},
        "MA20": {"CLEAN": 0, "CLEAN_MISMATCH": 0, "HOLE_AFFECTED": 0},
    }
    legacy_holes: list[str] = []

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
        fields: dict[str, Any] = {}
        for field in ("open", "high", "low", "close", "preclose"):
            lv = Decimal(str(legacy[field]))
            av = Decimal(str(adapter[field]))
            ok = _price_ok(lv, av)
            if not ok:
                hard_failures.append(
                    f"{code}:{day}:{field} outside tolerance "
                    f"(legacy {lv} vs adapter {av})"
                )
            fields[field] = {
                "legacy": str(lv), "adapter": str(av),
                "abs_diff": str(abs(lv - av)), "rel_diff": str(_rel(lv, av)),
                "ok": ok,
            }
        for field in ("volume", "amount"):
            lv = Decimal(str(legacy[field]))
            av = Decimal(str(adapter[field]))
            ok = _vol_ok(lv, av)
            if not ok:
                hard_failures.append(
                    f"{code}:{day}:{field} outside tolerance "
                    f"(legacy {lv} vs adapter {av})"
                )
            fields[field] = {
                "legacy": str(lv), "adapter": str(av),
                "rel_diff": str(_rel(lv, av)), "ok": ok,
            }

        preclose_total += 1
        if Decimal(str(legacy["preclose"])) == Decimal(str(adapter["preclose"])):
            preclose_exact += 1
        else:
            hard_failures.append(
                f"{code}:{day}:preclose mismatch "
                f"(legacy {legacy['preclose']} vs adapter {adapter['preclose']})"
            )

        lpct = _frozen_pct(legacy)
        apct = _frozen_pct(adapter)
        pct_ok = lpct is not None and apct is not None and abs(lpct - apct) <= PCT_ABS
        if not pct_ok:
            hard_failures.append(
                f"{code}:{day}:pct_change mismatch (legacy {lpct} vs adapter {apct})"
            )
        fields["pct_change_recomputed"] = {
            "legacy": str(lpct), "adapter": str(apct), "ok": pct_ok,
        }

        # Status semantic delta categories (never hidden).
        legacy_is_st = (
            bool(legacy["is_st"]) if legacy.get("is_st") is not None else None
        )
        adapter_is_st = adapter["is_st"]
        if legacy_is_st is None:
            if adapter_is_st is True:
                status_deltas["LEGACY_UNKNOWN_TO_ASL_TRUE"] += 1
            elif adapter_is_st is False:
                status_deltas["LEGACY_UNKNOWN_TO_ASL_FALSE"] += 1
        elif adapter_is_st is None:
            status_deltas["LEGACY_UNKNOWN_TO_ASL_FALSE"] += 1
        elif legacy_is_st == adapter_is_st:
            status_deltas["EXACT_STATUS_MATCH"] += 1
        else:
            status_deltas["TRUE_STATUS_CONFLICT"] += 1
        fields["status"] = {
            "legacy_is_st": legacy_is_st,
            "adapter_is_st": adapter_is_st,
            "legacy_trade_status": bool(legacy.get("trade_status", True)),
            "adapter_trade_status": adapter["trade_status"],
        }

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
                        "session": day, "check": name,
                        "legacy": lv, "adapter": av,
                        "theoretical_limit": str(
                            theoretical_limit_price(adapter_bar, config)
                        ),
                    }
                )
                hard_failures.append(
                    f"{code}:{day}:structure {name} mismatch "
                    f"(legacy {lv} vs adapter {av})"
                )

        if legacy.get("turnover_rate") is not None:
            turnover_not_comparable.append(
                {
                    "session": day,
                    "legacy_turnover_rate": str(legacy["turnover_rate"]),
                    "reason": "ASL has no PIT-safe per-stock turnover field",
                }
            )
        field_results.append({"session": day, "fields": fields})

    # MA windows: exact per-window bar-date sequences on each side.
    legacy_dates = [row["trade_date"] for row in legacy_rows]
    adapter_dates = [row["trade_date"] for row in adapter_rows]
    ma_report: dict[str, Any] = {}
    try:
        legacy_bars = [_to_bar(row) for row in legacy_rows]
        adapter_bars = [_to_bar(row) for row in adapter_rows]
        legacy_inds = calculate_indicators(legacy_bars, config.indicators, as_of)
        adapter_inds = calculate_indicators(adapter_bars, config.indicators, as_of)
        legacy_ma = {point.trade_date: point.raw_equivalent_mas for point in legacy_inds}
        adapter_ma = {point.trade_date: point.raw_equivalent_mas for point in adapter_inds}
        for d in sorted(set(legacy_by_date) & set(adapter_by_date)):
            for n in (5, 10, 20):
                key = f"MA{n}"
                classification = classify_ma_window(
                    legacy_dates, adapter_dates, d, n
                )
                if classification == "INSUFFICIENT":
                    continue
                lm = legacy_ma.get(d, {}).get(n)
                am = adapter_ma.get(d, {}).get(n)
                if lm is None or am is None:
                    continue
                if classification == "CLEAN":
                    ma_windows[key]["CLEAN"] += 1
                    if _rel(lm, am) > MA_REL:
                        ma_windows[key]["CLEAN_MISMATCH"] += 1
                        hard_failures.append(
                            f"{code}:{d}:CLEAN {key} mismatch "
                            f"(legacy {lm} vs adapter {am})"
                        )
                        ma_report[f"{d}:{key}"] = {
                            "legacy": str(lm), "adapter": str(am),
                            "rel_diff": str(_rel(lm, am)),
                        }
                else:
                    ma_windows[key]["HOLE_AFFECTED"] += 1
    except Exception as exc:  # noqa: BLE001 — recorded MA exception is a hard failure
        hard_failures.append(f"{code}:MA comparison exception: {exc}")
        ma_report = {"error": str(exc)}

    # Anchor + latest-date setup-stage SMOKE check (not episode parity).
    anchor_report: dict[str, Any] = {}
    stage_smoke: dict[str, Any] = {}
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
            hard_failures.append(f"{code}:anchor presence mismatch")
        else:
            anchor_report["match"] = (
                legacy_anchor.snapshot.anchor_date == adapter_anchor.snapshot.anchor_date
                and legacy_anchor.snapshot.anchor_price
                == adapter_anchor.snapshot.anchor_price
            )
            if not anchor_report["match"]:
                hard_failures.append(f"{code}:anchor mismatch")

        latest = max(
            (
                day for day in all_sessions
                if day in legacy_by_date and day in adapter_by_date
            ),
            default=None,
        )
        if latest is not None:
            legacy_signal = evaluate_strategy(
                bars=[_to_bar(row) for row in legacy_rows],
                as_of=latest, config=config, generated_at=FIXED_FETCHED_AT,
            )
            adapter_signal = evaluate_strategy(
                bars=[_to_bar(row) for row in adapter_rows],
                as_of=latest, config=config, generated_at=FIXED_FETCHED_AT,
            )
            stage_smoke = {
                "as_of": latest.isoformat(),
                "legacy": legacy_signal.setup_stage.value,
                "adapter": adapter_signal.setup_stage.value,
                "match": legacy_signal.setup_stage == adapter_signal.setup_stage,
                "note": "SMOKE CHECK ONLY (latest common date); not full episode parity",
            }
            if not stage_smoke["match"]:
                hard_failures.append(
                    f"{code}:stage smoke mismatch at {latest}"
                )
    except Exception as exc:  # noqa: BLE001 — recorded exceptions are hard failures
        hard_failures.append(f"{code}:anchor/stage comparison exception: {exc}")

    return {
        "code": code,
        "sessions": sessions,
        "field_comparisons": {
            "rows": field_results,
            "preclose_exact": preclose_exact,
            "preclose_total": preclose_total,
        },
        "structure_mismatches": structure_mismatches,
        "ma": ma_windows,
        "ma_details": ma_report,
        "anchor": anchor_report,
        "stage_smoke": stage_smoke,
        "status_deltas": status_deltas,
        "turnover_not_comparable": turnover_not_comparable,
        "legacy_holes": legacy_holes,
    }


def _corporate_action_intersection(
    asl_root: Path,
    codes: set[str],
    start: date,
    as_of: date,
    legacy: dict[str, list[dict[str, Any]]],
    adapter_by_date: dict[str, dict[date, dict[str, Any]]],
    config: Any,
) -> dict[str, Any]:
    """Find a real ex-date present in ASL corporate_actions, legacy rows AND
    adapter bars; compare the ex-date row.  Honest NOT_PROVEN when absent."""

    ca_root = asl_root / "curated" / "corporate_actions"
    if not ca_root.exists():
        return {"status": "NO_CORPORATE_ACTIONS_DATASET"}
    ex_dates: dict[tuple[str, date], str] = {}
    for path in sorted(ca_root.rglob("*.parquet")):
        table = pq.ParquetFile(path).read(
            columns=["symbol", "ex_date", "action_type"]
        )
        for symbol, ex_date, action_type in zip(
            table.column("symbol").to_pylist(),
            table.column("ex_date").to_pylist(),
            table.column("action_type").to_pylist(),
            strict=True,
        ):
            code = str(symbol).split(".")[0].zfill(6)
            if code not in codes:
                continue
            if not isinstance(ex_date, date):
                continue
            if start <= ex_date <= as_of:
                ex_dates[(code, ex_date)] = str(action_type)
    if not ex_dates:
        return {"status": "REAL_EX_DATE_INTERSECTION_PARITY_NOT_PROVEN",
                "reason": "no ASL corporate-action ex-date inside the window"}

    for (code, ex_date), action_type in sorted(ex_dates.items()):
        legacy_row = next(
            (
                row for row in legacy.get(code, [])
                if row["trade_date"] == ex_date
            ),
            None,
        )
        adapter_row = adapter_by_date.get(code, {}).get(ex_date)
        if legacy_row is None or adapter_row is None:
            continue
        comparison = {
            "status": "INTERSECTION_FOUND",
            "code": code,
            "ex_date": ex_date.isoformat(),
            "action_type": action_type,
            "legacy_preclose": str(legacy_row["preclose"]),
            "adapter_preclose": str(adapter_row["preclose"]),
            "close": str(legacy_row["close"]),
            "legacy_pct": str(_frozen_pct(legacy_row)),
            "adapter_pct": str(adapter_row["pct_change"]),
            "legacy_limit_close": bool(
                is_limit_close(
                    _to_bar(legacy_row),
                    config,
                )
            ),
            "adapter_limit_close": bool(adapter_row["close"]),
            "preclose_match": Decimal(str(legacy_row["preclose"]))
            == Decimal(str(adapter_row["preclose"])),
        }
        # pct equality check
        comparison["pct_match"] = (
            _frozen_pct(legacy_row) == adapter_row["pct_change"]
        )
        return comparison
    return {
        "status": "REAL_EX_DATE_INTERSECTION_PARITY_NOT_PROVEN",
        "reason": "all window ex-dates fall outside the legacy/adapter row intersection",
        "ex_dates_in_window": [
            f"{code}:{day.isoformat()}({action})"
            for (code, day), action in sorted(ex_dates.items())
        ],
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
    parser.add_argument(
        "--summary-out",
        default="research/asl_phase1a/parity_summary.json",
        type=Path,
    )
    parser.add_argument(
        "--full-out",
        default="research/asl_phase1a/artifacts/parity_report_full.json",
        type=Path,
    )
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start)
    as_of = date.fromisoformat(args.as_of)
    codes = tuple(sorted({str(code).zfill(6) for code in args.codes.split(",")}))
    config = load_strategy_config(args.config)

    hard_failures: list[str] = []
    try:
        legacy = _read_legacy(
            args.legacy_root, args.legacy_snapshot, set(codes), start, as_of
        )
        slice_ = load_asl_daily_slice(
            args.asl_root,
            as_of=as_of,
            start=start,
            codes=codes,
        )
    except (AslAdapterError, FileNotFoundError) as exc:
        summary = {
            "gate": GATE_BLOCKED_DATA,
            "reason": f"{type(exc).__name__}: {exc}",
            "input": {
                "tested_compat_revision": "ba5681a",
                "legacy_snapshot": args.legacy_snapshot,
                "window": {"start": start.isoformat(), "as_of": as_of.isoformat()},
                "codes": list(codes),
            },
        }
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 3

    adapter_by_code: dict[str, dict[date, dict[str, Any]]] = {}
    adapter_fail_closed: dict[str, int] = {}
    for row in slice_.rows:
        if row.row_status != "VALID_ROW":
            adapter_fail_closed[row.row_status] = (
                adapter_fail_closed.get(row.row_status, 0) + 1
            )
            continue
        adapter_by_code.setdefault(row.code, {})[row.trade_date] = {
            "open": row.open, "high": row.high, "low": row.low,
            "close": row.close, "preclose": row.preclose,
            "volume": row.volume, "amount": row.amount,
            "pct_change": row.pct_change,
            "trade_status": row.trade_status, "is_st": row.is_st,
            "code": row.code, "trade_date": row.trade_date,
        }
    adapter_rows_by_code: dict[str, list[dict[str, Any]]] = {}
    for code, by_date in adapter_by_code.items():
        adapter_rows_by_code[code] = [by_date[day] for day in sorted(by_date)]

    suspended_sessions = set(slice_.suspended_sessions)
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
            hard_failures.append(f"{code}: no legacy CONFIRMED rows in window")
            continue
        if code not in adapter_by_code:
            hard_failures.append(f"{code}: no adapter VALID rows in window")
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
                hard_failures,
            )
        )

    ca_result = _corporate_action_intersection(
        args.asl_root, set(codes), start, as_of, legacy, adapter_by_code, config
    )

    gate = GATE_PASS if not hard_failures else GATE_BLOCKED_PARITY

    full = {
        "gate": gate,
        "hard_failures": hard_failures,
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
            f"{code}:{day.isoformat()}"
            for code, day in slice_.suspended_sessions
        ],
        "missing_required_bars": [
            {
                "code": item.code,
                "trade_date": item.trade_date.isoformat(),
                "reason": item.reason,
            }
            for item in slice_.missing_required_bars
        ],
        "adapter_fail_closed_rows": adapter_fail_closed,
        "corporate_action_intersection": ca_result,
        "results": results,
        "warnings": list(slice_.warnings),
    }
    args.full_out.parent.mkdir(parents=True, exist_ok=True)
    args.full_out.write_text(
        json.dumps(full, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    compared_rows = sum(
        len(r["field_comparisons"]["rows"])
        for r in results
        if "field_comparisons" in r
    )
    preclose_exact = sum(
        r["field_comparisons"]["preclose_exact"]
        for r in results
        if "field_comparisons" in r
    )
    session_counts = {"BOTH": 0, "LEGACY_ONLY": 0, "ASL_ONLY": 0}
    for r in results:
        if "sessions" not in r:
            continue
        for key in session_counts:
            session_counts[key] += len(r["sessions"][key])
    status_totals = {
        key: sum(
            r["status_deltas"][key]
            for r in results
            if "status_deltas" in r
        )
        for key in (
            "EXACT_STATUS_MATCH",
            "LEGACY_UNKNOWN_TO_ASL_TRUE",
            "LEGACY_UNKNOWN_TO_ASL_FALSE",
            "TRUE_STATUS_CONFLICT",
        )
    }
    ma_totals = {
        key: {
            metric: sum(
                r["ma"][key][metric]
                for r in results
                if "ma" in r
            )
            for metric in ("CLEAN", "CLEAN_MISMATCH", "HOLE_AFFECTED")
        }
        for key in ("MA5", "MA10", "MA20")
    }
    structure_mismatch = sum(
        len(r["structure_mismatches"])
        for r in results
        if "structure_mismatches" in r
    )
    anchor_smoke = {
        "matched": sum(
            1 for r in results if "anchor" in r and r["anchor"].get("match") is True
        ),
        "total": sum(
            1 for r in results if "anchor" in r
        ),
    }
    stage_smoke = {
        "matched": sum(
            1 for r in results if "stage_smoke" in r and r["stage_smoke"].get("match") is True
        ),
        "total": sum(
            1 for r in results if "stage_smoke" in r and r["stage_smoke"]
        ),
    }
    legacy_holes_total = sum(
        len(r["legacy_holes"]) for r in results if "legacy_holes" in r
    )

    summary = {
        "contract": "VFLASH_ASL_PHASE1A_PARITY_SUMMARY_V2",
        "gate": gate,
        "input": {
            "tested_compat_revision": slice_.tested_compat_revision,
            "legacy_snapshot": args.legacy_snapshot,
            "legacy_snapshot_sha256": _sha256_file(
                args.legacy_root / "canonical" / "daily_bars" / args.legacy_snapshot
            ),
            "window": {"start": start.isoformat(), "as_of": as_of.isoformat()},
            "codes": list(codes),
        },
        "row_counts": {
            "compared_rows": compared_rows,
            "sessions": session_counts,
            "adapter_fail_closed_rows": adapter_fail_closed,
            "missing_required_bars": len(slice_.missing_required_bars),
        },
        "tolerances": {
            "price_abs": str(PRICE_ABS),
            "price_rel": str(PRICE_REL),
            "volume_rel": str(VOLUME_REL),
            "amount_rel": str(AMOUNT_REL),
            "pct_abs": str(PCT_ABS),
            "ma_rel": str(MA_REL),
        },
        "field": {
            "preclose_exact": f"{preclose_exact}/{compared_rows}",
            "structure_mismatches": structure_mismatch,
        },
        "status_deltas": status_totals,
        "ma": ma_totals,
        "anchor_smoke": anchor_smoke,
        "stage_smoke": stage_smoke,
        "corporate_action_intersection": {
            "status": ca_result["status"],
            **(
                {
                    "reason": ca_result["reason"],
                    "ex_dates_in_window": ca_result.get("ex_dates_in_window", []),
                }
                if ca_result["status"] != "INTERSECTION_FOUND"
                else {
                    "code": ca_result["code"],
                    "ex_date": ca_result["ex_date"],
                    "action_type": ca_result["action_type"],
                    "preclose_match": ca_result["preclose_match"],
                    "pct_match": ca_result["pct_match"],
                }
            ),
        },
        "legacy_holes_total": legacy_holes_total,
        "hard_failure_count": len(hard_failures),
    }
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    args.summary_out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if gate == GATE_PASS else (2 if gate == GATE_BLOCKED_PARITY else 3)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
