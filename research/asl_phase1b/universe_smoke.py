"""Main-board non-ST universe census at AS_OF + bounded smoke (<=50 codes).

READ-ONLY, bounded: no full-market strategy run, no ST backfill.

* Census: ASL instruments main-board universe + listing state + PIT
  trading-status/ST facts + AS_OF daily bars -> ELIGIBLE / EXCLUDED_ST /
  EXCLUDED_SUSPENDED / EXCLUDED_OTHER counts, with the frozen Phase-2D0
  universe as a QA cross-check.
* Smoke: at most 50 representative codes (eligible / ST / suspended /
  ChiNext / STAR / ETF / delisted).  For main-board codes the eligibility
  filter runs BEFORE screen_code; excluded code-dates produce no strategy
  output.

Usage:
    PYTHONPATH=src python research/asl_phase1b/universe_smoke.py \
        --asl-root /tmp/asl_phase1b_lake \
        --universe /tmp/frozen_universe_phase2d0.json \
        --out research/asl_phase1b/artifacts/universe_smoke.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyarrow.parquet as pq  # noqa: E402

from limit_pullback.config import load_strategy_config  # noqa: E402
from eligibility import (  # noqa: E402
    filter_eligible_rows,
    is_mainboard_instrument,
    is_strategy_eligible,
    load_instruments,
)
from shadow import (  # noqa: E402
    AS_OF,
    HISTORY_START,
    WINDOW_START,
    build_timeline,
    strategy_signature,
)
from shadow import _load_asl_recursive  # noqa: E402

SMOKE_LIMIT = 50


def _read_asof_bars(asl_root: Path) -> dict[str, dict[str, Any]]:
    """{code: {volume, amount}} for the AS_OF daily_bars partition."""

    partition = Path(asl_root) / "curated" / "daily_bars" / f"trade_date={AS_OF.isoformat()}"
    out: dict[str, dict[str, Any]] = {}
    if not partition.exists():
        return out
    for file_path in sorted(partition.glob("*.parquet")):
        table = pq.ParquetFile(file_path).read(
            columns=["symbol", "trade_date", "volume", "amount"]
        )
        for symbol, day, volume, amount in zip(
            table.column("symbol").to_pylist(),
            table.column("trade_date").to_pylist(),
            table.column("volume").to_pylist(),
            table.column("amount").to_pylist(),
            strict=True,
        ):
            if day != AS_OF:
                continue
            code = str(symbol).split(".")[0].zfill(6)
            out[code] = {"volume": volume, "amount": amount}
    return out


def _read_status_at_asof(asl_root: Path) -> tuple[set[str], set[str]]:
    """(baostock ST codes at AS_OF, derived-bar-gap codes at AS_OF)."""

    st_codes: set[str] = set()
    gap_codes: set[str] = set()
    status_root = Path(asl_root) / "curated" / "trading_status"
    for month in ("2026-07", "2026-08"):
        for file_path in sorted((status_root / f"trade_date={month}").glob("*.parquet")):
            table = pq.ParquetFile(file_path).read(
                columns=["symbol", "trade_date", "source"]
            )
            for symbol, day, source in zip(
                table.column("symbol").to_pylist(),
                table.column("trade_date").to_pylist(),
                table.column("source").to_pylist(),
                strict=True,
            ):
                if day != AS_OF:
                    continue
                code = str(symbol).split(".")[0].zfill(6)
                if source == "baostock":
                    st_codes.add(code)
                elif source == "derived_bar_gap":
                    gap_codes.add(code)
    return st_codes, gap_codes


def census(
    asl_root: Path,
    instruments: dict[str, dict[str, Any]],
    frozen_members: set[str],
) -> dict[str, Any]:
    """AS_OF universe counts over ASL instruments (main-board contract)."""

    mainboard = {
        code for code, inst in instruments.items()
        if is_mainboard_instrument(inst)
    }
    non_mainboard_stock = {
        code for code, inst in instruments.items()
        if inst["asset_type"] == "stock" and code not in mainboard
    }
    bars_asof = _read_asof_bars(asl_root)
    st_asof, gap_asof = _read_status_at_asof(asl_root)

    eligible: set[str] = set()
    excluded_st: set[str] = set()
    excluded_suspended: set[str] = set()
    excluded_other: set[str] = set()
    for code in sorted(mainboard):
        inst = instruments[code]
        list_date, delist_date = inst["list_date"], inst["delist_date"]
        listed = (list_date is None or list_date <= AS_OF) and (
            delist_date is None or delist_date > AS_OF
        )
        if not listed:
            excluded_other.add(code)
        elif code in st_asof:
            excluded_st.add(code)
        elif code in gap_asof:
            excluded_suspended.add(code)
        elif code not in bars_asof:
            excluded_suspended.add(code)
        elif (bars_asof[code]["volume"] or 0) <= 0:
            excluded_suspended.add(code)
        else:
            eligible.add(code)

    frozen = set(frozen_members)
    return {
        "as_of": AS_OF.isoformat(),
        "mainboard_universe_n": len(mainboard),
        "eligible_non_st_trading_n": len(eligible),
        "excluded_st_n": len(excluded_st),
        "excluded_suspended_n": len(excluded_suspended),
        "excluded_other_n": len(excluded_other),
        "non_mainboard_stock_n": len(non_mainboard_stock),
        "eligible_codes": sorted(eligible),
        "excluded_st_codes": sorted(excluded_st),
        "excluded_suspended_codes": sorted(excluded_suspended),
        "excluded_other_codes": sorted(excluded_other),
        "frozen_cross_check": {
            "frozen_universe_n": len(frozen),
            "frozen_within_mainboard": len(frozen & mainboard),
            "frozen_eligible_n": len(frozen & eligible),
            "frozen_excluded_st_n": len(frozen & excluded_st),
            "frozen_excluded_suspended_n": len(frozen & excluded_suspended),
        },
        "st_asof_row_n": len(st_asof),
    }


def _pick_smoke_codes(census_data: dict[str, Any], instruments: dict[str, dict[str, Any]]) -> list[str]:
    """<=50 representative codes: eligible / ST / suspended / ChiNext / STAR /
    ETF / delisted old SZ."""

    eligible = sorted(census_data["eligible_codes"])
    st = sorted(census_data["excluded_st_codes"])
    suspended = sorted(census_data["excluded_suspended_codes"])
    all_codes = sorted(instruments)
    chinext = [c for c in all_codes if c.startswith("300")]
    star = [c for c in all_codes if c.startswith("688")]
    etf = [c for c in all_codes if c.startswith(("510", "159"))]
    delisted = [c for c in ("000003", "000004") if c in instruments]

    smoke: list[str] = []
    smoke.extend(eligible[:10])
    smoke.extend(st[:8])
    smoke.extend(suspended[:3])
    smoke.extend(chinext[:5])
    smoke.extend(star[:5])
    smoke.extend(etf[:2])
    smoke.extend(delisted)
    # historical ST -> later normal demo (000838: ST period then suspension).
    if "000838" in all_codes:
        smoke.append("000838")
    return sorted(dict.fromkeys(smoke))[:SMOKE_LIMIT]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asl-root", required=True, type=Path)
    parser.add_argument("--universe", required=True, type=Path)
    parser.add_argument("--config", default="config/strategy.yaml", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    instruments = load_instruments(args.asl_root)
    frozen = set(json.loads(args.universe.read_text())["members"])
    counts = census(args.asl_root, instruments, frozen)
    smoke_codes = _pick_smoke_codes(counts, instruments)
    config = load_strategy_config(args.config)

    smoke: list[dict[str, Any]] = []
    for code in smoke_codes:
        inst = instruments.get(code)
        record: dict[str, Any] = {"code": code, "instrument": inst}
        if not is_mainboard_instrument(inst):
            record.update(
                {
                    "eligible": False,
                    "exclusion": "EXCLUDED_NON_MAINBOARD",
                    "note": "excluded at universe level (no strategy evaluation; "
                    "shadow lake carries no bars for non-mainboard securities)",
                }
            )
            smoke.append(record)
            continue
        asl, errors, _explained, _cov = _load_asl_recursive(
            args.asl_root, [code], HISTORY_START, AS_OF, {}
        )
        rows = asl.get(code, []) if asl else []
        eligible, exclusions = filter_eligible_rows(rows, instruments)
        excluded_counts = Counter(item["reason"] for item in exclusions)
        final_stage = None
        final_entry = None
        if eligible:
            items, _ = build_timeline(eligible, config, WINDOW_START, AS_OF)
            sigs = {item.trade_date: strategy_signature(item) for item in items}
            final_sig = sigs.get(AS_OF)
            final_stage = final_sig[0] if final_sig else None
            final_entry = final_sig[7] if final_sig else None
        record.update(
            {
                "eligible": True,
                "total_rows": len(rows),
                "eligible_rows": len(eligible),
                "excluded_counts": dict(excluded_counts),
                "exclusion_sample": exclusions[:5],
                "final_stage_at_asof": final_stage,
                "final_entry_candidate_at_asof": final_entry,
                "data_errors": errors,
            }
        )
        smoke.append(record)

    out = {
        "contract": "VFLASH_MAINBOARD_UNIVERSE_SIMPLIFICATION_V1",
        "universe_contract": (
            "SH/SZ MAINBOARD NORMAL A-SHARES ONLY; ST/*ST is an exclusion "
            "flag only; excluded code-dates produce no strategy output; "
            "normal periods of the same stock remain evaluable"
        ),
        "census": counts,
        "smoke": {
            "code_n": len(smoke_codes),
            "codes": smoke_codes,
            "rows": smoke,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
