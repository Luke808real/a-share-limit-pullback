"""SUCCESS_CONTROL_CASESET_V01B — consistency fix (research-only).

Outcome immutability:
- outcome comes exclusively from success_control_cases_v01.csv (episode_id key);
- V01A's 76 rows where V01=STRUCTURE_FAIL but V01A=UNKNOWN are restored to
  STRUCTURE_FAIL; event date is separated from outcome (never re-classify).

Event alignment (kept from V01A):
- SUCCESS/FAILED_BREAKOUT: OUTCOME_EVENT_DATE = first S1 touch day within the
  3-session horizon from canonical bars; EVENT_DATE_STATUS = RESOLVED_CANONICAL_S1_TOUCH.
- STRUCTURE_FAIL: first invalid touch day if rebuildable (RESOLVED_CANONICAL),
  else NA + PATTERN_ONLY_EVENT_UNRESOLVED (outcome unchanged).
- NO_LAUNCH/UNKNOWN: NA + N/A.

Hard assertions fail (no CSV/report) if parity or counts deviate.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "intraday"
EPISODES_PATH = (
    ROOT
    / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/episodes.parquet"
)
BARS_PATH = ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"
V01_PATH = OUT_DIR / "success_control_cases_v01.csv"
V01A_PATH = OUT_DIR / "success_control_cases_v01a.csv"
V01B_PATH = OUT_DIR / "success_control_cases_v01b.csv"

INTRADAY_WINDOW = (date(2026, 6, 5), date(2026, 8, 4))
EXPECTED_COUNTS = {
    "SUCCESS": 409,
    "FAILED_BREAKOUT": 950,
    "NO_LAUNCH": 1730,
    "STRUCTURE_FAIL": 5415,
    "UNKNOWN": 242,
}


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


def main() -> None:
    v01 = pd.read_csv(V01_PATH, dtype={"symbol": str})
    v01a = pd.read_csv(V01A_PATH, dtype={"symbol": str})
    v01_outcomes = dict(zip(v01["episode_id"], v01["outcome"], strict=False))
    v01_reasons = dict(zip(v01["episode_id"], v01["outcome_reason"], strict=False))

    ep = pd.read_parquet(EPISODES_PATH)
    ep["code"] = ep["code"].astype(str).str.zfill(6)
    ep["signal_date"] = pd.to_datetime(ep["signal_date"]).dt.date
    levels = dict(
        zip(
            ep["setup_id"],
            zip(ep["invalid_price"], ep["s1_price"], ep["signal_date"]),
            strict=False,
        )
    )
    bars = load_bars_by_code()

    out = v01a.copy()
    out["outcome"] = out["episode_id"].map(v01_outcomes)
    out["outcome_reason"] = out["episode_id"].map(v01_reasons)
    out["event_date"] = None
    out["event_offset"] = None
    out["EVENT_DATE_STATUS"] = "N/A"

    for i, row in out.iterrows():
        code = str(row["symbol"]).zfill(6)
        sig_date = date.fromisoformat(row["candidate_date"])
        levels_row = levels.get(row["episode_id"])
        if levels_row is None:
            out.loc[i, "EVENT_DATE_STATUS"] = "PATTERN_ONLY_EVENT_UNRESOLVED"
            continue
        invalid, s1, _ = levels_row
        code_bars = bars.get(code)
        if code_bars is None:
            if row["outcome"] == "STRUCTURE_FAIL":
                out.loc[i, "EVENT_DATE_STATUS"] = "PATTERN_ONLY_EVENT_UNRESOLVED"
            elif row["outcome"] in {"SUCCESS", "FAILED_BREAKOUT"}:
                out.loc[i, "EVENT_DATE_STATUS"] = "UNRESOLVED_BARS"
            continue
        horizon = code_bars[code_bars["trade_date"] > sig_date].head(3).reset_index(drop=True)
        if row["outcome"] in {"SUCCESS", "FAILED_BREAKOUT"}:
            hit = horizon[horizon["high"] >= float(s1)]
            if len(hit):
                idx = horizon.index[horizon["high"] >= float(s1)][0]
                out.loc[i, "event_date"] = hit.iloc[0]["trade_date"].isoformat()
                out.loc[i, "event_offset"] = int(idx + 1)
                out.loc[i, "EVENT_DATE_STATUS"] = "RESOLVED_CANONICAL_S1_TOUCH"
            else:
                out.loc[i, "EVENT_DATE_STATUS"] = "UNRESOLVED_BARS"
        elif row["outcome"] == "STRUCTURE_FAIL":
            hit = horizon[horizon["low"] <= float(invalid)]
            if len(hit):
                idx = horizon.index[horizon["low"] <= float(invalid)][0]
                out.loc[i, "event_date"] = hit.iloc[0]["trade_date"].isoformat()
                out.loc[i, "event_offset"] = int(idx + 1)
                out.loc[i, "EVENT_DATE_STATUS"] = "RESOLVED_CANONICAL"
            else:
                out.loc[i, "EVENT_DATE_STATUS"] = "PATTERN_ONLY_EVENT_UNRESOLVED"

    out["OUTCOME_EVENT_DATE"] = out["event_date"]
    out["EVENT_SESSION_OFFSET"] = out["event_offset"]
    out.drop(columns=["event_date", "event_offset"], inplace=True)
    out["EVENT_INTRADAY_AVAILABLE"] = out["OUTCOME_EVENT_DATE"].apply(
        lambda d: bool(
            isinstance(d, str)
            and INTRADAY_WINDOW[0] <= date.fromisoformat(d) <= INTRADAY_WINDOW[1]
        )
    )
    out["V02_EVENT_COHORT"] = (
        out["outcome"].isin(["SUCCESS", "FAILED_BREAKOUT"])
        & out["OUTCOME_EVENT_DATE"].notna()
        & out["EVENT_INTRADAY_AVAILABLE"]
    )

    # hard assertions
    assert len(out) == 8746, f"rows={len(out)}"
    assert out["episode_id"].duplicated().sum() == 0
    merged = out.merge(v01[["episode_id", "outcome"]], on="episode_id", how="outer", suffixes=("", "_v01"))
    assert merged["outcome"].isna().sum() == 0, "missing V01 episode"
    assert merged["outcome_v01"].isna().sum() == 0, "extra episode not in V01"
    mismatch = int((merged["outcome"] != merged["outcome_v01"]).sum())
    assert mismatch == 0, f"outcome mismatch={mismatch}"
    counts = out["outcome"].value_counts().to_dict()
    for key, expected in EXPECTED_COUNTS.items():
        assert counts.get(key, 0) == expected, f"{key}={counts.get(key,0)} != {expected}"

    out.to_csv(V01B_PATH, index=False)
    success_n = int((out["outcome"] == "SUCCESS").sum())
    failed_n = int((out["outcome"] == "FAILED_BREAKOUT").sum())
    success_intraday = int(
        ((out["outcome"] == "SUCCESS") & out["EVENT_INTRADAY_AVAILABLE"]).sum()
    )
    failed_intraday = int(
        ((out["outcome"] == "FAILED_BREAKOUT") & out["EVENT_INTRADAY_AVAILABLE"]).sum()
    )
    structurally_ready = success_intraday >= 20 and failed_intraday >= 20
    print("OUTCOME_PARITY_WITH_V01:", mismatch == 0)
    print("OUTCOME_MISMATCH_N:", mismatch)
    print("TOTAL_CASES:", len(out))
    print("OUTCOME_COUNTS:", counts)
    print("SUCCESS_N:", success_n, "FAILED_BREAKOUT_N:", failed_n)
    print("SUCCESS_EVENT_INTRADAY_N:", success_intraday)
    print("FAILED_BREAKOUT_EVENT_INTRADAY_N:", failed_intraday)
    print("EVENT_COHORT_STRUCTURALLY_READY:", structurally_ready)
    print("MINUTE_DATA_VERIFIED: false")
    print("READY_FOR_INTRADAY_V02A: false")
    print("EVENT_DATE_STATUS counts:")
    print(out["EVENT_DATE_STATUS"].value_counts(dropna=False).to_string())
    pattern_only_fail = int(
        (
            (out["outcome"] == "STRUCTURE_FAIL")
            & (out["EVENT_DATE_STATUS"] == "PATTERN_ONLY_EVENT_UNRESOLVED")
        ).sum()
    )
    print("restored STRUCTURE_FAIL rows with PATTERN_ONLY:", pattern_only_fail)


if __name__ == "__main__":
    main()
