"""Targeted preclose diagnostic for the 2026-08-03 UNKNOWN cases.

READ-ONLY, bounded: loads ONLY the affected codes (no full-market run).

For every preclose-mismatch row of the affected codes, proves the five
membership facts independently:

1. ASL predecessor date is absent from legacy CONFIRMED rows;
2. that predecessor date exists as a valid ASL bar (positive close);
3. legacy current preclose == legacy's own prior valid close;
4. ASL current preclose == ASL's own prior valid close;
5. the differing predecessor membership fully explains the preclose
   difference (asl_pre - legacy_pre == asl_prev_close - legacy_prev_close).

Then replays each code through the production engine (process_code) with the
strengthened classifier and reports the resulting per-date classes.

Usage:
    PYTHONPATH=src python research/asl_phase1b/preclose_diagnostic.py \
        --legacy-snapshot <path> --asl-root /tmp/asl_phase1b_lake \
        --codes 000756,000799,... --out <artifacts>/preclose_diagnostic_20260803.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from limit_pullback.config import load_strategy_config  # noqa: E402
from shadow import (  # noqa: E402
    HISTORY_START,
    AS_OF,
    WINDOW_START,
    classify_code_inputs,
    load_legacy_canonical,
    process_code,
)
from shadow import _load_asl_recursive  # noqa: E402

TARGET_DATE = date(2026, 8, 3)


def _row_proofs(
    code: str,
    day: date,
    legacy_rows: list[dict[str, Any]],
    asl_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    legacy_by = {r["trade_date"]: r for r in legacy_rows}
    asl_by = {r["trade_date"]: r for r in asl_rows}
    legacy_row = legacy_by.get(day)
    asl_row = asl_by.get(day)
    if legacy_row is None or asl_row is None:
        return {"code": code, "date": day.isoformat(), "both_rows": False}

    legacy_prev = None
    for r in legacy_rows:
        if r["trade_date"] < day and Decimal(str(r["close"])) > 0:
            legacy_prev = r
    asl_prev = None
    for r in asl_rows:
        if r["trade_date"] < day and Decimal(str(r["close"])) > 0:
            asl_prev = r
    if legacy_prev is None or asl_prev is None:
        return {
            "code": code,
            "date": day.isoformat(),
            "both_rows": True,
            "proofs": {
                "1_asl_predecessor_absent_from_legacy": None,
                "2_asl_predecessor_valid_asl_bar": None,
                "3_legacy_sequential": None,
                "4_asl_sequential": None,
                "5_membership_fully_explains": None,
            },
            "reason": "no predecessor on one side",
        }

    legacy_pre = Decimal(str(legacy_row["preclose"]))
    asl_pre = Decimal(str(asl_row["preclose"]))
    legacy_prev_close = Decimal(str(legacy_prev["close"]))
    asl_prev_close = Decimal(str(asl_prev["close"]))

    proof1 = asl_prev["trade_date"] not in legacy_by  # ASL-only predecessor
    proof2 = asl_prev["trade_date"] in asl_by  # valid ASL bar (adapter row)
    proof3 = legacy_pre == legacy_prev_close
    proof4 = asl_pre == asl_prev_close
    proof5 = (
        (asl_pre - legacy_pre) == (asl_prev_close - legacy_prev_close)
    )
    return {
        "code": code,
        "date": day.isoformat(),
        "both_rows": True,
        "legacy": {
            "preclose": str(legacy_pre),
            "prev_date": legacy_prev["trade_date"].isoformat(),
            "prev_close": str(legacy_prev_close),
        },
        "asl": {
            "preclose": str(asl_pre),
            "prev_date": asl_prev["trade_date"].isoformat(),
            "prev_close": str(asl_prev_close),
        },
        "proofs": {
            "1_asl_predecessor_absent_from_legacy": proof1,
            "2_asl_predecessor_valid_asl_bar": proof2,
            "3_legacy_sequential": proof3,
            "4_asl_sequential": proof4,
            "5_membership_fully_explains": proof5,
        },
        "all_proofs_hold": all(
            (proof1, proof2, proof3, proof4, proof5)
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-snapshot", required=True, type=Path)
    parser.add_argument("--asl-root", required=True, type=Path)
    parser.add_argument("--config", default="config/strategy.yaml", type=Path)
    parser.add_argument("--codes", required=True, help="comma-separated")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    codes = [code.strip() for code in args.codes.split(",") if code.strip()]
    config = load_strategy_config(args.config)
    legacy = load_legacy_canonical(
        args.legacy_snapshot, set(codes), HISTORY_START, AS_OF
    )
    asl, errors, explained, _coverage = _load_asl_recursive(
        args.asl_root, codes, HISTORY_START, AS_OF, legacy
    )
    if asl is None:
        asl = {}

    preclose_rows: list[dict[str, Any]] = []
    replay: list[dict[str, Any]] = []
    for code in codes:
        lrows = legacy.get(code, [])
        arows = asl.get(code, [])
        info = classify_code_inputs(code, lrows, arows, set())
        mismatches = [
            day
            for day, cls in sorted(info["per_date_class"].items())
            if cls
            in (
                "UNKNOWN_INPUT_DIVERGENCE",
                "LEGACY_PRECLOSE_ERA_DIVERGENCE",
                "LEGACY_HOLE_REPAIRED_BY_ASL",
            )
            and (
                "preclose" in info["per_date_detail"].get(day, "")
                or cls == "LEGACY_HOLE_REPAIRED_BY_ASL"
            )
        ]
        for day in mismatches:
            if day != TARGET_DATE:
                continue
            preclose_rows.append(_row_proofs(code, day, lrows, arows))
        result = process_code(code, lrows, arows, config, set(), [])
        replay.append(
            {
                "code": code,
                "skip": result.get("skip"),
                "unknown_per_date_n": result["per_date_class_counts"][
                    "UNKNOWN_INPUT_DIVERGENCE"
                ],
                "preclose_era_n": result["per_date_class_counts"][
                    "LEGACY_PRECLOSE_ERA_DIVERGENCE"
                ],
                "hole_repaired_n": result["per_date_class_counts"][
                    "LEGACY_HOLE_REPAIRED_BY_ASL"
                ],
                "first_divergence": result["first_input_divergence"],
            }
        )

    evidence = {
        "contract": "VFLASH_ASL_P1B_PRECLOSE_DIAGNOSTIC_V1",
        "target_date": TARGET_DATE.isoformat(),
        "codes": codes,
        "all_five_proofs_hold_for_all_target_rows": all(
            row.get("all_proofs_hold") for row in preclose_rows
        ),
        "preclose_rows": preclose_rows,
        "replay": replay,
        "data_errors": errors,
        "explained_absences": explained,
        "note": (
            "targeted diagnostic only; the strengthened classifier requires "
            "explicit ASL-only predecessor evidence (asl_prev_date not in "
            "legacy CONFIRMED) before classifying a sequential preclose "
            "delta as LEGACY_HOLE_REPAIRED_BY_ASL"
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
