"""Targeted tests for the INTERIM reproducible label package gate (R1A.3).

The publishing gate accepts only the registered quarantine exact set; any
bypass, missing/extra quarantine ids, or snapshot hash drift fails closed.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "outcome_v01"))

import build_second_launch_outcome_v01 as gen  # noqa: E402


CODE = "600000"
CAND = date(2026, 3, 2)


def write_bars(path: Path, rows: list[tuple[date, str, str, str, str, str, str]]) -> None:
    """Write a canonical-style parquet: (trade_date, o, h, l, c, v, recon_status)."""
    table = pa.table(
        {
            "code": pa.array([CODE] * len(rows), pa.string()),
            "trade_date": pa.array([d.isoformat() for d, *_ in rows], pa.string()),
            "open": pa.array([float(r[1]) for r in rows], pa.float64()),
            "high": pa.array([float(r[2]) for r in rows], pa.float64()),
            "low": pa.array([float(r[3]) for r in rows], pa.float64()),
            "close": pa.array([float(r[4]) for r in rows], pa.float64()),
            "preclose": pa.array([float(r[4]) for r in rows], pa.float64()),
            "volume": pa.array([float(r[5]) for r in rows], pa.float64()),
            "amount": pa.array([float(r[5]) for r in rows], pa.float64()),
            "turnover_rate": pa.array([0.03] * len(rows), pa.float64()),
            "pct_change": pa.array([0.0] * len(rows), pa.float64()),
            "trade_status": pa.array([True] * len(rows), pa.bool_()),
            "is_st": pa.array([False] * len(rows), pa.bool_()),
            "reconciliation_status": pa.array(
                [r[6] for r in rows], pa.string()
            ),
        }
    )
    pq.write_table(table, path)


def make_case_csv(path: Path, outcomes: dict[str, str]) -> None:
    rows = []
    for i, (eid, outcome) in enumerate(outcomes.items()):
        rows.append(
            {
                "episode_id": eid,
                "symbol": CODE,
                "name": "",
                "anchor_date": CAND,
                "candidate_date": CAND,
                "s1_price": "10.5" if i == 0 else "11",
                "invalid_price": "9.5" if i == 0 else "9.0",
                "outcome": outcome,
                "outcome_reason": "frozen reason",
                "data_quality": "OK",
                "quality_flags": "[]",
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def _setup(tmp_path, n_cases: int = 3, mismatch_ids: set[str] | None = None):
    """Shared fixture: 3 cases, one of which is a real 3D mismatch."""
    if mismatch_ids is None:
        mismatch_ids = {"E:1"}
    outcomes = {
        "E:1": "NO_LAUNCH",  # contradicts bars below (S1 first + acceptance)
        "E:2": "NO_LAUNCH",
        "E:3": "NO_LAUNCH",
    }
    cases_path = tmp_path / "cases.csv"
    make_case_csv(cases_path, {k: v for k, v in list(outcomes.items())[:n_cases]})
    feature = tmp_path / "feature.parquet"
    label = tmp_path / "label.parquet"
    write_bars(feature, [
        (CAND, "10", "10", "10", "10", "100", "CONFIRMED"),
        (date(2026, 3, 3), "10", "10.5", "9.9", "10.1", "150", "CONFIRMED"),
        (date(2026, 3, 4), "10", "10.4", "9.9", "10.2", "140", "CONFIRMED"),
        (date(2026, 3, 5), "10", "10.3", "9.9", "10.1", "130", "CONFIRMED"),
    ])
    write_bars(label, [
        (CAND, "10", "10", "10", "10", "100", "CONFIRMED"),
        (date(2026, 3, 3), "10", "10.5", "9.9", "10.1", "150", "CONFIRMED"),
        (date(2026, 3, 4), "10", "10.4", "9.9", "10.2", "140", "PROVISIONAL"),
        (date(2026, 3, 5), "10", "10.3", "9.9", "10.1", "130", "CONFIRMED"),
        (date(2026, 3, 6), "10", "10.2", "9.9", "10.1", "120", "CONFIRMED"),
        (date(2026, 3, 9), "10", "10.1", "9.9", "10.0", "110", "CONFIRMED"),
    ])
    quarantine = tmp_path / "quarantine.csv"
    pd.DataFrame(
        [
            {
                "episode_id": eid,
                "symbol": CODE,
                "candidate_date": CAND,
                "conflict_class": "PATTERN_CHANGED",
                "quarantine_reason": "3D_PROVENANCE_CONFLICT:PATTERN_CHANGED",
                "source_forensic_artifact": "x",
            }
            for eid in sorted(mismatch_ids)
        ],
        columns=[
            "episode_id", "symbol", "candidate_date", "conflict_class",
            "quarantine_reason", "source_forensic_artifact",
        ],
    ).to_csv(quarantine, index=False)
    return cases_path, feature, label, quarantine, tmp_path / "out"


def _pin_synthetic_hashes(monkeypatch, feature: Path, label: Path) -> None:
    import hashlib

    monkeypatch.setattr(
        gen, "EXPECTED_FEATURE_SNAPSHOT_SHA256",
        hashlib.sha256(feature.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        gen, "EXPECTED_LABEL_SNAPSHOT_SHA256",
        hashlib.sha256(label.read_bytes()).hexdigest(),
    )


def _run(tmp_path, monkeypatch, mismatch_ids, n_cases=3):
    cases_path, feature, label, quarantine, out = _setup(
        tmp_path, n_cases=n_cases, mismatch_ids=mismatch_ids
    )
    _pin_synthetic_hashes(monkeypatch, feature, label)
    manifest = gen.build_interim_reproducible_package(
        case_set_path=cases_path,
        case_set_expected_sha256=None,
        case_set_expected_row_n=None,
        feature_snapshot_path=feature,
        label_snapshot_path=label,
        quarantine_path=quarantine,
        out_dir=out,
    )
    return manifest, out


def test_quarantine_exact_set_allows_publish(tmp_path, monkeypatch):
    manifest, out = _run(tmp_path, monkeypatch, mismatch_ids={"E:1"})
    assert manifest["reproducible_row_count"] == 2
    assert manifest["quarantine_n"] == 1
    assert manifest["3d_mismatch_before_quarantine_n"] == 1
    assert manifest["3d_mismatch_after_quarantine_n"] == 0
    assert (out / "second_launch_outcome_v01b_reproducible.csv").exists()
    assert (out / "manifest_v01b_reproducible.json").exists()
    df = pd.read_csv(out / "second_launch_outcome_v01b_reproducible.csv")
    assert set(df["episode_id"]) == {"E:2", "E:3"}


def test_quarantine_missing_id_blocks(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="quarantine set != current"):
        _run(tmp_path, monkeypatch, mismatch_ids=set())


def test_quarantine_extra_id_blocks(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="quarantine set != current"):
        _run(tmp_path, monkeypatch, mismatch_ids={"E:1", "E:9"})


def test_reproducible_subset_has_zero_3d_mismatch(tmp_path, monkeypatch):
    manifest, out = _run(tmp_path, monkeypatch, mismatch_ids={"E:1"})
    assert manifest["3d_mismatch_after_quarantine_n"] == 0


def test_frozen_parent_v01b_bytes_unchanged(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, mismatch_ids={"E:1"})
    # The frozen parent case set is read-only; its pinned hash still matches.
    assert gen.sha256_file(gen.CASE_SET_PATH) == gen.CASE_SET_SHA256


def test_blocked_formal_csv_not_created(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, mismatch_ids={"E:1"})
    assert not (tmp_path / "out" / "second_launch_outcome_v01.csv").exists()
    assert not (gen.OUT_DIR / "second_launch_outcome_v01.csv").exists()


def test_snapshot_hash_mismatch_blocks_interim(tmp_path, monkeypatch):
    cases_path, feature, label, quarantine, out = _setup(tmp_path)
    _pin_synthetic_hashes(monkeypatch, feature, label)
    monkeypatch.setattr(gen, "EXPECTED_LABEL_SNAPSHOT_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="label snapshot hash mismatch"):
        gen.build_interim_reproducible_package(
            case_set_path=cases_path,
            case_set_expected_sha256=None,
            case_set_expected_row_n=None,
            feature_snapshot_path=feature,
            label_snapshot_path=label,
            quarantine_path=quarantine,
            out_dir=out,
        )
    assert not (out / "manifest_v01b_reproducible.json").exists()
