"""H10 R-metric reconciliation v01 (research / reconciliation only).

Question: in the H10 resolved sample, entry_quality>=80 win-share is
negative vs <80 (0.1007 vs 0.2505), while the frozen Phase 2D.0 baseline
reports a positive E[R] for ACTIONABLE entry>=80. Why?

R source: episodes.r_multiple = the Phase 2D.0 corrected outcome study
(FINAL_VINTAGE_CAUSAL, T+1 daily-bar theoretical execution, strict
variant). Frozen strict resolved expectancy = mean(r_multiple over
WIN_S1 union LOSS_INVALID). This is the SAME field the frozen baseline
E[R] table was computed from, so the reconciliation on r_multiple is
same-口径 with Phase 2D.0. The Phase 2D.1A T+1 friction numbers (e.g.
10bp E[R] +0.2605) come from a DIFFERENT execution model stored in
execution-reality/execution_episodes.parquet; they are NOT reproducible
from episodes.r_multiple and are reported as a 口径差异 (fail closed,
cited from the frozen execution-reality summary, never recomputed here).

DESCRIPTIVE ONLY. No threshold search, no promotion, no model rebuild.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import duckdb

EPISODES = Path(
    "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    "/corrected-b2-trigger-outcome/episodes.parquet"
)
EXPECTED_SHA = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
OUT_DIR = Path("research/factor-lab/runs/h10-r-v01")
GROUPS = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")
WIN = "WIN_S1"
LOSS = "LOSS_INVALID"
MIN_N = 20
STARTED = time.time()


def _log(msg: str) -> None:
    print(f"[{time.time() - STARTED:7.1f}s] {msg}", file=sys.stderr, flush=True)


def parse_score(value) -> float | None:
    """Fail-closed score parsing.

    None -> None (legitimate missing); a numeric string -> float; any
    non-NULL value that is not a finite number raises ValueError. Dirty
    data must never be silently converted into missing.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"unparseable score value: {value!r}") from e
    if not math.isfinite(f):
        raise ValueError(f"non-finite score value: {value!r}")
    return f


