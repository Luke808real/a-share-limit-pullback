"""Setup-level survival analysis for TTL (v01).

Per setup (setup_id): time to first B2 signal (d_b2), win flag (any WIN_S1 row),
and an approximate observation horizon. Outputs:
- Kaplan-Meier curve of first-B2 firing (days since anchor)
- P(B2 by day 10 | no B2 by day D) for D=1..9  (the real TTL quantity)
- win share by first-B2 day

Censoring approximation (stated honestly in the report): the episodes carry
actionable signals only; a setup without a B2 row by the sample end is
censored when its anchor is within 10 trading days of 2026-07-31, and the
horizon is 10 trading days. This is NOT a daily tracked lineage.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

EPISODES = Path(
    "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    "/corrected-b2-trigger-outcome/episodes.parquet"
)
EXPECTED_SHA = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
SAMPLE_END = date(2026, 7, 31)
HORIZON = 10
OUT_DIR = Path("research/factor-lab/runs/ttl-survival-v01")


def business_days(start: date, end: date) -> int:
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(EPISODES.read_bytes()).hexdigest()
    if sha != EXPECTED_SHA:
        raise SystemExit(f"hash mismatch: {sha}")

    con = duckdb.connect()
    rows = con.execute(
        "SELECT setup_id, setup_stage, anchor_date, days_since_anchor, outcome "
        "FROM read_parquet(?)",
        [str(EPISODES)],
    ).fetchall()

    setups: dict[str, dict] = {}
    for setup_id, stage, anchor_s, days, outcome in rows:
        anchor = date.fromisoformat(str(anchor_s))
        s = setups.setdefault(
            setup_id,
            {"anchor": anchor, "days": [], "outcomes": [], "b2_days": []},
        )
        s["days"].append(int(days))
        s["outcomes"].append(outcome)
        if stage in ("B2_READY", "B2_CONFIRMED"):
            s["b2_days"].append(int(days))

    n_setups = len(setups)
    n_b2 = 0
    n_win = 0
    n_censored = 0
    records: list[dict] = []
    for s in setups.values():
        d_b2 = min(s["b2_days"]) if s["b2_days"] else None
        won = "WIN_S1" in s["outcomes"]
        d_obs = business_days(s["anchor"], SAMPLE_END)
        censored = d_b2 is None and d_obs < HORIZON
        if censored:
            n_censored += 1
        if d_b2 is not None:
            n_b2 += 1
        if won:
            n_win += 1
        records.append(
            {
                "anchor": s["anchor"].isoformat(),
                "d_obs": min(d_obs, HORIZON) if not censored else d_obs,
                "censored": censored,
                "d_b2": d_b2,
                "won": won,
            }
        )

    # Kaplan-Meier for first B2 firing (uncensored-completeness: horizon 10)
    km: dict[str, float] = {}
    at_risk = sum(1 for r in records if r["d_obs"] >= HORIZON)
    survived = at_risk
    for d in range(1, HORIZON + 1):
        fired = sum(
            1
            for r in records
            if r["d_obs"] >= HORIZON and r["d_b2"] == d
        )
        if survived > 0:
            survived -= fired
            km[str(d)] = round(survived / at_risk, 4)
        else:
            km[str(d)] = 0.0

    # P(B2 by day 10 | no B2 by day D) — TTL quantity
    conditional: dict[str, dict] = {}
    full_obs = [r for r in records if r["d_obs"] >= HORIZON]
    for d in range(1, HORIZON):
        waited = [r for r in full_obs if r["d_b2"] is None or r["d_b2"] > d]
        if not waited:
            continue
        fired_later = sum(1 for r in waited if r["d_b2"] is not None)
        conditional[str(d)] = {
            "no_b2_by_day": len(waited),
            "fired_by_day10": fired_later,
            "share": round(fired_later / len(waited), 4),
        }

    # win share by first-B2 day
    win_by_day: dict[str, dict] = {}
    for d in range(1, HORIZON + 1):
        group = [r for r in full_obs if r["d_b2"] == d]
        if len(group) >= 20:
            win_by_day[str(d)] = {
                "n": len(group),
                "win_share": round(sum(1 for r in group if r["won"]) / len(group), 4),
            }

    payload = {
        "inputs": {"episodes": str(EPISODES), "sha256": sha, "sample_end": SAMPLE_END.isoformat()},
        "population": {
            "setups": n_setups,
            "with_b2": n_b2,
            "with_win": n_win,
            "censored": n_censored,
            "horizon_trading_days": HORIZON,
        },
        "km_first_b2": km,
        "conditional_fire_by_day10": conditional,
        "win_share_by_first_b2_day": win_by_day,
    }
    out = OUT_DIR / "ttl-survival-v01.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
