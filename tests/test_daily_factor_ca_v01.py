"""R2A corporate-action edge tests (offline, synthetic)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import extract_daily_factors_v01 as ext  # noqa: E402
from tests.test_daily_factor_extractor_v01 import make_bars  # noqa: E402


def dates(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        out.append(d)
        d += timedelta(days=1)
    return out


def write_adj_parquet(path: Path, code: str, rows: list[tuple[date, str]]) -> None:
    """(trade_date, adj_factor-as-string)."""
    table = pa.table(
        {
            "code": pa.array([code] * len(rows), pa.string()),
            "trade_date": pa.array([d.isoformat() for d, _ in rows], pa.string()),
            "adj_factor": pa.array([a for _, a in rows], pa.string()),
        }
    )
    pq.write_table(table, path)


def adj_map(code: str, rows: list[tuple[date, str]]) -> dict[str, dict[date, Decimal]]:
    return {code: {d: Decimal(a) for d, a in rows}}


def test_identical_adj_duplicates_deduped(tmp_path):
    p = tmp_path / "adj.parquet"
    d = date(2026, 3, 3)
    write_adj_parquet(p, "600000", [(d, "1.0"), (d, "1.0")])
    out = ext.load_adj_factors(p, codes={"600000"})
    assert out == {"600000": {d: Decimal("1.0")}}


def test_conflicting_adj_duplicates_block(tmp_path):
    p = tmp_path / "adj.parquet"
    d = date(2026, 3, 3)
    write_adj_parquet(p, "600000", [(d, "1.0"), (d, "0.8")])
    with pytest.raises(RuntimeError, match="conflicting adjustment-factor duplicates"):
        ext.load_adj_factors(p, codes={"600000"})


def test_ca_event_vs_unknown_distinct():
    ds = dates(date(2026, 3, 2), 4)
    adj_event = {ds[0]: Decimal("1.0"), ds[1]: Decimal("0.8"), ds[2]: Decimal("0.8")}
    status = ext.ca_edges_status(None, [ds[0], ds[1]], adj_event)
    assert status == "CA_EVENT"
    adj_unknown = {ds[0]: Decimal("1.0")}  # ds[1] missing
    status = ext.ca_edges_status(None, [ds[0], ds[1]], adj_unknown)
    assert status == "CA_UNKNOWN"


def test_ca_event_priority_over_unknown():
    ds = dates(date(2026, 3, 2), 4)
    adj = {ds[0]: Decimal("1.0"), ds[1]: Decimal("0.8")}  # event on first edge
    # second edge (ds[2]->ds[3]) unknown; event priority wins (frozen)
    status = ext.ca_edges_status(None, [ds[0], ds[1], ds[2], ds[3]], adj)
    assert status == "CA_EVENT"


def test_ca_predecessor_left_edge_missing_is_unknown():
    ds = dates(date(2026, 1, 5), 25)
    rows = [(d, 10.0, 11.0, 9.0, 10.5, 100.0, 10.0) for d in ds]
    bars = make_bars("600000", rows)
    # adj present for T0-19..T0 but MISSING for predecessor T0-20 -> UNKNOWN
    adj = {ds[i]: Decimal("1.0") for i in range(1, 21)}
    case = ext.FactorCaseContext(
        episode_id="E:1", symbol="600000", name="", anchor_date=ds[20],
        candidate_date=ds[24], s1_price="10", invalid_price="9",
        data_quality="OK", quality_flags="[]",
        candidate_reconciliation_status="CONFIRMED",
        feature_3d_has_provisional=False, label_5d_has_provisional=False,
    )
    ctx = ext.FactorContext(
        case=case, bars=bars, i0=20, iD=24, adj={case.symbol: adj}
    )
    res = ext.f_t0_position_20d(ctx)
    assert res.missing_reason == ext.CORPORATE_ACTION_UNKNOWN


def test_f18_f19_ca_event_null():
    ds = dates(date(2026, 3, 2), 5)
    rows = [
        (ds[0], 10, 10, 9, 10, 100, 10),      # predecessor
        (ds[1], 10, 11, 9, 10.5, 100, 10),    # T0
        (ds[2], 10, 11, 9, 10.5, 100, 10),
        (ds[3], 10, 11, 9, 10.5, 100, 10),
        (ds[4], 10, 11, 9, 10.5, 100, 10),    # D
    ]
    bars = make_bars("600000", rows)
    adj = {ds[0]: Decimal("1.0"), ds[1]: Decimal("0.8"), ds[2]: Decimal("0.8"),
           ds[3]: Decimal("0.8"), ds[4]: Decimal("0.8")}
    case = ext.FactorCaseContext(
        episode_id="E:1", symbol="600000", name="", anchor_date=ds[1],
        candidate_date=ds[4], s1_price="10", invalid_price="9",
        data_quality="OK", quality_flags="[]",
        candidate_reconciliation_status="CONFIRMED",
        feature_3d_has_provisional=False, label_5d_has_provisional=False,
    )
    ctx = ext.FactorContext(case=case, bars=bars, i0=1, iD=4, adj={case.symbol: adj})
    assert ext.f_median_range_ratio(ctx).missing_reason == ext.CORPORATE_ACTION_EVENT
    assert ext.f_range_slope(ctx).missing_reason == ext.CORPORATE_ACTION_EVENT


def test_f6_d_ca_event_null():
    ds = dates(date(2026, 3, 2), 4)
    rows = [
        (ds[0], 10, 10, 9, 10, 100, 10),
        (ds[1], 10, 10.5, 9.5, 10.2, 100, 10),
        (ds[2], 10, 10.4, 9.6, 10.1, 100, 10),
        (ds[3], 10, 10.6, 9.8, 10.5, 100, 10),
    ]
    bars = make_bars("600000", rows)
    # D edge (ds[2]->ds[3]) is a CA event
    adj = {ds[0]: Decimal("1.0"), ds[1]: Decimal("1.0"), ds[2]: Decimal("1.0"), ds[3]: Decimal("0.8")}
    case = ext.FactorCaseContext(
        episode_id="E:1", symbol="600000", name="", anchor_date=ds[0],
        candidate_date=ds[3], s1_price="10", invalid_price="9",
        data_quality="OK", quality_flags="[]",
        candidate_reconciliation_status="CONFIRMED",
        feature_3d_has_provisional=False, label_5d_has_provisional=False,
    )
    ctx = ext.FactorContext(case=case, bars=bars, i0=0, iD=3, adj={case.symbol: adj})
    assert ext.f_high_vs_pullback_high(ctx).missing_reason == ext.CORPORATE_ACTION_EVENT
    assert ext.f_close_vs_pullback_high(ctx).missing_reason == ext.CORPORATE_ACTION_EVENT


def test_f4_computable_on_ca_day():
    ds = dates(date(2026, 3, 2), 4)
    rows = [
        (ds[0], 10, 11, 9, 10.5, 100, 10),   # predecessor
        (ds[1], 10, 11, 9, 10.5, 100, 10),
        (ds[2], 10, 11, 9, 10.5, 100, 10),
        (ds[3], 10, 11, 9, 10.5, 100, 10),
    ]
    bars = make_bars("600000", rows)
    # T0 (ds[1]) is a CA event day: edge (ds[0]->ds[1]) changes adj factor
    adj = {ds[0]: Decimal("1.0"), ds[1]: Decimal("0.8"), ds[2]: Decimal("0.8"), ds[3]: Decimal("0.8")}
    case = ext.FactorCaseContext(
        episode_id="E:1", symbol="600000", name="", anchor_date=ds[1],
        candidate_date=ds[3], s1_price="10", invalid_price="9",
        data_quality="OK", quality_flags="[]",
        candidate_reconciliation_status="CONFIRMED",
        feature_3d_has_provisional=False, label_5d_has_provisional=False,
    )
    ctx = ext.FactorContext(case=case, bars=bars, i0=1, iD=3, adj={case.symbol: adj})
    res = ext.f_t0_close_location(ctx)
    assert res.value is not None  # CA_SAFE same-session geometry, no guard
    assert res.missing_reason is None
    # #1 t0_return on the same T0 CA day IS NULL (cross-session price)
    assert ext.f_t0_return(ctx).missing_reason == ext.CORPORATE_ACTION_EVENT
