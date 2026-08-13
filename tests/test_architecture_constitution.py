"""REF-R1 constitution checks: assert only rules that already hold at baseline.

These tests enforce the frozen strategy contract and the already-clean layer
boundaries. They must stay green during REF-R1 and guard against accidental
semantic or dependency drift in later refactor rounds.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from limit_pullback.models.enums import SetupStage
from limit_pullback.models.signal import StrategySignal
from limit_pullback.screen.generation import ACTIVE, REJECTED, STAGED, VERIFIED
from limit_pullback.warehouse.models import CanonicalDailyBar

ROOT = Path(__file__).resolve().parents[1]

FROZEN_STRATEGY_CONFIG_SHA256 = (
    "47a0ea2b41952f06f43d1fe3a5e066993bade6ecec45c81103022008c7eae6bf"
)
FROZEN_TRADE_PLAN_CONFIG_SHA256 = (
    "06fd5dc96989a47015ad89ec543ad41784d7ef3eba074f17b679bd99d73a3c00"
)
FORBIDDEN_DEP_PREFIXES = (
    "limit_pullback.providers",
    "limit_pullback.warehouse",
    "akshare",
    "baostock",
    "pytdx",
    "tushare",
    "duckdb",
    "pyarrow",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _imported_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _forbidden(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_DEP_PREFIXES)


def test_frozen_strategy_config_hashes_unchanged():
    assert _sha256(ROOT / "config" / "strategy.yaml") == FROZEN_STRATEGY_CONFIG_SHA256
    assert _sha256(ROOT / "config" / "trade_plan.yaml") == FROZEN_TRADE_PLAN_CONFIG_SHA256


def test_setup_stage_enum_is_frozen():
    assert {stage.value for stage in SetupStage} == {
        "NORMAL",
        "LIMIT_ANCHOR",
        "WATCH_PULLBACK",
        "B1_READY",
        "B2_READY",
        "B2_CONFIRMED",
        "INVALID",
    }


def test_models_and_strategy_do_not_import_providers_or_warehouse():
    offenders: list[str] = []
    for layer in ("models", "strategy"):
        for path in sorted((ROOT / "src" / "limit_pullback" / layer).rglob("*.py")):
            names = _imported_names(path.read_text(encoding="utf-8"))
            hits = {name for name in names if _forbidden(name)}
            if hits:
                offenders.append(f"{path.relative_to(ROOT)}: {sorted(hits)}")
    assert not offenders, f"layer boundary violations: {offenders}"


def test_canonical_bar_keeps_single_provider_lineage_fields():
    required = {
        "selected_provider",
        "source_row_hash",
        "dataset_snapshot_id",
        "trade_status",
        "is_st",
        "reconciliation_status",
    }
    assert required <= set(CanonicalDailyBar.model_fields)


def test_strategy_signal_keeps_frozen_contract_surface():
    required = {
        "code",
        "trade_date",
        "setup_id",
        "setup_stage",
        "strategy_version",
        "support",
        "invalid_price",
        "initial_invalid_price",
        "b2_trigger",
        "target_s1",
        "score",
        "entry_quality_score",
        "event_flags",
    }
    assert required <= set(StrategySignal.model_fields)


def test_generation_lifecycle_constants_present():
    assert {STAGED, VERIFIED, ACTIVE, REJECTED} == {
        "STAGED",
        "VERIFIED",
        "ACTIVE",
        "REJECTED",
    }
