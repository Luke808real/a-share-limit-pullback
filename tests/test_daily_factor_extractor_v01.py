"""R2A extractor tests: formulas, PIT, registry, session indexing (offline)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import extract_daily_factors_v01 as ext  # noqa: E402


def make_bars(
    code: str,
    rows: list[tuple[date, float, float, float, float, float, float]],
) -> pd.DataFrame:
    """(trade_date, open, high, low, close, volume, preclose)."""
    return pd.DataFrame(
        [
            {
                "code": code,
                "trade_date": d,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "preclose": pc,
                "volume": v,
                "amount": v,
                "turnover_rate": 0.03,
                "pct_change": 0.0,
                "trade_status": True,
                "is_st": False,
            }
            for d, o, h, lo, c, v, pc in rows
        ]
    )


def dates(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        out.append(d)
        d += timedelta(days=1)
    return out


def make_case(symbol: str = "600000", t0: date = date(2026, 3, 2), d: date = date(2026, 3, 6)) -> ext.FactorCaseContext:
    return ext.FactorCaseContext(
        episode_id="E:1",
        symbol=symbol,
        name="",
        anchor_date=t0,
        candidate_date=d,
        s1_price="10",
        invalid_price="9",
        data_quality="OK",
        quality_flags="[]",
        candidate_reconciliation_status="CONFIRMED",
        feature_3d_has_provisional=False,
        label_5d_has_provisional=False,
    )


def ctx_for(
    bars: pd.DataFrame,
    *,
    i0: int,
    iD: int,
    adj: dict[date, Decimal] | None = None,
) -> ext.FactorContext:
    case = make_case(symbol=bars.iloc[0]["code"], t0=bars.iloc[i0]["trade_date"], d=bars.iloc[iD]["trade_date"])
    if adj is None:
        adj = {d: Decimal("1.0") for d in bars["trade_date"]}
    return ext.FactorContext(
        case=case,
        bars=bars,
        i0=i0,
        iD=iD,
        adj={case.symbol: adj or {}},
    )


def value(res: ext.FactorResult):
    return float(res.value) if res.value is not None else None


def test_registry_contract_exact_match():
    contract = ext.load_contract()
    names = ext.validate_registry_against_contract(contract)
    assert len(names) == 25
    assert list(ext.FACTOR_REGISTRY) == list(contract["factor_name"])


def test_contract_sha_mismatch_blocks(monkeypatch):
    monkeypatch.setattr(ext, "EXPECTED_CONTRACT_CSV_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="contract CSV hash mismatch"):
        ext.load_contract()


def test_feature_snapshot_mismatch_blocks(monkeypatch):
    monkeypatch.setattr(ext, "EXPECTED_FEATURE_SNAPSHOT_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="feature snapshot hash mismatch"):
        ext.run_input_gate()


def test_outcome_columns_not_loaded_into_context():
    assert not (set(ext.FORBIDDEN_CASE_COLUMNS) & set(ext.CASE_USECOLS))
    fields = set(ext.FactorCaseContext.__dataclass_fields__)
    assert not (fields & set(ext.FORBIDDEN_CASE_COLUMNS))


def test_mutating_future_outcome_fields_does_not_change_factors(tmp_path):
    code = "600000"
    ds = dates(date(2026, 3, 2), 10)
    rows = []
    for i, d in enumerate(ds):
        rows.append((d, 10.0 + i, 11.0 + i, 9.0 + i, 10.5 + i, 1000.0 + i, 10.0 + i))
    bars = make_bars(code, rows)
    case = make_case(symbol=code, t0=ds[1], d=ds[6])
    base = {
        "episode_id": "E:1", "symbol": code, "name": "", "anchor_date": ds[1],
        "candidate_date": ds[6], "s1_price": "10", "invalid_price": "9",
        "data_quality": "OK", "quality_flags": "[]",
        "candidate_reconciliation_status": "CONFIRMED",
        "feature_3d_has_provisional": False, "label_5d_has_provisional": False,
        "outcome_3d": "SUCCESS", "outcome_5d": "FAILED_BREAKOUT",
        "time_to_s1_10d": 1, "first_event_date_10d": ds[7],
    }
    csv_path = tmp_path / "cases.csv"
    pd.DataFrame([base]).to_csv(csv_path, index=False)
    c1 = ext.load_cases(csv_path)[0]
    f1 = ext.extract_to_frame(
        [c1], bars_by_code={code: bars}, adj={code: {}}
    )
    base["outcome_3d"] = "STRUCTURE_FAIL"
    base["outcome_5d"] = "NO_LAUNCH"
    base["time_to_s1_10d"] = 99
    base["first_event_date_10d"] = ds[9]
    pd.DataFrame([base]).to_csv(csv_path, index=False)
    c2 = ext.load_cases(csv_path)[0]
    f2 = ext.extract_to_frame([c2], bars_by_code={code: bars}, adj={code: {}})
    factor_cols = [c for c in f1.columns if c not in ext.STRATIFICATION_COLUMNS]
    pd.testing.assert_frame_equal(
        f1[factor_cols], f2[factor_cols], check_exact=False
    )


def test_t0_d_session_off_by_one():
    ds = dates(date(2026, 3, 2), 6)
    bars = make_bars("600000", [(d, 10, 11, 9, 10.5, 100, 10) for d in ds])
    ctx = ctx_for(bars, i0=0, iD=4)
    assert ext.f_days_since_t0(ctx).value == 4


def test_suspension_gap_is_not_zero_volume_session():
    ds = dates(date(2026, 3, 2), 8)
    ds_with_gap = [ds[0], ds[1], ds[2], ds[4], ds[5], ds[6]]  # ds[3] suspended
    bars = make_bars("600000", [(d, 10, 11, 9, 10.5, 100, 10) for d in ds_with_gap])
    i0 = 0
    iD = len(ds_with_gap) - 1
    ctx = ctx_for(bars, i0=i0, iD=iD)
    assert ext.f_days_since_t0(ctx).value == iD - i0  # sessions, not calendar days
    pb = ext.pullback_asof_d(bars, i0, iD)
    assert len(pb) == iD  # suspended day never materializes as a zero-volume row
    assert (pb["volume"] > 0).all()


def test_t0_position_20d_window():
    ds = dates(date(2026, 1, 5), 25)
    rows = []
    for i, d in enumerate(ds):
        lo = 1.0 if i == 1 else (2.0 + i * 0.1)
        hi = 10.0 if i == 20 else (3.0 + i * 0.1)
        rows.append((d, 5.0, hi, lo, 5.0, 100.0, 5.0))
    rows[20] = (ds[20], 5.0, 10.0, 2.0, 5.0, 100.0, 5.0)
    rows[0] = (ds[0], 5.0, 30.0, 0.5, 5.0, 100.0, 5.0)  # outside window (must be excluded)
    bars = make_bars("600000", rows)
    ctx = ctx_for(bars, i0=20, iD=24)
    res = ext.f_t0_position_20d(ctx)
    # window = sessions 1..20: min_low = 1.0 (idx1), max_high = 10.0 (idx20), C0 = 5.0
    assert value(res) == pytest.approx((5.0 - 1.0) / (10.0 - 1.0))


def test_pre_t0_return_5d_intervals():
    ds = dates(date(2026, 2, 2), 8)
    closes = [2.0, 3.0, 4.0, 5.0, 6.0, 6.0, 9.0, 10.0]
    bars = make_bars("600000", [(d, 10, 11, 9, closes[i], 100, 10) for i, d in enumerate(ds)])
    ctx = ctx_for(bars, i0=6, iD=7)
    res = ext.f_pre_t0_return_5d(ctx)
    # close(T0-1)=9, close(T0-6)=3 -> 9/3-1 = 2.0 (NOT close(T0-5)=6)
    assert value(res) == pytest.approx(2.0)


def test_pre_t0_return_20d_intervals():
    ds = dates(date(2026, 1, 2), 23)
    closes = [1.0] + [2.0] * 20 + [3.0, 4.0]
    bars = make_bars("600000", [(d, 10, 11, 9, closes[i], 100, 10) for i, d in enumerate(ds)])
    ctx = ctx_for(bars, i0=21, iD=22)
    res = ext.f_pre_t0_return_20d(ctx)
    # close(T0-1)=close(20)=2.0, close(T0-21)=close(0)=1.0
    assert value(res) == pytest.approx(2.0 / 1.0 - 1.0)


def test_t0_volume_ratio_excludes_t0():
    ds = dates(date(2026, 2, 2), 7)
    vols = [10.0, 10.0, 10.0, 10.0, 10.0, 100.0, 10.0]
    bars = make_bars("600000", [(d, 10, 11, 9, 10.5, vols[i], 10) for i, d in enumerate(ds)])
    ctx = ctx_for(bars, i0=5, iD=6)
    res = ext.f_t0_volume_ratio_5d(ctx)
    assert value(res) == pytest.approx(100.0 / 10.0)  # T0 (100) excluded from mean


def test_max_drawdown_excludes_current_day_high():
    ds = dates(date(2026, 3, 2), 4)
    rows = [
        (ds[0], 10, 10, 9.5, 10, 100, 10),   # T0 high=10
        (ds[1], 10, 11, 9.0, 10, 100, 10),   # PB s1: high 11, low 9
        (ds[2], 10, 12, 7.0, 10, 100, 10),   # PB s2: high 12, low 7
        (ds[3], 10, 10, 9.5, 10, 100, 10),   # D: prior_peak=12 -> 9.5/12-1
    ]
    bars = make_bars("600000", rows)
    ctx = ctx_for(bars, i0=0, iD=3)
    res = ext.f_max_drawdown(ctx)
    # s2 prior_peak = max(10, 11) = 11 (NOT 12): dd2 = 7/11-1; D dd = 9.5/12-1
    assert value(res) == pytest.approx(7.0 / 11.0 - 1.0)


def test_impulse_retention_identity():
    ds = dates(date(2026, 3, 2), 4)
    rows = [
        (ds[0], 10, 11, 9.5, 10.8, 100, 10),
        (ds[1], 10, 10.5, 9.2, 9.5, 100, 10),
        (ds[2], 10, 10.2, 9.4, 9.8, 100, 10),
        (ds[3], 10, 10.6, 9.8, 10.4, 100, 10),
    ]
    bars = make_bars("600000", rows)
    ctx = ctx_for(bars, i0=0, iD=3)
    imp = ext.f_impulse_retrace_ratio(ctx)
    ret = ext.f_t0_gain_retention(ctx)
    assert imp.value is not None and ret.value is not None
    assert abs(float(imp.value) + float(ret.value) - 1.0) <= 1e-12


def test_days_above_t0_mid_is_close_based():
    ds = dates(date(2026, 3, 2), 3)
    # T0 body mid = (10+11)/2 = 10.5
    rows = [
        (ds[0], 10, 11, 9.5, 11, 100, 10),
        (ds[1], 10, 10.8, 10.6, 10.4, 100, 10),  # low>=mid but close<mid
        (ds[2], 10, 10.9, 10.2, 10.2, 100, 10),  # D
    ]
    bars = make_bars("600000", rows)
    ctx = ctx_for(bars, i0=0, iD=2)
    res = ext.f_days_above_t0_mid(ctx)
    assert res.value == 0  # close-based: neither PB close >= 10.5


def test_volume_slope_min_sessions_and_positive_volume():
    ds = dates(date(2026, 3, 2), 3)
    rows = [(ds[0], 10, 11, 9, 10.5, 100, 10), (ds[1], 10, 11, 9, 10.5, 50, 10), (ds[2], 10, 11, 9, 10.5, 50, 10)]
    bars = make_bars("600000", rows)
    ctx1 = ctx_for(bars, i0=0, iD=1)  # only 1 PB session
    assert ext.f_volume_slope(ctx1).missing_reason == ext.INSUFFICIENT_PULLBACK_SESSIONS
    ctx2 = ctx_for(bars, i0=0, iD=2)  # 2 PB sessions, vol>0
    res = ext.f_volume_slope(ctx2)
    assert res.value is not None
    rows_bad = [(ds[0], 10, 11, 9, 10.5, 100, 10), (ds[1], 10, 11, 9, 10.5, 0, 10), (ds[2], 10, 11, 9, 10.5, 50, 10)]
    ctx3 = ctx_for(make_bars("600000", rows_bad), i0=0, iD=2)
    assert ext.f_volume_slope(ctx3).missing_reason == ext.NONPOSITIVE_VOLUME


def test_quiet_days_exact_lt_one_thresholds():
    ds = dates(date(2026, 3, 2), 4)
    rows = [
        (ds[0], 10, 11, 9, 10.5, 100, 10),   # T0: range=(11-9)/10=0.2
        (ds[1], 10, 11, 9.5, 10.5, 100, 10),  # vol ratio 1.0 (not <1) -> not quiet
        (ds[2], 10, 10.6, 9.9, 10.5, 50, 10), # vol 0.5, range 0.07/0.2<1 -> quiet
        (ds[3], 10, 11, 9, 10.5, 60, 10),     # D
    ]
    bars = make_bars("600000", rows)
    ctx = ctx_for(bars, i0=0, iD=3)
    res = ext.f_quiet_days_n(ctx)
    assert res.value == 1  # exact boundary ratio 1.0 is NOT quiet


def test_days_to_pullback_low_first_occurrence():
    ds = dates(date(2026, 3, 2), 5)
    lows = [10.0, 9.0, 8.0, 8.0, 9.0]
    rows = [(ds[i], 10, 11, lows[i], 10.5, 100, 10) for i in range(5)]
    bars = make_bars("600000", rows)
    ctx = ctx_for(bars, i0=0, iD=4)
    res = ext.f_days_to_pullback_low(ctx)
    assert res.value == 2  # first offset of min LOW (offset 1-based from T0+1)


@pytest.mark.parametrize(
    "label,rows,expected",
    [
        ("t0_peak", None, 4),
        ("t2_new_high", None, 3),
        ("t3_tie", None, 2),
        ("d_t1", None, 1),
    ],
)
def test_pullback_duration_frozen_examples(label, rows, expected):
    ds = dates(date(2026, 3, 2), 7)
    if label == "t0_peak":
        highs = [10.0, 9.0, 9.5, 9.0, 9.2, 9.0, 9.1]  # T0 peak; D=T+4
        iD = 4
    elif label == "t2_new_high":
        highs = [10.0, 9.0, 11.0, 9.5, 9.6, 9.4]  # T+2 new high; D=T+5
        iD = 5
    elif label == "t3_tie":
        highs = [10.0, 9.0, 9.5, 10.0, 9.6, 9.4]  # T+3 ties T0 high; D=T+5
        iD = 5
    else:  # d_t1
        highs = [9.0, 10.0, 9.5]  # [predecessor, T0 peak, D]; D=T+1, empty PRE_D
        iD = 2
    rows = [(ds[i], 10, highs[i], 9, 10.5, 100, 10) for i in range(len(highs))]
    bars = make_bars("600000", rows)
    i0 = 1 if label == "d_t1" else 0
    ctx = ctx_for(bars, i0=i0, iD=iD)
    res = ext.f_pullback_duration(ctx)
    assert res.value == expected


def test_f6_reference_excludes_d():
    ds = dates(date(2026, 3, 2), 5)
    rows = [
        (ds[0], 10, 10, 9, 10, 100, 10),
        (ds[1], 10, 10.5, 9.5, 10.2, 100, 10),
        (ds[2], 10, 10.3, 9.6, 10.1, 100, 10),
        (ds[3], 10, 10.4, 9.7, 10.3, 100, 10),
        (ds[4], 10, 50.0, 9.8, 49.0, 100, 10),  # D huge high/close
    ]
    bars = make_bars("600000", rows)
    ctx = ctx_for(bars, i0=0, iD=4)
    res = ext.f_close_vs_pullback_high(ctx)
    # reference = max(10.5, 10.3, 10.4) = 10.5; D close 49
    assert value(res) == pytest.approx(49.0 / 10.5 - 1.0)


def test_f6_empty_pre_d():
    ds = dates(date(2026, 3, 2), 2)
    rows = [(ds[0], 10, 10, 9, 10, 100, 10), (ds[1], 10, 11, 9, 10.5, 100, 10)]
    bars = make_bars("600000", rows)
    ctx = ctx_for(bars, i0=0, iD=1)
    assert ext.f_high_vs_pullback_high(ctx).missing_reason == ext.EMPTY_PULLBACK_WINDOW
    assert ext.f_close_vs_pullback_high(ctx).missing_reason == ext.EMPTY_PULLBACK_WINDOW


def test_t0_close_location_zero_denominator():
    ds = dates(date(2026, 3, 2), 2)
    rows = [(ds[0], 10, 10, 10, 10, 100, 10), (ds[1], 10, 11, 9, 10.5, 100, 10)]
    bars = make_bars("600000", rows)
    ctx = ctx_for(bars, i0=0, iD=1)
    assert ext.f_t0_close_location(ctx).missing_reason == ext.ZERO_DENOMINATOR


def test_factor_result_invariant():
    with pytest.raises(RuntimeError):
        ext.FactorResult(value=1.0, missing_reason="X")
    with pytest.raises(RuntimeError):
        ext.FactorResult(value=None, missing_reason=None)
    with pytest.raises(RuntimeError):
        ext.FactorResult(value=float("nan"))
    ok = ext.FactorResult(value=Decimal("0.5"))
    assert ok.missing_reason is None
