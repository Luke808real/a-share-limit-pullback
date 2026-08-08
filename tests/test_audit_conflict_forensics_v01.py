"""Targeted tests for the R1A.2/3 conflict forensics audit (offline, synthetic)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "outcome_v01"))

import build_second_launch_outcome_v01 as gen  # noqa: E402
import audit_conflict_forensics_v01 as aud  # noqa: E402


def bars_df(
    code: str,
    rows: list[tuple[date, str, str, str, str, str, str]],
) -> pd.DataFrame:
    """(trade_date, open, high, low, close, volume, reconciliation_status)."""
    return pd.DataFrame(
        [
            {
                "code": code,
                "trade_date": d,
                "open": float(o),
                "high": float(h),
                "low": float(lo),
                "close": float(c),
                "preclose": float(c),
                "volume": float(v),
                "amount": float(v),
                "turnover_rate": 0.03,
                "pct_change": 0.0,
                "trade_status": True,
                "is_st": False,
                "reconciliation_status": rs,
            }
            for d, o, h, lo, c, v, rs in rows
        ]
    )


def case_df(episode_id: str, code: str, cand: date, s1: str, invalid: str,
            outcome: str, reason: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "episode_id": episode_id,
                "symbol": code,
                "name": "",
                "anchor_date": cand,
                "candidate_date": cand,
                "s1_price": s1,
                "invalid_price": invalid,
                "outcome": outcome,
                "outcome_reason": reason,
                "data_quality": "OK",
                "quality_flags": "[]",
            }
        ]
    )


def test_identical_raw_duplicate_is_deduped():
    df = bars_df("600000", [
        (date(2026, 3, 3), "10", "10.5", "9.8", "10.1", "150", "CONFIRMED"),
        (date(2026, 3, 3), "10", "10.5", "9.8", "10.1", "150", "PROVISIONAL"),
    ])
    deduped, stats = aud.dedupe_raw(df)
    assert stats["raw_duplicate_identical_n"] == 1
    assert stats["raw_duplicate_conflict_n"] == 0
    assert stats["raw_duplicate_conflict_dates"] == []
    assert len(deduped) == 1
    assert not deduped["_raw_version_conflict"].any()


def test_conflicting_raw_duplicate_is_conflict():
    df = bars_df("600000", [
        (date(2026, 3, 3), "10", "10.5", "9.8", "10.1", "150", "CONFIRMED"),
        (date(2026, 3, 3), "10", "10.5", "9.8", "10.05", "150", "PROVISIONAL"),
    ])
    deduped, stats = aud.dedupe_raw(df)
    assert stats["raw_duplicate_conflict_n"] == 1
    assert stats["raw_duplicate_conflict_dates"] == ["600000:2026-03-03"]
    # Conflict records are kept (not silently dropped) and flagged.
    assert len(deduped) == 2
    assert deduped["_raw_version_conflict"].all()


def test_provider_crosscheck_partial_coverage():
    code = "600000"
    cand = date(2026, 3, 2)
    cases = case_df("C:1", code, cand, "10", "9.5", "NO_LAUNCH", "reason")
    conflicts = pd.DataFrame(
        [{"episode_id": "C:1", "symbol": code, "candidate_date": cand}]
    )
    canonical = bars_df(code, [
        (cand, "10", "10", "10", "10", "100", "CONFIRMED"),
        (date(2026, 3, 3), "10", "10.5", "9.8", "10.1", "150", "CONFIRMED"),
        (date(2026, 3, 4), "10", "10.2", "9.9", "10.0", "120", "CONFIRMED"),
        (date(2026, 3, 5), "10", "10.1", "9.9", "10.0", "110", "CONFIRMED"),
    ])
    tushare = bars_df(code, [
        (cand, "10", "10", "10", "10", "100", "CONFIRMED"),
        (date(2026, 3, 3), "10", "10.5", "9.8", "10.1", "150", "CONFIRMED"),
        # 2026-03-04 row missing for tushare
    ])
    akshare = bars_df(code, [
        (cand, "10", "10", "10", "10", "100", "CONFIRMED"),
        (date(2026, 3, 3), "10", "10.5", "9.8", "10.1", "150", "CONFIRMED"),
        (date(2026, 3, 4), "10", "10.2", "9.9", "10.0", "120", "CONFIRMED"),
        (date(2026, 3, 5), "10", "10.1", "9.9", "10.0", "110", "CONFIRMED"),
    ])
    cross = aud.provider_crosscheck(
        conflicts, cases, canonical, tushare, akshare
    )
    assert cross.iloc[0]["provider_agreement_class"] == "CURRENT_CANONICAL_MATCHES_AKSHARE"


def _mismatch_conflict_case():
    """One synthetic conflict: frozen says SUCCESS, bars show invalid first."""
    code = "600000"
    cand = date(2026, 3, 2)
    cases = case_df(
        "C:2", code, cand, "10.5", "9.5",
        "SUCCESS", "S1 first + close>=S1 + volume>=signal-day volume",
    )
    feature = bars_df(code, [
        (cand, "10", "10", "10", "10", "100", "CONFIRMED"),
        (date(2026, 3, 3), "10", "10.2", "9.3", "9.8", "150", "CONFIRMED"),
        (date(2026, 3, 4), "10", "10.5", "9.9", "10.1", "160", "PROVISIONAL"),
        (date(2026, 3, 5), "10", "10.2", "9.9", "10.0", "120", "CONFIRMED"),
    ])
    episodes = pd.DataFrame(
        [
            {
                "episode_id": "C:2",
                "signal_date": cand,
                "pattern_3d": "S1_BEFORE_INVALID",
                "snapshot_id": "snap-2026-07-31-b5f84004de8a",
                "quality_flags": "[]",
            }
        ]
    )
    rows, _ = gen._build_rows(cases, {code: feature}, {code: feature})
    conflicts = aud.build_conflict_rows(cases, episodes, feature, rows)
    return conflicts, feature


def test_invalid_first_event_row_selected_by_real_order():
    """T+1 invalid / T+3 S1 => event row must be the T+1 invalid row."""
    conflicts, feature = _mismatch_conflict_case()
    row = conflicts.iloc[0]
    assert row["conflict_class"] == "PATTERN_CHANGED"
    # S1 exists later (2026-03-04) but the real first event is invalid at T+1.
    assert row["first_s1_touch_date"] == date(2026, 3, 4)
    assert row["first_invalid_touch_date"] == date(2026, 3, 3)
    # Event row follows the real first-event order: the T+1 invalid row.
    assert row["event_row_reconciliation_status"] == "CONFIRMED"


def test_ambiguous_first_event_row():
    code = "600000"
    cand = date(2026, 3, 2)
    cases = case_df(
        "C:3", code, cand, "10", "9.5",
        "SUCCESS", "S1 first + close>=S1 + volume>=signal-day volume",
    )
    feature = bars_df(code, [
        (cand, "10", "10", "10", "10", "100", "CONFIRMED"),
        (date(2026, 3, 3), "10", "10.5", "9.3", "9.8", "150", "PROVISIONAL"),
        (date(2026, 3, 4), "10", "10.2", "9.9", "10.0", "120", "CONFIRMED"),
        (date(2026, 3, 5), "10", "10.1", "9.9", "10.0", "110", "CONFIRMED"),
    ])
    episodes = pd.DataFrame(
        [
            {
                "episode_id": "C:3",
                "signal_date": cand,
                "pattern_3d": "S1_BEFORE_INVALID",
                "snapshot_id": "snap-2026-07-31-b5f84004de8a",
                "quality_flags": "[]",
            }
        ]
    )
    rows, _ = gen._build_rows(cases, {code: feature}, {code: feature})
    conflicts = aud.build_conflict_rows(cases, episodes, feature, rows)
    row = conflicts.iloc[0]
    # Same bar (T+1) touches both S1 and invalid -> AMBIGUOUS first event.
    assert row["first_s1_touch_date"] == date(2026, 3, 3)
    assert row["first_invalid_touch_date"] == date(2026, 3, 3)
    assert row["event_row_reconciliation_status"] == "PROVISIONAL"


def test_row_policy_role_exposure_and_unique_counts():
    code = "600000"
    cand = date(2026, 3, 2)
    cases = pd.concat(
        [
            case_df("R:1", code, cand, "10", "9.5", "NO_LAUNCH", "r1"),
            case_df("R:2", "600001", date(2026, 4, 1), "10", "9.5", "NO_LAUNCH", "r2"),
        ],
        ignore_index=True,
    )
    feature = pd.concat(
        [
            bars_df(code, [
                (cand, "10", "10", "10", "10", "100", "CONFIRMED"),
                (date(2026, 3, 3), "10", "10.2", "9.8", "10.0", "150", "PROVISIONAL"),
                (date(2026, 3, 4), "10", "10.2", "9.8", "10.0", "120", "CONFIRMED"),
            ]),
            bars_df("600001", [
                (date(2026, 4, 1), "10", "10", "10", "10", "100", "CONFIRMED"),
                (date(2026, 4, 2), "10", "10.2", "9.8", "10.0", "150", "CONFIRMED"),
            ]),
        ],
        ignore_index=True,
    )
    label = bars_df(code, [
        (cand, "10", "10", "10", "10", "100", "PROVISIONAL"),
        (date(2026, 3, 3), "10", "10.2", "9.8", "10.0", "150", "CONFIRMED"),
        (date(2026, 3, 4), "10", "10.2", "9.8", "10.0", "120", "CONFIRMED"),
        (date(2026, 3, 5), "10", "10.2", "9.8", "10.0", "110", "CONFIRMED"),
        (date(2026, 3, 6), "10", "10.2", "9.8", "10.0", "100", "CONFIRMED"),
        (date(2026, 3, 9), "10", "10.2", "9.8", "10.0", "90", "CONFIRMED"),
    ])
    policy = aud.row_policy_audit(cases, feature, label, conflict_ids=set())
    exposure = policy["row_role_exposure"]
    unique = policy["unique_case_date_snapshot"]
    # R:1 feature: candidate CONFIRMED + 03-03 PROVISIONAL + 03-04 CONFIRMED (3)
    # R:1 label: 5 rows: candidate(03-02 PROVISIONAL) + 03-03 CONFIRMED + 03-04 CONFIRMED + 03-05 + 03-06 (5)
    # R:2 feature: candidate CONFIRMED + 04-02 CONFIRMED (2)  [3D window = 1 row]
    # R:1 feature roles: cand CONFIRMED + 03-03 PROVISIONAL + 03-04 CONFIRMED (C2/P1)
    # R:1 label roles (strictly after cand): 03-03..03-09 CONFIRMED (C5/P0)
    # R:2 feature roles: cand CONFIRMED + 04-02 CONFIRMED (C2/P0)
    assert exposure["confirmed_n"] == 9
    assert exposure["provisional_n"] == 1
    # Unique (case, date, snapshot): 03-02 appears under FEATURE and LABEL as
    # distinct triples; 03-03 and 03-04 likewise appear under both snapshots.
    assert unique["confirmed_n"] == exposure["confirmed_n"]
    assert unique["provisional_n"] == exposure["provisional_n"]


def test_unique_case_date_snapshot_counting():
    """Same (case, date) under feature-3D and label-5D are distinct triples."""
    code = "600000"
    cand = date(2026, 3, 2)
    cases = case_df("U:1", code, cand, "11", "9.0", "NO_LAUNCH", "r")
    feature = bars_df(code, [
        (cand, "10", "10", "10", "10", "100", "CONFIRMED"),
        # 03-03 appears in BOTH the feature-3D window and the label-5D window.
        (date(2026, 3, 3), "10", "10.2", "9.8", "10.0", "150", "CONFIRMED"),
        (date(2026, 3, 4), "10", "10.2", "9.8", "10.0", "120", "PROVISIONAL"),
    ])
    label = bars_df(code, [
        (cand, "10", "10", "10", "10", "100", "CONFIRMED"),
        (date(2026, 3, 3), "10", "10.2", "9.8", "10.0", "150", "PROVISIONAL"),
        (date(2026, 3, 4), "10", "10.2", "9.8", "10.0", "120", "CONFIRMED"),
        (date(2026, 3, 5), "10", "10.2", "9.8", "10.0", "110", "CONFIRMED"),
        (date(2026, 3, 6), "10", "10.2", "9.8", "10.0", "100", "CONFIRMED"),
        (date(2026, 3, 9), "10", "10.2", "9.8", "10.0", "90", "CONFIRMED"),
    ])
    policy = aud.row_policy_audit(cases, feature, label, conflict_ids=set())
    exposure = policy["row_role_exposure"]
    unique = policy["unique_case_date_snapshot"]
    # Role exposure: cand C1 + f3d (03-03 C, 03-04 P) + l5d (03-03 P, 03-04..03-09 C4)
    #   = confirmed 1+1+4=6, provisional 1+1=2
    assert exposure["confirmed_n"] == 6
    assert exposure["provisional_n"] == 2
    # Unique (case, date, snapshot) triples: 03-03 (FEATURE, C) and
    # 03-03 (LABEL, P) are two distinct triples -> counts unchanged.
    assert unique["confirmed_n"] == exposure["confirmed_n"]
    assert unique["provisional_n"] == exposure["provisional_n"]
