"""T0 Registry V02 authority closeout — targeted offline tests.

Proves the minimal provenance/authority patch:

* every V02 registry row carries the repaired snapshot id (and foreign
  snapshot lineage fails closed);
* the input-authority binding fail-closes on tampered receipt fields
  (snapshot_id / repair_run_id / canonical daily SHA / canonical pool SHA);
* the July 23-session gate fail-closes;
* the T0 setup_id set is unchanged by the provenance rewrite (semantics
  untouched).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "factor-lab"))

from t0_registry_v02 import (  # noqa: E402
    SNAPSHOT_ID,
    bind_row_provenance,
    july_hard_gate,
    load_input_authority,
    verify_row_provenance,
)

SNAP = SNAPSHOT_ID
OTHER_SNAP = "snap-2026-07-31-b5f84004de8a"


def _row(setup_id: str = "000001:20260709:1000", snapshot_id: str = OTHER_SNAP) -> dict:
    return {
        "setup_id": setup_id,
        "code": "000001",
        "anchor_date": "2026-07-09",
        "anchor_price": "10.00",
        "anchor_source": "limit",
        "profile": "a",
        "limit_price": "10.00",
        "is_first_board": False,
        "recent_limit_count": 1,
        "recent_limits_non_consecutive": False,
        "seal_before_cutoff": True,
        "snapshot_id": snapshot_id,
        "strategy_commit": "315fbe0d",
        "strategy_config_hash": "47a0ea2b",
    }


# ---------- 1. row provenance rewrite ----------

def test_bind_row_provenance_rewrites_every_row() -> None:
    rows = [_row(setup_id="a", snapshot_id=OTHER_SNAP), _row(setup_id="b", snapshot_id=OTHER_SNAP)]
    bound = bind_row_provenance(rows, SNAP)
    assert all(r["snapshot_id"] == SNAP for r in bound)
    # every other field untouched
    assert bound[0]["setup_id"] == "a"
    assert bound[1]["setup_id"] == "b"
    assert bound[0]["anchor_price"] == "10.00"
    assert bound[0]["strategy_commit"] == "315fbe0d"
    # original list not mutated
    assert rows[0]["snapshot_id"] == OTHER_SNAP


def test_verify_row_provenance_unique_and_zero_mismatch() -> None:
    rows = bind_row_provenance([_row()], SNAP)
    unique, mismatch = verify_row_provenance(rows, SNAP)
    assert unique == [SNAP]
    assert mismatch == 0


def test_verify_row_provenance_foreign_snapshot_fails_closed() -> None:
    rows = bind_row_provenance([_row()], SNAP)
    rows[0]["snapshot_id"] = OTHER_SNAP
    with pytest.raises(RuntimeError) as excinfo:
        verify_row_provenance(rows, SNAP)
    assert "ROW_SNAPSHOT_ID_MISMATCH_N" in str(excinfo.value)


def test_bind_does_not_change_setup_id_set() -> None:
    raw = [
        _row(setup_id=s, snapshot_id=OTHER_SNAP)
        for s in ("a", "b", "c", "d")
    ]
    before = {r["setup_id"] for r in raw}
    after = {r["setup_id"] for r in bind_row_provenance(raw, SNAP)}
    assert before == after == {"a", "b", "c", "d"}


# ---------- 2. input-authority binding ----------

def _write_evidence(tmp_path: Path, receipt_patch: dict | None = None,
                    validation_patch: dict | None = None) -> tuple[Path, Path]:
    receipt = {
        "new_snapshot_id": SNAP,
        "snapshot_as_of": "2026-07-31",
        "snapshot_status": "RESEARCH_READY",
        "repair_run_id": "59aad30e65ae8c8d43928bcd",
        "provider_name": "ASL",
        "execution_code_head": "bea3317f5193a2b993332ec5322b953616b8bf0c",
        "new_canonical_file_hashes": {
            f"canonical/daily_bars/{SNAP}.parquet":
                "75fa706dd8575ee5c43d4a9462adda39c8e17af4c72866b00b1fabacea364dc0",
            f"canonical/limit_up_pool/{SNAP}.parquet":
                "10119d6237a2ff59440796dba9f2b24f1b9ad91178bb1705dcd081014dcf6d8a",
        },
    }
    validation = {
        "snapshot_invariants": {
            "july_sessions": 23,
            "july_confirmed_sessions": 23,
            "july_gap": [],
        }
    }
    if receipt_patch:
        receipt.update(receipt_patch)
    if validation_patch:
        validation["snapshot_invariants"].update(validation_patch)
    rp = tmp_path / "receipt.json"
    vp = tmp_path / "validation.json"
    rp.write_text(json.dumps(receipt), encoding="utf-8")
    vp.write_text(json.dumps(validation), encoding="utf-8")
    return rp, vp


def test_load_input_authority_passes_on_intact_evidence(tmp_path) -> None:
    rp, vp = _write_evidence(tmp_path)
    authority = load_input_authority(rp, vp)
    assert authority["snapshot_id"] == SNAP
    assert authority["snapshot_status"] == "RESEARCH_READY"
    assert authority["repair_run_id"] == "59aad30e65ae8c8d43928bcd"


@pytest.mark.parametrize(
    "patch",
    [
        {"new_snapshot_id": OTHER_SNAP},
        {"repair_run_id": "72e05fe83ffb6f2317a76824"},
        {"snapshot_status": "CURRENT"},
        {"provider_name": "TUSHARE"},
        {"execution_code_head": "deadbeef"},
    ],
)
def test_load_input_authority_tampered_receipt_fails(tmp_path, patch) -> None:
    rp, vp = _write_evidence(tmp_path, receipt_patch=patch)
    with pytest.raises(RuntimeError) as excinfo:
        load_input_authority(rp, vp)
    assert "INPUT_AUTHORITY_BINDING_FAIL" in str(excinfo.value)


def test_load_input_authority_tampered_daily_sha_fails(tmp_path) -> None:
    rp, vp = _write_evidence(tmp_path)
    receipt = json.loads(rp.read_text(encoding="utf-8"))
    receipt["new_canonical_file_hashes"][f"canonical/daily_bars/{SNAP}.parquet"] = "0" * 64
    rp.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(RuntimeError) as excinfo:
        load_input_authority(rp, vp)
    assert "INPUT_AUTHORITY_BINDING_FAIL" in str(excinfo.value)
    assert "canonical_daily_sha" in str(excinfo.value)


def test_load_input_authority_tampered_pool_sha_fails(tmp_path) -> None:
    rp, vp = _write_evidence(tmp_path)
    receipt = json.loads(rp.read_text(encoding="utf-8"))
    receipt["new_canonical_file_hashes"][f"canonical/limit_up_pool/{SNAP}.parquet"] = "0" * 64
    rp.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(RuntimeError) as excinfo:
        load_input_authority(rp, vp)
    assert "canonical_pool_sha" in str(excinfo.value)


def test_load_input_authority_july_gap_fails(tmp_path) -> None:
    rp, vp = _write_evidence(tmp_path, validation_patch={"july_gap": ["2026-07-09"]})
    with pytest.raises(RuntimeError) as excinfo:
        load_input_authority(rp, vp)
    assert "INPUT_AUTHORITY_BINDING_FAIL" in str(excinfo.value)


def test_load_input_authority_july_session_count_fails(tmp_path) -> None:
    rp, vp = _write_evidence(tmp_path, validation_patch={"july_sessions": 22})
    with pytest.raises(RuntimeError) as excinfo:
        load_input_authority(rp, vp)
    assert "INPUT_AUTHORITY_BINDING_FAIL" in str(excinfo.value)


# ---------- 3. July hard gate ----------

def _fake_daily(n_days: int) -> dict[str, tuple]:
    from datetime import date, datetime, timedelta, timezone

    from limit_pullback.models.market import DailyBar

    start = date(2026, 7, 1)
    bars = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        bars.append(
            DailyBar(
                code="000001",
                trade_date=d,
                open="10.00", high="10.50", low="9.80", close="10.20",
                preclose="10.00", volume="100000", amount="1020000.00",
                turnover_rate=None, pct_change="2.00",
                trade_status=True, is_st=None,
                source="synthetic",
                fetched_at=datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc),
            )
        )
    return {"000001": tuple(bars)}


def test_july_hard_gate_23_passes() -> None:
    daily = _fake_daily(23)
    result = july_hard_gate(daily)
    assert result["july_sessions_2026"] == 23


def test_july_hard_gate_not_23_fails() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        july_hard_gate(_fake_daily(22))
    assert "JULY_SESSION_GATE_FAIL" in str(excinfo.value)
