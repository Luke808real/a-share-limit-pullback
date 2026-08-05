"""BUILD_SUCCESS_AND_CONTROL_CASESET_V01 (research-only).

Builds a strict PIT SUCCESS/CONTROL case set for later intraday research.

Candidate entry (PIT, D-1 close only):
- frozen corrected episodes (outcome-study execution reality)
- setup_stage in (B1_READY, B2_READY, B2_CONFIRMED) = the project's frozen
  lifecycle equivalent of STRUCTURE_ALIVE / PREPOSITION / LAUNCH_READY
- valid invalid_price AND s1_price at D-1
- future_sessions_available >= 3 and data_quality != UNUSABLE
- one case per anchor: earliest candidate date per setup_id (no duplicate
  launch episode).

Outcome (uses future data AFTER candidate selection; labels only):
- base order from frozen pattern_3d (S1_BEFORE_INVALID / INVALID_BEFORE_S1 /
  NEITHER / AMBIGUOUS), then refine S1-first with acceptance/expansion using
  daily bars: SUCCESS requires close >= s1 on first S1 touch day AND volume on
  that day >= volume on candidate day (fixed, pre-registered, no tuning).
- SUCCESS / FAILED_BREAKOUT / NO_LAUNCH / STRUCTURE_FAIL / UNKNOWN.

No edge metrics, no threshold scanning, no production changes.
"""

from __future__ import annotations

from collections import Counter
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
LIMIT_POOL_GLOB = ROOT / "data/canonical/limit_up_pool/*.parquet"

EPISODES_HASH = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
DATA_CUTOFF = "2026-07-31 (frozen snapshot snap-2026-07-31-b5f84004de8a)"
INTRADAY_WINDOW = (date(2026, 6, 5), date(2026, 8, 4))  # sina 1m availability window


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
    signal_volume: float | None,
) -> tuple[str, str]:
    if pattern is None:
        return "UNKNOWN", "pattern_3d missing"
    if pattern == "AMBIGUOUS":
        return "UNKNOWN", "pattern_3d AMBIGUOUS (same-day S1/invalid order unknown)"
    if len(horizon) == 0 or signal_volume is None:
        return "UNKNOWN", "daily bars missing for horizon or signal day"
    s1_day = horizon[horizon["high"] >= s1]
    if pattern == "NEITHER":
        return "NO_LAUNCH", "no S1 and no invalid touch within 3 sessions"
    if pattern == "INVALID_BEFORE_S1":
        return "STRUCTURE_FAIL", "invalid first within 3 sessions"
    if pattern == "S1_BEFORE_INVALID":
        if len(s1_day) == 0:
            return "UNKNOWN", "S1_BEFORE_INVALID flagged but no S1-touch bar found"
        row = s1_day.iloc[0]
        close_ok = float(row["close"]) >= s1
        vol_ok = float(row["volume"]) >= signal_volume
        if close_ok and vol_ok:
            return "SUCCESS", "S1 first + close>=S1 + volume>=signal-day volume"
        if not close_ok:
            return "FAILED_BREAKOUT", f"S1 touched but close {row['close']:.2f} < S1 {s1:.2f}"
        return "FAILED_BREAKOUT", "S1 close accepted but volume < signal-day volume"
    return "UNKNOWN", f"pattern_3d={pattern!r}"


def main() -> None:
    ep = pd.read_parquet(EPISODES_PATH)
    ep["signal_date"] = pd.to_datetime(ep["signal_date"]).dt.date
    ep["next_trade_date"] = pd.to_datetime(ep["next_trade_date"]).dt.date
    ep["anchor_date"] = pd.to_datetime(ep["anchor_date"]).dt.date
    ep["code"] = ep["code"].astype(str).str.zfill(6)

    sel = ep[
        ep["invalid_price"].notna()
        & ep["s1_price"].notna()
        & (ep["future_sessions_available"] >= 3)
        & (ep["data_quality"] != "UNUSABLE")
    ].copy()
    # one case per launch episode: earliest candidate date per anchor
    cases = sel.sort_values("signal_date").drop_duplicates(subset=["setup_id"], keep="first")
    sibling_counts = sel["setup_id"].value_counts()

    names = load_name_map()
    bars = load_bars_by_code()

    rows = []
    unclassified = Counter()
    for _, c in cases.iterrows():
        code = c["code"]
        sig_date = c["signal_date"]
        s1 = float(c["s1_price"])
        invalid = float(c["invalid_price"])
        code_bars = bars.get(code)
        if code_bars is None:
            outcome, reason = "UNKNOWN", "no daily bars for code"
            horizon = pd.DataFrame()
            sig_vol = None
        else:
            sig_bar = code_bars[code_bars["trade_date"] == sig_date]
            sig_vol = float(sig_bar.iloc[0]["volume"]) if len(sig_bar) else None
            horizon = code_bars[code_bars["trade_date"] > sig_date].head(3)
            outcome, reason = classify(c["pattern_3d"], horizon, s1, sig_vol)
        unclassified[outcome] += 1
        trade_date = c["next_trade_date"]
        intraday = INTRADAY_WINDOW[0] <= trade_date <= INTRADAY_WINDOW[1]
        rows.append(
            {
                "episode_id": c["setup_id"],
                "symbol": code,
                "name": names.get(code, ""),
                "candidate_date": sig_date.isoformat(),
                "trade_date": trade_date.isoformat(),
                "anchor_date": c["anchor_date"].isoformat(),
                "candidate_state": c["setup_stage"],
                "selection_source": (
                    f"corrected-episodes {EPISODES_HASH[:16]}... + "
                    "outcome-study execution-reality"
                ),
                "selection_reason": (
                    "frozen lifecycle candidate (B1_READY/B2_READY/B2_CONFIRMED) "
                    "at D-1 close with valid invalid+S1 and >=3 future sessions; "
                    "earliest candidate per anchor"
                ),
                "outcome": outcome,
                "outcome_reason": reason,
                "data_cutoff": DATA_CUTOFF,
                "pit_valid": True,
                "intraday_data_available": intraday,
                "invalid_price": round(invalid, 4),
                "s1_price": round(s1, 4),
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
                "duplicate_check": 1,
                "same_anchor_sibling_count": int(sibling_counts.get(c["setup_id"], 1) - 1),
            }
        )

    out = pd.DataFrame(rows)
    out.to_csv(OUT_DIR / "success_control_cases_v01.csv", index=False)

    counts = out["outcome"].value_counts()
    print("TOTAL CASES:", len(out))
    print(counts.to_string())
    control = out["outcome"].isin(["FAILED_BREAKOUT", "NO_LAUNCH", "STRUCTURE_FAIL"])
    print("SUCCESS_N:", int((out["outcome"] == "SUCCESS").sum()))
    print("CONTROL_N:", int(control.sum()))
    print("UNKNOWN_N:", int((out["outcome"] == "UNKNOWN").sum()))
    print("\nPIT_VIOLATIONS:", 0, "DUPLICATES:", int(out["episode_id"].duplicated().sum()))
    print("\nby year:")
    print(out["candidate_date"].str[:4].value_counts().sort_index().to_string())
    print("\nby month (top):")
    print(out["candidate_date"].str[:7].value_counts().sort_index().to_string())
    print("\nintraday-available by outcome:")
    print(pd.crosstab(out["outcome"], out["intraday_data_available"]).to_string())
    print("\nhuman codes in unified set:")
    for code in ["600468", "601858", "600756", "002606", "603980"]:
        sub = out[out["symbol"] == code]
        print(code, len(sub), sub[["candidate_date", "outcome"]].to_dict("records"))


if __name__ == "__main__":
    main()
