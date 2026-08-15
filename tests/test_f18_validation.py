"""Offline synthetic tests for research/f18_validation_v01.py (no real data)."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from research.f18_validation_v01 import (
    bars_pit,
    check_accounting_counts,
    classify_group,
    group_daily,
    compute_f18,
    group_metrics,
    load_daily,
    load_episodes,
    main,
    primary_analysis,
    robust_r_diagnostics,
    timing_bucket,
    to_daily_bar,
    verdict,
)
from tests.synthetic_data import business_dates, make_bar

TZ = timezone(timedelta(hours=8))


def _daily_df(bars: list) -> pd.DataFrame:
    rows = []
    for b in bars:
        rows.append({
            "code": b.code,
            "trade_date": b.trade_date,
            "open": str(b.open),
            "high": str(b.high),
            "low": str(b.low),
            "close": str(b.close),
            "preclose": str(b.preclose),
            "volume": str(b.volume),
            "trade_status": True,
        })
    return pd.DataFrame(rows)


def _f18_episode_bars() -> list:
    """Same construction as the factor tests: 12 pre days @10.40, T0 (10.00/11.00),
    then two post days."""
    bars = []
    days = business_dates(date(2026, 2, 2), 12 + 1 + 2)
    p = Decimal("10.40")
    for day in days[:12]:
        bars.append(make_bar(day, open_price="10.40", high=str(p + Decimal("0.05")), low=str(p - Decimal("0.05")), close="10.40", preclose="10.00", volume="1000"))
    bars.append(make_bar(days[12], open_price="10.00", high="11.05", low="9.95", close="11.00", preclose="10.40", volume="1000"))
    bars.append(make_bar(days[13], open_price="10.50", high="10.80", low="10.10", close="10.50", preclose="10.00", volume="500"))
    bars.append(make_bar(days[14], open_price="9.90", high="10.80", low="9.90", close="10.50", preclose="10.00", volume="500"))
    return bars


def test_timing_bucket_boundaries() -> None:
    assert timing_bucket(1) == "T1-2"
    assert timing_bucket(2) == "T1-2"
    assert timing_bucket(3) == "T3"
    assert timing_bucket(4) == "T4-5"
    assert timing_bucket(5) == "T4-5"
    assert timing_bucket(6) == "T6-10"
    assert timing_bucket(9) == "T6-10"


def test_group_metrics_synthetic() -> None:
    outcomes = pd.Series(["WIN_S1", "WIN_S1", "LOSS_INVALID", "LOSS_INVALID", "CANCEL_GAP_INVALID"])
    r = pd.Series(["2.0", "1.5", "-1.0", "-0.5", None])
    m = group_metrics(outcomes, r)
    assert m["N"] == 5
    assert m["WIN_S1"] == 2
    assert m["LOSS_INVALID"] == 2
    assert m["CANCEL_GAP_INVALID"] == 1
    assert m["strict_win_rate"] == 0.5
    assert m["R_DEFINED_N"] == 4
    assert m["median_R"] == 0.5
    assert m["P(R>0)"] == 0.5
    assert m["P(R>=2)"] == 0.25


def test_group_metrics_empty_denominator() -> None:
    m = group_metrics(pd.Series(["CANCEL_GAP_INVALID"]), pd.Series([None]))
    assert m["strict_win_rate"] is None
    assert m["P(R>0)"] is None


def test_robust_r_diagnostics_synthetic() -> None:
    r = pd.Series([str(v) for v in range(1, 101)])
    d = robust_r_diagnostics(r)
    assert d["max_R"] == 100.0
    assert d["p90_R"] == 90.1
    assert d["p95_R"] == 95.05
    assert d["top1pct_R_contribution"] == pytest.approx(100.0 / 5050.0, rel=1e-6)
    assert d["trim_top1pct_mean_R"] == pytest.approx((5050.0 - 100.0) / 99.0, rel=1e-6)


def test_verdict_rules() -> None:
    assert verdict(0.05, 0.03) == "SUPPORTED_DIRECTIONALLY"
    assert verdict(0.05, -0.01) == "REJECT"
    assert verdict(-0.01, 0.03) == "REJECT"
    assert verdict(None, 0.03) == "REJECT"


def test_to_daily_bar_conversion() -> None:
    bars = _f18_episode_bars()
    row = _daily_df(bars).iloc[0]
    db = to_daily_bar(row)
    assert db.trade_date == row["trade_date"]
    assert db.close == Decimal("10.40")
    assert db.code == "600000"


def test_bars_pit_cuts_future() -> None:
    bars = _f18_episode_bars()
    df = _daily_df(bars)
    anchor = bars[12].trade_date
    pit = bars_pit(df, "600000", anchor, anchor)
    assert all(b.trade_date <= anchor for b in pit)
    assert pit[-1].trade_date == anchor
    assert len(pit) >= 10  # MA10 computable at the anchor


def test_compute_f18_pit_episode() -> None:
    bars = _f18_episode_bars()
    df = _daily_df(bars)
    episode = {
        "code": "600000",
        "anchor_date": bars[12].trade_date.isoformat(),
        "signal_date": bars[14].trade_date.isoformat(),
        "support_low": "10.20",
        "support_high": "10.60",
    }
    f18, reason = compute_f18(group_daily(df), episode)
    assert f18 == 3  # day1: MA+BODY+PLATFORM 同日激活且 m∈实体∩平台 → 三重 3
    assert reason is None


def test_compute_f18_missing_support() -> None:
    bars = _f18_episode_bars()
    df = _daily_df(bars)
    episode = {
        "code": "600000",
        "anchor_date": bars[12].trade_date.isoformat(),
        "signal_date": bars[14].trade_date.isoformat(),
        "support_low": None,
        "support_high": None,
    }
    f18, reason = compute_f18(group_daily(df), episode)
    assert f18 is None
    assert reason == "MISSING_SUPPORT"


def test_classify_group_undefined_not_in_primary() -> None:
    # Audited fix: None/NaN must not fall into NON_CONFLUENCE
    assert classify_group(None) == "UNDEFINED"
    assert classify_group(float("nan")) == "UNDEFINED"
    assert classify_group(0) == "NON_CONFLUENCE"
    assert classify_group(1) == "NON_CONFLUENCE"
    assert classify_group(2) == "CONFLUENCE"
    assert classify_group(3) == "CONFLUENCE"


# ---- F18 validation final hardening v01: fail-closed accounting + isolation ----

def _synthetic_resolved(rows: list[dict]) -> pd.DataFrame:
    """Build a synthetic resolved frame with the columns main() relies on."""
    df = pd.DataFrame(rows)
    df["r_multiple_num"] = pd.to_numeric(df["r_multiple"], errors="coerce")
    df["group"] = df["f18"].apply(classify_group)
    return df


def test_accounting_invariant_defined_plus_undefined_equals_resolved() -> None:
    # A. defined + undefined == resolved (invariant holds)
    check_accounting_counts(resolved_n=100, defined_n=95, undefined_n=5, con_n=60, non_n=35, frozen=None)
    # Broken: 95 + 6 != 100
    with pytest.raises(RuntimeError, match="ACCOUNTING INVARIANT"):
        check_accounting_counts(resolved_n=100, defined_n=95, undefined_n=6, con_n=60, non_n=35, frozen=None)


def test_primary_invariant_confluence_plus_non_confluence_equals_defined() -> None:
    # B. confluence + non_confluence == defined (invariant holds)
    check_accounting_counts(resolved_n=100, defined_n=95, undefined_n=5, con_n=60, non_n=35, frozen=None)
    # Broken: 60 + 36 != 95
    with pytest.raises(RuntimeError, match="ACCOUNTING INVARIANT"):
        check_accounting_counts(resolved_n=100, defined_n=95, undefined_n=5, con_n=60, non_n=36, frozen=None)


def test_frozen_materialization_locks() -> None:
    # Frozen V01 numbers must be locked: any drift raises (no artifact written).
    from research.f18_validation_v01 import FROZEN_ACCOUNTING
    check_accounting_counts(resolved_n=9625, defined_n=9594, undefined_n=31,
                            con_n=6634, non_n=2960, frozen=FROZEN_ACCOUNTING)
    with pytest.raises(RuntimeError, match="FROZEN MATERIALIZATION LOCK"):
        check_accounting_counts(resolved_n=9625, defined_n=9594, undefined_n=31,
                                con_n=6635, non_n=2959, frozen=FROZEN_ACCOUNTING)


def test_undefined_isolation_primary_unchanged() -> None:
    # C. A single F18=None episode with extreme outcome/R must not move
    # primary metrics or verdict: undefined is accounting-only.
    base_rows = [
        {"f18": 0, "outcome": "LOSS_INVALID", "r_multiple": "-1.0"},
        {"f18": 1, "outcome": "WIN_S1", "r_multiple": "1.5"},
        {"f18": 1, "outcome": "LOSS_INVALID", "r_multiple": "-0.5"},
        {"f18": 2, "outcome": "WIN_S1", "r_multiple": "2.0"},
        {"f18": 2, "outcome": "LOSS_INVALID", "r_multiple": "-1.2"},
        {"f18": 3, "outcome": "WIN_S1", "r_multiple": "3.0"},
    ]
    base = _synthetic_resolved(base_rows)
    base_primary = primary_analysis(base[base["group"] != "UNDEFINED"])
    assert base_primary["VERDICT"] in ("SUPPORTED_DIRECTIONALLY", "REJECT")

    # Identical defined population + one undefined episode: WIN_S1 with huge +R
    df_pos = _synthetic_resolved(base_rows + [{"f18": None, "outcome": "WIN_S1", "r_multiple": "9999.0"}])
    assert (df_pos["group"] == "UNDEFINED").sum() == 1
    defined_pos = df_pos[df_pos["group"] != "UNDEFINED"]
    primary_pos = primary_analysis(defined_pos)

    # Same defined population + one undefined episode: LOSS_INVALID with huge -R
    df_neg = _synthetic_resolved(base_rows + [{"f18": None, "outcome": "LOSS_INVALID", "r_multiple": "-9999.0"}])
    defined_neg = df_neg[df_neg["group"] != "UNDEFINED"]
    primary_neg = primary_analysis(defined_neg)

    assert primary_pos == primary_neg == base_primary
    # Undefined row only affects ACCOUNTING, never metrics
    check_accounting_counts(
        resolved_n=len(df_pos), defined_n=len(defined_pos),
        undefined_n=1, con_n=len(defined_pos[defined_pos["group"] == "CONFLUENCE"]),
        non_n=len(defined_pos[defined_pos["group"] == "NON_CONFLUENCE"]),
        frozen=None,
    )


def test_load_daily_wrong_sha_fail_closed(tmp_path, monkeypatch) -> None:
    # D. Wrong daily SHA must raise; authoritative main() writes no artifact.
    bad_daily = tmp_path / "daily_bad.parquet"
    pd.DataFrame({"code": ["600000"], "trade_date": [date(2026, 2, 2)],
                  "open": ["10.0"], "high": ["10.5"], "low": ["9.9"], "close": ["10.2"],
                  "preclose": ["10.0"], "volume": ["1000"], "trade_status": [True]}).to_parquet(bad_daily)
    with pytest.raises(RuntimeError, match="daily SHA mismatch"):
        load_daily(bad_daily)

    # Authoritative main: load_episodes gate satisfied via monkeypatch (episodes
    # SHA is not under test here); daily SHA mismatch -> fail closed, no artifact.
    def fake_load_episodes(_path: object) -> pd.DataFrame:
        return _synthetic_resolved([
            {"f18": 1, "outcome": "WIN_S1", "r_multiple": "1.0"},
            {"f18": 2, "outcome": "LOSS_INVALID", "r_multiple": "-1.0"},
        ])
    monkeypatch.setattr("research.f18_validation_v01.load_episodes", fake_load_episodes)
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="daily SHA mismatch"):
        main(episodes_path=tmp_path / "episodes.parquet", daily_path=bad_daily, out_dir=out_dir)
    # No formal JSON/report generated on failure
    assert not out_dir.exists()
    assert not list(tmp_path.glob("*.json"))
    assert not list(tmp_path.glob("*.md"))


def test_main_signature_no_daily_bypass() -> None:
    # E. main() accepts only paths — no caller-supplied DataFrame daily/episodes.
    import inspect
    sig = inspect.signature(main)
    assert list(sig.parameters) == ["episodes_path", "daily_path", "out_dir"]
    assert all(p.annotation is Path or p.default is inspect.Parameter.empty
               for p in sig.parameters.values())
    # load_daily/load_episodes refuse DataFrame arguments outright
    with pytest.raises(TypeError, match="bypass forbidden"):
        load_daily(pd.DataFrame())
    with pytest.raises(TypeError, match="bypass forbidden"):
        load_episodes(pd.DataFrame())
