"""Main-board ST-exclusion readiness report (V4) — metadata only.

READ-ONLY: no strategy run, no shadow.py, no ST backfill.  Reads ASL
metadata / manifest / resume-marker evidence only.

Dataset-level ST readiness contract:

    the screen for an evaluation date is published only when the required
    eligibility universe is covered by a COMPLETED trusted ST data
    operation, proven by the official ASL ST-backfill completion evidence
    (the ``trading_status_st_backfill`` resume marker).

Completeness is NEVER inferred from ST row counts, from a non-empty
trading_status dataset, or from a stock's absence from the ST set.

Per-stock eligibility is a separate concept and stays unchanged
(NON_MAINBOARD > NOT_LISTED > SUSPENDED > ST > ELIGIBLE).

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
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyarrow.parquet as pq  # noqa: E402

from eligibility import (  # noqa: E402
    eligibility_for_date,
    is_mainboard_instrument,
    load_instruments,
    official_st_completed_symbols,
    required_st_codes_for_asof,
    screen_gate,
)
from shadow import AS_OF  # noqa: E402  (date constant only; no strategy run)

SMOKE_CODES = [
    "000001", "000002", "600519", "601318",   # ordinary main board
    "000826",                                  # trusted ST at AS_OF
    "000838",                                  # suspended at AS_OF
    "300001", "688001",                        # ChiNext / STAR
    "510050",                                  # ETF
]


def _read_st_set_at_asof(asl_root: Path) -> set[str]:
    """Trusted ST exclusion facts at AS_OF (source=baostock), metadata read."""

    out: set[str] = set()
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
                if day == AS_OF and str(source).lower() == "baostock":
                    out.add(str(symbol).split(".")[0].zfill(6))
    return out


def _read_bars_at_asof(asl_root: Path) -> dict[str, int]:
    """{code: volume} for AS_OF daily bars (metadata read)."""

    partition = Path(asl_root) / "curated" / "daily_bars" / f"trade_date={AS_OF.isoformat()}"
    out: dict[str, int] = {}
    if not partition.exists():
        return out
    for file_path in sorted(partition.glob("*.parquet")):
        table = pq.ParquetFile(file_path).read(
            columns=["symbol", "trade_date", "volume"]
        )
        for symbol, day, volume in zip(
            table.column("symbol").to_pylist(),
            table.column("trade_date").to_pylist(),
            table.column("volume").to_pylist(),
            strict=True,
        ):
            if day == AS_OF:
                out[str(symbol).split(".")[0].zfill(6)] = volume
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asl-root", required=True, type=Path)
    parser.add_argument("--universe", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    instruments = load_instruments(args.asl_root)
    mainboard = sorted(
        code for code, inst in instruments.items()
        if is_mainboard_instrument(inst)
    )
    bars_volume = _read_bars_at_asof(args.asl_root)
    required_st_codes = required_st_codes_for_asof(
        instruments, bars_volume, AS_OF
    )
    listed = {
        code
        for code in mainboard
        if not (
            (instruments[code]["list_date"] is not None
             and AS_OF < instruments[code]["list_date"])
            or (instruments[code]["delist_date"] is not None
                and AS_OF >= instruments[code]["delist_date"])
        )
    }
    required_symbols = {
        code + (".SH" if code.startswith("6") else ".SZ")
        for code in required_st_codes
    }
    completed = official_st_completed_symbols(args.asl_root)
    frozen = set(json.loads(args.universe.read_text())["members"])

    summary = json.loads(
        Path("research/asl_phase1b/shadow_summary.json").read_text(encoding="utf-8")
    )
    targeted_codes = set(
        summary["st_coverage"]["decision_relevant_st_unknown_codes"]
    )
    targeted_symbols = {
        code + (".SH" if code.startswith("6") else ".SZ") for code in targeted_codes
    }

    gate = screen_gate(args.asl_root, AS_OF, required_st_codes)

    # Per-stock eligibility table (metadata only; no strategy).
    st_asof = _read_st_set_at_asof(args.asl_root)
    rows: list[dict[str, Any]] = []
    for code in SMOKE_CODES:
        inst = instruments.get(code)
        if not is_mainboard_instrument(inst):
            rows.append(
                {
                    "code": code,
                    "eligibility": "EXCLUDED_NON_MAINBOARD",
                    "note": "universe-level exclusion; no strategy run",
                }
            )
            continue
        bar = code in bars_volume and (bars_volume[code] or 0) > 0
        row = (
            {
                "trade_date": AS_OF,
                "is_st": code in st_asof,
                "trade_status": True,
            }
            if bar
            else None
        )
        rows.append(
            {
                "code": code,
                "bar_at_asof": bar,
                "in_trusted_st_set_at_asof": code in st_asof,
                "eligibility": eligibility_for_date(
                    code, AS_OF, inst, row
                ),
            }
        )

    out = {
        "contract": "VFLASH_MAINBOARD_UNIVERSE_FIX_V4",
        "readiness_contract": (
            "screen published only when the required eligibility universe is "
            "covered by a COMPLETED trusted ST data operation (official ASL "
            "resume-marker evidence); completeness never inferred from ST "
            "row counts, dataset presence, or absence from the ST set"
        ),
        "official_asl_coverage_evidence": {
            "source": "meta/state/trading_status_st_backfill.json "
            "(official _mark_st_backfilled completion registry)",
            "completed_symbol_n": len(completed),
            "targeted_st_completed_code_n": len(
                targeted_symbols & completed
            ),
            "frozen_universe_n": len(frozen),
        },
        "required_scope": {
            "mainboard_instrument_n": len(mainboard),
            "not_listed_or_delisted_n": len(mainboard) - len(listed),
            "suspended_or_no_bar_n": len(listed) - len(required_st_codes),
            "required_st_code_n": len(required_st_codes),
            "completed_st_code_n_within_required": len(
                required_symbols & completed
            ),
            "missing_st_coverage_n": len(required_symbols - completed),
        },
        "screen_gate": gate,
        "per_stock_smoke": {"code_n": len(rows), "rows": rows},
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
