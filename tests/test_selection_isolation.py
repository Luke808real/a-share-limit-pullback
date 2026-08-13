"""REF-R6 selection isolation tests: verbatim move identity and boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from limit_pullback.selection import build_score
from limit_pullback.strategy import scoring as strategy_scoring
from limit_pullback.models.signal import ScoreBreakdown

ROOT = Path(__file__).resolve().parents[1]


def test_strategy_scoring_shim_reexports_selection():
    assert strategy_scoring.build_score is build_score
    assert strategy_scoring._fractional_score.__module__ == (
        "limit_pullback.selection.ranking"
    )


def test_selection_layer_import_boundary():
    """Selection imports only models/domain/stdlib; never state or data."""

    forbidden = (
        "limit_pullback.state",
        "limit_pullback.strategy",
        "limit_pullback.data",
        "limit_pullback.warehouse",
        "limit_pullback.screen",
        "limit_pullback.runtime",
        "limit_pullback.providers",
        "duckdb",
        "pyarrow",
        "akshare",
        "baostock",
        "pytdx",
        "tushare",
    )
    offenders: list[str] = []
    for path in sorted(
        (ROOT / "src" / "limit_pullback" / "selection").rglob("*.py")
    ):
        names: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        hits = {
            name
            for name in names
            if name.startswith("limit_pullback")
            and any(
                name == root or name.startswith(root + ".")
                for root in forbidden
            )
        } | {name for name in names if name.split(".")[0] in {
            "duckdb", "pyarrow", "akshare", "baostock", "pytdx", "tushare",
        }}
        if hits:
            offenders.append(f"{path.relative_to(ROOT)}: {sorted(hits)}")
    assert not offenders, f"selection layer boundary violations: {offenders}"


def test_score_breakdown_is_frozen():
    assert ScoreBreakdown.model_config.get("frozen") is True
