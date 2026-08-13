"""Import-order regression guards for package cycles introduced by shims."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fresh_import(module: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.returncode, result.stderr


def test_standalone_imports_have_no_cycle():
    for module in (
        "limit_pullback.universe",
        "limit_pullback.data",
        "limit_pullback.screen",
        "limit_pullback.strategy",
        "limit_pullback.state",
        "limit_pullback.selection",
        "limit_pullback.runtime",
        "limit_pullback.evidence",
        "limit_pullback.trade_plan",
        "limit_pullback.outcome",
    ):
        code, stderr = _fresh_import(module)
        assert code == 0, f"{module}: {stderr}"
