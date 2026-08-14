"""H4 MA10 support outcome validation v01 (research / frozen-sample only).

H4A: is MA10 CLOSE BREAK (E02) a negative structure? E02=True vs E02=False
over frozen resolved episodes. Pre-registered negative direction:
strict_win_rate_delta < 0 AND mean_R_delta < 0 (DELTA = BREAK - NO_BREAK).

H4B: conditional primary on the E02=True subset: does reclaim within 3
sessions (E03) carry recovery meaning? E03=True vs E03=False.
Pre-registered positive direction: strict_win_rate_delta > 0 AND
mean_R_delta > 0 (DELTA = RECLAIM - NO_RECLAIM). E02=False rows never
enter the H4B denominator.

E01 (touch+hold) is SECONDARY descriptive only, evaluated on the
E02=False subset; it never drives a SUPPORTED verdict.

STRICT PIT MATERIALIZATION: every episode pure-function call receives only
canonical bars with trade_date <= episode.signal_date — the anchor bar,
the 9 visible sessions before the anchor (when they exist), and every
session in (anchor, signal]. Future bars are never passed.

R source: episodes.r_multiple (Phase 2D.0 corrected outcome study, strict
variant). Frozen inputs: episodes SHA 66d5943f... +
snap-2026-07-31-b5f84004de8a. DESCRIPTIVE ONLY: no thresholds tuned, no
promotion, no production change.
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
FROZEN_AS_OF = date(2026, 7, 31)
OUT_DIR = Path("research/factor-lab/runs/h4-ma10-v01")
GROUPS = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")
WIN = "WIN_S1"
LOSS = "LOSS_INVALID"
CANCEL = "CANCEL_GAP_INVALID"
MIN_N = 20
STAGES = ("B1_READY", "B2_READY", "B2_CONFIRMED")
STARTED = time.time()

Bar = namedtuple("Bar", "code trade_date close volume low")


def _log(msg: str) -> None:
    print(f"[{time.time() - STARTED:7.1f}s] {msg}", file=sys.stderr, flush=True)


def parse_r(value) -> float | None:
    """Fail-closed parse of r_multiple (H10 audit-fixed contract)."""
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
    """Counts always reported; interpreted stats None below MIN_N."""
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


def _deltas(cell_true: dict, cell_false: dict) -> dict:
    out: dict[str, float | None] = {}
    for key in ("win_share", "strict_win_rate", "mean_r", "median_r"):
        a, b = cell_true[key], cell_false[key]
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


def _group_comparison(rows: list[dict], flag: str) -> dict:
    true_rows = [r for r in rows if r[flag] is True]
    false_rows = [r for r in rows if r[flag] is False]
    cell_true = _cell(true_rows)
    cell_false = _cell(false_rows)
    return {
        "true": cell_true,
        "false": cell_false,
        "delta": _deltas(cell_true, cell_false),
    }


def _verdict(primary: dict, stage: dict, timing: dict, positive: bool) -> str:
    """Sol frozen verdict contract.

    negative (H4A): SUPPORTED needs strict_win_rate_delta < 0 AND
    mean_R_delta < 0, win_share not obviously opposite, and no key
    structural reversal in main strata.
    positive (H4B): same with > 0.
    Primary not meeting the co-direction -> REJECT; primary holds but
    strata/composition unstable -> OBSERVE_ONLY.
    """
    sign = 1 if positive else -1
    swr = primary["delta"].get("strict_win_rate")
    mr = primary["delta"].get("mean_r")
    if swr is None or mr is None:
        return "REJECT"
    if not (swr * sign > 0 and mr * sign > 0):
        return "REJECT"
    ws = primary["delta"].get("win_share")
    if ws is not None and ws * sign <= 0:
        return "OBSERVE_ONLY"
    for strata in (stage, timing):
        for cell in strata.values():
            d = cell["delta"].get("strict_win_rate")
            if d is not None and d * sign <= 0:
                return "OBSERVE_ONLY"
    return "SUPPORTED"


def _strata(rows: list[dict], flag: str) -> dict:
    out: dict[str, dict] = {}
    for s in STAGES:
        out[f"stage_{s}"] = _group_comparison(
            [r for r in rows if r["stage"] == s], flag
        )
    for b in ("1-2", "3", "4-5", "6-10"):
        out[f"timing_{b}"] = _group_comparison(
            [r for r in rows if _bucket(r["days"]) == b], flag
        )
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    episodes_sha = hashlib.sha256(EPISODES.read_bytes()).hexdigest()
    if episodes_sha != EXPECTED_SHA:
        raise SystemExit(f"episodes hash mismatch: {episodes_sha}")
    bars_sha = hashlib.sha256(DAILY_BARS.read_bytes()).hexdigest()
    script_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    _log("input hashes verified")

    con = duckdb.connect()
    episodes_total = con.execute(
        "SELECT count(*) FROM read_parquet(?)", [str(EPISODES)]
    ).fetchone()[0]
    max_signal = con.execute(
        "SELECT max(CAST(signal_date AS DATE)) FROM read_parquet(?)",
        [str(EPISODES)],
    ).fetchone()[0]
    if max_signal is not None and date.fromisoformat(str(max_signal)) > FROZEN_AS_OF:
        raise SystemExit(f"episodes contain post-frozen signal dates: {max_signal}")
    bars_snap_ids = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT dataset_snapshot_id FROM read_parquet(?)",
            [str(DAILY_BARS)],
        ).fetchall()
    }
    if bars_snap_ids != {SNAPSHOT_ID}:
        raise SystemExit(f"daily bars snapshot mismatch: {bars_snap_ids}")
    _log(f"provenance gates pass: total={episodes_total}")

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
        "CREATE TEMP TABLE cb AS "
        "SELECT code, trade_date, close, volume, low, "
        "row_number() OVER (PARTITION BY code ORDER BY trade_date) AS rn "
        "FROM read_parquet(?) WHERE code IN (SELECT DISTINCT code FROM eps)",
        [str(DAILY_BARS)],
    )
    code_has_bars = {
        r[0] for r in con.execute("SELECT DISTINCT code FROM cb").fetchall()
    }
    _log(f"bars loaded for resolved codes: {len(code_has_bars)} codes")

    con.execute(
        "CREATE TEMP TABLE e2 AS "
        "SELECT e.rid, e.code, e.setup_stage, e.anchor_date, e.signal_date, "
        "e.outcome, e.r_multiple, e.days_since_anchor, a.rn AS anchor_rn "
        "FROM eps e JOIN cb a ON a.code = e.code AND a.trade_date = e.anchor_date"
    )
    rows = con.execute(
        "SELECT e.rid, b.trade_date, b.close, b.volume, b.low "
        "FROM e2 e JOIN cb b ON b.code = e.code "
        "AND b.rn >= e.anchor_rn - 9 AND b.trade_date <= e.signal_date "
        "ORDER BY e.rid, b.trade_date"
    ).fetchall()
    _log(f"window bar rows: {len(rows)}")

    by_rid: dict[int, list[Bar]] = {}
    for rid, trade_date, close, volume, low in rows:
        by_rid.setdefault(rid, []).append(Bar("x", trade_date, close, volume, low))

    episodes = con.execute(
        "SELECT rid, code, setup_stage, anchor_date, signal_date, "
        "outcome, r_multiple, days_since_anchor FROM eps"
    ).fetchall()

    def new_reason_counters() -> dict[str, dict[str, int]]:
        return {
            ev: {
                "INSUFFICIENT_MA10_HISTORY": 0,
                "NO_POST_ANCHOR_BAR": 0,
                "MISSING_CANONICAL_WINDOW": 0,
            }
            for ev in ("E01", "E02", "E03")
        }

    reasons = new_reason_counters()
    records: list[dict] = []
    for rid, code, stage, anchor_s, signal_s, outcome, r_raw, days in episodes:
        anchor = date.fromisoformat(str(anchor_s))
        signal = date.fromisoformat(str(signal_s))
        if code not in code_has_bars:
            for ev in ("E01", "E02", "E03"):
                reasons[ev]["MISSING_CANONICAL_WINDOW"] += 1
            continue
        if rid not in by_rid:
            raise SystemExit(
                f"DATA_ERROR: canonical window missing anchor bar "
                f"(code={code} anchor={anchor} signal={signal})"
            )
        window = by_rid[rid]
        after = [b for b in window if anchor < b.trade_date <= signal]
        if not after:
            for ev in ("E01", "E02", "E03"):
                reasons[ev]["NO_POST_ANCHOR_BAR"] += 1
            continue
        try:
            e01 = fl.ma10_touch_hold(window, anchor, signal)
            e02 = fl.ma10_close_break(window, anchor, signal)
            e03 = fl.ma10_reclaim_within_3d(window, anchor, signal)
        except ValueError as exc:
            raise SystemExit(
                f"DATA_ERROR: {exc} (code={code} anchor={anchor} signal={signal})"
            ) from exc
        for ev, value in (("E01", e01), ("E02", e02), ("E03", e03)):
            if value is None:
                reasons[ev]["INSUFFICIENT_MA10_HISTORY"] += 1
        records.append(
            {
                "code": code,
                "stage": stage,
                "days": int(days),
                "outcome": outcome,
                "r": parse_r(r_raw),
                "e01": e01,
                "e02": e02,
                "e03": e03,
            }
        )

    def defined_n(ev: str) -> int:
        return sum(1 for r in records if r[ev.lower()] is not None)

    sample = {
        "episodes_total": episodes_total,
        "resolved_n": resolved_n,
        "resolved_groups": list(GROUPS),
        "min_n": MIN_N,
        "defined": {
            "E01": defined_n("E01"),
            "E02": defined_n("E02"),
            "E03": defined_n("E03"),
        },
        "undefined": {
            ev: {
                "n": sum(reasons[ev].values()),
                "reasons": reasons[ev],
            }
            for ev in ("E01", "E02", "E03")
        },
    }
    _log(f"sample: {json.dumps(sample['defined'])}")

    h4a = _group_comparison([r for r in records if r["e02"] is not None], "e02")
    h4b_rows = [r for r in records if r["e02"] is True and r["e03"] is not None]
    h4b = _group_comparison(h4b_rows, "e03")
    e01_rows = [r for r in records if r["e02"] is False and r["e01"] is not None]
    e01_secondary = _group_comparison(e01_rows, "e01")

    h4a_strata = _strata([r for r in records if r["e02"] is not None], "e02")
    h4b_strata = _strata(h4b_rows, "e03")

    h4a_verdict = _verdict(h4a, h4a_strata, h4a_strata, positive=False)
    h4b_verdict = _verdict(h4b, h4b_strata, h4b_strata, positive=True)

    payload = {
        "inputs": {
            "episodes": str(EPISODES),
            "episodes_sha256": episodes_sha,
            "daily_bars": str(DAILY_BARS),
            "daily_bars_sha256": bars_sha,
            "snapshot_id": SNAPSHOT_ID,
            "bars_dataset_snapshot_ids": sorted(bars_snap_ids),
            "frozen_as_of": str(FROZEN_AS_OF),
            "r_source": "episodes.r_multiple — Phase 2D.0 corrected outcome study, strict variant",
            "pit_boundary": "pure functions receive only trade_date <= episode.signal_date "
            "(anchor + 9 visible sessions before anchor + (anchor, signal])",
            "contract_source": "E01/E02/E03 frozen in commit 7741ba5 (H4 MA10 contract v01)",
        },
        "sample": sample,
        "h4a_primary": {"question": "E02 close break negative structure", **h4a},
        "h4b_conditional": {
            "question": "E03 reclaim recovery meaning (E02=True subset only)",
            "e02_true_subset_n": sum(1 for r in records if r["e02"] is True),
            **h4b,
        },
        "e01_secondary": {
            "scope": "E02=False subset, descriptive only, never drives a verdict",
            "label": "OBSERVATION at most",
            **e01_secondary,
        },
        "h4a_strata": h4a_strata,
        "h4b_strata": h4b_strata,
        "h4a_verdict": h4a_verdict,
        "h4b_verdict": h4b_verdict,
        "verdict_logic": "REJECT: primary strict_win_rate and mean_R not co-directional "
        "with the pre-registered sign (H4A negative, H4B positive) or coverage "
        "insufficient. OBSERVE_ONLY: primary holds but win_share is obviously "
        "opposite or a main stratum shows a structural reversal. SUPPORTED: primary "
        "co-directional, win_share not opposite, no key reversal in main strata. "
        "SUPPORTED != PROMOTED.",
        "script_sha256": script_sha,
    }
    out_json = OUT_DIR / "h4-ma10-v01.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _log(f"stats -> {out_json}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
