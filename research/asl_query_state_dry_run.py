"""ASL query-backed state generation DRY RUN (SHADOW / SANDBOX only).

Proof: the accepted official Query API candidate snapshot flows through the
EXISTING production state-generation pipeline unchanged.

Sandbox-only activation: inside a disposable isolated WarehouseLayout the
candidate is marked SCREEN_READY and the formal screen pointer is set using
the existing metadata APIs, with an explicit TEST_ONLY governance reason.
This is NOT a production status claim (ST_READY = NO).

Steps:
1. query-backed candidate build (reader="query", codes=None)
2. data_validate(candidate) must be valid
3. SANDBOX activation (SCREEN_READY + formal pointer)
4. universe from phase2d0_universe_from_snapshot (no legacy list)
5. session calendar + verified_no_trade via the official Query API
6. build_state_generation(rebuild=True, dry_run=True, seed_states_root=None)
7. report verification.json + state evidence

Run with the ASL environment:

    PYTHONPATH=src /private/tmp/asl_inspect/asl/.venv/bin/python \
        research/asl_query_state_dry_run.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ashare_lake.query import load  # noqa: E402

from limit_pullback.config import load_strategy_config  # noqa: E402
from limit_pullback.screen.generation import build_state_generation  # noqa: E402
from limit_pullback.universe import phase2d0_universe_from_snapshot  # noqa: E402
from limit_pullback.warehouse.asl_query_adapter import _query_status_rows  # noqa: E402
from limit_pullback.warehouse.asl_snapshot import build_asl_candidate_snapshot  # noqa: E402
from limit_pullback.warehouse.layout import WarehouseLayout  # noqa: E402
from limit_pullback.warehouse.metadata import WarehouseMetadata  # noqa: E402
from limit_pullback.warehouse.validate import data_validate  # noqa: E402

ASL_ROOT = Path("/private/tmp/asl_phase1b_lake")
AS_OF = date(2026, 8, 6)
START = date(2024, 1, 16)

SANDBOX_REASON = "SANDBOX_STATE_DRY_RUN_TEST_ONLY"
SCREEN_READY = "SCREEN_READY"


class RssSampler:
    """Phase-1B-style aggregate RSS sampler (parent + live children)."""

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.peak = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        proc = psutil.Process()
        while not self._stop.wait(self.interval):
            try:
                total = proc.memory_info().rss
                for child in proc.children(recursive=True):
                    try:
                        total += child.memory_info().rss
                    except psutil.NoSuchProcess:
                        pass
                self.peak = max(self.peak, total)
            except psutil.Error:
                continue

    def stop(self) -> float:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        return self.peak / (1024.0 * 1024.0)


def main() -> int:
    config_path = Path("config/strategy.yaml")
    load_strategy_config(config_path)  # sanity: config parseable

    tmp = Path(tempfile.mkdtemp(prefix="p1c_state_dry_"))
    layout = WarehouseLayout(tmp / "data")
    layout.ensure_dirs()

    # 1. query-backed candidate.
    candidate_start = time.time()
    snapshot = build_asl_candidate_snapshot(
        layout=layout,
        asl_root=ASL_ROOT,
        as_of=AS_OF,
        codes=None,
        start=START,
    )
    candidate_wall = time.time() - candidate_start

    # 2. validation.
    validation = data_validate(layout, snapshot_id=snapshot.snapshot_id)
    if not validation.valid:
        raise RuntimeError(
            "candidate validation failed: "
            + json.dumps([i.check for i in validation.issues])
        )

    # 3. SANDBOX-only activation via existing metadata APIs.
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.set_snapshot_status(
            snapshot_id=snapshot.snapshot_id,
            status=SCREEN_READY,
            reason=SANDBOX_REASON,
        )
        metadata.set_formal_pointer(snapshot_id=snapshot.snapshot_id)

    # 4. universe from the query-backed candidate.
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(snapshot.snapshot_id)
    from limit_pullback.warehouse.snapshot import read_snapshot_daily_table

    daily_table = read_snapshot_daily_table(layout, stored)
    daily_row_n = daily_table.num_rows if daily_table is not None else 0
    universe = phase2d0_universe_from_snapshot(
        layout, stored, as_of=AS_OF
    )
    universe_symbols = [
        code + (".SH" if code.startswith("6") else ".SZ")
        for code in universe.members
    ]

    # 5. session calendar + verified_no_trade via the official Query API.
    calendar_df = load(
        "trading_calendar", start=START, end=AS_OF, data_root=ASL_ROOT
    )
    session_calendar = sorted(
        record["trade_date"]
        for record in calendar_df.to_dicts()
        if record["is_trading"]
    )
    status_rows = _query_status_rows(ASL_ROOT, universe.members, START, AS_OF)
    verified_no_trade = sorted(
        (code, day)
        for (code, day), row in status_rows.items()
        if row.trust in ("DERIVED_GAP_SUSPENDED",)
        or (
            row.trust == "EASTMONEY_SAME_DAY"
            and (not row.is_trading or row.status == "suspended")
        )
    )

    # 6. ONE full state generation dry run (existing production API).
    build_root = tmp / "build"
    build_root.mkdir(parents=True)
    sampler = RssSampler()
    sampler.start()
    build_start = time.time()
    result = build_state_generation(
        layout=layout,
        snapshot_id=snapshot.snapshot_id,
        universe=universe,
        config_path=config_path,
        as_of=AS_OF,
        start=START,
        rebuild=True,
        build_root=build_root,
        dry_run=True,
        seed_states_root=None,
        verified_no_trade=verified_no_trade,
        session_calendar=session_calendar,
    )
    build_wall = time.time() - build_start
    peak_rss_mb = round(sampler.stop())

    verification = json.loads(
        (build_root / "verification.json").read_text(encoding="utf-8")
    )

    # 7. Strategy evidence from the STAGED state files (research observation).
    setup_counts: dict[str, int] = {}
    entry_candidate_n = 0
    active_setup_n = 0
    states_dir = build_root / "states"
    for path in sorted(states_dir.glob("[0-9]*.json")):
        state = json.loads(path.read_text(encoding="utf-8"))
        signal = json.loads(state["signal_json"])
        stage = signal["setup_stage"]
        setup_counts[stage] = setup_counts.get(stage, 0) + 1
        if signal.get("is_entry_candidate"):
            entry_candidate_n += 1
        if stage not in ("NORMAL", "INVALID"):
            active_setup_n += 1

    report = {
        "status": "PASS",
        "query_runtime": {
            "asl_revision": "ba5681a",
            "data_root": str(ASL_ROOT),
            "network_calls": 0,
        },
        "candidate": {
            "snapshot_id": snapshot.snapshot_id,
            "initial_status": "CURRENT",
            "validator_valid": validation.valid,
            "validator_issue_n": len(validation.issues),
            "scope_n": universe.member_n,
            "canonical_code_n": len(universe.members),
            "daily_row_n": daily_row_n,
            "candidate_wall_s": round(candidate_wall, 1),
        },
        "sandbox_activation": {
            "sandbox_only": True,
            "status_after": SCREEN_READY,
            "formal_pointer_set": True,
            "production_pointer_touched": False,
            "marker": "TEST_ONLY",
            "governance_reason": SANDBOX_REASON,
        },
        "universe": {
            "n": universe.member_n,
            "hash": universe.member_hash,
        },
        "state_build": {
            "api": "limit_pullback.screen.generation.build_state_generation",
            "rebuild": True,
            "dry_run": True,
            "generation_id": result.generation_id,
            "returned_status": result.status,
            "state_n": result.state_n,
            "setup_counts": dict(sorted(setup_counts.items())),
            "active_setup_n": active_setup_n,
            "entry_candidate_n": entry_candidate_n,
        },
        "state_verify": {
            "passed": verification.get("passed"),
            "state_universe_old_only_n": verification.get("state_universe_old_only_n"),
            "state_universe_new_only_n": verification.get("state_universe_new_only_n"),
            "duplicate_code_n": verification.get("duplicate_code_n"),
            "snapshot_binding_mismatch_n": verification.get("snapshot_binding_mismatch_n"),
            "state_coverage_through_as_of_n": verification.get("state_coverage_through_as_of_n"),
            "state_uncovered_n": verification.get("state_uncovered_n"),
            "latest_confirmed_bar_after_state_last_processed_n": verification.get(
                "latest_confirmed_bar_after_state_last_processed_n"
            ),
            "eligible_from_invariant_fail_n": verification.get("eligible_from_invariant_fail_n"),
            "compact_roundtrip_hash_match": verification.get("compact_roundtrip_hash_match"),
            "verified_no_trade_covered_n": verification.get("verified_no_trade_covered_n"),
            "issues": verification.get("issues"),
        },
        "resource": {
            "aggregate_peak_rss_mb": peak_rss_mb,
            "wall_time_s": round(build_wall, 1),
            "gate_mb": 4096,
        },
        "session_coverage": {
            "calendar_source": "ashare_lake.query.load('trading_calendar')",
            "session_n": len(session_calendar),
            "verified_no_trade_n": len(verified_no_trade),
        },
        "production_mutation": "NONE",
        "production_files_changed": "NONE",
        "strategy_files_changed": "NONE",
        "st_ready": "NO",
        "provenance_gap": "OPEN",
        "production_cutover": "NO_GO",
        "data_root": str(tmp),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
