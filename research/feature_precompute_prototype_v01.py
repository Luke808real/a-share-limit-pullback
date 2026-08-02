"""FEATURE PRECOMPUTE V0.1 exact-semantic micro prototype (research-only)."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import time
from collections import defaultdict
from datetime import date
from decimal import Decimal, getcontext
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from limit_pullback.config import load_strategy_config
from limit_pullback.screen.canonical import load_canonical_market
from limit_pullback.screen.runner import _digest, _git_head, run_screen
from limit_pullback.strategy.math import (
    build_continuous_prices,
    calculate_indicators,
    calculate_kline_metrics,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.parquet import sha256_file


ROOT = Path("/Users/luke808/AI/V flash")
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
WINDOWS = (5, 10, 20, 30, 120, 250)
SAMPLE = [
    "000001",
    "000610",
    "000890",
    "001365",
    "002152",
    "002327",
    "002513",
    "002690",
    "002881",
    "600025",
    "600250",
    "600495",
    "600703",
    "600906",
    "601512",
    "603061",
    "603273",
    "603596",
    "603900",
    "605599",
]
OUT = ROOT / "data/tmp/feature-precompute-prototype"


def rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if os.uname().sysname == "Darwin" else value * 1024


def load_bars() -> dict[str, list]:
    layout = WarehouseLayout(ROOT / "data")
    market = load_canonical_market(layout, snapshot_id=SNAPSHOT_ID, codes=SAMPLE)
    return {code: list(bars) for code, bars in market.bars_by_code.items()}


def reference_features(bars_by_code: dict[str, list]) -> dict:
    rows = []
    indicator_config = load_strategy_config(ROOT / "config/strategy.yaml").indicators
    started = time.perf_counter()
    for code in SAMPLE:
        points = calculate_indicators(bars_by_code[code], indicator_config)
        for point in points:
            rows.append(
                {
                    "code": code,
                    "trade_date": point.trade_date,
                    "continuous_mas": {
                        str(k): (None if v is None else str(v))
                        for k, v in point.continuous_mas.items()
                    },
                    "raw_equivalent_mas": {
                        str(k): (None if v is None else str(v))
                        for k, v in point.raw_equivalent_mas.items()
                    },
                    "ma_compression": (
                        None if point.ma_compression is None else str(point.ma_compression)
                    ),
                    "position_120": (
                        None if point.position_120 is None else str(point.position_120)
                    ),
                }
            )
    return {"rows": rows, "seconds": time.perf_counter() - started}


def duckdb_features(bars_by_code: dict[str, list]) -> dict:
    continuous_rows = []
    for code in SAMPLE:
        for point in build_continuous_prices(bars_by_code[code]):
            continuous_rows.append(
                {
                    "code": code,
                    "trade_date": point.trade_date,
                    "continuous_close": point.continuous_close,
                }
            )
    table = pa.Table.from_pylist(
        [
            {
                "code": row["code"],
                "trade_date": row["trade_date"],
                "continuous_close": row["continuous_close"],
            }
            for row in continuous_rows
        ]
    )
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='4GB'")
    con.execute("SET preserve_insertion_order=false")
    con.register("continuous_input", table)
    sum_sql = ", ".join(
        f"SUM(continuous_close) OVER (PARTITION BY code ORDER BY trade_date "
        f"ROWS BETWEEN {w-1} PRECEDING AND CURRENT ROW) AS s_{w}, "
        f"COUNT(*) OVER (PARTITION BY code ORDER BY trade_date "
        f"ROWS BETWEEN {w-1} PRECEDING AND CURRENT ROW) AS c_{w}"
        for w in WINDOWS
    )
    minmax_sql = (
        "MIN(continuous_close) OVER (PARTITION BY code ORDER BY trade_date "
        "ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) AS min_120, "
        "MAX(continuous_close) OVER (PARTITION BY code ORDER BY trade_date "
        "ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) AS max_120"
    )
    sql = f"SELECT code, trade_date, {sum_sql}, {minmax_sql} FROM continuous_input ORDER BY code, trade_date"
    started = time.perf_counter()
    result = con.execute(sql).fetch_record_batch()
    batches = list(result)
    elapsed = time.perf_counter() - started
    table = pa.Table.from_batches(batches)
    rows = table.to_pylist()
    return {"rows": rows, "seconds": elapsed, "table": table}


def build_duckdb_derived(features: dict, bars_by_code: dict[str, list]) -> dict:
    bars_by_date = {
        code: {bar.trade_date: bar for bar in bars}
        for code, bars in bars_by_code.items()
    }
    output = []
    for row in features["rows"]:
        code = row["code"]
        trade_date = row["trade_date"]
        bar = bars_by_date[code][trade_date]
        cont = next(
            p
            for p in build_continuous_prices(bars_by_code[code])
            if p.trade_date == trade_date
        )
        continuous_mas = {}
        raw_mas = {}
        for w in WINDOWS:
            count = int(row[f"c_{w}"])
            if count < w:
                continuous_mas[w] = None
                raw_mas[w] = None
                continue
            total = Decimal(str(row[f"s_{w}"]))
            ma = total / Decimal(count)
            continuous_mas[w] = ma
            raw_mas[w] = ma * bar.close / cont.continuous_close
        compression = None
        values = [continuous_mas[w] for w in (5, 10, 20)]
        if all(v is not None for v in values):
            compression = (max(values) - min(values)) / cont.continuous_close
        count120 = int(row["c_120"])
        if count120 < 120:
            position = None
        else:
            low = Decimal(str(row["min_120"]))
            high = Decimal(str(row["max_120"]))
            position = (
                Decimal("0")
                if high == low
                else (cont.continuous_close - low) / (high - low)
            )
        output.append(
            {
                "code": code,
                "trade_date": trade_date,
                "continuous_mas": {
                    str(k): (None if v is None else str(v))
                    for k, v in continuous_mas.items()
                },
                "raw_equivalent_mas": {
                    str(k): (None if v is None else str(v))
                    for k, v in raw_mas.items()
                },
                "ma_compression": (
                    None if compression is None else str(compression)
                ),
                "position_120": None if position is None else str(position),
            }
        )
    return output


def compare(ref: dict, derived: list[dict]) -> list[dict]:
    ref_by_key = {
        (row["code"], row["trade_date"]): row
        for row in ref["rows"]
    }
    diffs = []
    fields = [
        "continuous_mas",
        "raw_equivalent_mas",
        "ma_compression",
        "position_120",
    ]
    for row in derived:
        key = (row["code"], row["trade_date"])
        ref_row = ref_by_key[key]
        for field in fields:
            if not _equal(ref_row[field], row[field]):
                diffs.append(
                    {
                        "code": key[0],
                        "trade_date": key[1].isoformat(),
                        "field": field,
                        "python": ref_row[field],
                        "duckdb": row[field],
                    }
                )
    return diffs


def _equal(left, right) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            _equal(left[k], right[k]) for k in left
        )
    if left is None or right is None:
        return left is right
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except Exception:
        return left == right


def run_cold_rebuild(monkeypatch_indicator=None) -> dict:
    import limit_pullback.strategy.math as math_mod

    original = math_mod.calculate_indicators
    if monkeypatch_indicator is not None:
        math_mod.calculate_indicators = monkeypatch_indicator
    config_hash = sha256_file(ROOT / "config/strategy.yaml")
    commit = _git_head()
    run_id = (
        f"screen-rebuild-2026-07-31-{SNAPSHOT_ID[:12]}-"
        f"{_digest(date(2024, 1, 1), tuple(SAMPLE), commit, config_hash, 'formal')[:12]}"
    )
    (ROOT / "data/screen/runs" / f"{run_id}.json").unlink(missing_ok=True)
    started = time.perf_counter()
    result = run_screen(
        layout=WarehouseLayout(ROOT / "data"),
        as_of=date(2026, 7, 31),
        snapshot_id=SNAPSHOT_ID,
        codes=SAMPLE,
        rebuild=True,
        start=date(2024, 1, 1),
    )
    elapsed = time.perf_counter() - started
    math_mod.calculate_indicators = original
    return {"seconds": elapsed, "output_hash": result.output_hash, "result": result}


def make_precomputed_indicator(lookup: dict, bars_by_code: dict[str, list]):
    indicator_config = load_strategy_config(ROOT / "config/strategy.yaml").indicators

    def calculate_indicators_precomputed(bars, strategy_config, as_of=None):
        points = build_continuous_prices(bars, as_of)
        ordered = tuple(sorted(bars, key=lambda b: b.trade_date))
        output = []
        for bar, point in zip(ordered, points):
            key = (bar.code, bar.trade_date)
            pre = lookup[key]
            continuous_mas = {int(k): (None if v is None else Decimal(v)) for k, v in pre["continuous_mas"].items()}
            raw_mas = {int(k): (None if v is None else Decimal(v)) for k, v in pre["raw_equivalent_mas"].items()}
            compression = None if pre["ma_compression"] is None else Decimal(pre["ma_compression"])
            position = None if pre["position_120"] is None else Decimal(pre["position_120"])
            from limit_pullback.models.strategy import IndicatorPoint

            output.append(
                IndicatorPoint(
                    trade_date=bar.trade_date,
                    code=bar.code,
                    continuous_close=point.continuous_close,
                    continuous_mas=continuous_mas,
                    raw_equivalent_mas=raw_mas,
                    ma_compression=compression,
                    position_120=position,
                    kline=calculate_kline_metrics(bar, indicator_config),
                )
            )
        return tuple(output)

    return calculate_indicators_precomputed


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bars = load_bars()
    ref = reference_features(bars)
    ref_table = pa.Table.from_pylist(ref["rows"])
    pq.write_table(ref_table, OUT / "reference_features.parquet", compression="zstd")
    ref_hash = hashlib.sha256(
        json.dumps(ref["rows"], sort_keys=True, default=str).encode()
    ).hexdigest()
    feats = duckdb_features(bars)
    derived = build_duckdb_derived(feats, bars)
    duck_table = pa.Table.from_pylist(derived)
    pq.write_table(duck_table, OUT / "duckdb_features.parquet", compression="zstd")
    duck_hash = hashlib.sha256(
        json.dumps(derived, sort_keys=True, default=str).encode()
    ).hexdigest()
    diffs = compare(ref, derived)
    result = {
        "rows": len(derived),
        "reference_feature_seconds": ref["seconds"],
        "reference_feature_hash": ref_hash,
        "duckdb_raw_seconds": feats["seconds"],
        "duckdb_feature_hash": duck_hash,
        "diff_count": len(diffs),
        "diffs": diffs[:50],
        "peak_rss_bytes": rss_bytes(),
    }
    (OUT / "prototype.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    if diffs:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return
    lookup = {
        (row["code"], row["trade_date"]): row
        for row in derived
    }
    ref_run = run_cold_rebuild()
    opt_run = run_cold_rebuild(make_precomputed_indicator(lookup, bars))
    result["reference_cold_rebuild_seconds"] = ref_run["seconds"]
    result["precomputed_cold_rebuild_seconds"] = opt_run["seconds"]
    result["reference_output_hash"] = ref_run["output_hash"]
    result["precomputed_output_hash"] = opt_run["output_hash"]
    result["output_hash_equal"] = ref_run["output_hash"] == opt_run["output_hash"]
    (OUT / "prototype.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    getcontext().prec = 28
    main()
