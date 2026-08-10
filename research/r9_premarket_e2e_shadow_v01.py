"""R9 premarket end-to-end shadow rehearsal (DRY RUN, no OOS writes).

E2E_SHADOW_REHEARSAL=true / PRIMARY_OOS=false.

Scope is deliberately bounded (600000.SH / 000001.SZ).  FULL-universe state
generation through the ASL query bridge is blocked by a narrow shared-lake
incompatibility that this task must NOT redesign or data-fix: the bridge's
required-bar check needs per-session trading_status evidence, and the shared
root only carries a 5-day trading_status snapshot (2026-08-03..07).  First
failure observed: 000007.SZ missing a bar on 2024-07-01 with status_row=None
(historical suspension evidence absent).  This rehearsal therefore validates
the frozen plumbing on complete-series symbols and reports the blocker.

Run:
    PYTHONPATH=src <venv-with-ashare_lake> python research/r9_premarket_e2e_shadow_v01.py
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import date, time
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "intraday_v01"))
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from ashare_lake.query import load  # noqa: E402

import r8a_intraday_contract_v01 as r8a  # noqa: E402
import r9_asl_pit_data_adapter_v01 as adapter  # noqa: E402
import r9_checkpoint_artifact_v01 as checkpoint  # noqa: E402
import r9_population_generator_v01 as population  # noqa: E402
import r9_protocol_v02 as protocol  # noqa: E402
import r9_prospective_factor_producer_v01 as producer  # noqa: E402
import r9_setup_accumulator_v01 as accumulator  # noqa: E402
import r9_ttl_event_eligibility_v01 as ttl  # noqa: E402
from limit_pullback.config import load_strategy_config  # noqa: E402
from limit_pullback.models.enums import DataQuality, SetupStage  # noqa: E402
from limit_pullback.screen.generation import build_state_generation  # noqa: E402
from limit_pullback.strategy.engine import make_setup_id  # noqa: E402
from limit_pullback.universe import phase2d0_universe_from_snapshot  # noqa: E402
from limit_pullback.warehouse.asl_query_adapter import _query_status_rows  # noqa: E402
from limit_pullback.warehouse.asl_snapshot import build_asl_candidate_snapshot  # noqa: E402
from limit_pullback.warehouse.layout import WarehouseLayout  # noqa: E402
from limit_pullback.warehouse.metadata import WarehouseMetadata  # noqa: E402
from limit_pullback.warehouse.snapshot import read_snapshot_daily_table  # noqa: E402
from limit_pullback.warehouse.validate import data_validate  # noqa: E402


ASL_ROOT = Path("/Users/luke808/AI/asl-shared")
R8_5M_ROOT = Path("/Users/luke808/AI/asl-r8-5m-lake")
AS_OF = date(2026, 8, 7)
START = date(2023, 8, 7)
TARGET_SESSION = date(2026, 8, 10)
SMOKE_CODES = ("600000", "000001")
R9_HEAD = "e00bb9adf1ded2e6bcbd2dfda0b8c8f7f72459ed"
PROTOCOL_FREEZE = "r9-protocol-freeze-v04"
ASL_PROJECT_SHA = adapter.ASL_VALIDATED_PROJECT_SHA
REHEARSAL_SESSION = date(2026, 7, 30)  # latest covered r8 5m session


def main() -> dict[str, Any]:
    load_strategy_config(REPO_ROOT / "config" / "strategy.yaml")
    report: dict[str, Any] = {"E2E_SHADOW_REHEARSAL": True, "PRIMARY_OOS": False}

    # --- A. bounded state generation through the ASL query bridge -----------
    tmp = Path(tempfile.mkdtemp(prefix="r9_premarket_shadow_"))
    layout = WarehouseLayout(tmp / "data")
    layout.ensure_dirs()
    snapshot = build_asl_candidate_snapshot(
        layout=layout,
        asl_root=ASL_ROOT,
        as_of=AS_OF,
        codes=SMOKE_CODES,
        start=START,
    )
    validation = data_validate(layout, snapshot_id=snapshot.snapshot_id)
    if not validation.valid:
        raise RuntimeError(
            "candidate validation failed: "
            + json.dumps([i.check for i in validation.issues])
        )
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.set_snapshot_status(
            snapshot_id=snapshot.snapshot_id,
            status="SCREEN_READY",
            reason="R9_PREMARKET_SHADOW_TEST_ONLY",
        )
        metadata.set_formal_pointer(snapshot_id=snapshot.snapshot_id)
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as metadata:
        stored = metadata.snapshot_by_id(snapshot.snapshot_id)
    daily_table = read_snapshot_daily_table(layout, stored)
    universe = phase2d0_universe_from_snapshot(layout, stored, as_of=AS_OF)
    report["state"] = {
        "candidate_snapshot_id": snapshot.snapshot_id,
        "state_as_of": AS_OF.isoformat(),
        "universe_n": universe.member_n,
        "universe_hash": universe.member_hash,
        "daily_row_n": daily_table.num_rows if daily_table is not None else 0,
        "full_universe_blocker": (
            "shared ASL trading_status coverage is only 2026-08-03..07; "
            "ASL bridge required-bar check fails closed on historical "
            "suspension gaps (first observed 000007.SZ 2024-07-01 "
            "status_row=None); full universe state generation requires the "
            "pending trading_status historical backfill (separate authorized task)"
        ),
    }

    calendar_df = load("trading_calendar", start=START, end=AS_OF, data_root=ASL_ROOT)
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
    build_root = tmp / "build"
    build_root.mkdir(parents=True)
    result = build_state_generation(
        layout=layout,
        snapshot_id=snapshot.snapshot_id,
        universe=universe,
        config_path=REPO_ROOT / "config" / "strategy.yaml",
        as_of=AS_OF,
        start=START,
        rebuild=True,
        build_root=build_root,
        dry_run=True,
        seed_states_root=None,
        verified_no_trade=verified_no_trade,
        session_calendar=session_calendar,
    )
    report["state"]["generation_id"] = result.generation_id
    report["state"]["premarket_state_ready"] = True

    # --- B. active setups from the bounded states ---------------------------
    states_dir = build_root / "states"
    stage_counts: Counter[str] = Counter()
    active_states: list[dict[str, Any]] = []
    for path in sorted(states_dir.glob("[0-9]*.json")):
        state = json.loads(path.read_text(encoding="utf-8"))
        signal = json.loads(state["signal_json"])
        stage = signal["setup_stage"]
        stage_counts[stage] += 1
        if stage not in ("NORMAL", "INVALID"):
            active_states.append({"code": state["code"], "signal": signal})
    report["setups"] = {
        "active_setup_n": len(active_states),
        "active_symbol_n": len({s["code"] for s in active_states}),
        "stage_distribution": dict(stage_counts),
        "b1_n": stage_counts.get("B1_READY", 0),
        "b2_ready_n": stage_counts.get("B2_READY", 0),
        "b2_confirmed_preobserved_n": stage_counts.get("B2_CONFIRMED", 0),
        "ttl_contract": {
            "T0_age": ttl.T0_AGE,
            "window": ttl.TTL_WINDOW,
            "unit": ttl.TTL_UNIT,
            "repeat_creates_new_event": ttl.REPEAT_CONFIRMATION_CREATES_NEW_EVENT,
            "checkpoint": ttl.PRIMARY_CHECKPOINT,
        },
    }

    # --- C. daily PIT factor package (bounded plumbing probes) --------------
    candidates = []
    for path in sorted(states_dir.glob("[0-9]*.json")):
        state = json.loads(path.read_text(encoding="utf-8"))
        signal = json.loads(state["signal_json"])
        code = state["code"]
        anchor_raw = signal.get("anchor_date")
        anchor = (
            date.fromisoformat(anchor_raw)
            if isinstance(anchor_raw, str) and anchor_raw
            else None
        )
        anchor_price = signal.get("anchor_price")
        candidates.append(
            population.DailySetupInput(
                setup_id=state.get("setup_id") or make_setup_id(
                    code,
                    anchor or AS_OF,
                    Decimal(str(anchor_price)) if anchor_price else Decimal("10.00"),
                    Decimal("0.01"),
                ),
                symbol=code,
                state_as_of=AS_OF,
                anchor_date=anchor,
                anchor_price=Decimal(str(anchor_price)) if anchor_price else Decimal("10.00"),
                setup_stage=signal["setup_stage"],
                invalid_price=signal.get("invalid_price"),
                s1_price=signal.get("s1_price"),
                data_quality=DataQuality.OK,
                price_tick=Decimal("0.01"),
            )
        )
    factor_report = _daily_factor_probe(candidates, as_of=AS_OF)
    # C2: fully historical fixture (existing 08-06 state generation) with a
    # REAL active setup (002828 B2_READY), per the shadow fallback contract.
    factor_report["fixture_0806"] = _fixture_factor_probe()
    report["daily_factors"] = factor_report

    # --- D. intraday rehearsal on a historical r8 5m session ---------------
    intraday = _intraday_rehearsal()
    report["intraday"] = intraday

    # --- E. OOS writer dry-run (schema only, in memory) ---------------------
    report["oos_dry_run"] = _oos_dry_run(intraday["observation_row"])
    report["oos_rows_before"] = 0
    report["oos_rows_after"] = 0
    report["primary_oos_written"] = False
    report["today_20260810_data_read"] = False
    return report


def _daily_factor_probe(
    candidates: list[population.DailySetupInput],
    *,
    as_of: date,
) -> dict[str, Any]:
    """Bounded adapter + producer probe; fail-closed reasons are expected."""
    if not candidates:
        return {
            "factor_eligible_n": 0,
            "factor_missing_n": 0,
            "m0_scoreable_n": 0,
            "m1_scoreable_n": 0,
            "m2_scoreable_n": 0,
            "note": "no active setups in bounded scope",
        }
    candidate_state_hash = hashlib.sha256(
        json.dumps(
            sorted(c.setup_id for c in candidates), separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    try:
        pit_input = adapter.build_pit_factor_input(
            as_of=as_of,
            candidates=tuple(candidates),
            candidate_state_source_hash=candidate_state_hash,
            limit_pool_source_hash=hashlib.sha256(b"shadow-empty-pool").hexdigest(),
            configuration_version_hash=hashlib.sha256(b"shadow-config").hexdigest(),
            asl_data_root=ASL_ROOT,
        )
    except adapter.ASLPITAdapterBlocked as exc:
        return {
            "factor_eligible_n": 0,
            "factor_missing_n": len(candidates),
            "missing_reasons": {"MISSING_T0_OR_COVERAGE": len(candidates)},
            "m0_scoreable_n": 0,
            "m1_scoreable_n": 0,
            "m2_scoreable_n": 0,
            "blocked": str(exc),
        }
    bundles = producer.produce_prospective_factor_bundles(pit_input)
    eligible = len(bundles)
    missing: Counter[str] = Counter()
    m0 = m1 = m2 = 0
    for bundle in bundles:
        values = {
            field: getattr(bundle, field)
            for field in ("B4", "B5", "B6", "B7", "median_range_ratio", "quiet_days_n")
        }
        for field, value in values.items():
            if value is None:
                missing[field] += 1
        for name, predictors in (
            ("M0", ("B4", "B5", "B6", "B7")),
            ("M1", ("B4", "B5", "B6", "B7", "median_range_ratio")),
            ("M2", ("B4", "B5", "B6", "B7", "median_range_ratio", "quiet_days_n")),
        ):
            if all(values[p] is not None for p in predictors):
                protocol.frozen_daily_score(name, values)
                if name == "M0":
                    m0 += 1
                elif name == "M1":
                    m1 += 1
                else:
                    m2 += 1
    return {
        "factor_eligible_n": eligible,
        "factor_missing_n": sum(missing.values()),
        "missing_reasons": dict(missing),
        "m0_scoreable_n": m0,
        "m1_scoreable_n": m1,
        "m2_scoreable_n": m2,
        "pit_boundary": {
            "as_of": as_of.isoformat(),
            "max_daily_allowed": as_of.isoformat(),
            "adapter_revision_gate": adapter.ASL_CODE_SHA,
        },
    }


def _fixture_factor_probe() -> dict[str, Any]:
    """Fully historical fixture: existing 08-06 state generation, active setup."""
    states_root = Path(
        os.environ.get(
            "VFLASH_STATES_ROOT",
            "/Users/luke808/AI/V flash/data/screen/states",
        )
    )
    if not states_root.exists():
        return {"note": "fixture states not present in this worktree"}
    candidates = []
    for path in sorted(states_root.glob("[0-9]*.json")):
        state = json.loads(path.read_text(encoding="utf-8"))
        signal = json.loads(state["signal_json"])
        if signal["setup_stage"] not in ("B1_READY", "B2_READY", "B2_CONFIRMED"):
            continue
        parts = str(signal.get("setup_id") or state.get("setup_id")).split(":")
        if len(parts) < 2:
            continue
        anchor = date.fromisoformat(parts[1])
        anchor_price = Decimal(parts[2]) if len(parts) > 2 else Decimal("10.00")
        state_as_of = date.fromisoformat(state["last_processed_date"])
        setup_id = make_setup_id(
            state["code"], anchor, anchor_price, Decimal("0.01")
        )
        candidates.append(
            population.DailySetupInput(
                setup_id=setup_id,
                symbol=state["code"],
                state_as_of=state_as_of,
                anchor_date=anchor,
                anchor_price=anchor_price,
                setup_stage=signal["setup_stage"],
                invalid_price=signal.get("invalid_price"),
                s1_price=signal.get("target_s1"),
                data_quality=DataQuality.OK,
                price_tick=Decimal("0.01"),
            )
        )
    if not candidates:
        return {"note": "no active setups in fixture states"}
    return _daily_factor_probe(candidates, as_of=candidates[0].state_as_of)


def _intraday_rehearsal() -> dict[str, Any]:
    """Historical r8 5m session -> features -> checkpoint -> observation row."""
    import duckdb

    symbol = "600563.SH"  # covered in the r8 5m research lake on the session
    con = duckdb.connect()
    files = sorted((R8_5M_ROOT / "curated" / "minute_bars_5m").rglob("*.parquet"))
    bars = con.execute(
        f"""
        SELECT symbol, trade_date, bar_time, open, high, low, close, volume
        FROM read_parquet({[str(f) for f in files]!r}, hive_partitioning=false)
        WHERE symbol = '{symbol}' AND trade_date = '{REHEARSAL_SESSION.isoformat()}'
        ORDER BY bar_time
        """
    ).df()
    max_bar_time = bars["bar_time"].max()
    rows_for_hash = bars.to_dict("records")
    source_hash = checkpoint.source_data_hash(rows_for_hash)

    cutoff = bars[bars["bar_time"] <= pd.Timestamp("2026-07-30 10:30:00")]
    s1 = float(cutoff.iloc[0]["open"])  # rehearsal-only S1 anchor (plumbing)
    window = cutoff[cutoff["high"] >= s1]
    features = {
        "breakout_hold_ratio": r8a.breakout_hold_ratio(window, s1),
        "retest_depth": r8a.retest_depth(window, s1),
        "false_break_duration": r8a.false_break_duration(window, s1),
        "vwap_acceptance_ratio": r8a.vwap_acceptance_ratio(
            window, float(cutoff["close"].mean())
        ),
    }
    artifact_path = Path(tempfile.mkdtemp(prefix="r9_checkpoint_")) / "checkpoint.json"
    checkpoint.create_checkpoint_artifact(
        target_session=REHEARSAL_SESSION,
        symbol_set=[symbol],
        bars=[
            {"bar_time": row["bar_time"], "high": row["high"], "low": row["low"]}
            for row in cutoff.to_dict("records")
        ],
        source="asl-r8-5m-lake",
        source_data_hash=source_hash,
        asl_project_sha=ASL_PROJECT_SHA,
        r9_head=R9_HEAD,
        protocol_freeze=PROTOCOL_FREEZE,
        out_path=artifact_path,
    )
    artifact = checkpoint.load_checkpoint_artifact(artifact_path)
    observation_row = {
        "event_id": f"shadow-{REHEARSAL_SESSION:%Y%m%d}-{symbol}",
        "setup_id": f"shadow-setup-{symbol}",
        "event_date": REHEARSAL_SESSION.isoformat(),
        "checkpoint": "10:30",
        "activation_time": "10:30",
        "post_activation_bar_n": len(window),
        "intraday_primary_feature_status": "REHEARSAL",
        "breakout_hold_ratio": features["breakout_hold_ratio"],
        "retest_depth": features["retest_depth"],
        "false_break_duration": features["false_break_duration"],
        "vwap_acceptance_ratio": features["vwap_acceptance_ratio"],
        "reference_price_10_30": float(cutoff["close"].iloc[-1]),
        "minute_manifest_hash": source_hash,
        "feature_hash": checkpoint.artifact_hash(features),
    }
    return {
        "historical_session": REHEARSAL_SESSION.isoformat(),
        "source": "asl-r8-5m-lake",
        "bar_timestamp_semantic": "right-labeled 5m grid (bar_time = interval end)",
        "max_bar_time": str(max_bar_time),
        "cutoff_1030_bar_n": len(cutoff),
        "features_ready": all(
            isinstance(v, (int, float)) and v == v for v in features.values()
        ),
        "features": features,
        "artifact_path": str(artifact_path),
        "artifact": artifact,
        "observation_row": observation_row,
    }


def _oos_dry_run(row: dict[str, Any]) -> dict[str, Any]:
    """Validate one in-memory observation row against the frozen ledger schema."""
    schema_path = (
        REPO_ROOT
        / "research"
        / "second_launch"
        / "walk_forward_v01"
        / "r9_intraday_observation_ledger_schema_v01.csv"
    )
    schema_cols = [
        line.strip()
        for line in schema_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][0].split(",")
    missing = [c for c in schema_cols if c not in row]
    return {
        "would_write_row_n": 1,
        "schema_valid": not missing,
        "missing_columns": missing,
        "dedup_key_valid": bool(row.get("event_id")) and bool(row.get("setup_id")),
        "mode": "DRY_RUN",
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