def parse_r(value) -> float | None:
    """Fail-closed R parsing, same contract as parse_score."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"unparseable r_multiple value: {value!r}") from e
    if not math.isfinite(f):
        raise ValueError(f"non-finite r_multiple value: {value!r}")
    return f


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(int(q * (len(ordered) - 1)), len(ordered) - 1)]


def r_summary(values: list[float], min_n: int = MIN_N) -> dict:
    """R distribution summary. n is always reported; interpreted stats
    are None when n < min_n (do not interpret small cells)."""
    n = len(values)
    if n < min_n:
        return {"n": n}
    total = sum(values)
    pos = [v for v in values if v > 0]
    neg = [v for v in values if v < 0]
    ordered = sorted(values)
    mid = n // 2
    median = (
        (ordered[mid - 1] + ordered[mid]) / 2 if n % 2 == 0 else ordered[mid]
    )
    return {
        "n": n,
        "mean_r": round(total / n, 4),
        "median_r": round(median, 4),
        "p25_r": round(_quantile(ordered, 0.25), 4),
        "p75_r": round(_quantile(ordered, 0.75), 4),
        "p_gt0": round(len(pos) / n, 4),
        "p_ge1": round(sum(1 for v in values if v >= 1) / n, 4),
        "p_ge2": round(sum(1 for v in values if v >= 2) / n, 4),
        "mean_pos_r": round(sum(pos) / len(pos), 4) if pos else None,
        "mean_neg_r": round(sum(neg) / len(neg), 4) if neg else None,
    }


def tail_check(values: list[float]) -> dict:
    """Right-tail diagnostics: top 1%/5% contribution to total R and
    trimmed means. Contributions are None when total R is <= 0."""
    n = len(values)
    if n == 0:
        return {}
    ordered = sorted(values, reverse=True)
    total = sum(ordered)
    top1_n = max(1, math.ceil(n * 0.01))
    top5_n = max(1, math.ceil(n * 0.05))
    top1_sum = sum(ordered[:top1_n])
    top5_sum = sum(ordered[:top5_n])
    trimmed_top1 = sum(ordered[top1_n:]) / (n - top1_n) if n > top1_n else None
    trimmed_sym = None
    if n > 2 * top1_n:
        trimmed_sym = sum(ordered[top1_n:n - top1_n]) / (n - 2 * top1_n)
    return {
        "n": n,
        "total_r": round(total, 4),
        "top1_n": top1_n,
        "top1_contribution": round(top1_sum / total, 4) if total > 0 else None,
        "top5_n": top5_n,
        "top5_contribution": round(top5_sum / total, 4) if total > 0 else None,
        "trimmed_mean_top1pct": round(trimmed_top1, 4) if trimmed_top1 is not None else None,
        "trimmed_mean_sym1pct": round(trimmed_sym, 4) if trimmed_sym is not None else None,
    }


def r_strata(rows, min_n: int = MIN_N) -> dict:
    """ge80/lt80 mutually exclusive strata over score-DEFINED rows.

    rows: (outcome, parsed_score_or_None, parsed_r_or_None).
    Per stratum: N (score-defined), win_share = WIN/N (H10-compatible),
    strict_win_rate = WIN/(WIN+LOSS) (frozen denominator), R coverage
    (n_with_r / r_missing_n), and the R distribution over rows with R.
    Accounting identity: ge80_n + lt80_n == defined_n; per stratum
    N == n_with_r + r_missing_n.
    """
    rows = list(rows)
    score_missing = sum(1 for _, s, _ in rows if s is None)
    ge80 = [(o, r) for o, s, r in rows if s is not None and s >= 80.0]
    lt80 = [(o, r) for o, s, r in rows if s is not None and s < 80.0]
    out: dict[str, dict] = {}
    for name, bucket in (("ge80", ge80), ("lt80", lt80)):
        n = len(bucket)
        wins = sum(1 for o, _ in bucket if o == WIN)
        losses = sum(1 for o, _ in bucket if o == LOSS)
        r_values = [r for _, r in bucket if r is not None]
        strict_denom = wins + losses
        out[name] = {
            "n": n,
            # Small-cell contract: interpreted rates are None below min_n,
            # so the JSON is the authority and the report never hides cells.
            "win_share": round(wins / n, 4) if n >= min_n else None,
            "strict_win_rate": round(wins / strict_denom, 4) if strict_denom >= min_n else None,
            "n_with_r": len(r_values),
            "r_missing_n": n - len(r_values),
            "r": r_summary(r_values, min_n),
        }
    delta = {}
    for key in ("win_share", "strict_win_rate"):
        a, b = out["ge80"][key], out["lt80"][key]
        delta[key] = round(a - b, 4) if a is not None and b is not None else None
    for key in ("mean_r", "median_r"):
        a = out["ge80"]["r"].get(key)
        b = out["lt80"]["r"].get(key)
        delta[key] = round(a - b, 4) if a is not None and b is not None else None
    return {
        "defined_n": len(ge80) + len(lt80),
        "score_missing_n": score_missing,
        "ge80": out["ge80"],
        "lt80": out["lt80"],
        "delta": delta,
    }


def _bucket(days: int) -> str:
    if days <= 2:
        return "1-2"
    if days <= 3:
        return "3"
    if days <= 5:
        return "4-5"
    return "6-10"


def keyed_strata(rows, min_n: int = MIN_N) -> dict:
    """Per-key entry_quality strata. rows: (key, outcome, score, r)."""
    buckets: dict[str, list] = {}
    for key, o, s, r in rows:
        buckets.setdefault(key, []).append((o, s, r))
    out: dict[str, dict] = {}
    for key in sorted(buckets):
        strata = r_strata(buckets[key], min_n)
        out[key] = {}
        for name in ("ge80", "lt80"):
            cell = strata[name]
            r = cell["r"]
            out[key][name] = {
                "n": cell["n"],
                "mean_r": r.get("mean_r"),
                "median_r": r.get("median_r"),
                "win_share": cell["win_share"],
            }
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(EPISODES.read_bytes()).hexdigest()
    if sha != EXPECTED_SHA:
        raise SystemExit(f"episodes hash mismatch: {sha}")
    _log("episodes hash verified")

    con = duckdb.connect()
    rows = con.execute(
        "SELECT days_since_anchor, setup_stage, outcome, setup_quality_score, "
        "entry_quality_score, r_multiple, conservative_r_multiple, is_entry_candidate "
        "FROM read_parquet(?) WHERE outcome IS NOT NULL",
        [str(EPISODES)],
    ).fetchall()
    records = [
        {
            "days": int(r[0]),
            "stage": r[1],
            "outcome": r[2],
            "setup_score": parse_score(r[3]),
            "entry_score": parse_score(r[4]),
            "r": parse_r(r[5]),
            "conservative_r": parse_r(r[6]),
            "actionable": bool(r[7]),
        }
        for r in rows
    ]
    _log(f"rows loaded: {len(records)}")

    resolved = [r for r in records if r["outcome"] in GROUPS]
    entry_rows = [(r["outcome"], r["entry_score"], r["r"]) for r in resolved]
    setup_rows = [(r["outcome"], r["setup_score"], r["r"]) for r in resolved]
    entry_strata = r_strata(entry_rows)
    setup_strata = r_strata(setup_rows)

    entry_ge80_r = [r["r"] for r in resolved if r["entry_score"] is not None and r["entry_score"] >= 80.0 and r["r"] is not None]
    entry_lt80_r = [r["r"] for r in resolved if r["entry_score"] is not None and r["entry_score"] < 80.0 and r["r"] is not None]
    tail = {
        "entry_ge80": tail_check(entry_ge80_r),
        "entry_lt80": tail_check(entry_lt80_r),
    }

    timing = keyed_strata(
        [(_bucket(r["days"]), r["outcome"], r["entry_score"], r["r"]) for r in resolved]
    )

    stage = {}
    for s in ("B1_READY", "B2_READY", "B2_CONFIRMED"):
        rows_s = [(r["outcome"], r["entry_score"], r["r"]) for r in resolved if r["stage"] == s]
        strata = r_strata(rows_s)
        stage[s] = {}
        for name in ("ge80", "lt80"):
            cell = strata[name]
            stage[s][name] = {
                "n": cell["n"],
                "mean_r": cell["r"].get("mean_r"),
                "median_r": cell["r"].get("median_r"),
                "win_share": cell["win_share"],
            }

    # Frozen echo: ACTIONABLE cohorts, strict/conservative resolved E[R]
    # reproduced from the SAME r_multiple fields (Phase 2D.0 corrected).
    def echo(score_key: str, ge80: bool) -> dict:
        subset = [
            r for r in records
            if r["actionable"]
            and r[score_key] is not None
            and (r[score_key] >= 80.0 if ge80 else r[score_key] < 80.0)
        ]
        wins = [r for r in subset if r["outcome"] == WIN]
        losses = [r for r in subset if r["outcome"] == LOSS]
        ambiguous = [r for r in subset if r["outcome"] == "AMBIGUOUS_INTRADAY"]
        strict_r = [r["r"] for r in wins + losses if r["r"] is not None]
        cons_r = [
            r["conservative_r"]
            for r in wins + losses + ambiguous
            if r["conservative_r"] is not None
        ]
        strict_denom = len(wins) + len(losses)
        cons_denom = strict_denom + len(ambiguous)
        return {
            "episodes": len(subset),
            "wins": len(wins),
            "losses": len(losses),
            "ambiguous": len(ambiguous),
            "strict_win_rate": round(len(wins) / strict_denom, 4) if strict_denom >= MIN_N else None,
            "strict_resolved_e_r": round(sum(strict_r) / len(strict_r), 4) if strict_r else None,
            "conservative_resolved_e_r": round(sum(cons_r) / len(cons_r), 4) if cons_r else None,
            "strict_r_distribution": r_summary(strict_r, MIN_N),
            "strict_r_tail": tail_check(strict_r),
        }

    frozen_echo = {
        "entry_ge80": echo("entry_score", True),
        "entry_lt80": echo("entry_score", False),
        "setup_ge80": echo("setup_score", True),
        "setup_lt80": echo("setup_score", False),
    }

    payload = {
        "inputs": {
            "episodes": str(EPISODES),
            "episodes_sha256": sha,
            "snapshot_id": SNAPSHOT_ID,
            "r_source": "episodes.r_multiple — Phase 2D.0 corrected outcome study, strict variant (FINAL_VINTAGE_CAUSAL)",
            "r_scope_note": "Phase 2D.1A T+1 friction E[R] (+0.2605 etc.) is a DIFFERENT execution model (execution_episodes.parquet); NOT reproducible from r_multiple -> fail-closed, cited from frozen ER summary only.",
        },
        "sample": {
            "resolved_n": len(resolved),
            "resolved_groups": list(GROUPS),
            "min_n": MIN_N,
        },
        "entry_quality": entry_strata,
        "setup_quality": setup_strata,
        "tail_diagnostics": tail,
        "timing_strata_entry_quality": timing,
        "stage_strata_entry_quality": stage,
        "frozen_echo_actionable": frozen_echo,
    }
    out = OUT_DIR / "h10-r-v01.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _log(f"stats -> {out}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
