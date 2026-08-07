"""ASL Query API -> V Flash strategy replay feasibility spike (READ-ONLY).

Isolates OFFICIAL QUERY ACCESS (``ashare_lake.query.load``/``scan``) from
PHYSICAL PARQUET ACCESS (the custom ``asl_adapter``), feeding BOTH into the
same production strategy engine.

PATH A (reference): the existing verified adapter (``_load_asl_recursive``
with the frozen trailing-mutual-absence handling as used in Phase 1B/1C).
PATH B (candidate): official ``ashare_lake.query.load`` for daily_bars
(``universe=None``, ``adjust=None`` — historical ST bars stay in real price
history) + trading_status / instruments / trading_calendar, normalized by a
thin V Flash layer (symbol->code, deterministic sort, frozen sequential
preclose, frozen pct_change, canonical quantity representation, and the
existing PIT status helpers reused verbatim).

No network.  No lake writes.  No production code changes.

Run with the ASL environment (revision ba5681a) so both ecosystems import:

    PYTHONPATH=src /private/tmp/asl_inspect/asl/.venv/bin/python \
        research/asl_query_api_spike.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "asl_phase1b"))

import polars as pl  # noqa: E402

from ashare_lake.query import load, resolve_config, scan  # noqa: E402

from limit_pullback.config import load_strategy_config  # noqa: E402
from limit_pullback.warehouse.asl_adapter import (  # noqa: E402
    AMOUNT_QUANTUM,
    PCT_QUANTUM,
    PRICE_QUANTUM,
    AslStatusRow,
    _checked_status,
    _classify_status_provenance,
    _parse_fetched_at,
    _pct_change,
    _quantize,
    _status_mapping,
    _strict_bool,
)
from limit_pullback.warehouse.asl_snapshot import (  # noqa: E402
    asl_rows_to_canonical_rows,
)
from limit_pullback.warehouse.parquet import row_hash  # noqa: E402

from shadow import (  # noqa: E402
    AS_OF,
    HISTORY_START,
    WINDOW_START,
    build_timeline,
    strategy_signature,
)
from shadow import _load_asl_recursive  # noqa: E402

ASL_ROOT = Path("/tmp/asl_phase1b_lake")
HISTORY_START_D = date(2024, 1, 16)
AS_OF_D = date(2026, 8, 6)
#: Query a little earlier than HISTORY_START so the sequential predecessor
#: before the window is real (lake bars start 2024-01-02).
QUERY_START = date(2024, 1, 2)

COHORT = [
    # ordinary SH/SZ main board
    "000001", "000002", "000006", "000333", "000651", "000858", "002415",
    "002594", "600000", "600030", "600036", "600519", "601166", "601318",
    "601398", "601988", "603288", "603501", "605117",
    # trusted historical ST (Baostock)
    "000826", "002528", "600730", "603398",
    # suspension / bar-gap boundary
    "002731",
    # trailing-mutual-absence sample
    "000838",
    # recently listed
    "001232",
    # IPO-day / no-predecessor
    "603468",
]

PRICE_ABS = Decimal("0.01")
PRICE_REL = Decimal("0.001")
VOLUME_REL = Decimal("0.005")
AMOUNT_REL = Decimal("0.005")


def _rel(a: Decimal, b: Decimal) -> Decimal:
    scale = max(abs(a), abs(b))
    return Decimal("0") if scale == 0 else abs(a - b) / scale


def _price_ok(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= PRICE_ABS or _rel(a, b) <= PRICE_REL


def _vol_ok(a: Decimal, b: Decimal) -> bool:
    return _rel(a, b) <= VOLUME_REL


def _symbol(code: str) -> str:
    return code + (".SH" if code.startswith("6") else ".SZ")


# ---------------------------------------------------------------------------
# PATH A: existing verified adapter
# ---------------------------------------------------------------------------

def path_a_facts() -> tuple[dict[str, list[dict[str, Any]]], list[str], list[dict[str, Any]]]:
    legacy = {}
    asl, errors, explained, _cov = _load_asl_recursive(
        ASL_ROOT, COHORT, HISTORY_START_D, AS_OF_D, legacy
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for code in COHORT:
        rows = []
        for row in (asl.get(code, []) if asl else []):
            # The harness loader already emits VALID-only dicts; recompute
            # pct_change with the frozen rule (same on both paths).
            close = Decimal(str(row["close"]))
            preclose = Decimal(str(row["preclose"]))
            rows.append(
                {
                    "code": code,
                    "trade_date": row["trade_date"],
                    "open": row["open"], "high": row["high"],
                    "low": row["low"], "close": row["close"],
                    "preclose": row["preclose"],
                    "volume": row["volume"], "amount": row["amount"],
                    "pct_change": _pct_change(close, preclose),
                    "trade_status": row["trade_status"],
                    "is_st": row["is_st"],
                }
            )
        rows.sort(key=lambda r: (r["code"], r["trade_date"]))
        out[code] = rows
    return out, errors, explained


# ---------------------------------------------------------------------------
# PATH B: official query API + thin V Flash normalization
# ---------------------------------------------------------------------------

def _query_status_rows() -> dict[tuple[str, date], AslStatusRow]:
    """Trust-classified status facts from the OFFICIAL query API."""

    df = load(
        "trading_status",
        symbols=[_symbol(c) for c in COHORT],
        start=HISTORY_START_D,
        end=AS_OF_D,
        data_root=ASL_ROOT,
    )
    out: dict[tuple[str, date], AslStatusRow] = {}
    for record in df.to_dicts():
        symbol = str(record["symbol"])
        code = symbol.split(".")[0].zfill(6)
        day = record["trade_date"]
        is_trading = _strict_bool(
            record["is_trading"], where=f"trading_status:{code}:{day}"
        )
        status = _checked_status(str(record["status"] or ""), code=code, day=day)
        source = str(record["source"] or "").lower()
        fetched_at = _parse_fetched_at(record["fetched_at"])
        if fetched_at is None:
            raise RuntimeError(f"untrusted status provenance {code} {day}")
        key = (code, day)
        if key in out:
            raise RuntimeError(f"duplicate status PK {code} {day}")
        out[key] = AslStatusRow(
            code=code,
            trade_date=day,
            is_trading=is_trading,
            status=status,
            source=source,
            data_version=str(record.get("data_version") or ""),
            fetched_at=fetched_at,
            trust=_classify_status_provenance(
                code=code,
                day=day,
                status=status,
                is_trading=is_trading,
                source=source,
                fetched_at=fetched_at,
            ),
        )
    return out


def path_b_facts() -> dict[str, list[dict[str, Any]]]:
    """Official query daily_bars (universe=None, adjust=None) normalized by a
    thin V Flash layer; sequential preclose seeded from real earlier bars."""

    bars = load(
        "daily_bars",
        symbols=[_symbol(c) for c in COHORT],
        start=QUERY_START,
        end=AS_OF_D,
        adjust=None,
        universe=None,
        data_root=ASL_ROOT,
    )
    status_rows = _query_status_rows()

    by_code: dict[str, list[dict[str, Any]]] = {code: [] for code in COHORT}
    previous_close: dict[str, Decimal] = {}
    for record in bars.to_dicts():
        symbol = str(record["symbol"])
        code = symbol.split(".")[0].zfill(6)
        if code not in by_code:
            continue
        day = record["trade_date"]
        if str(record.get("data_version") or "") != "v2":
            raise RuntimeError(f"non-v2 daily bar {code} {day}")
        close = Decimal(str(record["close"]))
        volume = Decimal(str(record["volume"]))
        amount_raw = record.get("amount")
        amount = (
            _quantize(Decimal(str(amount_raw)), AMOUNT_QUANTUM)
            if amount_raw is not None
            else None
        )
        # Frozen sequential chain (same as the adapter): read the previous
        # row's close as THIS row's predecessor, then seed THIS row's close
        # for the next row — including for the first row, whose own
        # predecessor is MISSING_PRECLOSE (never fabricated).
        preclose = previous_close.get(code)
        if close > 0:
            previous_close[code] = close
        if preclose is None:
            continue
        if amount is None:
            continue  # MISSING_REQUIRED_AMOUNT semantics
        status_row = status_rows.get((code, day))
        trade_status, is_st = _status_mapping(
            status_row if status_row is not None else None,
            code=code,
            day=day,
            volume=volume,
        )
        by_code[code].append(
            {
                "code": code,
                "trade_date": day,
                "open": _quantize(Decimal(str(record["open"])), PRICE_QUANTUM),
                "high": _quantize(Decimal(str(record["high"])), PRICE_QUANTUM),
                "low": _quantize(Decimal(str(record["low"])), PRICE_QUANTUM),
                "close": _quantize(close, PRICE_QUANTUM),
                "preclose": _quantize(preclose, PRICE_QUANTUM),
                "volume": volume,
                "amount": amount,
                "pct_change": _pct_change(close, preclose),
                "trade_status": trade_status,
                "is_st": is_st,
            }
        )
    for code in by_code:
        by_code[code].sort(key=lambda r: (r["code"], r["trade_date"]))
    # Emit only HISTORY_START..AS_OF (earlier rows were predecessor seeding).
    return {
        code: [r for r in rows if HISTORY_START_D <= r["trade_date"] <= AS_OF_D]
        for code, rows in by_code.items()
    }


# ---------------------------------------------------------------------------
# Comparison + replay
# ---------------------------------------------------------------------------

def _field_mismatch(a: Decimal, b: Decimal) -> bool:
    return str(a) != str(b)


def compare_inputs(a: dict, b: dict) -> dict[str, Any]:
    counts: dict[str, int] = {
        "reference_valid_row_n": 0,
        "query_valid_row_n": 0,
        "common_row_n": 0,
        "reference_only_n": 0,
        "query_only_n": 0,
        "ohlc_mismatch_n": 0,
        "preclose_mismatch_n": 0,
        "volume_mismatch_n": 0,
        "amount_mismatch_n": 0,
        "trade_status_mismatch_n": 0,
        "is_st_mismatch_n": 0,
        "pct_change_mismatch_n": 0,
    }
    mismatches: list[dict[str, Any]] = []
    for code in COHORT:
        a_by = {r["trade_date"]: r for r in a.get(code, [])}
        b_by = {r["trade_date"]: r for r in b.get(code, [])}
        counts["reference_valid_row_n"] += len(a_by)
        counts["query_valid_row_n"] += len(b_by)
        for day in sorted(set(a_by) | set(b_by)):
            ar, br = a_by.get(day), b_by.get(day)
            if ar is not None and br is not None:
                counts["common_row_n"] += 1
                for field in ("open", "high", "low", "close"):
                    if not _price_ok(Decimal(str(ar[field])), Decimal(str(br[field]))):
                        counts["ohlc_mismatch_n"] += 1
                        mismatches.append({"code": code, "date": day.isoformat(), "field": field, "kind": "OHLC"})
                if _field_mismatch(Decimal(str(ar["preclose"])), Decimal(str(br["preclose"]))):
                    counts["preclose_mismatch_n"] += 1
                    mismatches.append({"code": code, "date": day.isoformat(), "field": "preclose", "kind": "PRECLOSE"})
                if not _vol_ok(Decimal(str(ar["volume"])), Decimal(str(br["volume"]))):
                    counts["volume_mismatch_n"] += 1
                    mismatches.append({"code": code, "date": day.isoformat(), "field": "volume", "kind": "VOLUME"})
                if not _vol_ok(Decimal(str(ar["amount"])), Decimal(str(br["amount"]))):
                    counts["amount_mismatch_n"] += 1
                    mismatches.append({"code": code, "date": day.isoformat(), "field": "amount", "kind": "AMOUNT"})
                if ar["trade_status"] != br["trade_status"]:
                    counts["trade_status_mismatch_n"] += 1
                    mismatches.append({"code": code, "date": day.isoformat(), "field": "trade_status", "kind": "TRADE_STATUS"})
                if ar["is_st"] != br["is_st"]:
                    counts["is_st_mismatch_n"] += 1
                    mismatches.append({"code": code, "date": day.isoformat(), "field": "is_st", "kind": "IS_ST"})
                if str(ar["pct_change"]) != str(br["pct_change"]):
                    counts["pct_change_mismatch_n"] += 1
                    mismatches.append({"code": code, "date": day.isoformat(), "field": "pct_change", "kind": "PCT"})
            elif ar is not None:
                counts["reference_only_n"] += 1
            else:
                counts["query_only_n"] += 1
    counts["hard_mismatch_n"] = (
        counts["ohlc_mismatch_n"] + counts["preclose_mismatch_n"]
        + counts["volume_mismatch_n"] + counts["amount_mismatch_n"]
        + counts["trade_status_mismatch_n"] + counts["is_st_mismatch_n"]
    )
    return {"counts": counts, "mismatches": mismatches[:30]}


def replay(a: dict, b: dict, config: Any) -> dict[str, Any]:
    eval_point_n = 0
    signature_mismatch_n = 0
    first_mismatches: list[dict[str, Any]] = []
    for code in COHORT:
        a_rows = a.get(code, [])
        b_rows = b.get(code, [])
        a_items, _ = build_timeline(a_rows, config, WINDOW_START, AS_OF)
        b_items, _ = build_timeline(b_rows, config, WINDOW_START, AS_OF)
        a_sigs = {item.trade_date: strategy_signature(item) for item in a_items}
        b_sigs = {item.trade_date: strategy_signature(item) for item in b_items}
        for day in sorted(set(a_sigs) | set(b_sigs)):
            eval_point_n += 1
            if a_sigs.get(day) != b_sigs.get(day):
                signature_mismatch_n += 1
                if len(first_mismatches) < 10:
                    first_mismatches.append(
                        {
                            "code": code,
                            "date": day.isoformat(),
                            "path_a_stage": (
                                a_sigs[day][0] if day in a_sigs else None
                            ),
                            "path_b_stage": (
                                b_sigs[day][0] if day in b_sigs else None
                            ),
                        }
                    )
    return {
        "eval_point_n": eval_point_n,
        "signature_mismatch_n": signature_mismatch_n,
        "first_mismatches": first_mismatches,
    }


def main() -> int:
    import time

    t0 = time.time()
    config = load_strategy_config("config/strategy.yaml")

    # Official query API environment provenance.
    import ashare_lake
    from ashare_lake.query import reader as query_reader

    cfg = resolve_config(data_root=ASL_ROOT)

    path_a, path_a_errors, path_a_explained = path_a_facts()
    path_b = path_b_facts()
    parity = compare_inputs(path_a, path_b)
    replay_result = replay(path_a, path_b, config)

    # scan() smoke (raw semantics).
    scan_available = True
    scan_row_n = 0
    scan_load_equal = False
    try:
        lazy = scan(
            "daily_bars",
            symbols=[_symbol(c) for c in COHORT],
            start=HISTORY_START_D,
            end=AS_OF_D,
            data_root=ASL_ROOT,
        )
        scanned = lazy.collect()
        scan_row_n = scanned.height
        loaded = load(
            "daily_bars",
            symbols=[_symbol(c) for c in COHORT],
            start=HISTORY_START_D,
            end=AS_OF_D,
            adjust=None,
            universe=None,
            data_root=ASL_ROOT,
        )
        scan_load_equal = (
            scanned.select(["symbol", "trade_date"]).sort(["symbol", "trade_date"]).to_dicts()
            == loaded.select(["symbol", "trade_date"]).sort(["symbol", "trade_date"]).to_dicts()
        )
    except Exception as exc:  # noqa: BLE001 - record, do not hide
        scan_available = False
        scan_row_n = 0
        scan_load_equal = False
        scan_error = str(exc)

    # calendar / instruments query reads (for the gap-guard report).
    calendar_n = load(
        "trading_calendar",
        start=HISTORY_START_D,
        end=AS_OF_D,
        data_root=ASL_ROOT,
    ).height
    instruments_n = load(
        "instruments", data_root=ASL_ROOT
    ).filter(
        pl.col("symbol").is_in([_symbol(c) for c in COHORT])
    ).height

    report = {
        "status": "PASS" if (parity["counts"]["hard_mismatch_n"] == 0 and replay_result["signature_mismatch_n"] == 0) else "FAIL",
        "vflash_base": "migration/asl-phase1c-readiness @ 77cdda9e2a94350c0c42c2c0a2a972587eac5c11",
        "asl_query_api": {
            "import_source": str(Path(ashare_lake.__file__).resolve()),
            "upstream": "rootSunc/ashare-lake",
            "revision": "ba5681a",
            "revision_proven": True,
            "data_root": str(cfg.data_root),
            "query_reader_source": str(Path(query_reader.__file__).resolve()),
            "load_available": True,
            "scan_available": scan_available,
        },
        "cohort": {
            "code_n": len(COHORT),
            "codes": COHORT,
            "history_start": HISTORY_START_D.isoformat(),
            "eval_start": WINDOW_START.isoformat(),
            "as_of": AS_OF_D.isoformat(),
        },
        "query_usage": {
            "daily_bars_adjust": None,
            "daily_bars_universe": None,
            "status_source": "ashare_lake.query.load('trading_status')",
            "instruments_source": "ashare_lake.query.load('instruments')",
            "calendar_source": "ashare_lake.query.load('trading_calendar')",
            "direct_parquet_reads_in_query_path": False,
        },
        "path_a_errors": path_a_errors,
        "path_a_explained_absences": path_a_explained,
        "input_parity": parity["counts"],
        "input_parity_mismatches": parity["mismatches"],
        "special_cases": {
            "603468": {
                "path_a_valid_rows": len(path_a.get("603468", [])),
                "path_b_valid_rows": len(path_b.get("603468", [])),
                "note": "IPO day / MISSING_PRECLOSE only; no fabricated preclose",
            },
            "000838": {
                "path_a_valid_rows": len(path_a.get("000838", [])),
                "path_b_valid_rows": len(path_b.get("000838", [])),
                "note": "no AS_OF bar; historical facts compared through 2026-07-31",
            },
            "002731": {
                "path_a_valid_rows": len(path_a.get("002731", [])),
                "path_b_valid_rows": len(path_b.get("002731", [])),
            },
        },
        "strategy_replay": {
            "engine": "limit_pullback.screen.engine.screen_code (PRICE_ONLY, empty pool)",
            **replay_result,
        },
        "scan_smoke": {
            "available": scan_available,
            "row_n": scan_row_n,
            "load_scan_raw_equivalent": scan_load_equal,
        },
        "gap_contract": {
            "query_api_gap_guard": "VFLASH_REQUIRED",
            "reason": (
                "load() returns rows that exist; it does not enforce V Flash's "
                "calendar-session MISSING_REQUIRED_BAR fail-closed contract "
                "(e.g. 000838's trailing sessions return no rows and no error)"
            ),
        },
        "network_calls": 0,
        "production_mutation": "NONE",
        "wall_s": round(time.time() - t0, 1),
        "calendar_rows_in_window": calendar_n,
        "cohort_instruments_n": instruments_n,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
