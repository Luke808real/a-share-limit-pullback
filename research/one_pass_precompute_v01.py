"""EXACT PYTHON ONE-PASS INDICATOR PRECOMPUTE v0.1 (research-only)."""

from __future__ import annotations

import bisect
import hashlib
import itertools
import json
import os
import resource
import shutil
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from limit_pullback.config import load_strategy_config
from limit_pullback.screen.canonical import load_canonical_market
from limit_pullback.screen.runner import _digest, _git_head, run_screen
from limit_pullback.strategy.math import (
    build_continuous_prices,
    calculate_indicators,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.parquet import sha256_file


ROOT = Path("/Users/luke808/AI/V flash")
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
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
OUT = ROOT / "data/tmp/one-pass-precompute"


class IndicatorPrefixView(Sequence):
    def __init__(self, points: tuple, end: int) -> None:
        self._points = points
        self._end = end

    def __len__(self) -> int:
        return self._end

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self._points[index])
        if index < 0:
            index += self._end
        if index < 0 or index >= self._end:
            raise IndexError(index)
        return self._points[index]

    def __iter__(self):
        return itertools.islice(self._points, 0, self._end)


def rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if os.uname().sysname == "Darwin" else value * 1024


def load_bars() -> dict[str, list]:
    market = load_canonical_market(
        WarehouseLayout(ROOT / "data"),
        snapshot_id=SNAPSHOT_ID,
        codes=SAMPLE,
    )
    return {code: list(bars) for code, bars in market.bars_by_code.items()}


def prefix_equivalence(bars_by_code: dict[str, list]) -> dict:
    config = load_strategy_config(ROOT / "config/strategy.yaml").indicators
    diffs = []
    compared = 0
    for code in SAMPLE:
        bars = bars_by_code[code]
        full = calculate_indicators(bars, config)
        for index in range(len(full)):
            prefix_point = calculate_indicators(bars[: index + 1], config)[-1]
            full_point = full[index]
            compared += 1
            if not _equal_point(full_point, prefix_point):
                diffs.append(
                    {
                        "code": code,
                        "trade_date": full_point.trade_date.isoformat(),
                        "index": index,
                    }
                )
                if len(diffs) >= 20:
                    break
        if len(diffs) >= 20:
            break
    return {"compared": compared, "diff_count": len(diffs), "diffs": diffs}


def _equal_point(left, right) -> bool:
    if (
        left.trade_date != right.trade_date
        or left.code != right.code
        or left.continuous_close != right.continuous_close
        or left.continuous_mas != right.continuous_mas
        or left.raw_equivalent_mas != right.raw_equivalent_mas
        or left.ma_compression != right.ma_compression
        or left.position_120 != right.position_120
        or left.kline != right.kline
    ):
        return False
    return True


def run_cold_rebuild(
    bars_by_code: dict[str, list],
    counters: dict,
    *,
    optimized: bool,
) -> dict:
    import limit_pullback.strategy.engine as engine_mod
    import limit_pullback.strategy.math as math_mod
    import limit_pullback.screen.engine as screen_engine_mod

    original_indicators = math_mod.calculate_indicators
    original_continuous = math_mod.build_continuous_prices
    original_evaluate = engine_mod.evaluate_strategy
    cache: dict[str, tuple] = {}

    def counting_indicators(bars, config, as_of=None):
        counters["calculate_indicators_calls"] += 1
        result = original_indicators(bars, config, as_of)
        counters["indicator_points_constructed"] += len(result)
        return result

    def counting_continuous(bars, as_of=None):
        counters["build_continuous_prices_calls"] += 1
        return original_continuous(bars, as_of)

    def counting_evaluate(*args, **kwargs):
        counters["evaluate_strategy_calls"] += 1
        return original_evaluate(*args, **kwargs)

    def precomputed_indicators(bars, config, as_of=None):
        counters["calculate_indicators_calls"] += 1
        code = bars[0].code
        if code not in cache:
            cache[code] = original_indicators(bars_by_code[code], config)
            counters["indicator_points_constructed"] += len(cache[code])
            counters["full_series_computations"] += 1
        full = cache[code]
        if as_of is None:
            return IndicatorPrefixView(full, len(full))
        dates = [point.trade_date for point in full]
        end = bisect.bisect_right(dates, as_of)
        return IndicatorPrefixView(full, end)

    if optimized:
        engine_mod.calculate_indicators = precomputed_indicators
    else:
        engine_mod.calculate_indicators = counting_indicators
    math_mod.build_continuous_prices = counting_continuous
    screen_engine_mod.evaluate_strategy = counting_evaluate

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
    engine_mod.calculate_indicators = original_indicators
    math_mod.build_continuous_prices = original_continuous
    screen_engine_mod.evaluate_strategy = original_evaluate
    state_hash = _state_hash(SAMPLE)
    return {
        "seconds": elapsed,
        "output_hash": result.output_hash,
        "state_hash": state_hash,
    }


def _state_hash(codes: list[str]) -> str:
    payload = []
    for code in sorted(codes):
        path = ROOT / "data/screen/states" / f"{code}.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data.pop("processed_at", None)
        payload.append(data)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bars = load_bars()
    prefix_path = OUT / "prefix_equivalence.json"
    if prefix_path.exists():
        prefix = json.loads(prefix_path.read_text(encoding="utf-8"))
    else:
        prefix = prefix_equivalence(bars)
        prefix_path.write_text(
            json.dumps(prefix, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    if prefix["diff_count"]:
        result = {"status": "PREFIX_EQUIVALENCE_FAIL", "prefix": prefix}
        (OUT / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return
    ref_counters = {
        "calculate_indicators_calls": 0,
        "build_continuous_prices_calls": 0,
        "indicator_points_constructed": 0,
        "evaluate_strategy_calls": 0,
        "full_series_computations": 0,
    }
    opt_counters = dict(ref_counters)
    ref = run_cold_rebuild(bars, ref_counters, optimized=False)
    opt = run_cold_rebuild(bars, opt_counters, optimized=True)
    result = {
        "status": "PREFIX_EQUIVALENCE_OK",
        "prefix": prefix,
        "reference": ref,
        "optimized": opt,
        "reference_counters": ref_counters,
        "optimized_counters": opt_counters,
        "peak_rss_bytes": rss_bytes(),
        "speedup": (
            round(ref["seconds"] / opt["seconds"], 2)
            if opt["seconds"] and opt["seconds"] > 0
            else None
        ),
        "output_hash_equal": ref["output_hash"] == opt["output_hash"],
        "state_hash_equal": ref["state_hash"] == opt["state_hash"],
    }
    (OUT / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
