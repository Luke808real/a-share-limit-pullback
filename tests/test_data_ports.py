"""REF-R3 data boundary tests: CanonicalDataPort adapters and shim parity."""

from __future__ import annotations

import ast
import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from limit_pullback.data import CanonicalDataPort, SnapshotDataAdapter
from limit_pullback.data.fixtures import InMemoryCanonicalAdapter
from limit_pullback.domain.provenance import DataProvenance
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.models import (
    CanonicalDailyBar,
)

ROOT = Path(__file__).resolve().parents[1]
ISOLATED_DATA = ROOT / "data" / "warehouse.duckdb"


def _bar(
    code: str,
    day: str,
    close: str = "10.00",
    *,
    is_st: bool | None = False,
    trade_status: bool = True,
    snapshot_id: str = "snap-test-000000000000",
) -> CanonicalDailyBar:
    return CanonicalDailyBar(
        code=code,
        trade_date=date.fromisoformat(day),
        open="9.90",
        high="10.10",
        low="9.80",
        close=close,
        preclose="9.85",
        volume="100000",
        amount="1000000",
        trade_status=trade_status,
        is_st=is_st,
        selected_provider="tushare",
        reconciliation_status="CONFIRMED",
        source_row_hash="h" * 64,
        dataset_snapshot_id=snapshot_id,
    )


def _provenance() -> DataProvenance:
    return DataProvenance(
        data_provider_system="fixture",
        data_snapshot_id="snap-test-000000000000",
        data_as_of="2026-07-31",
    )


def test_in_memory_adapter_conforms_to_port():
    adapter = InMemoryCanonicalAdapter(provenance=_provenance())
    assert isinstance(adapter, CanonicalDataPort)


def test_in_memory_adapter_daily_universe_status():
    bars = (
        _bar("600000", "2026-07-30", is_st=False),
        _bar("600000", "2026-07-31", is_st=True),
        _bar("000001", "2026-07-31"),
        _bar("000002", "2026-07-31", trade_status=False),
        _bar("000003", "2026-07-31", is_st=None),
    )
    adapter = InMemoryCanonicalAdapter(bars=bars, provenance=_provenance())

    got = adapter.get_daily("600000", date(2026, 7, 29), date(2026, 7, 31))
    assert tuple(bar.trade_date for bar in got) == (
        date(2026, 7, 30),
        date(2026, 7, 31),
    )
    assert adapter.get_daily_universe(date(2026, 7, 31)) == (
        "000001",
        "000002",
        "000003",
        "600000",
    )
    assert adapter.get_trading_status("600000", date(2026, 7, 31)) == "ST"
    assert adapter.get_trading_status("000001", date(2026, 7, 31)) == "NORMAL"
    assert adapter.get_trading_status("000002", date(2026, 7, 31)) == "NO_TRADE"
    assert adapter.get_trading_status("000003", date(2026, 7, 31)) == "UNKNOWN"
    assert adapter.get_trading_status("999999", date(2026, 7, 31)) is None
    assert adapter.get_data_provenance().data_provider_system == "fixture"
    with pytest.raises(NotImplementedError):
        adapter.get_minute("600000", date(2026, 7, 1), date(2026, 7, 31))
    with pytest.raises(NotImplementedError):
        adapter.get_corporate_action(
            "600000",
            date(2026, 7, 1),
            date(2026, 7, 31),
        )


@pytest.mark.skipif(
    not ISOLATED_DATA.exists(),
    reason="frozen snapshot data dir not present in this checkout",
)
def test_snapshot_adapter_fail_closed_on_unknown_snapshot():
    layout = WarehouseLayout(ROOT / "data")
    with pytest.raises(ValueError):
        SnapshotDataAdapter(layout, snapshot_id="snap-does-not-exist")


@pytest.mark.skipif(
    not ISOLATED_DATA.exists(),
    reason="frozen snapshot data dir not present in this checkout",
)
def test_snapshot_adapter_matches_legacy_reader():
    from limit_pullback.warehouse.snapshot import read_snapshot_daily

    layout = WarehouseLayout(ROOT / "data")
    snapshot_id = "snap-2026-07-31-b5f84004de8a"
    adapter = SnapshotDataAdapter(layout, snapshot_id=snapshot_id)
    assert isinstance(adapter, CanonicalDataPort)

    got = adapter.get_daily(
        "000001",
        date(2026, 7, 29),
        date(2026, 7, 31),
    )
    legacy_rows = [
        row
        for row in read_snapshot_daily(layout, adapter._snapshot)
        if str(row["code"]) == "000001"
        and date(2026, 7, 29)
        <= row["trade_date"]
        <= date(2026, 7, 31)
    ]
    assert got and len(got) == len(legacy_rows)
    for bar, row in zip(got, legacy_rows):
        assert bar.code == str(row["code"])
        assert bar.trade_date == row["trade_date"]
        assert bar.close == Decimal(str(row["close"]))
        assert bar.selected_provider == str(row["selected_provider"])
        assert bar.source_row_hash == str(row["source_row_hash"])
        assert bar.dataset_snapshot_id == str(row["dataset_snapshot_id"])
        assert bar.reconciliation_status == str(
            row["reconciliation_status"]
        )


@pytest.mark.skipif(
    not ISOLATED_DATA.exists(),
    reason="frozen snapshot data dir not present in this checkout",
)
def test_snapshot_adapter_status_universe_provenance():
    layout = WarehouseLayout(ROOT / "data")
    adapter = SnapshotDataAdapter(
        layout,
        snapshot_id="snap-2026-07-31-b5f84004de8a",
    )
    status = adapter.get_trading_status("000001", date(2026, 7, 31))
    assert status in {"NORMAL", "ST", "NO_TRADE"}
    assert adapter.get_trading_status("999999", date(2026, 7, 31)) is None
    universe = adapter.get_daily_universe(date(2026, 7, 31))
    assert "000001" in universe
    assert len(universe) > 1000
    provenance = adapter.get_data_provenance()
    assert provenance.data_snapshot_id == "snap-2026-07-31-b5f84004de8a"
    assert provenance.data_as_of == date(2026, 7, 31)
    assert provenance.quality_summary == "SCREEN_READY"
    assert provenance.source_version == "phase-2c2a-r1"
    manifest_path = ROOT / "data" / "manifests" / (
        "snap-2026-07-31-b5f84004de8a.json"
    )
    assert provenance.hash == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()


def test_screen_canonical_shim_reexports_data_layer():
    import limit_pullback.screen.canonical as shim
    from limit_pullback.data import canonical as data_canonical

    assert shim.load_canonical_market is data_canonical.load_canonical_market
    assert shim.load_canonical_metadata is data_canonical.load_canonical_metadata
    assert shim.iter_canonical_code_bars is data_canonical.iter_canonical_code_bars
    assert shim.FIXED_FETCHED_AT == data_canonical.FIXED_FETCHED_AT


def test_data_layer_import_boundary():
    """Data layer must not depend on strategy/selection/runtime orchestration.

    """

    forbidden_roots = (
        "limit_pullback.strategy",
        "limit_pullback.selection",
        "limit_pullback.runtime",
        "limit_pullback.screen",
    )
    offenders: list[str] = []
    for path in sorted((ROOT / "src" / "limit_pullback" / "data").rglob("*.py")):
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
            if any(
                name == root or name.startswith(root + ".")
                for root in forbidden_roots
            )
        }
        if hits:
            offenders.append(f"{path.relative_to(ROOT)}: {sorted(hits)}")
    assert not offenders, f"data layer boundary violations: {offenders}"
