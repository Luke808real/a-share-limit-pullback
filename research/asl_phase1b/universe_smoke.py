"""Main-board non-ST universe smoke (<=10 codes) — eligibility MASK model.

READ-ONLY, bounded: no full-market strategy run, no ST backfill.

Correct model demonstrated here:

    all real ASL bars -> screen_code (complete history) ->
    eligibility mask on evaluation date -> user-facing candidates

The strategy input is ALWAYS the complete unmodified ASL bar series; ST dates
are never deleted from price history.  Eligibility only gates output: an
excluded AS_OF date returns no candidate; excluded historical dates never
surface as candidates.

Usage:
    PYTHONPATH=src python research/asl_phase1b/universe_smoke.py \
        --asl-root /tmp/asl_phase1b_lake \
        --out research/asl_phase1b/artifacts/universe_smoke.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyarrow.parquet as pq  # noqa: E402

from limit_pullback.config import load_strategy_config  # noqa: E402
from eligibility import (  # noqa: E402
    classify_rows_evidence,
    eligibility_for_date,
    is_asof_strategy_eligible,
    is_mainboard_instrument,
    load_instruments,
    mask_timeline_dates,
)
from shadow import (  # noqa: E402
    AS_OF,
    HISTORY_START,
    WINDOW_START,
    build_timeline,
    strategy_signature,
)
from shadow import _load_asl_recursive  # noqa: E402

SHANGHAI_TZ = timezone(timedelta(hours=8))
SMOKE_LIMIT = 10

#: Representative smoke codes: eligible-looking main-board (status unknown in
#: the current lake -> fail closed), ST, suspended, non-main-board, delisted.
SMOKE_CODES = [
    "000001", "000002", "600519", "601318",   # main board, status unknown
    "000826",                                  # trusted ST at AS_OF
    "000838",                                  # suspended at AS_OF
    "300001", "688001",                        # ChiNext / STAR
    "510050",                                  # ETF
]


def _read_status_at_asof(asl_root: Path) -> dict[str, str]:
    """{code: "ST" | "SUSPENDED" | "NON_ST"} for AS_OF from curated
    trading_status, classified per the ASL PIT provenance contract."""

    out: dict[str, str] = {}
    status_root = Path(asl_root) / "curated" / "trading_status"
    for month in ("2026-07", "2026-08"):
        for file_path in sorted((status_root / f"trade_date={month}").glob("*.parquet")):
            table = pq.ParquetFile(file_path).read(
                columns=["symbol", "trade_date", "is_trading", "status", "source", "fetched_at"]
            )
            for symbol, day, is_trading, status, source, fetched_at in zip(
                table.column("symbol").to_pylist(),
                table.column("trade_date").to_pylist(),
                table.column("is_trading").to_pylist(),
                table.column("status").to_pylist(),
                table.column("source").to_pylist(),
                table.column("fetched_at").to_pylist(),
                strict=True,
            ):
                if day != AS_OF:
                    continue
                code = str(symbol).split(".")[0].zfill(6)
                source = str(source or "").lower()
                if source == "baostock":
                    out[code] = "ST"
                elif source == "derived_bar_gap":
                    out[code] = "SUSPENDED"
                elif source in ("eastmoney", "tdx_protocol"):
                    try:
                        fetched = (
                            fetched_at
                            if isinstance(fetched_at, datetime)
                            else datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
                        )
                    except ValueError:
                        continue
                    if fetched.astimezone(SHANGHAI_TZ).date() == AS_OF:
                        out[code] = "NON_ST"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asl-root", required=True, type=Path)
    parser.add_argument("--config", default="config/strategy.yaml", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    instruments = load_instruments(args.asl_root)
    status_asof = _read_status_at_asof(args.asl_root)
    config = load_strategy_config(args.config)

    smoke: list[dict[str, Any]] = []
    for code in SMOKE_CODES:
        inst = instruments.get(code)
        record: dict[str, Any] = {"code": code, "instrument": inst}
        if not is_mainboard_instrument(inst):
            record.update(
                {
                    "eligibility": "EXCLUDED_NON_MAINBOARD",
                    "strategy_run": False,
                    "note": "excluded at universe level; no strategy evaluation",
                }
            )
            smoke.append(record)
            continue

        asl, errors, _explained, _cov = _load_asl_recursive(
            args.asl_root, [code], HISTORY_START, AS_OF, {}
        )
        full_rows = asl.get(code, []) if asl else []

        # 1) AS_OF eligibility FIRST (fail-closed gate).
        asof_row = next(
            (row for row in full_rows if row["trade_date"] == AS_OF), None
        )
        asof_eligibility = is_asof_strategy_eligible(code, AS_OF, inst, asof_row)

        # 2) Strategy runs on the COMPLETE historical bar series.
        items, _ = build_timeline(full_rows, config, WINDOW_START, AS_OF)
        all_sigs = {item.trade_date: strategy_signature(item) for item in items}
        # 3) Eligibility mask on evaluation output.
        rows_by_date = {row["trade_date"]: row for row in full_rows}
        masked_items = mask_timeline_dates(items, instruments, rows_by_date, code)
        masked_sigs = {item.trade_date: strategy_signature(item) for item in masked_items}

        eligible_dates, exclusions = classify_rows_evidence(full_rows, instruments)
        excluded_counts = Counter(item["reason"] for item in exclusions)

        record.update(
            {
                "strategy_run": True,
                "strategy_input_rows": len(full_rows),
                "history_intact": len(full_rows) > 0,
                "asof_row_present": asof_row is not None,
                "asof_eligibility": asof_eligibility,
                "asof_status_evidence": status_asof.get(code, "NO_STATUS_ROW"),
                "final_stage_unmasked": (
                    all_sigs[AS_OF][0] if AS_OF in all_sigs else None
                ),
                "final_stage_masked": (
                    masked_sigs[AS_OF][0] if AS_OF in masked_sigs else None
                ),
                "final_entry_masked": (
                    masked_sigs[AS_OF][7] if AS_OF in masked_sigs else None
                ),
                "excluded_counts": dict(excluded_counts),
                "eligible_date_n": len(eligible_dates),
                "exclusion_sample": exclusions[:5],
                "data_errors": errors,
            }
        )
        smoke.append(record)

    out = {
        "contract": "VFLASH_MAINBOARD_UNIVERSE_FIX_V2",
        "universe_contract": (
            "SH/SZ MAINBOARD NORMAL A-SHARES ONLY; eligibility is a MASK, "
            "never a price-history deletion; ST/*ST exclusion flag only; "
            "status unknown fails closed (EXCLUDED_STATUS_UNKNOWN); excluded "
            "evaluation dates produce no user-facing candidates"
        ),
        "strategy_model": (
            "all real ASL bars -> screen_code (complete history) -> "
            "eligibility mask on evaluation date -> candidates"
        ),
        "smoke": {"code_n": len(smoke), "rows": smoke},
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
