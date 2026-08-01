"""Runtime hardware detection and the APPLE_SILICON_16GB performance profile."""

from __future__ import annotations

import os
import platform
import resource
import subprocess
from dataclasses import dataclass, fields
from typing import Any


def _sysctl(name: str) -> int | None:
    try:
        result = subprocess.run(
            ["sysctl", "-n", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception:
        pass
    return None


def _vm_stat() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        output = subprocess.run(
            ["vm_stat"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        for line in output.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            digits = "".join(character for character in value if character.isdigit())
            if digits:
                result[key.strip()] = int(digits)
    except Exception:
        pass
    return result


def total_memory_bytes() -> int:
    value = _sysctl("hw.memsize")
    return value if value else 0


def available_memory_bytes() -> int:
    page_size = _sysctl("hw.pagesize") or 4096
    stat = _vm_stat()
    free = stat.get("Pages free", 0)
    inactive = stat.get("Pages inactive", 0)
    purgeable = stat.get("Pages purgeable", 0)
    return (free + inactive + purgeable) * page_size


def process_rss_bytes() -> int:
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip()) * 1024
    except Exception:
        pass
    return 0


def peak_rss_bytes() -> int:
    # macOS ru_maxrss is in bytes; Linux in kilobytes.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Darwin":
        return value
    return value * 1024


def _rosetta_translated() -> bool:
    value = _sysctl("sysctl.proc_translated")
    return value == 1


def detect_hardware() -> dict[str, Any]:
    architecture = platform.machine()
    translated = _rosetta_translated()
    native_arm64 = architecture == "arm64" and not translated
    return {
        "architecture": architecture,
        "logical_cpus": os.cpu_count() or 1,
        "total_memory_mb": total_memory_bytes() // (1024 * 1024),
        "available_memory_mb": available_memory_bytes() // (1024 * 1024),
        "process_rss_mb": process_rss_bytes() // (1024 * 1024),
        "rosetta_translated": translated,
        "native_arm64": native_arm64,
    }


@dataclass
class PerformanceProfile:
    """APPLE_SILICON_16GB defaults; every field is env-overridable."""

    name: str = "apple-silicon-16gb"
    duckdb_threads: int = 4
    duckdb_memory_limit_gb: int = 5
    screen_workers: int = 4
    replay_verify_workers: int = 3
    tushare_workers: int = 1
    akshare_workers: int = 1
    baostock_workers: int = 3
    reconciliation_code_chunk: int = 96
    arrow_batch_rows: int = 50000
    canonical_flush_rows: int = 100000
    parquet_compression: str = "zstd"
    parquet_compression_level: int = 3
    parquet_row_group_rows: int = 100000
    minimum_available_memory_gb: float = 3.0
    pause_available_memory_gb: float = 2.0

    @classmethod
    def load(cls, name: str = "apple-silicon-16gb") -> "PerformanceProfile":
        profile = cls(name=name)
        for field_info in fields(cls):
            env_name = "LIMIT_PULLBACK_" + field_info.name.upper()
            value = os.environ.get(env_name)
            if value is None:
                continue
            if field_info.type in ("int", "float"):
                converter = int if field_info.type == "int" else float
                setattr(profile, field_info.name, converter(value))
            else:
                setattr(profile, field_info.name, value)
        return profile

    def as_dict(self) -> dict[str, Any]:
        return {field_info.name: getattr(self, field_info.name) for field_info in fields(self)}


def apply_duckdb_settings(connection: Any, profile: PerformanceProfile, temp_dir: str) -> None:
    connection.execute(f"PRAGMA threads={int(profile.duckdb_threads)}")
    connection.execute(
        f"PRAGMA memory_limit='{int(profile.duckdb_memory_limit_gb)}GB'"
    )
    if temp_dir:
        connection.execute(f"PRAGMA temp_directory='{temp_dir}'")
