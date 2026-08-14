"""Cold-fetch benchmark for 2026-08-14 with the concurrent fetch + 32 workers.

Reads the 08-13 formal snapshot as base; writes only under data/tmp/bench-*
(per-code caches + summary). No warehouse mutation, no promotion.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from limit_pullback.ops import _layout
from limit_pullback.runtime import load_runtime_config
from limit_pullback.warehouse.daily_catchup import fetch_daily_delta

SESSION = date(2026, 8, 14)
BASE = "snap-2026-08-13-bed1fd379696"


def main() -> int:
    layout = _layout()
    runtime = load_runtime_config()
    cache_root = layout.root / "tmp" / "bench-catchup-20260814"
    result = fetch_daily_delta(
        layout,
        base_snapshot_id=BASE,
        session=SESSION,
        runtime=runtime,
        run_id="BENCH_20260814_COLD",
        cache_root=cache_root,
    )
    payload = {
        "session": SESSION.isoformat(),
        "provider_wall_time": result.provider_wall_time,
        "total_codes": result.provider_total_codes,
        "cached": result.provider_cached_codes,
        "requested": result.provider_requested_codes,
        "retry_codes": result.provider_retry_codes,
        "tdx_row_n": result.tdx_row_n,
        "tencent_row_n": result.tencent_row_n,
        "tdx_failure_n": result.tdx_failure_n,
        "tencent_failure_n": result.tencent_failure_n,
    }
    summary = json.loads(result.summary_path.read_text())
    payload["tdx_wall_seconds"] = summary.get("tdx_wall_seconds")
    payload["tencent_wall_seconds"] = summary.get("tencent_wall_seconds")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
