"""Offline tests for the daily provider delta fast path (concurrent fetch)."""

from __future__ import annotations

import json
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from limit_pullback.warehouse import daily_catchup as dc

SESSION = date(2026, 8, 13)


class _FakeMetadata:
    def __init__(self, path, read_only=True):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def snapshot_by_id(self, snapshot_id):
        return SimpleNamespace()


@pytest.fixture
def env(tmp_path, monkeypatch):
    layout = SimpleNamespace()
    layout.duckdb_path = tmp_path / "warehouse.duckdb"
    cache_root = tmp_path / "catchup"
    monkeypatch.setattr(dc, "WarehouseMetadata", _FakeMetadata)
    monkeypatch.setattr(
        dc,
        "load_seed_previous_closes",
        lambda layout, base: {
            "600001": Decimal("10"),
            "000001": Decimal("20"),
            "002112": Decimal("30"),
        },
    )
    runtime = SimpleNamespace(tencent_workers=8)
    return layout, cache_root, runtime


def _run(layout, cache_root, runtime, run_id="test-run"):
    return dc.fetch_daily_delta(
        layout,
        base_snapshot_id="snap-base",
        session=SESSION,
        runtime=runtime,
        run_id=run_id,
        cache_root=cache_root,
    )


def _row(code: str) -> dict:
    return {"code": code, "trade_date": SESSION}


def test_fetch_overlaps_tdx_and_tencent(env, monkeypatch) -> None:
    layout, cache_root, runtime = env
    tdx_started = threading.Event()
    tx_started = threading.Event()

    def tdx(codes, *, sessions, run_id, normalize):
        tdx_started.set()
        assert tx_started.wait(timeout=5), "tencent never overlapped tdx"
        return [_row(c) for c in codes], []

    def tencent(codes, *, sessions, cache_dir, workers, retries, run_id, normalize):
        tx_started.set()
        assert tdx_started.wait(timeout=5), "tdx never overlapped tencent"
        return [], []

    monkeypatch.setattr(dc, "fetch_tdx_daily", tdx)
    monkeypatch.setattr(dc, "fetch_tencent_daily", tencent)
    result = _run(layout, cache_root, runtime)
    assert result.tdx_row_n == 3
    assert result.tencent_row_n == 0
    assert result.tdx_failure_n == 0 and result.tencent_failure_n == 0


def test_fetch_resumes_cached_codes(env, monkeypatch) -> None:
    layout, cache_root, runtime = env
    tdx_cache = cache_root / "raw_tdx"
    tdx_cache.mkdir(parents=True, exist_ok=True)
    dc._write_code_cache(tdx_cache / "600001.parquet", [_row("600001")])

    def tdx(codes, *, sessions, run_id, normalize):
        assert "600001" not in codes
        return [_row(c) for c in codes], []

    def tencent(codes, *, sessions, cache_dir, workers, retries, run_id, normalize):
        return [], []

    monkeypatch.setattr(dc, "fetch_tdx_daily", tdx)
    monkeypatch.setattr(dc, "fetch_tencent_daily", tencent)
    result = _run(layout, cache_root, runtime)
    assert result.provider_cached_codes == 1
    assert result.provider_requested_codes == 2
    assert result.tdx_row_n == 3


def test_fetch_records_failures_and_summary(env, monkeypatch) -> None:
    layout, cache_root, runtime = env

    def tdx(codes, *, sessions, run_id, normalize):
        return [], [ValueError("tdx down")]

    def tencent(codes, *, sessions, cache_dir, workers, retries, run_id, normalize):
        return [], [ValueError("tx down")]

    monkeypatch.setattr(dc, "fetch_tdx_daily", tdx)
    monkeypatch.setattr(dc, "fetch_tencent_daily", tencent)
    result = _run(layout, cache_root, runtime)
    assert result.tdx_failure_n == 1 and result.tencent_failure_n == 1
    assert result.provider_retry_codes == 2
    summary = json.loads(result.summary_path.read_text())
    assert "tdx_wall_seconds" in summary and "tencent_wall_seconds" in summary
    assert summary["tdx_failure_n"] == 1


def test_fetch_propagates_provider_exception(env, monkeypatch) -> None:
    layout, cache_root, runtime = env

    def tdx(codes, *, sessions, run_id, normalize):
        raise RuntimeError("tdx crash")

    def tencent(codes, *, sessions, cache_dir, workers, retries, run_id, normalize):
        return [], []

    monkeypatch.setattr(dc, "fetch_tdx_daily", tdx)
    monkeypatch.setattr(dc, "fetch_tencent_daily", tencent)
    with pytest.raises(RuntimeError):
        _run(layout, cache_root, runtime)
