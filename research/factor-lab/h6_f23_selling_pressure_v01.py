"""H6 F23 pullback selling-pressure study v01 (research / validation only).

Question: is F23 — down-close + up-volume sessions during the pullback
window after T0 — a negative structural factor for second-launch success?

F23 pure function: limit_pullback.factor_lab.pullback_down_volume_count
(bars, anchor_date, as_of) — count of visible sessions i after T0 through
as_of with close(i) < close(i-1) AND volume(i) > volume(i-1). F23_ANY =
count >= 1, used ONLY as a pre-registered grouping. No threshold search.

Primary comparison: F23_ANY=false vs F23_ANY=true over frozen resolved
episodes (WIN_S1 union LOSS_INVALID union CANCEL_GAP_INVALID). R source =
episodes.r_multiple (Phase 2D.0 corrected outcome study, strict variant,
same field the frozen baseline E[R] table was computed from).

DESCRIPTIVE ONLY. No thresholds tuned, no promotion, no model rebuild.
Frozen inputs: episodes SHA 66d5943f... + snap-2026-07-31-b5f84004de8a.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from collections import namedtuple
from datetime import date
from pathlib import Path

import duckdb

from limit_pullback import factor_lab as fl

EPISODES = Path(
    "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    "/corrected-b2-trigger-outcome/episodes.parquet"
)
EXPECTED_SHA = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
DAILY_BARS = Path("data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet")
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
OUT_DIR = Path("research/factor-lab/runs/h6-f23-v01")
GROUPS = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")
WIN = "WIN_S1"
LOSS = "LOSS_INVALID"
CANCEL = "CANCEL_GAP_INVALID"
MIN_N = 20
STAGES = ("B1_READY", "B2_READY", "B2_CONFIRMED")
STARTED = time.time()

# Lightweight bar carrier: only the fields pullback_down_volume_count reads.
Bar = namedtuple("Bar", "code trade_date close volume")


def _log(msg: str) -> None:
    print(f"[{time.time() - STARTED:7.1f}s] {msg}", file=sys.stderr, flush=True)


def parse_r(value) -> float | None:
    """Fail-closed parse of r_multiple (H10 audit-fixed contract).

    None -> None; unparseable -> ValueError; non-finite -> ValueError.
    """
    if value is None:
        return None
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"non-finite r_multiple: {value!r}")
    return v


def _median(values) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def _cell(rows: list[dict]) -> dict:
    """One group cell. Counts are always reported; interpreted stats are
    None when the corresponding denominator is below MIN_N (small-cell
    null; do not interpret small cells)."""
    n = len(rows)
    wins = sum(1 for r in rows if r["outcome"] == WIN)
    losses = sum(1 for r in rows if r["outcome"] == LOSS)
    cancels = n - wins - losses
    strict_denom = wins + losses
    r_values = [
        r["r"]
        for r in rows
        if r["outcome"] in (WIN, LOSS) and r["r"] is not None
    ]
    cell = {
        "n": n,
        "win": wins,
        "loss": losses,
        "cancel_gap_invalid": cancels,
        "win_share": None,
        "strict_win_rate": None,
        "mean_r": None,
        "median_r": None,
        "p_r_gt0": None,
        "p_r_ge2": None,
        "n_with_r": len(r_values),
        "r_missing_n": strict_denom - len(r_values),
    }
    if n >= MIN_N:
        cell["win_share"] = round(wins / n, 4)
    if strict_denom >= MIN_N:
        cell["strict_win_rate"] = round(wins / strict_denom, 4)
    if len(r_values) >= MIN_N:
        total = sum(r_values)
        cell["mean_r"] = round(total / len(r_values), 4)
        cell["median_r"] = round(_median(r_values), 4)
        cell["p_r_gt0"] = round(sum(1 for v in r_values if v > 0) / len(r_values), 4)
        cell["p_r_ge2"] = round(sum(1 for v in r_values if v >= 2) / len(r_values), 4)
    return cell


def _deltas(cell_any: dict, cell_none: dict) -> dict:
    out: dict[str, float | None] = {}
    for key in ("win_share", "strict_win_rate", "mean_r", "median_r"):
        a, b = cell_any[key], cell_none[key]
        out[key] = round(a - b, 4) if a is not None and b is not None else None
    return out


def _bucket(days: int) -> str:
    if days <= 2:
        return "1-2"
    if days <= 3:
        return "3"
    if days <= 5:
        return "4-5"
    return "6-10"


def _group_comparison(rows: list[dict]) -> dict:
    any_rows = [r for r in rows if r["count"] >= 1]
    none_rows = [r for r in rows if r["count"] == 0]
    cell_any = _cell(any_rows)
    cell_none = _cell(none_rows)
    return {
        "any": cell_any,
        "none": cell_none,
        "delta": _deltas(cell_any, cell_none),
    }


def _verdict(primary: dict, stage: dict, timing: dict) -> str:
    """Pre-registered mechanical verdict.

    Hypothesis: F23_ANY=true (selling pressure during pullback) is NEGATIVE
    for second-launch success, i.e. lower win_share and lower mean_R.

    REJECT: primary win_share delta is defined and >= 0 (direction absent
    or opposite on the primary metric).
    SUPPORTED: primary win_share delta < 0 AND primary mean_R delta < 0
    when defined AND every stage/timing stratum whose delta is defined
    also has win_share delta < 0 (direction stable across strata).
    Otherwise OBSERVE_ONLY.
    """
    p_ws = primary["delta"].get("win_share")
    if p_ws is None:
        return "OBSERVE_ONLY"
    if p_ws >= 0:
        return "REJECT"
    p_mr = primary["delta"].get("mean_r")
    if p_mr is not None and p_mr >= 0:
        return "OBSERVE_ONLY"
    for strata in (stage, timing):
        for cell in strata.values():
            ws = cell["delta"].get("win_share")
            if ws is not None and ws >= 0:
                return "OBSERVE_ONLY"
    return "SUPPORTED"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    episodes_sha = hashlib.sha256(EPISODES.read_bytes()).hexdigest()
    if episodes_sha != EXPECTED_SHA:
        raise SystemExit(f"episodes hash mismatch: {episodes_sha}")
    bars_sha = hashlib.sha256(DAILY_BARS.read_bytes()).hexdigest()
    script_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    _log("input hashes verified")

    con = duckdb.connect()
    con.execute(
        "CREATE TEMP TABLE eps AS "
        "SELECT row_number() OVER () AS rid, code, setup_stage, "
        "CAST(anchor_date AS DATE) AS anchor_date, "
        "CAST(signal_date AS DATE) AS signal_date, "
        "outcome, r_multiple, days_since_anchor "
        "FROM read_parquet(?) WHERE outcome IN (?, ?, ?)",
        [str(EPISODES), WIN, LOSS, CANCEL],
    )
    resolved_n = con.execute("SELECT count(*) FROM eps").fetchone()[0]
    _log(f"resolved episodes: {resolved_n}")

    con.execute(
        "CREATE TEMP TABLE bars AS "
        "SELECT code, trade_date, close, volume FROM read_parquet(?) "
        "WHERE code IN (SELECT DISTINCT code FROM eps)",
        [str(DAILY_BARS)],
    )
    _log("bars loaded for resolved codes")

    rows = con.execute(
        "SELECT e.rid, b.trade_date, b.close, b.volume "
        "FROM eps e JOIN bars b "
        "ON b.code = e.code AND b.trade_date >= e.anchor_date "
        "AND b.trade_date <= e.signal_date "
        "ORDER BY e.rid, b.trade_date"
    ).fetchall()
    _log(f"window bar rows: {len(rows)}")

    by_rid: dict[int, list[Bar]] = {}
    for rid, trade_date, close, volume in rows:
        by_rid.setdefault(rid, []).append(Bar("x", trade_date, close, volume))

    episodes = con.execute(
        "SELECT rid, code, setup_stage, anchor_date, signal_date, "
        "outcome, r_multiple, days_since_anchor FROM eps"
    ).fetchall()

    defined: list[dict] = []
    undefined_codes: list[str] = []
    for rid, code, stage, anchor, signal, outcome, r_raw, days in episodes:
        window = by_rid.get(rid)
        if not window:
            undefined_codes.append("NO_WINDOW")
            continue
        try:
            count = fl.pullback_down_volume_count(
                window, date.fromisoformat(str(anchor)), date.fromisoformat(str(signal))
            )
        except ValueError as exc:
            undefined_codes.append(f"{exc}")
            continue
        if count is None:
            undefined_codes.append("NO_AFTER")
            continue
        defined.append(
            {
                "code": code,
                "stage": stage,
                "days": int(days),
                "outcome": outcome,
                "r": parse_r(r_raw),
                "count": count,
            }
        )
    _log(f"F23 defined: {len(defined)} / undefined: {len(undefined_codes)}")

    any_n = sum(1 for r in defined if r["count"] >= 1)
    none_n = len(defined) - any_n
    primary = _group_comparison(defined)

    stage_strata = {}
    for s in STAGES:
        stage_strata[s] = _group_comparison([r for r in defined if r["stage"] == s])

    timing_strata = {}
    for b in ("1-2", "3", "4-5", "6-10"):
        timing_strata[b] = _group_comparison(
            [r for r in defined if _bucket(r["days"]) == b]
        )

    verdict = _verdict(primary, stage_strata, timing_strata)

    payload = {
        "inputs": {
            "episodes": str(EPISODES),
            "episodes_sha256": episodes_sha,
            "daily_bars": str(DAILY_BARS),
            "daily_bars_sha256": bars_sha,
            "snapshot_id": SNAPSHOT_ID,
            "r_source": "episodes.r_multiple — Phase 2D.0 corrected outcome study, strict variant",
            "f23_definition": "count of pullback sessions after T0 through signal_date "
            "where close(i) < close(i-1) AND volume(i) > volume(i-1)",
            "f23_any_definition": "F23_COUNT >= 1 (pre-registered grouping only)",
        },
        "sample": {
            "resolved_n": resolved_n,
            "resolved_groups": list(GROUPS),
            "f23_defined_n": len(defined),
            "f23_undefined_n": len(undefined_codes),
            "f23_any_n": any_n,
            "f23_none_n": none_n,
            "min_n": MIN_N,
        },
        "primary": primary,
        "stage_strata": stage_strata,
        "timing_strata": timing_strata,
        "verdict": verdict,
        "verdict_logic": "REJECT: primary win_share delta defined and >= 0. "
        "SUPPORTED: primary win_share delta < 0, mean_R delta < 0 when defined, "
        "and every defined stage/timing stratum win_share delta < 0. Else OBSERVE_ONLY.",
        "script_sha256": script_sha,
    }
    out_json = OUT_DIR / "h6-f23-v01.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _log(f"stats -> {out_json}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
