"""T0 complete registry V01 — targeted tests (anchor-only extractor).

Covers: candidate->valid anchor, one-word reject, T-word reject,
consecutive-board reject, setup_id determinism, CONFIRMED filter,
warmup-not-in-cohort, duplicate fail-closed, population accounting identity,
parity gate wiring.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "factor-lab"))

import t0_registry_v01 as m  # noqa: E402
from limit_pullback.config import load_strategy_config  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_strategy_config(ROOT / "config/strategy.yaml")


def _bar(code: str, d: str, close: str, preclose: str, high: str | None = None,
         vol: str = "1000000", amount: str = "10000000", is_st: bool = False) -> dict:
    c = Decimal(close)
    p = Decimal(preclose)
    return {
        "trade_date": date.fromisoformat(d),
        "code": code,
        "open": p,
        "high": Decimal(high) if high is not None else c,
        "low": min(c, p),
        "close": c,
        "preclose": p,
        "volume": Decimal(vol),
        "amount": Decimal(amount),
        "turnover_rate": None,
        "pct_change": None,
        "trade_status": True,
        "is_st": is_st,
        "reconciliation_status": "CONFIRMED",
        "source": "TEST",
        "fetched_at": None,
    }


def _limit_up(code: str, d: str, prev_close: str) -> dict:
    """A 10% limit-up bar: close == theoretical limit price."""
    p = Decimal(prev_close)
    limit = (p * Decimal("1.10")).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
    return _bar(code, d, str(limit), prev_close, high=str(limit))


def _bars_from(rows: list[dict]) -> tuple:
    from limit_pullback.outcome import _daily_bar
    return tuple(_daily_bar(r) for r in rows)


def _config_for(module_config=CONFIG) -> object:
    return module_config


# ---------- 1. candidate -> valid anchor ----------

def test_valid_first_board_anchor_emitted() -> None:
    rows = []
    d = date(2026, 1, 5)
    # 5 normal days then one limit-up
    for i in range(5):
        prev = Decimal("10.0")
        rows.append(_bar("000001", f"2026-01-0{i+1}", "10.0", "10.0"))
    rows.append(_limit_up("000001", "2026-01-08", "10.0"))
    bars = _bars_from(rows)
    out = m.anchor_only_scan_code(bars, (), _config_for())
    assert len(out) == 1
    r = out[0]
    assert r["anchor_date"] == "2026-01-08"
    assert r["code"] == "000001"
    assert r["is_first_board"] is True
    assert r["setup_id"].startswith("000001:20260108:")


# ---------- 2. one-word reject ----------

def test_one_word_limit_rejected() -> None:
    """一字板：open == high == low == close == limit price."""
    rows = []
    for i in range(5):
        rows.append(_bar("000001", f"2026-01-0{i+1}", "10.0", "10.0"))
    p = Decimal("10.0")
    limit = (p * Decimal("1.10")).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
    # all OHLC at limit -> one-word
    rows.append(_bar("000001", "2026-01-08", str(limit), "10.0", high=str(limit)))
    rows[-1]["open"] = limit
    rows[-1]["low"] = limit
    bars = _bars_from(rows)
    out = m.anchor_only_scan_code(bars, (), _config_for())
    assert out == []


# ---------- 3. T-word reject ----------

def test_t_word_limit_rejected() -> None:
    """T 字板：open == high == close == limit, low < limit."""
    rows = []
    for i in range(5):
        rows.append(_bar("000001", f"2026-01-0{i+1}", "10.0", "10.0"))
    p = Decimal("10.0")
    limit = (p * Decimal("1.10")).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
    rows.append(_bar("000001", "2026-01-08", str(limit), "10.0", high=str(limit)))
    rows[-1]["open"] = limit
    rows[-1]["low"] = p  # low < limit -> T shape
    bars = _bars_from(rows)
    out = m.anchor_only_scan_code(bars, (), _config_for())
    assert out == []


# ---------- 4. consecutive-board reject ----------

def test_consecutive_board_rejected() -> None:
    rows = []
    for i in range(5):
        rows.append(_bar("000001", f"2026-01-0{i+1}", "10.0", "10.0"))
    rows.append(_limit_up("000001", "2026-01-08", "10.0"))    # first board
    rows.append(_limit_up("000001", "2026-01-09", "11.0"))    # second consecutive board
    bars = _bars_from(rows)
    out = m.anchor_only_scan_code(bars, (), _config_for())
    assert len(out) == 1  # only the first board is a valid anchor
    assert out[0]["anchor_date"] == "2026-01-08"


# ---------- 5. setup_id determinism ----------

def test_setup_id_deterministic() -> None:
    rows = []
    for i in range(5):
        rows.append(_bar("000001", f"2026-01-0{i+1}", "10.0", "10.0"))
    rows.append(_limit_up("000001", "2026-01-08", "10.0"))
    bars = _bars_from(rows)
    a = m.anchor_only_scan_code(bars, (), _config_for())[0]
    b = m.anchor_only_scan_code(bars, (), _config_for())[0]
    assert a["setup_id"] == b["setup_id"]
    # setup_id = code:anchor_date:price_ticks (ROUND_HALF_UP)
    from limit_pullback.strategy.engine import make_setup_id
    expected = make_setup_id("000001", date(2026, 1, 8), Decimal("11.00"), CONFIG.anchor.price_tick)
    assert a["setup_id"] == expected


# ---------- 6. CONFIRMED filter ----------

def test_confirmed_filter_in_load_daily(tmp_path: Path) -> None:
    """load_daily must reject a DataFrame bypass and use SHA gate; the actual
    CONFIRMED filter is enforced by _iter_confirmed_code_bars (frozen)."""
    with pytest.raises(TypeError, match="DataFrame bypass forbidden"):
        m.load_daily(pd.DataFrame())  # type: ignore[arg-type]


# ---------- 7. warmup not in cohort ----------

def test_warmup_not_in_cohort() -> None:
    rows = []
    for i in range(5):
        rows.append(_bar("000001", f"2025-12-2{i}", "10.0", "10.0"))
    rows.append(_limit_up("000001", "2025-12-31", "10.0"))  # anchor BEFORE cohort start
    # normal bars between so 2026-01-08 is a fresh first board
    for d in ("2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"):
        rows.append(_bar("000001", d, "10.0", "10.0"))
    rows.append(_limit_up("000001", "2026-01-08", "10.0"))  # anchor inside cohort
    bars = _bars_from(rows)
    out = m.anchor_only_scan_code(
        bars, (), _config_for(),
        cohort_start=date(2026, 1, 1), cohort_end=date(2026, 7, 31),
    )
    assert len(out) == 1
    assert out[0]["anchor_date"] == "2026-01-08"


# ---------- 8. duplicate fail-closed ----------

def test_registry_duplicate_fail_closed() -> None:
    rows = [
        {"setup_id": "000001:20260108:1100", "code": "000001", "anchor_date": "2026-01-08"},
        {"setup_id": "000001:20260108:1100", "code": "000001", "anchor_date": "2026-01-08"},
    ]
    with pytest.raises(RuntimeError, match="REGISTRY_DUPLICATE_SETUP_ID_N"):
        m.population_accounting(rows, pd.DataFrame())


def test_registry_conflict_fail_closed() -> None:
    rows = [
        {"setup_id": "000001:20260108:1100", "code": "000001", "anchor_date": "2026-01-08"},
        {"setup_id": "000001:20260108:9999", "code": "000001", "anchor_date": "2026-01-08"},
    ]
    with pytest.raises(RuntimeError, match="REGISTRY_CODE_ANCHOR_CONFLICT_N"):
        m.population_accounting(rows, pd.DataFrame())


# ---------- 9. population accounting identity ----------

def test_population_accounting_identity() -> None:
    rows = [
        {"setup_id": "000001:20260108:1100", "code": "000001", "anchor_date": "2026-01-08"},
        {"setup_id": "000001:20260201:1100", "code": "000001", "anchor_date": "2026-02-01"},
    ]
    ep = pd.DataFrame([
        {"setup_id": "000001:20260108:1100", "anchor_date": "2026-01-08", "outcome": "WIN_S1"},
        {"setup_id": "000001:20260201:1100", "anchor_date": "2026-02-01", "outcome": "NO_FILL"},
    ])
    acct = m.population_accounting(rows, ep)
    assert acct["TOTAL_T0_SETUP_N"] == 2
    assert acct["OBSERVED_SIGNAL_SETUP_N"] == 2
    assert acct["NEVER_SIGNAL_SETUP_N"] == 0
    assert acct["EPISODE_SETUP_NOT_IN_REGISTRY_N"] == 0


def test_population_accounting_never_signal() -> None:
    rows = [
        {"setup_id": "000001:20260108:1100", "code": "000001", "anchor_date": "2026-01-08"},
        {"setup_id": "000001:20260201:1100", "code": "000001", "anchor_date": "2026-02-01"},
    ]
    ep = pd.DataFrame([
        {"setup_id": "000001:20260108:1100", "anchor_date": "2026-01-08", "outcome": "WIN_S1"},
    ])
    acct = m.population_accounting(rows, ep)
    assert acct["TOTAL_T0_SETUP_N"] == 2
    assert acct["OBSERVED_SIGNAL_SETUP_N"] == 1
    assert acct["NEVER_SIGNAL_SETUP_N"] == 1


def test_population_accounting_episode_not_in_registry_fails() -> None:
    rows = [
        {"setup_id": "000001:20260108:1100", "code": "000001", "anchor_date": "2026-01-08"},
    ]
    ep = pd.DataFrame([
        {"setup_id": "000001:20260108:1100", "anchor_date": "2026-01-08", "outcome": "WIN_S1"},
        {"setup_id": "999999:20260201:1100", "anchor_date": "2026-02-01", "outcome": "NO_FILL"},
    ])
    with pytest.raises(RuntimeError, match="EPISODE_SETUP_NOT_IN_REGISTRY_N"):
        m.population_accounting(rows, ep)


# ---------- 10. parity gate wiring ----------

def test_parity_gate_synthetic() -> None:
    """On synthetic bars, anchor-only and frozen strategy LIMIT_ANCHOR must
    agree (both emitted for the first board; none for one-word / consecutive)."""
    rows = []
    for i in range(5):
        rows.append(_bar("000001", f"2026-01-0{i+1}", "10.0", "10.0"))
    rows.append(_limit_up("000001", "2026-01-08", "10.0"))
    bars = _bars_from(rows)
    anchor = {r["setup_id"] for r in m.anchor_only_scan_code(bars, (), _config_for())}
    strategy = m.frozen_strategy_t0_set(bars, (), _config_for())
    assert anchor == strategy
    assert len(anchor) == 1
