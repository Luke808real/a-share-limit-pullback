"""Per-code screen state persistence."""

from __future__ import annotations

from pathlib import Path

from limit_pullback.models.signal import StrategySignal
from limit_pullback.screen.models import ScreenState
from limit_pullback.warehouse.parquet import write_json_atomic


def state_path(root: Path, code: str) -> Path:
    return root / "screen" / "states" / f"{code}.json"


def load_state(path: Path) -> ScreenState | None:
    if not path.exists():
        return None
    return ScreenState.model_validate_json(path.read_text(encoding="utf-8"))


def save_state(
    path: Path,
    *,
    code: str,
    last_processed_date,
    signal: StrategySignal,
    snapshot_id: str,
    bars_prefix_hash: str,
    limit_pool_prefix_hash: str,
    strategy_commit: str,
    config_hash: str,
    reconciliation_policy_version: str,
    processed_at,
) -> ScreenState:
    state = ScreenState(
        code=code,
        last_processed_date=last_processed_date,
        signal_json=signal.model_dump_json(exclude_computed_fields=True),
        setup_id=signal.setup_id,
        snapshot_id=snapshot_id,
        bars_prefix_hash=bars_prefix_hash,
        limit_pool_prefix_hash=limit_pool_prefix_hash,
        strategy_commit=strategy_commit,
        config_hash=config_hash,
        reconciliation_policy_version=reconciliation_policy_version,
        processed_at=processed_at,
    )
    write_json_atomic(
        state.model_dump(mode="json"),
        path,
    )
    return state
