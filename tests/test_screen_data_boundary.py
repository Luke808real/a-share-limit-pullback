"""P3 boundary test: screen depends on the data layer, not warehouse internals."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_screen_package_has_no_warehouse_imports():
    offenders: list[str] = []
    for path in sorted(
        (ROOT / "src" / "limit_pullback" / "screen").rglob("*.py")
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
            if name == "limit_pullback.warehouse"
            or name.startswith("limit_pullback.warehouse.")
        }
        if hits:
            offenders.append(f"{path.relative_to(ROOT)}: {sorted(hits)}")
    assert not offenders, f"screen warehouse imports: {offenders}"


def test_facade_reexports_are_identity():
    from limit_pullback.data.facade import (
        WarehouseLayout,
        WarehouseMetadata,
        sha256_file,
    )
    from limit_pullback.warehouse.layout import (
        WarehouseLayout as WarehouseWarehouseLayout,
    )
    from limit_pullback.warehouse.metadata import (
        WarehouseMetadata as WarehouseWarehouseMetadata,
    )
    from limit_pullback.warehouse.parquet import (
        sha256_file as warehouse_sha256_file,
    )

    assert WarehouseLayout is WarehouseWarehouseLayout
    assert WarehouseMetadata is WarehouseWarehouseMetadata
    assert sha256_file is warehouse_sha256_file


def test_read_side_tool_modules_have_no_warehouse_imports():
    """Read-side tool modules depend on the data layer, not warehouse internals.

    cli.py is deliberately exempt: its bootstrap/update/probe/status/validate/
    asl-snapshot commands are the warehouse acquisition surface itself and stay
    warehouse-owned until retirement.
    """

    modules = (
        "execution_reality.py",
        "outcome.py",
        "prc_audit.py",
        "trade_plan.py",
    )
    for filename in modules:
        path = ROOT / "src" / "limit_pullback" / filename
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
            if name == "limit_pullback.warehouse"
            or name.startswith("limit_pullback.warehouse.")
        }
        assert not hits, f"{filename}: {sorted(hits)}"


def test_universe_module_does_not_import_data_facade():
    """universe.py is re-exported by data/universe.py; importing the data
    facade from it would create a package import cycle. It keeps the direct
    warehouse.layout import until the future data-layer move."""

    path = ROOT / "src" / "limit_pullback" / "universe.py"
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert not any(name.startswith("limit_pullback.data") for name in names)


def test_pool_quality_reexport_is_identity():
    from limit_pullback.data.pool_quality import pool_quality as data_pool_quality
    from limit_pullback.screen.engine import pool_quality as screen_pool_quality

    assert screen_pool_quality is data_pool_quality
