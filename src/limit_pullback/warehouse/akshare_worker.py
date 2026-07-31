"""Subprocess entry that fetches AKShare data in a minimal interpreter.

AKShare eagerly loads ``py_mini_racer`` (V8), which can crash when initialized
inside a process that already loaded DuckDB/pyarrow (address-space cage
conflict). Running AKShare fetches in a fresh subprocess isolates that native
runtime: if V8 crashes, only the worker dies and the parent records the chunk
as failed and continues.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from typing import Any


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    return value


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "pool"), required=True)
    parser.add_argument("--codes", default="")
    parser.add_argument("--dates", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    args = parser.parse_args()

    # Import AKShare only inside this minimal process.
    from limit_pullback.warehouse.akshare_provider import AkshareWarehouseProvider

    provider = AkshareWarehouseProvider()
    codes = tuple(code for code in args.codes.split(",") if code)
    if args.mode == "daily":
        if not args.start or not args.end:
            raise ValueError("daily mode requires --start and --end")
        rows = provider.fetch_daily(
            codes,
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
        )
    else:
        dates = [
            date.fromisoformat(value)
            for value in args.dates.split(",")
            if value
        ]
        rows = provider.fetch_limit_up_pool(dates, codes)
    json.dump(rows, sys.stdout, ensure_ascii=False, default=_encode)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
