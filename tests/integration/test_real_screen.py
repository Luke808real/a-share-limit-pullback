"""Phase 2C.2B real acceptance: 8 existing cases over a canonical snapshot.

The screen runs fully offline against canonical data; artifacts are written
only to the system temporary directory and never committed.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
import resource
import tempfile
import time

import pytest

from limit_pullback.screen.runner import run_screen
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.pipeline import bootstrap, update

EIGHT_CASES = (
    "001382",
    "002606",
    "603123",
    "603318",
    "002640",
    "600199",
    "002891",
    "603918",
)


@pytest.mark.integration
def test_real_screen_eight_case_regression(tmp_path):
    if not os.environ.get("TUSHARE_TOKEN"):
        pytest.skip("TUSHARE_TOKEN is not configured")

    layout = WarehouseLayout(tmp_path / "warehouse")
    start = date(2025, 3, 1)  # >= 500 natural days before 2026-07-30
    end = date(2026, 7, 30)
    today = date.today()

    bootstrap_result = bootstrap(
        layout=layout,
        start=start,
        end=end,
        codes=EIGHT_CASES,
        today=today,
    )
    assert bootstrap_result.snapshot_id is not None

    from limit_pullback.screen.canonical import load_canonical_market

    market = load_canonical_market(
        layout, snapshot_id=bootstrap_result.snapshot_id
    )
    per_stock_bars = {
        code: len(bars) for code, bars in market.bars_by_code.items()
    }
    assert all(count >= 120 for count in per_stock_bars.values()), per_stock_bars

    began = time.monotonic()
    rebuild_30 = run_screen(
        layout=layout,
        as_of=end,
        start=start,
        rebuild=True,
        codes=EIGHT_CASES,
        verify_replay=True,
    )
    elapsed = time.monotonic() - began
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    assert rebuild_30.universe_size == 8
    assert rebuild_30.verify_replay_matched is True
    assert rebuild_30.rows_count > 0

    if today > end:
        update_result = update(
            layout=layout,
            as_of=today,
            today=today,
        )
        assert update_result.snapshot_id is not None
        incremental_31 = run_screen(
            layout=layout,
            as_of=today,
            codes=EIGHT_CASES,
            verify_replay=True,
        )
        assert incremental_31.verify_replay_matched is True
        final_rebuild = run_screen(
            layout=layout,
            as_of=today,
            start=start,
            rebuild=True,
            codes=EIGHT_CASES,
        )
    else:
        incremental_31 = rebuild_30
        final_rebuild = rebuild_30

    outdir = Path(tempfile.gettempdir()) / f"phase-2c2b-acceptance-{os.getpid()}"
    outdir.mkdir(parents=True, exist_ok=True)
    summary = {
        "bootstrap": bootstrap_result.model_dump(mode="json"),
        "screen_rebuild_30": rebuild_30.model_dump(mode="json"),
        "screen_incremental": incremental_31.model_dump(mode="json"),
        "screen_final_rebuild": final_rebuild.model_dump(mode="json"),
        "update": (
            update_result.model_dump(mode="json")
            if today > end
            else None
        ),
        "performance": {
            "rebuild_wall_seconds": round(elapsed, 3),
            "peak_rss_kb": peak_rss,
        },
        "per_stock_bar_counts": per_stock_bars,
    }
    (outdir / "acceptance.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    def rows_by_date(path_value):
        payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
        return {
            (row["code"], row["trade_date"]): row
            for row in payload["rows"]
        }

    rows_30 = rows_by_date(rebuild_30.output_path)
    rows_final = rows_by_date(final_rebuild.output_path)
    overlap_30 = {
        key: value
        for key, value in rows_30.items()
        if key[1] <= end.isoformat()
    }
    overlap_final = {
        key: value
        for key, value in rows_final.items()
        if key[1] <= end.isoformat()
    }
    assert overlap_30 == overlap_final
