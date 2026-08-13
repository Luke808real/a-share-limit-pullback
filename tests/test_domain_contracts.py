"""REF-R2 domain contract tests: formalize existing vocabulary without drift."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from limit_pullback import domain
from limit_pullback.domain.features import FeatureAvailability, FeatureRecord
from limit_pullback.domain.provenance import DataProvenance
from limit_pullback.domain.run import RunContext
from limit_pullback.domain.setup import PRODUCT_TO_RUNTIME_STAGE, SetupIdentity
from limit_pullback.domain.state import Lifecycle
from limit_pullback.models import market as models_market
from limit_pullback.models import signal as models_signal
from limit_pullback.models.enums import SetupStage

ROOT = Path(__file__).resolve().parents[1]


def test_domain_market_reexports_are_identical():
    assert domain.DailyBar is models_market.DailyBar
    assert domain.LimitUpRecord is models_market.LimitUpRecord


def test_domain_state_reexports_are_identical():
    assert domain.AnchorSnapshot is models_signal.AnchorSnapshot
    assert domain.SupportSnapshot is models_signal.SupportSnapshot
    assert domain.B2TriggerSnapshot is models_signal.B2TriggerSnapshot
    assert domain.S1Snapshot is models_signal.S1Snapshot
    assert domain.InvalidPriceSnapshot is models_signal.InvalidPriceSnapshot


def test_lifecycle_vocabulary_is_frozen():
    assert {item.value for item in Lifecycle} == {
        "ACTIVE",
        "INVALIDATED",
        "SUPERSEDED_BY_NEW_ANCHOR",
        "EXPIRED",
    }


def test_product_to_runtime_stage_mapping():
    assert PRODUCT_TO_RUNTIME_STAGE == {
        "T0": SetupStage.LIMIT_ANCHOR,
        "PULLBACK": SetupStage.WATCH_PULLBACK,
        "B1": SetupStage.B1_READY,
        "B2_READY": SetupStage.B2_READY,
        "B2_CONFIRMED": SetupStage.B2_CONFIRMED,
    }
    assert "SECOND_LAUNCH" not in PRODUCT_TO_RUNTIME_STAGE


def test_setup_identity_contract():
    identity = SetupIdentity(
        setup_id="600000:20260731:NORMAL",
        symbol="600000",
        anchor_date="2026-07-31",
        created_as_of="2026-07-31",
        strategy_version="phase-2d0",
    )
    assert identity.anchor_event_id is None
    with pytest.raises(ValidationError):
        SetupIdentity(
            setup_id="000001:20260731:NORMAL",
            symbol="600000",
            anchor_date="2026-07-31",
            created_as_of="2026-07-31",
            strategy_version="phase-2d0",
        )


def test_feature_availability_vocabulary():
    assert {item.value for item in FeatureAvailability} == {
        "AVAILABLE",
        "NOT_APPLICABLE",
        "INSUFFICIENT_HISTORY",
        "SOURCE_MISSING",
        "DATA_QUALITY_BLOCKED",
        "INVALID_INPUT",
        "CENSORED",
        "NOT_YET_ELIGIBLE",
    }


def test_feature_record_contract():
    record = FeatureRecord(
        feature_id="pullback_volume_ratio",
        feature_version="v1",
        symbol="600000",
        as_of="2026-07-31",
        value="0.78",
        availability=FeatureAvailability.AVAILABLE,
    )
    assert record.missing_reason is None
    assert record.source_refs == ()


def test_run_context_contract():
    context = RunContext(
        run_id="run-1",
        runtime_mode="DAILY",
        as_of="2026-07-31",
    )
    assert context.predecessor_generation_id is None
    with pytest.raises(ValidationError):
        RunContext(run_id="run-2", runtime_mode="INTRADAY", as_of="2026-07-31")
    with pytest.raises(ValidationError):
        RunContext(
            run_id="run-3",
            runtime_mode="DAILY",
            as_of="2026-07-31",
            started_at="2026-07-31T15:00:00",
        )


def test_data_provenance_contract():
    provenance = DataProvenance(
        data_provider_system="ashare-lake",
        data_snapshot_id="snap-2026-07-31-b5f84004de8a",
        data_as_of="2026-07-31",
    )
    assert provenance.hash is None


def test_existing_contract_hashes_unchanged():
    """REF-R2 must not change any pre-existing public schema."""

    manifest_path = (
        ROOT
        / ".goal-task"
        / "architecture-convergence-v01"
        / "baseline"
        / "contract-schema-file-hashes.txt"
    )
    schemas_dir = manifest_path.parent / "contract-schemas"
    entries = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        digest, rel_path = line.split("  ", 1)
        entries[rel_path] = digest
    for rel_path, digest in entries.items():
        content = (schemas_dir.parent / rel_path).read_bytes()
        assert hashlib.sha256(content).hexdigest() == digest, rel_path


def test_existing_contract_schemas_unchanged():
    """Live model schemas must still equal the frozen baseline schemas."""

    baseline = (
        ROOT
        / ".goal-task"
        / "architecture-convergence-v01"
        / "baseline"
        / "contract-schemas"
    )
    from limit_pullback.models.signal import StrategySignal
    from limit_pullback.warehouse.models import CanonicalDailyBar

    checks = {
        StrategySignal: baseline / "signal.StrategySignal.schema.json",
        CanonicalDailyBar: baseline / "models.CanonicalDailyBar.schema.json",
    }
    for model, path in checks.items():
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert model.model_json_schema() == stored, model.__name__


def test_domain_package_imports_only_models_and_stdlib():
    """Domain layer boundary: no warehouse, providers, screen, or CLI imports."""

    allowed_roots = {
        "limit_pullback.models",
        "limit_pullback.domain",
    }
    offenders: list[str] = []
    for path in sorted(
        (ROOT / "src" / "limit_pullback" / "domain").rglob("*.py")
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
            and not any(
                name == root or name.startswith(root + ".")
                for root in allowed_roots
            )
        }
        if hits:
            offenders.append(f"{path.relative_to(ROOT)}: {sorted(hits)}")
    assert not offenders, f"domain layer boundary violations: {offenders}"
