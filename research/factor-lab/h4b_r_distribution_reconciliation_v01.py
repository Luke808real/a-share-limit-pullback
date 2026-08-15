"""H4B R distribution reconciliation v01 (research / reconciliation only).

Purpose: explain why in the H4 V01 frozen sample, for the E02=True subset,
RECLAIM (E03=True) has strict win rate 62.10% vs NO_RECLAIM (E03=False)
11.67%, yet RECLAIM mean_R is LOWER by 0.0608 (-0.0608 delta, H4B_VERDICT
REJECT).

This is a reconciliation / diagnostic, NOT a new hypothesis validation:
H4B_VERDICT stays REJECT, E03 is NOT upgraded, no production change. The
population must EXACTLY reproduce H4 V01's counts (RECLAIM 525 / NO_RECLAIM
960; strict WIN/LOSS 290/177 vs 90/681), otherwise FAIL CLOSED.

R source: episodes.r_multiple, Phase 2D.0 corrected outcome study strict
variant only. E02/E03 semantics reused as frozen in commit 7741ba5 /
validated in 6a4bbe0. Frozen inputs: episodes SHA 66d5943f... +
snap-2026-07-31-b5f84004de8a.
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
OUT_DIR = Path("research/factor-lab/runs/h4b-r-v01")
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


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(int(q * (len(ordered) - 1)), len(ordered) - 1)]


def _mean(values) -> float | None:
    values = tuple(values)
    if not values:
        return None
    return sum(values) / len(values)


def _median(values) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def _bucket(days: int) -> str:
    if days <= 2:
        return "1-2"
    if days <= 3:
        return "3"
    if days <= 5:
        return "4-5"
    return "6-10"


def r_distribution(values: list[float]) -> dict:
    """Full R quantile / tail distribution for a strict-R group."""
    n = len(values)
    if n == 0:
        return {"n": 0}
    pos = [v for v in values if v > 0]
    neg = [v for v in values if v < 0]
    return {
        "n": n,
        "win_count": len(pos),
        "loss_count": len(neg),
        "mean_r": round(sum(values) / n, 4),
        "median_r": round(_median(values), 4),
        "p10": round(_quantile(values, 0.10), 4),
        "p25": round(_quantile(values, 0.25), 4),
        "p75": round(_quantile(values, 0.75), 4),
        "p90": round(_quantile(values, 0.90), 4),
        "p95": round(_quantile(values, 0.95), 4),
        "p99": round(_quantile(values, 0.99), 4),
        "max_r": round(max(values), 4),
        "p_r_gt0": round(len(pos) / n, 4),
        "p_r_ge1": round(sum(1 for v in values if v >= 1) / n, 4),
        "p_r_ge2": round(sum(1 for v in values if v >= 2) / n, 4),
        "p_r_ge5": round(sum(1 for v in values if v >= 5) / n, 4),
        "p_r_ge10": round(sum(1 for v in values if v >= 10) / n, 4),
        "mean_positive_r": round(_mean(pos), 4) if pos else None,
        "median_positive_r": round(_median(pos), 4) if pos else None,
        "mean_negative_r": round(_mean(neg), 4) if neg else None,
        "loss_r_unique": sorted(set(neg)),
    }


def tail_driver(values: list[float]) -> dict:
    """Right-tail concentration diagnostics (H10 fail-closed for contribution)."""
    if not values:
        return {}
    ordered = sorted(values, reverse=True)
    total = sum(ordered)
    n = len(ordered)
    top1_n = max(1, math.ceil(n * 0.01))
    top5_n = max(1, math.ceil(n * 0.05))
    top1_sum = sum(ordered[:top1_n])
    top5_sum = sum(ordered[:top5_n])
    trim1 = sum(ordered[top1_n:]) / (n - top1_n) if n > top1_n else None
    trim5 = sum(ordered[top5_n:]) / (n - top5_n) if n > top5_n else None
    # wins required to make total_R positive: smallest k such that the sum
    # of the k largest R makes cumulative total > 0 (0 when already > 0).
    wins_required = 0
    if total <= 0:
        cum = 0
        for i, v in enumerate(ordered):
            cum += v
            if cum > 0:
                wins_required = i + 1
                break
    return {
        "n": n,
        "total_r": round(total, 4),
        "top1_n": top1_n,
        "top1_sum_r": round(top1_sum, 4),
        "top1_contribution_to_total": round(top1_sum / total, 4) if total > 0 else None,
        "top5_n": top5_n,
        "top5_sum_r": round(top5_sum, 4),
        "top5_contribution_to_total": round(top5_sum / total, 4) if total > 0 else None,
        "trimmed_mean_remove_top1pct": round(trim1, 4) if trim1 is not None else None,
        "trimmed_mean_remove_top5pct": round(trim5, 4) if trim5 is not None else None,
        "wins_required_to_make_total_positive": wins_required,
        "top_winner_r": round(ordered[0], 4),
        "top5_winner_r": [round(v, 4) for v in ordered[:5]],
    }


def winner_payoff(values: list[float]) -> dict:
    """Payoff stats over PAYOFF-POSITIVE rows (r > 0), NOT outcome==WIN_S1.

    The frozen outcome label and r_multiple are not perfectly aligned (some
    WIN_S1 rows carry r <= 0 and some LOSS_INVALID rows carry r > 0); the
    reconciliation therefore reports BOTH definitions explicitly and never
    conflates them. Keys are named payoff_positive_* to keep the 口径 distinct.
    """
    pos = sorted(v for v in values if v > 0)
    if not pos:
        return {"n_payoff_positive": 0}
    return {
        "n_payoff_positive": len(pos),
        "mean_payoff_positive_r": round(_mean(pos), 4),
        "median_payoff_positive_r": round(_median(pos), 4),
        "p90_payoff_positive_r": round(_quantile(pos, 0.90), 4),
        "max_payoff_positive_r": round(max(pos), 4),
    }


def winner_payoff_by_outcome(rows: list[dict]) -> dict:
    """Payoff stats over rows with outcome == WIN_S1 (frozen label口径).

    Kept separate from winner_payoff(): the outcome label is the frozen
    semantic definition of a win, while payoff_positive is the P&L sign.
    """
    wins = [r["r"] for r in rows if r["outcome"] == WIN and r["r"] is not None]
    if not wins:
        return {"n_win_s1": 0}
    return {
        "n_win_s1": len(wins),
        "mean_win_s1_r": round(_mean(wins), 4),
        "median_win_s1_r": round(_median(wins), 4),
        "p90_win_s1_r": round(_quantile(wins, 0.90), 4),
        "max_win_s1_r": round(max(wins), 4),
    }


def outcome_vs_payoff_reconciliation(rows: list[dict]) -> dict:
    """Document the divergence between the outcome label and the R sign."""
    win_s1 = [r["r"] for r in rows if r["outcome"] == WIN and r["r"] is not None]
    loss_inv = [r["r"] for r in rows if r["outcome"] == LOSS and r["r"] is not None]
    r_values = [r["r"] for r in rows if r["outcome"] in (WIN, LOSS) and r["r"] is not None]
    return {
        "win_s1_n": len(win_s1),
        "loss_invalid_n": len(loss_inv),
        "payoff_positive_n": sum(1 for v in r_values if v > 0),
        "payoff_negative_n": sum(1 for v in r_values if v < 0),
        "r_zero_n": sum(1 for v in r_values if v == 0),
        "win_s1_with_r_le0_n": sum(1 for v in win_s1 if v <= 0),
        "loss_invalid_with_r_gt0_n": sum(1 for v in loss_inv if v > 0),
    }


def _cell_diag(rows: list[dict]) -> dict:
    wins = sum(1 for r in rows if r["outcome"] == WIN)
    losses = sum(1 for r in rows if r["outcome"] == LOSS)
    n = len(rows)
    strict_denom = wins + losses
    r_values = [r["r"] for r in rows if r["outcome"] in (WIN, LOSS) and r["r"] is not None]
    pos = [v for v in r_values if v > 0]
    cell = {
        "n": n,
        "strict_win_rate": round(wins / strict_denom, 4) if strict_denom >= MIN_N else None,
        "mean_r": round(sum(r_values) / len(r_values), 4) if len(r_values) >= MIN_N else None,
        "median_r": round(_median(r_values), 4) if len(r_values) >= MIN_N else None,
        "mean_payoff_positive_r": round(_mean(pos), 4) if len(pos) >= MIN_N else None,
    }
    return cell


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
        r[0] for r in con.execute(
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

    by_rid: dict[int, list[Bar]] = {}
    for rid, trade_date, close, volume, low in rows:
        by_rid.setdefault(rid, []).append(Bar("x", trade_date, close, volume, low))

    episodes = con.execute(
        "SELECT rid, code, setup_stage, anchor_date, signal_date, "
        "outcome, r_multiple, days_since_anchor FROM eps"
    ).fetchall()

    records: list[dict] = []
    for rid, code, stage, anchor_s, signal_s, outcome, r_raw, days in episodes:
        anchor = date.fromisoformat(str(anchor_s))
        signal = date.fromisoformat(str(signal_s))
        if code not in code_has_bars:
            continue
        if rid not in by_rid:
            raise SystemExit(
                f"DATA_ERROR: canonical window missing anchor (code={code} anchor={anchor})"
            )
        window = by_rid[rid]
        if not [b for b in window if anchor < b.trade_date <= signal]:
            continue
        try:
            e02 = fl.ma10_close_break(window, anchor, signal)
            e03 = fl.ma10_reclaim_within_3d(window, anchor, signal)
        except ValueError as exc:
            raise SystemExit(f"DATA_ERROR: {exc} (code={code} anchor={anchor} signal={signal})")
        records.append(
            {
                "code": code,
                "stage": stage,
                "days": int(days),
                "outcome": outcome,
                "r": parse_r(r_raw),
                "e02": e02,
                "e03": e03,
            }
        )

    reclaim = [r for r in records if r["e02"] is True and r["e03"] is True]
    no_reclaim = [r for r in records if r["e02"] is True and r["e03"] is False]
    _log(f"reclaim={len(reclaim)} no_reclaim={len(no_reclaim)}")

    # HARD population reproduction gate (must equal H4 V01 exactly).
    def strict_counts(group: list[dict]) -> tuple[int, int]:
        w = sum(1 for r in group if r["outcome"] == WIN)
        l = sum(1 for r in group if r["outcome"] == LOSS)
        return w, l

    exp = {
        "reclaim_n": 525, "no_reclaim_n": 960,
        "reclaim_win": 290, "reclaim_loss": 177,
        "no_win": 90, "no_loss": 681,
    }
    rw, rl = strict_counts(reclaim)
    nw, nl = strict_counts(no_reclaim)
    if not (
        len(reclaim) == exp["reclaim_n"]
        and len(no_reclaim) == exp["no_reclaim_n"]
        and (rw, rl) == (exp["reclaim_win"], exp["reclaim_loss"])
        and (nw, nl) == (exp["no_win"], exp["no_loss"])
    ):
        raise SystemExit(
            "FAIL CLOSED: population does not reproduce H4 V01 "
            f"(reclaim {len(reclaim)}/{rw}/{rl} vs exp 525/290/177; "
            f"no_reclaim {len(no_reclaim)}/{nw}/{nl} vs exp 960/90/681)"
        )
    _log("population reproduction gate PASS")

    def strict_r(group: list[dict]) -> list[float]:
        return [
            r["r"] for r in group
            if r["outcome"] in (WIN, LOSS) and r["r"] is not None
        ]

    rv_reclaim = strict_r(reclaim)
    rv_no = strict_r(no_reclaim)

    dist_reclaim = r_distribution(rv_reclaim)
    dist_no = r_distribution(rv_no)
    tail_reclaim = tail_driver(rv_reclaim)
    tail_no = tail_driver(rv_no)
    win_reclaim = winner_payoff(rv_reclaim)
    win_no = winner_payoff(rv_no)
    win_s1_reclaim = winner_payoff_by_outcome(reclaim)
    win_s1_no = winner_payoff_by_outcome(no_reclaim)
    recon_reclaim = outcome_vs_payoff_reconciliation(reclaim)
    recon_no = outcome_vs_payoff_reconciliation(no_reclaim)

    payoff_ratio = (
        round(win_no["mean_payoff_positive_r"] / win_reclaim["mean_payoff_positive_r"], 4)
        if win_reclaim.get("mean_payoff_positive_r") and win_no.get("mean_payoff_positive_r")
        else None
    )
    win_s1_ratio = (
        round(win_s1_no["mean_win_s1_r"] / win_s1_reclaim["mean_win_s1_r"], 4)
        if win_s1_reclaim.get("mean_win_s1_r") and win_s1_no.get("mean_win_s1_r")
        else None
    )

    # Conclusion questions (factual reconciliation).
    # A: is NO_RECLAIM +0.2474 mean_R driven by tail concentration?
    a_tail = (
        dist_no.get("median_r") == -1.0
        and tail_no.get("trimmed_mean_remove_top1pct") is not None
        and tail_no["trimmed_mean_remove_top1pct"] < 0
    )
    # B: is RECLAIM's advantage hit-probability / median rather than right tail?
    b_median = (
        dist_reclaim.get("median_r") is not None
        and dist_no.get("median_r") is not None
        and dist_reclaim["median_r"] > dist_no["median_r"]
    )
    # C: after removing top1% / top5%, relative direction of mean_R.
    c_dir = None
    if tail_reclaim.get("trimmed_mean_remove_top1pct") is not None and tail_no.get("trimmed_mean_remove_top1pct") is not None:
        c_dir = (
            "reclaim_greater"
            if tail_reclaim["trimmed_mean_remove_top1pct"] > tail_no["trimmed_mean_remove_top1pct"]
            else "no_reclaim_greater_or_equal"
        )
    if c_dir is None and tail_reclaim.get("trimmed_mean_remove_top5pct") is not None and tail_no.get("trimmed_mean_remove_top5pct") is not None:
        tr5r = tail_reclaim["trimmed_mean_remove_top5pct"]
        tr5n = tail_no["trimmed_mean_remove_top5pct"]
        c_dir = "reclaim_greater" if tr5r > tr5n else "no_reclaim_greater_or_equal"

    question_answers = {
        "A_no_reclaim_tail_driven": a_tail,
        "B_reclaim_median_advantage": b_median,
        "C_after_tail_removal_direction": c_dir,
    }
    conclusion = "REJECT_EXPLANATION" if a_tail else "OBSERVATION"

    # Strata diagnostics.
    diag_rows_reclaim = [
        {"stage": r["stage"], "days": r["days"], "outcome": r["outcome"], "r": r["r"], "positive": True}
        for r in reclaim
    ]
    diag_rows_no = [
        {"stage": r["stage"], "days": r["days"], "outcome": r["outcome"], "r": r["r"], "positive": False}
        for r in no_reclaim
    ]
    diag_rows = diag_rows_reclaim + diag_rows_no
    strata_diag: dict[str, dict] = {}
    groups: dict[str, list[dict]] = {}
    for s in STAGES:
        groups[f"stage_{s}"] = [r for r in diag_rows if r["stage"] == s]
    for b in ("1-2", "3", "4-5", "6-10"):
        groups[f"timing_{b}"] = [r for r in diag_rows if _bucket(r["days"]) == b]
    for key, sub in groups.items():
        reclaim_sub = [r for r in sub if r["positive"]]
        no_sub = [r for r in sub if not r["positive"]]
        strata_diag[key] = {
            "reclaim": _cell_diag(reclaim_sub),
            "no_reclaim": _cell_diag(no_sub),
        }

    payload = {
        "inputs": {
            "episodes": str(EPISODES),
            "episodes_sha256": episodes_sha,
            "daily_bars": str(DAILY_BARS),
            "daily_bars_sha256": bars_sha,
            "snapshot_id": SNAPSHOT_ID,
            "bars_dataset_snapshot_ids": sorted(bars_snap_ids),
            "frozen_as_of": str(FROZEN_AS_OF),
            "r_source": "episodes.r_multiple — Phase 2D.0 corrected outcome study, strict variant only",
            "e02_e03_source": "H4 MA10 contract v01 (7741ba5) / validation (6a4bbe0), reused as-is",
            "pit_boundary": "pure functions receive only trade_date <= episode.signal_date",
        },
        "population": {
            "reclaim_n": len(reclaim),
            "no_reclaim_n": len(no_reclaim),
            "reclaim_win_loss": [rw, rl],
            "no_reclaim_win_loss": [nw, nl],
            "reproduction_gate": "525/960, strict 290/177 vs 90/681 — PASS (exact)",
            "h4b_verdict_unchanged": "REJECT",
        },
        "reclaim_r_distribution": dist_reclaim,
        "no_reclaim_r_distribution": dist_no,
        "reclaim_tail_driver": tail_reclaim,
        "no_reclaim_tail_driver": tail_no,
        "reclaim_winner_payoff_payoff_positive": win_reclaim,
        "no_reclaim_winner_payoff_payoff_positive": win_no,
        "reclaim_winner_payoff_win_s1_outcome": win_s1_reclaim,
        "no_reclaim_winner_payoff_win_s1_outcome": win_s1_no,
        "reclaim_outcome_vs_payoff": recon_reclaim,
        "no_reclaim_outcome_vs_payoff": recon_no,
        "mean_payoff_positive_ratio_no_over_reclaim": payoff_ratio,
        "mean_win_s1_ratio_no_over_reclaim": win_s1_ratio,
        "strata_diagnostics": strata_diag,
        "question_answers": question_answers,
        "conclusion": conclusion,
        "h4b_verdict_unchanged": "REJECT",
        "script_sha256": script_sha,
    }
    out_json = OUT_DIR / "h4b-r-v01.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _log(f"stats -> {out_json}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
