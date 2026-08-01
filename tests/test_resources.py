from __future__ import annotations

from datetime import date

import duckdb

from limit_pullback.resources import (
    PerformanceProfile,
    apply_duckdb_settings,
    detect_hardware,
    available_memory_bytes,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.pipeline import bootstrap
from tests.warehouse_fakes import FakeProviderSet, daily_row


def test_detect_hardware_reports_fields():
    profile = detect_hardware()
    assert "architecture" in profile
    assert "logical_cpus" in profile
    assert "total_memory_mb" in profile
    assert "available_memory_mb" in profile
    assert "native_arm64" in profile
    assert available_memory_bytes() > 0


def test_performance_profile_env_overrides(monkeypatch):
    monkeypatch.setenv("LIMIT_PULLBACK_DUCKDB_THREADS", "2")
    monkeypatch.setenv("LIMIT_PULLBACK_CANONICAL_FLUSH_ROWS", "123")
    profile = PerformanceProfile.load()
    assert profile.duckdb_threads == 2
    assert profile.canonical_flush_rows == 123
    assert profile.screen_workers == 4  # default untouched


def test_apply_duckdb_settings():
    connection = duckdb.connect()
    apply_duckdb_settings(
        connection,
        PerformanceProfile.load(),
        temp_dir="",
    )
    threads = connection.execute(
        "SELECT value FROM duckdb_settings() WHERE name = 'threads'"
    ).fetchone()[0]
    assert int(threads) == 4
    limit = connection.execute(
        "SELECT value FROM duckdb_settings() WHERE name = 'memory_limit'"
    ).fetchone()[0]
    assert "GiB" in str(limit) or "5.0GB" in str(limit)


def test_bootstrap_metrics_and_canonical_flush(tmp_path):
    layout = WarehouseLayout(tmp_path / "data")
    day = date(2026, 7, 30)
    fake = FakeProviderSet(
        calendar=[day],
        tushare_daily=[daily_row("603318", day.isoformat())],
        akshare_daily=[daily_row("603318", day.isoformat())],
    )
    profile = PerformanceProfile.load()
    profile.canonical_flush_rows = 1
    result = bootstrap(
        layout=layout,
        start=day,
        end=day,
        codes=["603318"],
        provider_set=fake,
        today=day,
        profile=profile,
    )
    assert result.snapshot_id is not None
    assert result.metrics["peak_rss_mb"] > 0
    assert result.metrics["rows_written"] > 0
    parts = list((layout.root / "tmp" / "canonical").glob("part-*.parquet"))
    assert parts
