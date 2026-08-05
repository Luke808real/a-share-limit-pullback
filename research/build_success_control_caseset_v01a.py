"""SUCCESS_CONTROL_CASESET_V01A — event alignment fix (research-only).

Keeps the 8,746 V01 cases and their outcomes unchanged. Adds:
- PIT_CANDIDATE_ELIGIBLE (D-1 fields only) vs OUTCOME_EVALUABLE
  (future_sessions_available >= 3, label-availability only);
- OUTCOME_EVENT_DATE / EVENT_SESSION_OFFSET for SUCCESS / FAILED_BREAKOUT
  (first S1 touch day) and STRUCTURE_FAIL (first invalid touch day);
- EVENT_INTRADAY_AVAILABLE based on OUTCOME_EVENT_DATE (sina 1m window,
  ESTIMATED; not per-case fetched);
- provenance columns quality_flags / data_quality plus D-1 geometry
  candidate_close / dist_to_s1_pct / dist_to_invalid_pct;
- V02_EVENT_COHORT = SUCCESS/FAILED_BREAKOUT with event date + event intraday.

No outcome redefinition, no threshold scan, no production changes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "intraday"
OUT_DIR.mkdir(parents=True, exist_ok=True)

EPISODES_PATH = (
    ROOT
    / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/episodes.parquet"
)
BARS_PATH = ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"

EPISODES_HASH = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
DATA_CUTOFF = "2026-07-31 (frozen snapshot snap-2026-07-31-b5f84004de8a)"
INTRADAY_WINDOW = (date(2026, 6, 5), date(2026, 8, 4))  # sina 1m availability window
VALID_STAGES = {"B1_READY", "B2_READY", "B2_CONFIRMED"}


def load_name_map() -> dict[str, str]:
    names: dict[str, str] = {}
    for path in sorted(ROOT.glob("data/canonical/limit_up_pool/*.parquet")):
        df = pd.read_parquet(path, columns=["code", "name"])
        for code, name in zip(df["code"], df["name"], strict=False):
            if isinstance(name, str) and name.strip():
                names[str(code).zfill(6)] = name.strip()
    return names


def load_bars_by_code() -> dict[str, pd.DataFrame]:
    df = pd.read_parquet(
        BARS_PATH, columns=["code", "trade_date", "open", "high", "low", "close", "volume"]
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["code"] = df["code"].astype(str).str.zfill(6)
    out: dict[str, pd.DataFrame] = {}
    for code, group in df.groupby("code", sort=False):
        out[code] = group.sort_values("trade_date").reset_index(drop=True)
    return out


def classify(
    pattern: str | None,
    horizon: pd.DataFrame,
    s1: float,
    invalid: float,
    signal_volume: float | None,
) -> tuple[str, str, str | None, int | None]:
    """Returns (outcome, reason, event_date, event_offset)."""
    if pattern is None:
        return "UNKNOWN", "pattern_3d missing", None, None
    if pattern == "AMBIGUOUS":
        return "UNKNOWN", "pattern_3d AMBIGUOUS (same-day S1/invalid order unknown)", None, None
    if len(horizon) == 0 or signal_volume is None:
        return "UNKNOWN", "daily bars missing for horizon or signal day", None, None
    s1_day = horizon[horizon["high"] >= s1]
    invalid_day = horizon[horizon["low"] <= invalid]
    if pattern == "NEITHER":
        return "NO_LAUNCH", "no S1 and no invalid touch within 3 sessions", None, None
    if pattern == "INVALID_BEFORE_S1":
        if len(invalid_day) == 0:
            return "UNKNOWN", "INVALID_BEFORE_S1 flagged but no invalid-touch bar found", None, None
        row = invalid_day.iloc[0]
        idx = horizon.index.get_loc(row.name)
        return (
            "STRUCTURE_FAIL",
            "invalid first within 3 sessions",
            row["trade_date"].isoformat(),
            int(idx + 1),
        )
    if pattern == "S1_BEFORE_INVALID":
        if len(s1_day) == 0:
            return "UNKNOWN", "S1_BEFORE_INVALID flagged but no S1-touch bar found", None, None
        row = s1_day.iloc[0]
        idx = horizon.index.get_loc(row.name)
        event_date = row["trade_date"].isoformat()
        offset = int(idx + 1)
        close_ok = float(row["close"]) >= s1
        vol_ok = float(row["volume"]) >= signal_volume
        if close_ok and vol_ok:
            return "SUCCESS", "S1 first + close>=S1 + volume>=signal-day volume", event_date, offset
        if not close_ok:
            return (
                "FAILED_BREAKOUT",
                f"S1 touched but close {row['close']:.2f} < S1 {s1:.2f}",
                event_date,
                offset,
            )
        return (
            "FAILED_BREAKOUT",
            "S1 close accepted but volume < signal-day volume",
            event_date,
            offset,
        )
    return "UNKNOWN", f"pattern_3d={pattern!r}", None, None


def main() -> None:
    ep = pd.read_parquet(EPISODES_PATH)
    ep["signal_date"] = pd.to_datetime(ep["signal_date"]).dt.date
    ep["next_trade_date"] = pd.to_datetime(ep["next_trade_date"]).dt.date
    ep["anchor_date"] = pd.to_datetime(ep["anchor_date"]).dt.date
    ep["code"] = ep["code"].astype(str).str.zfill(6)

    # PIT eligibility uses D-1 fields only (no future_sessions_available).
    pit_mask = (
        ep["setup_stage"].isin(VALID_STAGES)
        & ep["invalid_price"].notna()
        & ep["s1_price"].notna()
        & (ep["data_quality"] != "UNUSABLE")
    )
    pit_rows = ep[pit_mask]
    outcome_ok = pit_rows["future_sessions_available"] >= 3
    sel = pit_rows[outcome_ok].copy()

    # Keep exactly the V01 main sample: earliest candidate per anchor.
    cases = sel.sort_values("signal_date").drop_duplicates(subset=["setup_id"], keep="first")
    sibling_counts = sel["setup_id"].value_counts()

    names = load_name_map()
    bars = load_bars_by_code()
    rows = []
    for _, c in cases.iterrows():
        code = c["code"]
        sig_date = c["signal_date"]
        s1 = float(c["s1_price"])
        invalid = float(c["invalid_price"])
        code_bars = bars.get(code)
        if code_bars is None:
            outcome, reason, event_date, offset = "UNKNOWN", "no daily bars for code", None, None
            sig_vol = None
            candidate_close = None
        else:
            sig_bar = code_bars[code_bars["trade_date"] == sig_date]
            sig_vol = float(sig_bar.iloc[0]["volume"]) if len(sig_bar) else None
            candidate_close = float(sig_bar.iloc[0]["close"]) if len(sig_bar) else None
            horizon = code_bars[code_bars["trade_date"] > sig_date].head(3)
            outcome, reason, event_date, offset = classify(
                c["pattern_3d"], horizon, s1, invalid, sig_vol
            )
        dist_s1 = (candidate_close / s1 - 1.0) * 100.0 if candidate_close else None
        dist_inv = (candidate_close / invalid - 1.0) * 100.0 if candidate_close else None
        event_intraday = (
            event_date is not None
            and INTRADAY_WINDOW[0] <= date.fromisoformat(event_date) <= INTRADAY_WINDOW[1]
        )
        next_session = c["next_trade_date"]
        next_intraday = INTRADAY_WINDOW[0] <= next_session <= INTRADAY_WINDOW[1]
        v02_cohort = bool(
            outcome in {"SUCCESS", "FAILED_BREAKOUT"}
            and event_date is not None
            and event_intraday
        )
        rows.append(
            {
                "episode_id": c["setup_id"],
                "symbol": code,
                "name": names.get(code, ""),
                "candidate_date": sig_date.isoformat(),
                "trade_date": next_session.isoformat(),
                "NEXT_SESSION_DATE": next_session.isoformat(),
                "anchor_date": c["anchor_date"].isoformat(),
                "candidate_state": c["setup_stage"],
                "selection_source": (
                    f"corrected-episodes {EPISODES_HASH[:16]}... + "
                    "outcome-study execution-reality"
                ),
                "selection_reason": (
                    "frozen lifecycle candidate (B1_READY/B2_READY/B2_CONFIRMED) "
                    "at D-1 close with valid invalid+S1; earliest candidate per anchor"
                ),
                "PIT_CANDIDATE_ELIGIBLE": True,
                "OUTCOME_EVALUABLE": bool(c["future_sessions_available"] >= 3),
                "outcome": outcome,
                "outcome_reason": reason,
                "OUTCOME_EVENT_DATE": event_date,
                "EVENT_SESSION_OFFSET": offset,
                "EVENT_INTRADAY_AVAILABLE": bool(event_intraday),
                "NEXT_SESSION_INTRADAY_AVAILABLE_ESTIMATED": bool(next_intraday),
                "V02_EVENT_COHORT": v02_cohort,
                "data_cutoff": DATA_CUTOFF,
                "pit_valid": True,
                "invalid_price": round(invalid, 4),
                "s1_price": round(s1, 4),
                "candidate_close": round(candidate_close, 4) if candidate_close else None,
                "dist_to_s1_pct": round(dist_s1, 4) if dist_s1 is not None else None,
                "dist_to_invalid_pct": round(dist_inv, 4) if dist_inv is not None else None,
                "b2_trigger_price": round(float(c["b2_trigger_price"]), 4)
                if pd.notna(c["b2_trigger_price"])
                else None,
                "pattern_3d": c["pattern_3d"],
                "setup_quality_score": round(float(c["setup_quality_score"]), 2)
                if pd.notna(c["setup_quality_score"])
                else None,
                "entry_quality_score": round(float(c["entry_quality_score"]), 2)
                if pd.notna(c["entry_quality_score"])
                else None,
                "data_quality": c["data_quality"],
                "quality_flags": c["quality_flags"],
                "duplicate_check": 1,
                "same_anchor_sibling_count": int(sibling_counts.get(c["setup_id"], 1) - 1),
            }
        )

    out = pd.DataFrame(rows)
    out.to_csv(OUT_DIR / "success_control_cases_v01a.csv", index=False)

    success = out["outcome"] == "SUCCESS"
    failed = out["outcome"] == "FAILED_BREAKOUT"
    offsets = out.loc[success | failed, "EVENT_SESSION_OFFSET"].value_counts()
    missing_event = int(out.loc[success | failed, "OUTCOME_EVENT_DATE"].isna().sum())
    flags_cov = out["quality_flags"].notna().mean()
    inferred = out["quality_flags"].astype(str).str.contains("INFERRED_LIMIT_ANCHOR").mean()
    print("TOTAL_CASES:", len(out))
    print("PIT_CANDIDATE_ELIGIBLE_N:", int(out["PIT_CANDIDATE_ELIGIBLE"].sum()))
    print("OUTCOME_EVALUABLE_N:", int(out["OUTCOME_EVALUABLE"].sum()))
    print("SUCCESS_N:", int(success.sum()), "FAILED_BREAKOUT_N:", int(failed.sum()))
    print(
        "SUCCESS_EVENT_INTRADAY_N:",
        int((success & out["EVENT_INTRADAY_AVAILABLE"]).sum()),
    )
    print(
        "FAILED_BREAKOUT_EVENT_INTRADAY_N:",
        int((failed & out["EVENT_INTRADAY_AVAILABLE"]).sum()),
    )
    print("EVENT_OFFSET:", offsets.sort_index().to_dict())
    print("MISSING_EVENT_DATE:", missing_event)
    print("QUALITY_FLAG_COVERAGE:", round(float(flags_cov), 4),
          "INFERRED_SHARE:", round(float(inferred), 4))
    print("V02_EVENT_COHORT_N:", int(out["V02_EVENT_COHORT"].sum()))
    print("V02 cohort by outcome:")
    print(out.loc[out["V02_EVENT_COHORT"], "outcome"].value_counts().to_string())
    # PIT-eligible but NOT outcome-evaluable anchors (for transparency)
    not_eval = pit_rows[~outcome_ok].sort_values("signal_date").drop_duplicates(
        subset=["setup_id"], keep="first"
    )
    print("PIT-eligible but NOT outcome-evaluable anchors:", len(not_eval))


if __name__ == "__main__":
    main()
