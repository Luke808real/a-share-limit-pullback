"""Operational runtime defaults for the daily fast path.

These are not strategy thresholds: they control provider workers, canonical
reader memory/threads, screen process workers and the bounded lookback window
used by true incremental state advance.  Environment variables override.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RuntimeConfig:
    tencent_workers: int = 16
    canonical_reader_threads: int = 4
    canonical_reader_memory_limit: str = "2GB"
    screen_process_workers: int = 4
    screen_worker_memory_limit_mb: int = 512
    daily_window_calendar_days: int = 400


def load_runtime_config(path: str | Path | None = None) -> RuntimeConfig:
    path = Path(path or Path(__file__).resolve().parents[2] / "config" / "runtime.yaml")
    payload: dict = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded

    def _int(name: str, default: int) -> int:
        return int(os.environ.get(name, payload.get(name, default)))

    return RuntimeConfig(
        tencent_workers=_int("OPS_TENCENT_WORKERS", 16),
        canonical_reader_threads=_int("OPS_READER_THREADS", 4),
        canonical_reader_memory_limit=os.environ.get(
            "OPS_READER_MEMORY_LIMIT",
            payload.get("canonical_reader_memory_limit", "2GB"),
        ),
        screen_process_workers=_int("OPS_PROCESS_WORKERS", 4),
        screen_worker_memory_limit_mb=_int("OPS_WORKER_MEMORY_MB", 512),
        daily_window_calendar_days=_int(
            "OPS_DAILY_WINDOW_CALENDAR_DAYS", 400
        ),
    )
