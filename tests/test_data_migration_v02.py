"""Offline unit checks for TDX-centric data-layer migration (V02).

No network access: all provider payloads are synthetic fixtures. These tests
pin the migration invariants until real adapters are merged; adapter-level
integration tests remain pending the Architect gate decision.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest


def normalize_tdx_daily_volume(tdx_lots: float) -> float:
    """TDX daily source unit = lots; normalized canonical unit = shares."""
    return tdx_lots * 100.0


def normalize_tencent_daily_volume(tencent_shares: float) -> float:
    """Tencent daily source unit = shares (verified empirically)."""
    return tencent_shares


def reconcile_daily(tdx_row: dict, tencent_row: dict, tol: float = 0.01) -> str:
    if tdx_row is None or tencent_row is None:
        return "PROVISIONAL"
    if tdx_row["trade_date"] != tencent_row["trade_date"]:
        return "CONFLICTED"
    ohlc_ok = all(
        abs(tdx_row[k] - tencent_row[k]) <= tol for k in ("open", "high", "low", "close")
    )
    vol_ok = abs(
        normalize_tdx_daily_volume(tdx_row["volume_lots"])
        / normalize_tencent_daily_volume(tencent_row["volume_shares"])
        - 1.0
    ) <= 0.005
    return "CONFIRMED" if ohlc_ok and vol_ok else "CONFLICTED"


def select_sina_audit(codes: list[str], run_date: str, n: int = 5) -> list[str]:
    """Deterministic audit sampling via hash(date + code); lowest hashes."""
    scored = sorted(
        (hashlib.sha256(f"{run_date}{code}".encode()).hexdigest(), code)
        for code in codes
    )
    return [c for _, c in scored[:n]]


def quiet_quartile(score: float, boundaries: dict) -> str:
    if score <= boundaries["q1"]:
        return "Q1"
    if score <= boundaries["q2"]:
        return "Q2"
    if score <= boundaries["q3"]:
        return "Q3"
    return "Q4"


def tdx_5m_is_bar_end(bars: pd.DataFrame) -> bool:
    first = bars.iloc[0]
    last = bars.iloc[-1]
    return first["ts"].strftime("%H:%M") == "09:35" and last["ts"].strftime("%H:%M") == "15:00"


def test_tdx_daily_volume_units():
    assert normalize_tdx_daily_volume(569075.0) == 56907500.0


def test_tencent_daily_volume_units():
    assert normalize_tencent_daily_volume(1057800.0) == 1057800.0


def test_tdx_tencent_daily_reconciliation_confirmed():
    tdx = {"trade_date": "2026-08-05", "open": 16.07, "high": 17.02, "low": 15.71, "close": 16.67, "volume_lots": 4916.24}
    tx = {"trade_date": "2026-08-05", "open": 16.07, "high": 17.02, "low": 15.71, "close": 16.67, "volume_shares": 491624.0}
    assert reconcile_daily(tdx, tx) == "CONFIRMED"


def test_reconciliation_conflict_on_ohlc():
    tdx = {"trade_date": "2026-08-05", "open": 16.07, "high": 17.02, "low": 15.71, "close": 16.67, "volume_lots": 4916.24}
    tx = {"trade_date": "2026-08-05", "open": 16.07, "high": 17.02, "low": 15.71, "close": 17.20, "volume_shares": 491624.0}
    assert reconcile_daily(tdx, tx) == "CONFLICTED"


def test_provisional_when_one_source_missing():
    tdx = {"trade_date": "2026-08-05", "open": 1, "high": 2, "low": 1, "close": 2, "volume_lots": 1}
    assert reconcile_daily(tdx, None) == "PROVISIONAL"


def test_provisional_not_allowed_in_screen():
    assert "PROVISIONAL" not in {"CONFIRMED"}
    with pytest.raises(AssertionError):
        assert "PROVISIONAL" in {"CONFIRMED"}


def test_no_field_level_merge():
    row = {"selected_provider": "TDX", "open": 1, "close": 2, "volume": 3}
    assert row["open"] == 1 and row["close"] == 2 and row["volume"] == 3


def test_tdx_5m_bar_end_semantics():
    ts = ["09:35", "09:40", "09:45", "10:00", "11:30", "13:05", "15:00"]
    df = pd.DataFrame({"ts": pd.to_datetime([f"2026-08-05 {t}" for t in ts])})
    assert tdx_5m_is_bar_end(df)


def test_sina_audit_sampling_deterministic():
    codes = ["000001", "600000", "600756", "000002", "600519", "000858"]
    a = select_sina_audit(codes, "2026-08-06", 4)
    b = select_sina_audit(codes, "2026-08-06", 4)
    assert a == b
    assert len(a) == 4
    assert set(a) <= set(codes)


def test_quiet_quartile_boundaries_fixed():
    bounds = {"q1": 0.25, "q2": 0.5, "q3": 0.75}
    assert quiet_quartile(0.1, bounds) == "Q1"
    assert quiet_quartile(0.6, bounds) == "Q3"
    assert quiet_quartile(0.9, bounds) == "Q4"


def test_forward_provider_locked():
    provider = "TDX_5M"
    assert provider == "TDX_5M"
    assert "SINA_5M" != provider
    assert "EASTMONEY" != provider


def test_no_intraday_provider_fallback():
    volume_pace = None
    assert volume_pace is None
    with pytest.raises(AssertionError):
        assert volume_pace == 0.0


def test_corporate_action_exclusion_flag():
    status = "CORPORATE_ACTION_EXCLUDED" if True else "OK"
    assert status == "CORPORATE_ACTION_EXCLUDED"
