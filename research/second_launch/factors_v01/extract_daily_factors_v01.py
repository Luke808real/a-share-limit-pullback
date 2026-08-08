"""R2A daily factor extractor for the frozen 25-factor contract (research-only).

Implements exactly the formulas in
`research/second_launch/factors_v01/daily_factor_contract_v01.csv`
(SHA pinned; runtime mismatch FAIL CLOSED). No outcome fields are ever read
into factor computation; labels may only be joined later.

This module NEVER writes the full 8,682-row dataset: bounded mode requires an
explicit codes/episode-id filter, and full mode requires --allow-full (not used
in this round).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import glob
from pathlib import Path
import sys
from typing import Any, Callable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "outcome_v01"))

import build_second_launch_outcome_v01 as gen  # noqa: E402


# ---------------------------------------------------------------------------
# Frozen inputs / pins.
# ---------------------------------------------------------------------------

CONTRACT_CSV = REPO_ROOT / "research" / "second_launch" / "factors_v01" / "daily_factor_contract_v01.csv"
EXPECTED_CONTRACT_CSV_SHA256 = (
    "a67e7e2adab07f87227e467cfdb8234b56a5068fd8b739ac91e77bf2623606c9"
)

CASE_SET_PATH = gen.INTERIM_OUT_CSV
FEATURE_SNAPSHOT_ID = gen.FEATURE_SNAPSHOT_ID
FEATURE_SNAPSHOT_PATH = gen.FEATURE_SNAPSHOT_PATH
EXPECTED_FEATURE_SNAPSHOT_SHA256 = gen.EXPECTED_FEATURE_SNAPSHOT_SHA256

ADJ_FACTOR_GLOB = REPO_ROOT / "data" / "raw" / "tushare" / "adjustment_factor" / "*.parquet"

# PIT whitelist: the ONLY case columns that may enter factor computation.
CASE_USECOLS = [
    "episode_id",
    "symbol",
    "name",
    "anchor_date",
    "candidate_date",
    "s1_price",
    "invalid_price",
    "data_quality",
    "quality_flags",
    "candidate_reconciliation_status",
    "feature_3d_has_provisional",
    "label_5d_has_provisional",
]

# Forbidden: label/outcome/event fields must never enter factor context.
FORBIDDEN_CASE_COLUMNS = [
    "outcome_3d",
    "outcome_reason_3d",
    "outcome_5d",
    "outcome_reason_5d",
    "time_to_s1_10d",
    "time_to_invalid_10d",
    "first_event_type_10d",
    "first_event_date_10d",
]

# Missing reason taxonomy (frozen contract).
MISSING_T0_BAR = "MISSING_T0_BAR"
MISSING_D_BAR = "MISSING_D_BAR"
INSUFFICIENT_PRE_T0_HISTORY = "INSUFFICIENT_PRE_T0_HISTORY"
EMPTY_PULLBACK_WINDOW = "EMPTY_PULLBACK_WINDOW"
INSUFFICIENT_PULLBACK_SESSIONS = "INSUFFICIENT_PULLBACK_SESSIONS"
ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
NONPOSITIVE_VOLUME = "NONPOSITIVE_VOLUME"
MISSING_PRECLOSE = "MISSING_PRECLOSE"
MISSING_REQUIRED_COLUMN = "MISSING_REQUIRED_COLUMN"
CORPORATE_ACTION_EVENT = "CORPORATE_ACTION_EVENT"
CORPORATE_ACTION_UNKNOWN = "CORPORATE_ACTION_UNKNOWN"
OTHER = "OTHER"

STRATIFICATION_COLUMNS = [
    "candidate_reconciliation_status",
    "feature_3d_has_provisional",
    "label_5d_has_provisional",
    "data_quality",
    "quality_flags",
]

OUTPUT_ID_COLUMNS = ["episode_id", "symbol", "anchor_date", "candidate_date"]


# ---------------------------------------------------------------------------
# Core result / context types.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactorResult:
    """One factor value; exactly one of value/reason is populated."""

    value: Decimal | float | int | None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        if self.value is not None:
            if self.missing_reason is not None:
                raise RuntimeError("FactorResult: value and missing_reason both set")
            if isinstance(self.value, float) and not np.isfinite(self.value):
                raise RuntimeError("FactorResult: non-finite value forbidden")
        else:
            if self.missing_reason is None:
                raise RuntimeError("FactorResult: None value without missing_reason")


@dataclass(frozen=True)
class FactorCaseContext:
    """PIT case fields ONLY (no outcome/label/event columns exist here)."""

    episode_id: str
    symbol: str
    name: str
    anchor_date: date
    candidate_date: date
    s1_price: str
    invalid_price: str
    data_quality: str
    quality_flags: str
    candidate_reconciliation_status: str
    feature_3d_has_provisional: bool
    label_5d_has_provisional: bool


@dataclass(frozen=True)
class FactorContext:
    """Everything a factor formula needs (bars + CA lookup)."""

    case: FactorCaseContext
    bars: pd.DataFrame | None          # per-code canonical bars, sorted
    i0: int | None                     # T0 session index
    iD: int | None                     # D session index
    adj: dict[str, dict[date, Decimal]]  # code -> {trade_date: adj_factor}


# ---------------------------------------------------------------------------
# Loading (explicit paths; fail closed).
# ---------------------------------------------------------------------------

def D(x: Any) -> Decimal:
    """Decimal from a float/str/int; exact decimal expansion of the value."""
    return Decimal(str(x))


def load_contract(path: Path = CONTRACT_CSV) -> pd.DataFrame:
    if gen.sha256_file(path) != EXPECTED_CONTRACT_CSV_SHA256:
        raise RuntimeError("contract CSV hash mismatch (fail closed)")
    contract = pd.read_csv(path)
    if len(contract) != 25 or contract["factor_name"].nunique() != 25:
        raise RuntimeError("contract CSV must contain exactly 25 unique factors")
    if not (contract["contract_status"] == "FROZEN_FOR_R2").all():
        raise RuntimeError("contract status must be FROZEN_FOR_R2 for all 25")
    roles = contract.set_index("factor_name")["analysis_role"].to_dict()
    if roles.get("impulse_retrace_ratio") != "DERIVED_ALIAS":
        raise RuntimeError("contract: #11 must be DERIVED_ALIAS")
    if roles.get("t0_gain_retention") != "PRIMARY":
        raise RuntimeError("contract: #12 must be PRIMARY")
    return contract


def _read_header(path: Path) -> list[str]:
    return pd.read_csv(path, nrows=0).columns.tolist()


def load_cases(path: Path = CASE_SET_PATH) -> list[FactorCaseContext]:
    header = _read_header(path)
    missing = [c for c in CASE_USECOLS if c not in header]
    if missing:
        raise RuntimeError(f"case set missing required columns: {missing}")
    overlap = set(FORBIDDEN_CASE_COLUMNS) & set(CASE_USECOLS)
    if overlap:
        raise RuntimeError(
            f"PIT violation: forbidden columns in usecols whitelist: {overlap}"
        )
    df = pd.read_csv(path, usecols=CASE_USECOLS, dtype={"symbol": str})
    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    df["anchor_date"] = pd.to_datetime(df["anchor_date"]).dt.date
    df["candidate_date"] = pd.to_datetime(df["candidate_date"]).dt.date
    out = []
    for _, r in df.iterrows():
        f3_prov = r["feature_3d_has_provisional"]
        l5_prov = r["label_5d_has_provisional"]
        out.append(
            FactorCaseContext(
                episode_id=r["episode_id"],
                symbol=r["symbol"],
                name=r["name"],
                anchor_date=r["anchor_date"],
                candidate_date=r["candidate_date"],
                s1_price=r["s1_price"],
                invalid_price=r["invalid_price"],
                data_quality=r["data_quality"],
                quality_flags=r["quality_flags"],
                candidate_reconciliation_status=r["candidate_reconciliation_status"],
                feature_3d_has_provisional=f3_prov in (True, 1, "True", "true", "1"),
                label_5d_has_provisional=l5_prov in (True, 1, "True", "true", "1"),
            )
        )
    return out


def load_adj_factors(
    glob_pattern: Path = ADJ_FACTOR_GLOB,
    *,
    codes: set[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, dict[date, Decimal]]:
    """Bounded adjustment-factor loader (code/date filtered).

    Duplicate (code, trade_date): identical values -> deterministic dedupe;
    conflicting values -> FAIL CLOSED (never keep-last).
    """
    frames = []
    filters = None
    if codes is not None:
        filters = [("code", "in", sorted(codes))]
    for path in sorted(glob.glob(str(glob_pattern))):
        frames.append(
            pq.read_table(
                path,
                columns=["code", "trade_date", "adj_factor"],
                filters=filters,
            ).to_pandas()
        )
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True)
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    if start_date is not None:
        df = df[df["trade_date"] >= start_date]
    if end_date is not None:
        df = df[df["trade_date"] <= end_date]
    grouped = df.groupby(["code", "trade_date"], sort=False)
    out: dict[str, dict[date, Decimal]] = {}
    for (code, trade_date), group in grouped:
        values = {D(v) for v in group["adj_factor"]}
        if len(values) > 1:
            raise RuntimeError(
                f"conflicting adjustment-factor duplicates (fail closed): "
                f"{code} {trade_date}"
            )
        out.setdefault(code, {})[trade_date] = values.pop()
    return out


# ---------------------------------------------------------------------------
# Session / window helpers (single source of slicing truth).
# ---------------------------------------------------------------------------

def find_session_index(bars: pd.DataFrame, d: date) -> int | None:
    idx = np.searchsorted(bars["trade_date"].values, d, side="left")
    if idx < len(bars) and bars.iloc[idx]["trade_date"] == d:
        return int(idx)
    return None


def prior_sessions(bars: pd.DataFrame, i0: int, n: int) -> pd.DataFrame:
    return bars.iloc[max(0, i0 - n):i0].reset_index(drop=True)


def pullback_pre_d(bars: pd.DataFrame, i0: int, iD: int) -> pd.DataFrame:
    return bars.iloc[i0 + 1:iD].reset_index(drop=True)


def pullback_asof_d(bars: pd.DataFrame, i0: int, iD: int) -> pd.DataFrame:
    return bars.iloc[i0 + 1:iD + 1].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Corporate action: edge semantics (strict canonical predecessor).
# ---------------------------------------------------------------------------

def ca_edges_status(
    bars: pd.DataFrame,
    required_observations: list[date],
    adj: dict[date, Decimal],
) -> str:
    """Evaluate CA transitions over consecutive canonical sessions.

    Returns OK / CA_EVENT / CA_UNKNOWN. Priority when both present:
    CA_EVENT > CA_UNKNOWN (deterministic, frozen).
    """
    if len(required_observations) < 2:
        # A single (or empty) observation cannot form the required edge:
        # the missing side (e.g. predecessor at snapshot start) -> UNKNOWN.
        return "CA_UNKNOWN"
    has_event = False
    has_unknown = False
    for s_prev, s in zip(required_observations, required_observations[1:]):
        a_prev = adj.get(s_prev)
        a_s = adj.get(s)
        if a_prev is None or a_s is None:
            has_unknown = True
        elif a_prev != a_s:
            has_event = True
    if has_event:
        return "CA_EVENT"
    if has_unknown:
        return "CA_UNKNOWN"
    return "OK"


def ca_guard(ctx: FactorContext, span_start: int, span_end: int) -> str | None:
    """CA guard for CA_UNSAFE factors over the required observation span.

    Required observations = comparison span + one immediately preceding
    canonical session (to judge whether the span's first session is a CA
    transition). If the predecessor lies outside available history
    (span_start < 0), the edge is unevaluable -> CORPORATE_ACTION_UNKNOWN.
    """
    if ctx.bars is None:
        return None  # bar-level missing handled by the factor itself
    if span_start < 0:
        return CORPORATE_ACTION_UNKNOWN
    required_observations = _ca_obs_from_span(ctx, span_start, span_end)
    adj = ctx.adj.get(ctx.case.symbol, {})
    status = ca_edges_status(ctx.bars, required_observations, adj)
    if status == "CA_EVENT":
        return CORPORATE_ACTION_EVENT
    if status == "CA_UNKNOWN":
        return CORPORATE_ACTION_UNKNOWN
    return None


# ---------------------------------------------------------------------------
# Shared per-factor guards.
# ---------------------------------------------------------------------------

def _require_bars(ctx: FactorContext) -> str | None:
    if ctx.bars is None:
        return MISSING_T0_BAR
    return None


def _t0_d_indices(ctx: FactorContext) -> str | None:
    if ctx.i0 is None:
        return MISSING_T0_BAR
    if ctx.iD is None:
        return MISSING_D_BAR
    if ctx.iD < ctx.i0:
        return OTHER
    return None


def _ca_obs_from_span(ctx: FactorContext, start: int, end: int) -> list[date]:
    """Dates of canonical sessions [start, end] (clamped at 0)."""
    lo = max(0, start)
    return list(ctx.bars.iloc[lo:end + 1]["trade_date"])


# ---------------------------------------------------------------------------
# The 25 formulas (contract order; no extra factors).
# ---------------------------------------------------------------------------

def f_t0_return(ctx: FactorContext) -> FactorResult:
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return FactorResult(None, r)
    b0 = ctx.bars.iloc[ctx.i0]
    if pd.isna(b0["preclose"]):
        return FactorResult(None, MISSING_PRECLOSE)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.i0)
    if ca:
        return FactorResult(None, ca)
    if D(b0["preclose"]) <= 0:
        return FactorResult(None, ZERO_DENOMINATOR)
    return FactorResult(D(b0["close"]) / D(b0["preclose"]) - 1)


def f_t0_gap(ctx: FactorContext) -> FactorResult:
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return FactorResult(None, r)
    b0 = ctx.bars.iloc[ctx.i0]
    if pd.isna(b0["preclose"]):
        return FactorResult(None, MISSING_PRECLOSE)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.i0)
    if ca:
        return FactorResult(None, ca)
    if D(b0["preclose"]) <= 0:
        return FactorResult(None, ZERO_DENOMINATOR)
    return FactorResult(D(b0["open"]) / D(b0["preclose"]) - 1)


def f_t0_range_pct(ctx: FactorContext) -> FactorResult:
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return FactorResult(None, r)
    b0 = ctx.bars.iloc[ctx.i0]
    if pd.isna(b0["preclose"]):
        return FactorResult(None, MISSING_PRECLOSE)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.i0)
    if ca:
        return FactorResult(None, ca)
    if D(b0["preclose"]) <= 0:
        return FactorResult(None, ZERO_DENOMINATOR)
    return FactorResult((D(b0["high"]) - D(b0["low"])) / D(b0["preclose"]))


def f_t0_close_location(ctx: FactorContext) -> FactorResult:
    """CA_SAFE_SAME_SESSION_GEOMETRY: no CA guard by contract."""
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return FactorResult(None, r)
    b0 = ctx.bars.iloc[ctx.i0]
    denom = D(b0["high"]) - D(b0["low"])
    if denom == 0:
        return FactorResult(None, ZERO_DENOMINATOR)
    return FactorResult((D(b0["close"]) - D(b0["low"])) / denom)


def f_t0_position_20d(ctx: FactorContext) -> FactorResult:
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return FactorResult(None, r)
    if ctx.i0 < 19:
        return FactorResult(None, INSUFFICIENT_PRE_T0_HISTORY)
    ca = ca_guard(ctx, ctx.i0 - 20, ctx.i0)
    if ca:
        return FactorResult(None, ca)
    win = ctx.bars.iloc[ctx.i0 - 19:ctx.i0 + 1]
    c0 = D(ctx.bars.iloc[ctx.i0]["close"])
    min_low = D(win["low"].min())
    max_high = D(win["high"].max())
    denom = max_high - min_low
    if denom == 0:
        return FactorResult(None, ZERO_DENOMINATOR)
    return FactorResult((c0 - min_low) / denom)


def f_pre_t0_return_5d(ctx: FactorContext) -> FactorResult:
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return FactorResult(None, r)
    if ctx.i0 < 6:
        return FactorResult(None, INSUFFICIENT_PRE_T0_HISTORY)
    ca = ca_guard(ctx, ctx.i0 - 7, ctx.i0 - 1)
    if ca:
        return FactorResult(None, ca)
    close_1 = D(ctx.bars.iloc[ctx.i0 - 1]["close"])
    close_6 = D(ctx.bars.iloc[ctx.i0 - 6]["close"])
    if close_6 == 0:
        return FactorResult(None, ZERO_DENOMINATOR)
    return FactorResult(close_1 / close_6 - 1)


def f_pre_t0_return_20d(ctx: FactorContext) -> FactorResult:
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return FactorResult(None, r)
    if ctx.i0 < 21:
        return FactorResult(None, INSUFFICIENT_PRE_T0_HISTORY)
    ca = ca_guard(ctx, ctx.i0 - 22, ctx.i0 - 1)
    if ca:
        return FactorResult(None, ca)
    close_1 = D(ctx.bars.iloc[ctx.i0 - 1]["close"])
    close_21 = D(ctx.bars.iloc[ctx.i0 - 21]["close"])
    if close_21 == 0:
        return FactorResult(None, ZERO_DENOMINATOR)
    return FactorResult(close_1 / close_21 - 1)


def f_t0_volume_ratio_5d(ctx: FactorContext) -> FactorResult:
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return FactorResult(None, r)
    if ctx.i0 < 5:
        return FactorResult(None, INSUFFICIENT_PRE_T0_HISTORY)
    ca = ca_guard(ctx, ctx.i0 - 6, ctx.i0 - 1)
    if ca:
        return FactorResult(None, ca)
    v0 = float(ctx.bars.iloc[ctx.i0]["volume"])
    prior = ctx.bars.iloc[ctx.i0 - 5:ctx.i0]["volume"].astype(float)
    if v0 <= 0 or (prior <= 0).any():
        return FactorResult(None, NONPOSITIVE_VOLUME)
    return FactorResult(D(v0) / D(prior.mean()))


def _pb_window(ctx: FactorContext) -> tuple[pd.DataFrame | None, str | None]:
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return None, r
    pb = pullback_asof_d(ctx.bars, ctx.i0, ctx.iD)
    if len(pb) == 0:
        return None, EMPTY_PULLBACK_WINDOW
    return pb, None


def f_pullback_depth_close(ctx: FactorContext) -> FactorResult:
    pb, r = _pb_window(ctx)
    if r:
        return FactorResult(None, r)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD)
    if ca:
        return FactorResult(None, ca)
    c0 = D(ctx.bars.iloc[ctx.i0]["close"])
    return FactorResult(D(pb["close"].min()) / c0 - 1)


def f_max_drawdown(ctx: FactorContext) -> FactorResult:
    pb, r = _pb_window(ctx)
    if r:
        return FactorResult(None, r)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD)
    if ca:
        return FactorResult(None, ca)
    peak = D(ctx.bars.iloc[ctx.i0]["high"])
    dds: list[Decimal] = []
    for _, row in pb.iterrows():
        dds.append(D(row["low"]) / peak - 1)
        peak = max(peak, D(row["high"]))
    return FactorResult(min(dds))


def _impulse_retention_inputs(
    ctx: FactorContext,
) -> tuple[Decimal, Decimal, Decimal] | str:
    pb, r = _pb_window(ctx)
    if r:
        return r
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD)
    if ca:
        return ca
    b0 = ctx.bars.iloc[ctx.i0]
    c0 = D(b0["close"])
    pc0 = D(b0["preclose"])
    denom = c0 - pc0
    if denom <= 0:
        return ZERO_DENOMINATOR
    return c0, pc0, D(pb["close"].min())


def f_impulse_retrace_ratio(ctx: FactorContext) -> FactorResult:
    inp = _impulse_retention_inputs(ctx)
    if isinstance(inp, str):
        return FactorResult(None, inp)
    c0, pc0, min_pb_close = inp
    return FactorResult((c0 - min_pb_close) / (c0 - pc0))


def f_t0_gain_retention(ctx: FactorContext) -> FactorResult:
    inp = _impulse_retention_inputs(ctx)
    if isinstance(inp, str):
        return FactorResult(None, inp)
    c0, pc0, min_pb_close = inp
    return FactorResult((min_pb_close - pc0) / (c0 - pc0))


def f_low_vs_t0_mid(ctx: FactorContext) -> FactorResult:
    pb, r = _pb_window(ctx)
    if r:
        return FactorResult(None, r)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD)
    if ca:
        return FactorResult(None, ca)
    b0 = ctx.bars.iloc[ctx.i0]
    body_mid = (D(b0["open"]) + D(b0["close"])) / 2
    if body_mid == 0:
        return FactorResult(None, ZERO_DENOMINATOR)
    return FactorResult(D(pb["low"].min()) / body_mid - 1)


def f_days_above_t0_mid(ctx: FactorContext) -> FactorResult:
    pb, r = _pb_window(ctx)
    if r:
        return FactorResult(None, r)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD)
    if ca:
        return FactorResult(None, ca)
    b0 = ctx.bars.iloc[ctx.i0]
    body_mid = (D(b0["open"]) + D(b0["close"])) / 2
    n = int((pb["close"].map(D) >= body_mid).sum())
    return FactorResult(n)


def _pb_volume_ratio(ctx: FactorContext, agg: str) -> FactorResult:
    pb, r = _pb_window(ctx)
    if r:
        return FactorResult(None, r)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD)
    if ca:
        return FactorResult(None, ca)
    v0 = float(ctx.bars.iloc[ctx.i0]["volume"])
    vols = pb["volume"].astype(float)
    if v0 <= 0 or (vols <= 0).any():
        return FactorResult(None, NONPOSITIVE_VOLUME)
    stat = float(vols.median()) if agg == "median" else float(vols.min())
    return FactorResult(D(stat) / D(v0))


def f_pullback_volume_ratio(ctx: FactorContext) -> FactorResult:
    return _pb_volume_ratio(ctx, "median")


def f_min_volume_ratio(ctx: FactorContext) -> FactorResult:
    return _pb_volume_ratio(ctx, "min")


def f_volume_slope(ctx: FactorContext) -> FactorResult:
    pb, r = _pb_window(ctx)
    if r:
        return FactorResult(None, r)
    if len(pb) < 2:
        return FactorResult(None, INSUFFICIENT_PULLBACK_SESSIONS)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD)
    if ca:
        return FactorResult(None, ca)
    v0 = float(ctx.bars.iloc[ctx.i0]["volume"])
    vols = pb["volume"].astype(float)
    if v0 <= 0 or (vols <= 0).any():
        return FactorResult(None, NONPOSITIVE_VOLUME)
    x = np.arange(1, len(pb) + 1, dtype=float)
    y = np.log(vols.to_numpy() / v0)
    return FactorResult(float(np.polyfit(x, y, 1)[0]))


def _pb_ranges(ctx: FactorContext) -> tuple[pd.Series | None, str | None]:
    pb, r = _pb_window(ctx)
    if r:
        return None, r
    if pb["preclose"].isna().any():
        return None, MISSING_PRECLOSE
    if (pb["preclose"] <= 0).any():
        return None, ZERO_DENOMINATOR
    b0 = ctx.bars.iloc[ctx.i0]
    if pd.isna(b0["preclose"]):
        return None, MISSING_PRECLOSE
    if D(b0["preclose"]) <= 0:
        return None, ZERO_DENOMINATOR
    t0_range = (D(b0["high"]) - D(b0["low"])) / D(b0["preclose"])
    if t0_range <= 0:
        return None, ZERO_DENOMINATOR
    ranges = (pb["high"].map(D) - pb["low"].map(D)) / pb["preclose"].map(D)
    return ranges, t0_range


def _pb_ranges_guarded(ctx: FactorContext) -> tuple[pd.Series | None, str | None]:
    ranges, t0_range = _pb_ranges(ctx)
    if ranges is None:
        return None, t0_range
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD)
    if ca:
        return None, ca
    return ranges, t0_range


def f_median_range_ratio(ctx: FactorContext) -> FactorResult:
    ranges, t0_range = _pb_ranges_guarded(ctx)
    if ranges is None:
        return FactorResult(None, t0_range)
    return FactorResult(D(float(ranges.median())) / D(t0_range))


def f_range_slope(ctx: FactorContext) -> FactorResult:
    ranges, t0_range = _pb_ranges_guarded(ctx)
    if ranges is None:
        return FactorResult(None, t0_range)
    if len(ranges) < 2:
        return FactorResult(None, INSUFFICIENT_PULLBACK_SESSIONS)
    x = np.arange(1, len(ranges) + 1, dtype=float)
    y = (ranges.map(float).to_numpy() / float(t0_range))
    return FactorResult(float(np.polyfit(x, y, 1)[0]))


def f_quiet_days_n(ctx: FactorContext) -> FactorResult:
    ranges, t0_range = _pb_ranges(ctx)
    if ranges is None:
        return FactorResult(None, t0_range)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD)
    if ca:
        return FactorResult(None, ca)
    v0 = float(ctx.bars.iloc[ctx.i0]["volume"])
    if v0 <= 0:
        return FactorResult(None, NONPOSITIVE_VOLUME)
    vols = ctx.bars.iloc[ctx.i0 + 1:ctx.iD + 1]["volume"].astype(float)
    # numpy masks: avoids pandas index-alignment between bars slices and pb frames
    quiet = ((vols.to_numpy() / v0) < 1.0) & (
        (ranges.map(float).to_numpy() / float(t0_range)) < 1.0
    )
    return FactorResult(int(quiet.sum()))


def f_days_since_t0(ctx: FactorContext) -> FactorResult:
    """CA_SAFE: session counting only, never NULL due to CA."""
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return FactorResult(None, r)
    return FactorResult(ctx.iD - ctx.i0)


def f_days_to_pullback_low(ctx: FactorContext) -> FactorResult:
    pb, r = _pb_window(ctx)
    if r:
        return FactorResult(None, r)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD)
    if ca:
        return FactorResult(None, ca)
    lows = pb["low"].astype(float)
    min_low = float(lows.min())
    first_idx = int(np.argmax(lows.to_numpy() == min_low))
    return FactorResult(first_idx + 1)


def f_pullback_duration(ctx: FactorContext) -> FactorResult:
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return FactorResult(None, r)
    ca = ca_guard(ctx, ctx.i0 - 1, ctx.iD - 1)
    if ca:
        return FactorResult(None, ca)
    reference = ctx.bars.iloc[ctx.i0:ctx.iD]  # {T0} ∪ PULLBACK_PRE_D; D excluded
    highs = reference["high"].astype(float).to_numpy()
    peak_high = float(highs.max())
    last_peak_idx = int(np.argmax(highs[::-1] == peak_high))  # LAST occurrence
    peak_offset = len(highs) - 1 - last_peak_idx
    return FactorResult((ctx.iD - ctx.i0) - peak_offset)


def _f6_reference(ctx: FactorContext) -> tuple[float | None, str | None]:
    r = _require_bars(ctx) or _t0_d_indices(ctx)
    if r:
        return None, r
    pre_d = pullback_pre_d(ctx.bars, ctx.i0, ctx.iD)
    if len(pre_d) == 0:
        return None, EMPTY_PULLBACK_WINDOW
    ca = ca_guard(ctx, ctx.i0, ctx.iD)
    if ca:
        return None, ca
    ref = float(pre_d["high"].max())
    if ref <= 0:
        return None, ZERO_DENOMINATOR
    return ref, None


def f_high_vs_pullback_high(ctx: FactorContext) -> FactorResult:
    ref, r = _f6_reference(ctx)
    if r:
        return FactorResult(None, r)
    h_d = D(ctx.bars.iloc[ctx.iD]["high"])
    return FactorResult(h_d / D(ref) - 1)


def f_close_vs_pullback_high(ctx: FactorContext) -> FactorResult:
    ref, r = _f6_reference(ctx)
    if r:
        return FactorResult(None, r)
    c_d = D(ctx.bars.iloc[ctx.iD]["close"])
    return FactorResult(c_d / D(ref) - 1)


# ---------------------------------------------------------------------------
# Registry (contract order; exact bidirectional match with contract CSV).
# ---------------------------------------------------------------------------

FACTOR_REGISTRY: dict[str, Callable[[FactorContext], FactorResult]] = {
    "t0_return": f_t0_return,
    "t0_gap": f_t0_gap,
    "t0_range_pct": f_t0_range_pct,
    "t0_close_location": f_t0_close_location,
    "t0_position_20d": f_t0_position_20d,
    "pre_t0_return_5d": f_pre_t0_return_5d,
    "pre_t0_return_20d": f_pre_t0_return_20d,
    "t0_volume_ratio_5d": f_t0_volume_ratio_5d,
    "pullback_depth_close": f_pullback_depth_close,
    "max_drawdown_from_post_t0_high": f_max_drawdown,
    "impulse_retrace_ratio": f_impulse_retrace_ratio,
    "t0_gain_retention": f_t0_gain_retention,
    "low_vs_t0_mid": f_low_vs_t0_mid,
    "days_above_t0_mid": f_days_above_t0_mid,
    "pullback_volume_ratio": f_pullback_volume_ratio,
    "min_volume_ratio": f_min_volume_ratio,
    "volume_slope": f_volume_slope,
    "median_range_ratio": f_median_range_ratio,
    "range_slope": f_range_slope,
    "quiet_days_n": f_quiet_days_n,
    "days_since_t0": f_days_since_t0,
    "days_to_pullback_low": f_days_to_pullback_low,
    "pullback_duration": f_pullback_duration,
    "high_vs_pullback_high": f_high_vs_pullback_high,
    "close_vs_pullback_high": f_close_vs_pullback_high,
}


def validate_registry_against_contract(contract: pd.DataFrame) -> list[str]:
    """Registry names == contract names, bidirectional exact match."""
    contract_names = list(contract["factor_name"])
    registry_names = list(FACTOR_REGISTRY)
    if len(registry_names) != len(set(registry_names)):
        raise RuntimeError("registry contains duplicate factor names")
    if registry_names != contract_names:
        raise RuntimeError(
            "registry/contract mismatch: "
            f"missing={set(contract_names) - set(registry_names)} "
            f"extra={set(registry_names) - set(contract_names)}"
        )
    return contract_names


# ---------------------------------------------------------------------------
# Extraction orchestration.
# ---------------------------------------------------------------------------

def run_input_gate() -> None:
    """Contract hash + immutable input + feature snapshot verification."""
    load_contract()
    gen.verify_interim_manifest_artifacts()
    if gen.sha256_file(FEATURE_SNAPSHOT_PATH) != EXPECTED_FEATURE_SNAPSHOT_SHA256:
        raise RuntimeError("feature snapshot hash mismatch (fail closed)")


def extract_case_factors(
    ctx: FactorContext,
    factor_names: list[str],
) -> dict[str, FactorResult]:
    return {name: FACTOR_REGISTRY[name](ctx) for name in factor_names}


def build_factor_contexts(
    cases: list[FactorCaseContext],
    bars_by_code: dict[str, pd.DataFrame],
    adj: dict[str, dict[date, Decimal]],
) -> list[FactorContext]:
    contexts = []
    for case in cases:
        bars = bars_by_code.get(case.symbol)
        i0 = find_session_index(bars, case.anchor_date) if bars is not None else None
        iD = find_session_index(bars, case.candidate_date) if bars is not None else None
        contexts.append(FactorContext(case=case, bars=bars, i0=i0, iD=iD, adj=adj))
    return contexts


def extract_to_frame(
    cases: list[FactorCaseContext],
    *,
    bars_by_code: dict[str, pd.DataFrame] | None = None,
    adj: dict[str, dict[date, Decimal]] | None = None,
    snapshot_path: Path = FEATURE_SNAPSHOT_PATH,
    adj_glob: Path = ADJ_FACTOR_GLOB,
) -> pd.DataFrame:
    """Extract factors for the given cases; returns the wide output frame."""
    contract = load_contract()
    factor_names = validate_registry_against_contract(contract)
    if bars_by_code is None:
        codes = {c.symbol for c in cases}
        bars_by_code = gen.load_bars_by_code(snapshot_path, codes)
    if adj is None:
        adj = load_adj_factors(adj_glob, codes={c.symbol for c in cases})
    contexts = build_factor_contexts(cases, bars_by_code, adj)
    rows = []
    for ctx in contexts:
        results = extract_case_factors(ctx, factor_names)
        row: dict[str, Any] = {
            "episode_id": ctx.case.episode_id,
            "symbol": ctx.case.symbol,
            "anchor_date": ctx.case.anchor_date,
            "candidate_date": ctx.case.candidate_date,
        }
        for name in factor_names:
            res = results[name]
            row[name] = res.value
            row[f"{name}__missing_reason"] = res.missing_reason
        for col in STRATIFICATION_COLUMNS:
            row[col] = getattr(ctx.case, col)
        rows.append(row)
    columns = list(OUTPUT_ID_COLUMNS)
    for name in factor_names:
        columns += [name, f"{name}__missing_reason"]
    columns += STRATIFICATION_COLUMNS
    return pd.DataFrame(rows, columns=columns)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codes", nargs="*", default=None)
    parser.add_argument("--episode-ids", nargs="*", default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--allow-full", action="store_true")
    args = parser.parse_args()

    run_input_gate()
    all_cases = load_cases()
    if args.codes:
        codes = {c.zfill(6) for c in args.codes}
        cases = [c for c in all_cases if c.symbol in codes]
    elif args.episode_ids:
        ids = set(args.episode_ids)
        cases = [c for c in all_cases if c.episode_id in ids]
    else:
        if not args.allow_full:
            raise RuntimeError(
                "full 8,682-row extraction requires --allow-full (not used in R2A)"
            )
        cases = all_cases
    if not cases:
        raise RuntimeError("no cases selected")
    frame = extract_to_frame(cases)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(args.out, index=False)
        print(f"wrote {len(frame)} rows -> {args.out}")
    else:
        print(frame.head(3).to_string(index=False))


if __name__ == "__main__":
    main()
