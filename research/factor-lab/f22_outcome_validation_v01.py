"""F22 B2 HUGE UPPER SHADOW VOLUME OUTCOME VALIDATION V01 — preregistered outcome validation.

Frozen prereg: research/factor-lab/runs/f22-outcome-prereg-v01/f22-outcome-prereg-v01.md
(AUTHORITY 3d2c8a7, Sol audit PASS / FROZEN / CLOSED, 2026-08-16).

Frozen authorities:
  CONTRACT_HEAD       = d3325e298a5c518afae6c82499c4c6acd71352dc (F22 CONTRACT/PIT)
  IMPLEMENTATION_HEAD = cd3d676c756a85e4c0ef2d3ffb82d2edc61ea43f (factor_lab.b2_huge_upper_shadow_volume)
  PREREG_HEAD         = 3d2c8a71318aa8d45fca499100c880f962ad9caf (this prereg)

Frozen design (unchanged; no threshold mining / no subgroup rescue / no
significance test / no continuity correction):
  1. population = resolved episodes (outcome in {WIN_S1, LOSS_INVALID,
     CANCEL_GAP_INVALID}) AND setup_stage in {B2_READY, B2_CONFIRMED};
     b2_date = episode.signal_date; PIT bars = visible sessions with
     trade_date <= b2_date for that code. B1_READY never enters.
  2. materialize F22 for EVERY domain episode (no outcome/F22/timing
     pre-filter); accounting: DEFINED_TRUE_N + DEFINED_FALSE_N + UNDEFINED_N
     == POPULATION_N (fail closed); any OTHER_ERROR -> fail closed.
  3. primary binary population: WIN_S1 / LOSS_INVALID only;
     CANCEL_GAP_INVALID excluded from the strict denominator (descriptive
     accounting only).
  4. primary metrics (exact Decimal; gate on exact values; no continuity
     correction):
       FAIL_RATE    = LOSS_INVALID / (WIN_S1 + LOSS_INVALID)
       DELTA_FAIL_RATE = FAIL_RATE_TRUE - FAIL_RATE_FALSE
       OR_FAILURE   = odds(LOSS_INVALID | TRUE) / odds(LOSS_INVALID | FALSE),
                      odds(group) = LOSS_INVALID / WIN_S1 (within group)
  5. PRIMARY_METRIC_UNDEFINED (any group strict N < 2, or any zero odds cell:
     WIN_S1 = 0 or LOSS_INVALID = 0 in a group) -> FAIL CLOSED (RuntimeError,
     no artifact; never mapped to REJECT).
  6. verdict precedence (frozen):
       A. accounting mismatch or OTHER_ERROR  -> FAIL CLOSED (no artifact)
       B. PRIMARY_METRIC_UNDEFINED            -> FAIL CLOSED (no artifact)
       C. PRIMARY_TRUE_N < 20 OR PRIMARY_FALSE_N < 20 -> STATUS =
          INSUFFICIENT_PRIMARY_N (descriptive metrics only; SUPPORTED/REJECT
          forbidden)
       D. else DELTA_FAIL_RATE > 0 AND OR_FAILURE > 1 -> SUPPORTED_DIRECTIONALLY
          else REJECT.
     SUPPORTED_DIRECTIONALLY != statistically significant != VALIDATED != PROMOTED.
  7. secondary descriptive (never changes the verdict): group tables
     (strict_win_rate / FAIL_RATE / P(R>0) / mean_R / median_R / CANCEL_GAP),
     stage composition (B2_READY / B2_CONFIRMED), timing composition
     (T1-2 / T3 / T4-5 / T6-10), each stratum per F22_TRUE vs F22_FALSE side
     with SMALL_CELL when either side strict N < 20; R tail diagnostics
     (H4B right-tail caveat); F22_TRUE event frequency.
  8. artifacts: JSON (machine-readable authority) + MD (rendered from the same
     result dict) under research/factor-lab/runs/f22-outcome-validation-v01/.

Frozen inputs (SHA gate, fail closed):
  episodes: data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/
            corrected-b2-trigger-outcome/episodes.parquet   (66d5943f...)
  daily:    data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet (e7243dee...)
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

# Deterministic import: always use THIS checkout's src.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from limit_pullback import factor_lab as fl  # noqa: E402
from limit_pullback.models.market import DailyBar  # noqa: E402

EPISODES_SHA = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
DAILY_SHA = "e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514"
EPISODES_TOTAL = 31422
RESOLVED_OUTCOMES = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")
STRICT_OUTCOMES = ("WIN_S1", "LOSS_INVALID")
POPULATION_STAGES = ("B2_READY", "B2_CONFIRMED")
COMPOSITION_STAGES = ("B2_READY", "B2_CONFIRMED")
TIMING_BUCKETS = ("T1-2", "T3", "T4-5", "T6-10")
SMALL_CELL_N = 20
CONTRACT_HEAD = "d3325e298a5c518afae6c82499c4c6acd71352dc"
IMPLEMENTATION_HEAD = "cd3d676c756a85e4c0ef2d3ffb82d2edc61ea43f"
PREREG_HEAD = "3d2c8a71318aa8d45fca499100c880f962ad9caf"
TZ = timezone(timedelta(hours=8))
ZERO = Decimal("0")
ONE = Decimal("1")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_episodes(path: Path, expected_sha: str = EPISODES_SHA, expected_total: int = EPISODES_TOTAL) -> pd.DataFrame:
    if isinstance(path, pd.DataFrame):
        raise TypeError("load_episodes: DataFrame bypass forbidden; path + SHA gate required (no bypass)")
    if sha256(path) != expected_sha:
        raise RuntimeError(f"episodes SHA mismatch: {path}")
    df = pd.read_parquet(path)
    if len(df) != expected_total:
        raise RuntimeError(f"episodes total mismatch: {len(df)} != {expected_total}")
    return df


def load_daily(path: Path, expected_sha: str = DAILY_SHA) -> pd.DataFrame:
    if isinstance(path, pd.DataFrame):
        raise TypeError("load_daily: DataFrame bypass forbidden; path + SHA gate required (no bypass)")
    if sha256(path) != expected_sha:
        raise RuntimeError(f"daily SHA mismatch: {path}")
    return pd.read_parquet(path)


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return None
    return Decimal(text)


def to_daily_bar(row: pd.Series) -> DailyBar:
    close = _dec(row["close"])
    volume = _dec(row.get("volume")) or Decimal("0")
    return DailyBar(
        trade_date=row["trade_date"],
        code=str(row["code"]),
        open=_dec(row["open"]),
        high=_dec(row["high"]),
        low=_dec(row["low"]),
        close=close,
        preclose=_dec(row.get("preclose")) or close,
        volume=volume,
        amount=volume * close,
        turnover_rate=None,
        pct_change=None,
        trade_status=True,
        source="F22_VALIDATION",
        fetched_at=datetime.combine(row["trade_date"], time(16, 0), tzinfo=TZ),
    )


def group_daily(daily: pd.DataFrame) -> dict[str, pd.DataFrame]:
    visible = daily[daily["trade_status"] == True]  # noqa: E712
    return {code: grp.sort_values("trade_date") for code, grp in visible.groupby("code", sort=False)}


def bars_pit_f22(grp: pd.DataFrame, as_of: date) -> list[DailyBar]:
    """All visible sessions with trade_date <= as_of for one code (PIT hygiene;
    F22 itself only ever touches trade_date < b2_date internally plus the B2 bar)."""
    return [to_daily_bar(row) for _, row in grp[grp["trade_date"] <= as_of].iterrows()]


def compute_f22(groups: dict[str, pd.DataFrame], episode: dict) -> tuple[bool | None, str | None]:
    """PIT materialization of F22 for one frozen domain episode.

    Frozen mapping: b2_date = signal_date, as_of = signal_date. Returns
    (value, reason); reason in {MISSING_B2_BAR, INSUFFICIENT_PRE5,
    ZERO_DENOMINATOR, OTHER_ERROR:...} or None when defined.
    """
    b2 = date.fromisoformat(episode["signal_date"])
    grp = groups.get(str(episode["code"]))
    if grp is None:
        return None, "MISSING_B2_BAR"
    bars = bars_pit_f22(grp, b2)
    if not bars:
        return None, "MISSING_B2_BAR"
    # Pre-compute PRE5_N with the SAME PIT bars and the same window rule as
    # the frozen factor (trade_date < b2_date) so undefined reasons are
    # auditable: <5 -> INSUFFICIENT_PRE5, >=5 with zero mean ->
    # ZERO_DENOMINATOR, everything else from the factor -> OTHER_ERROR.
    pre5_n = sum(1 for bar in bars if bar.trade_date < b2)
    try:
        value = fl.b2_huge_upper_shadow_volume(bars, b2)
    except ValueError as exc:
        if "b2 bar missing" in str(exc):
            return None, "MISSING_B2_BAR"
        return None, f"OTHER_ERROR:{type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001 - any error is a fail-closed OTHER_ERROR
        return None, f"OTHER_ERROR:{type(exc).__name__}"
    if value is None:
        if pre5_n < 5:
            return None, "INSUFFICIENT_PRE5"
        return None, "ZERO_DENOMINATOR"
    return value, None


def timing_bucket(days_since_anchor: int) -> str:
    if days_since_anchor <= 2:
        return "T1-2"
    if days_since_anchor == 3:
        return "T3"
    if days_since_anchor <= 5:
        return "T4-5"
    return "T6-10"


def _round(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        fv = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if fv != fv or fv in (float("inf"), float("-inf")):
        return None
    return round(fv, 6)


def check_accounting(population_n: int, defined_true_n: int, defined_false_n: int, undefined_n: int) -> dict:
    if defined_true_n + defined_false_n + undefined_n != population_n:
        raise RuntimeError(
            f"ACCOUNTING INVARIANT FAILED: DEFINED_TRUE_N({defined_true_n}) + DEFINED_FALSE_N({defined_false_n}) "
            f"+ UNDEFINED_N({undefined_n}) != POPULATION_N({population_n})"
        )
    return {
        "POPULATION_N": population_n,
        "DEFINED_TRUE_N": defined_true_n,
        "DEFINED_FALSE_N": defined_false_n,
        "UNDEFINED_N": undefined_n,
    }


def group_metrics(outcomes: pd.Series, r: pd.Series) -> dict:
    """Descriptive metrics for one F22 group (strict denominator = WIN_S1 +
    LOSS_INVALID; CANCEL_GAP_INVALID excluded from strict; R metrics strictly
    on the WIN_S1 + LOSS_INVALID subset with numeric r_multiple only —
    CANCEL_GAP_INVALID must never enter R_DEFINED_N / P(R>0) / mean_R /
    median_R even when it carries a numeric r_multiple)."""
    win = int((outcomes == "WIN_S1").sum())
    loss = int((outcomes == "LOSS_INVALID").sum())
    cancel_gap = int((outcomes == "CANCEL_GAP_INVALID").sum())
    total = int(outcomes.size)
    strict_mask = outcomes.isin(STRICT_OUTCOMES)
    r_num = pd.to_numeric(r[strict_mask], errors="coerce")
    r_defined = r_num.dropna()
    r_def = int(r_defined.size)
    denominator = win + loss
    strict_win_rate = win / denominator if denominator > 0 else float("nan")
    fail_rate = loss / denominator if denominator > 0 else float("nan")
    return {
        "N": total,
        "STRICT_N": denominator,
        "WIN_S1": win,
        "LOSS_INVALID": loss,
        "CANCEL_GAP_INVALID": cancel_gap,
        "strict_win_rate": _round(strict_win_rate),
        "FAIL_RATE": _round(fail_rate),
        "R_DEFINED_N": r_def,
        "P(R>0)": _round(float((r_defined > 0).mean())) if r_def else None,
        "mean_R": _round(float(r_defined.mean())) if r_def else None,
        "median_R": _round(float(r_defined.median())) if r_def else None,
    }


def primary_metrics_exact(win_true: int, loss_true: int, win_false: int, loss_false: int) -> dict:
    """Pre-registered primary metrics as exact Decimals.

    PRIMARY_METRIC_UNDEFINED -> RuntimeError (fail closed): any group strict
    denominator N < 2 (zero cell), or any zero odds cell (WIN_S1 == 0 or
    LOSS_INVALID == 0 within a group) which makes OR_FAILURE undefined.
    No continuity correction (pre-registration does not freeze one).
    """
    n_true = win_true + loss_true
    n_false = win_false + loss_false
    if n_true < 2 or n_false < 2:
        raise RuntimeError(
            f"PRIMARY_METRIC_UNDEFINED: strict denominator N < 2 (TRUE {n_true}, FALSE {n_false})"
        )
    if win_true == 0 or loss_true == 0 or win_false == 0 or loss_false == 0:
        raise RuntimeError(
            f"PRIMARY_METRIC_UNDEFINED: zero odds cell (TRUE {win_true}/{loss_true}, FALSE {win_false}/{loss_false})"
        )
    fr_true = Decimal(loss_true) / Decimal(win_true + loss_true)
    fr_false = Decimal(loss_false) / Decimal(win_false + loss_false)
    odds_true = Decimal(loss_true) / Decimal(win_true)
    odds_false = Decimal(loss_false) / Decimal(win_false)
    return {
        "FAIL_RATE_TRUE": fr_true,
        "FAIL_RATE_FALSE": fr_false,
        "DELTA_FAIL_RATE": fr_true - fr_false,
        "OR_FAILURE": odds_true / odds_false,
    }


def verdict(delta_fail_rate: Decimal, or_failure: Decimal) -> str:
    """Frozen H22A verdict gate (single gate; exact Decimal comparison)."""
    if delta_fail_rate > ZERO and or_failure > ONE:
        return "SUPPORTED_DIRECTIONALLY"
    return "REJECT"


def stratum_side_rows(df: pd.DataFrame, strata: list[str], key: str) -> list[dict]:
    """Secondary descriptive: per stratum, F22_TRUE vs F22_FALSE sides on the
    strict subset; SMALL_CELL when either side strict N < 20."""
    rows = []
    for s in strata:
        sub = df[df[key] == s]
        if sub.empty:
            continue
        strict = sub[sub["outcome"].isin(STRICT_OUTCOMES)]
        row: dict = {"stratum": s, "N": int(len(sub)), "SMALL_CELL": False}
        for side, label in ((True, "TRUE"), (False, "FALSE")):
            side_df = strict[strict["f22"] == side]
            m = group_metrics(side_df["outcome"], side_df["r_multiple"])
            row[f"{label}_N"] = m["N"]
            row[f"{label}_STRICT_N"] = m["STRICT_N"]
            row[f"{label}_FAIL_RATE"] = m["FAIL_RATE"]
            row[f"{label}_P_R_POSITIVE"] = m["P(R>0)"]
            row[f"{label}_MEAN_R"] = m["mean_R"]
            if m["STRICT_N"] < SMALL_CELL_N:
                row["SMALL_CELL"] = True
        rows.append(row)
    return rows


def robust_r_diagnostics(r: pd.Series) -> dict:
    r_num = pd.to_numeric(r, errors="coerce").dropna()
    if r_num.empty:
        return {k: None for k in ("p90_R", "p95_R", "p99_R", "max_R", "top1pct_R_contribution", "trim_top1pct_mean_R")}
    total = float(r_num.sum())
    sorted_r = r_num.sort_values(ascending=False)
    n_top = max(1, int(len(sorted_r) * 0.01))
    top = sorted_r.head(n_top)
    top_contrib = float(top.sum()) / total if total else float("nan")
    trim_mean = float(sorted_r.iloc[n_top:].mean())
    return {
        "p90_R": _round(float(r_num.quantile(0.90))),
        "p95_R": _round(float(r_num.quantile(0.95))),
        "p99_R": _round(float(r_num.quantile(0.99))),
        "max_R": _round(float(r_num.max())),
        "top1pct_R_contribution": _round(top_contrib),
        "trim_top1pct_mean_R": _round(trim_mean),
    }


def main(episodes_path: Path, daily_path: Path, out_dir: Path) -> dict:
    """Full pre-registered pipeline. Writes JSON + MD.

    No input bypass: episodes and daily are ALWAYS loaded through their SHA
    gates inside this function. Fail closed before writing any artifact.
    """
    episodes = load_episodes(episodes_path)
    daily = load_daily(daily_path)
    groups = group_daily(daily)

    domain = episodes[
        episodes["outcome"].isin(RESOLVED_OUTCOMES)
        & episodes["setup_stage"].isin(POPULATION_STAGES)
    ].copy()
    domain["r_multiple"] = pd.to_numeric(domain["r_multiple"], errors="coerce")

    f22_vals: list[bool | None] = []
    reasons: list[str | None] = []
    errors: list[str] = []
    for _, ep in domain.iterrows():
        value, reason = compute_f22(groups, ep.to_dict())
        f22_vals.append(value)
        reasons.append(reason)
        if reason is not None and reason.startswith("OTHER_ERROR"):
            errors.append(f"{ep['setup_id']}: {reason}")
    if errors:
        raise RuntimeError(f"OTHER_ERROR count > 0: {errors[:5]}")

    domain["f22"] = f22_vals
    domain["undefined_reason"] = reasons

    defined_true = domain[domain["f22"] == True]  # noqa: E712
    defined_false = domain[domain["f22"] == False]  # noqa: E712
    undefined = domain[domain["f22"].isna()]

    accounting = check_accounting(len(domain), len(defined_true), len(defined_false), len(undefined))

    strict_true = defined_true[defined_true["outcome"].isin(STRICT_OUTCOMES)]
    strict_false = defined_false[defined_false["outcome"].isin(STRICT_OUTCOMES)]
    primary_true_n = int(len(strict_true))
    primary_false_n = int(len(strict_false))

    win_true = int((strict_true["outcome"] == "WIN_S1").sum())
    loss_true = int((strict_true["outcome"] == "LOSS_INVALID").sum())
    win_false = int((strict_false["outcome"] == "WIN_S1").sum())
    loss_false = int((strict_false["outcome"] == "LOSS_INVALID").sum())

    exact = primary_metrics_exact(win_true, loss_true, win_false, loss_false)  # PRIMARY_METRIC_UNDEFINED -> raise
    primary_small_cell = primary_true_n < SMALL_CELL_N or primary_false_n < SMALL_CELL_N
    if primary_small_cell:
        status = "INSUFFICIENT_PRIMARY_N"
        result_verdict = None
    else:
        result_verdict = verdict(exact["DELTA_FAIL_RATE"], exact["OR_FAILURE"])
        status = result_verdict

    reason_counts = {}
    for k, v in undefined["undefined_reason"].value_counts(dropna=False).items():
        reason_counts[str(k)] = int(v)

    groups_desc = [
        {"group": "F22_TRUE", **group_metrics(defined_true["outcome"], defined_true["r_multiple"])},
        {"group": "F22_FALSE", **group_metrics(defined_false["outcome"], defined_false["r_multiple"])},
    ]

    domain["timing"] = domain["days_since_anchor"].apply(timing_bucket)
    stage_rows = stratum_side_rows(domain, COMPOSITION_STAGES, "setup_stage")
    timing_rows = stratum_side_rows(domain, TIMING_BUCKETS, "timing")

    r_strict = pd.concat([strict_true["r_multiple"], strict_false["r_multiple"]])

    defined_n = len(defined_true) + len(defined_false)
    f22_true_frequency = len(defined_true) / defined_n if defined_n else None

    direction_reversal = exact["DELTA_FAIL_RATE"] < ZERO

    result = {
        "CONTRACT_HEAD": CONTRACT_HEAD,
        "IMPLEMENTATION_HEAD": IMPLEMENTATION_HEAD,
        "PREREG_HEAD": PREREG_HEAD,
        "EPISODES_PATH": str(episodes_path),
        "EPISODES_SHA256": EPISODES_SHA,
        "DAILY_PATH": str(daily_path),
        "DAILY_SHA256": DAILY_SHA,
        "POPULATION_DEFINITION": "resolved episodes AND setup_stage in {B2_READY, B2_CONFIRMED}; b2_date = signal_date",
        "POPULATION_N": accounting["POPULATION_N"],
        "DEFINED_TRUE_N": accounting["DEFINED_TRUE_N"],
        "DEFINED_FALSE_N": accounting["DEFINED_FALSE_N"],
        "UNDEFINED_N": accounting["UNDEFINED_N"],
        "UNDEFINED_REASONS": reason_counts,
        "ACCOUNTING_MATCH": True,
        "PRIMARY_TRUE_N": primary_true_n,
        "PRIMARY_FALSE_N": primary_false_n,
        "WIN_S1_TRUE": win_true,
        "LOSS_INVALID_TRUE": loss_true,
        "WIN_S1_FALSE": win_false,
        "LOSS_INVALID_FALSE": loss_false,
        "FAIL_RATE_TRUE": _round(exact["FAIL_RATE_TRUE"]),
        "FAIL_RATE_FALSE": _round(exact["FAIL_RATE_FALSE"]),
        "DELTA_FAIL_RATE": _round(exact["DELTA_FAIL_RATE"]),
        "OR_FAILURE": _round(exact["OR_FAILURE"]),
        "PRIMARY_SMALL_CELL": primary_small_cell,
        "PRIMARY_METRIC_UNDEFINED": False,
        "STATUS": status,
        "VERDICT": result_verdict,
        "VERDICT_RULE": "A) accounting/OTHER_ERROR -> FAIL CLOSED; B) PRIMARY_METRIC_UNDEFINED -> FAIL CLOSED; "
                        "C) PRIMARY_TRUE_N<20 OR PRIMARY_FALSE_N<20 -> INSUFFICIENT_PRIMARY_N; "
                        "D) DELTA_FAIL_RATE>0 AND OR_FAILURE>1 -> SUPPORTED_DIRECTIONALLY else REJECT "
                        "(SUPPORTED_DIRECTIONALLY != statistical significance != VALIDATED != PROMOTED)",
        "GROUPS": groups_desc,
        "F22_TRUE_FREQUENCY": _round(f22_true_frequency),
        "DIRECTION_REVERSAL_OBSERVATION": (
            "DELTA_FAIL_RATE < 0: F22_TRUE group has LOWER failure rate than F22_FALSE "
            "(direction reversed vs H22A; prereg section 6 requires recording this observation)"
            if direction_reversal
            else None
        ),
        "STAGE_STRATA": stage_rows,
        "TIMING_STRATA": timing_rows,
        "R_TAIL": robust_r_diagnostics(r_strict),
        "NEW_HYPOTHESES": [],
        "CONCLUSION": {
            "F22_OUTCOME_VALIDATION_V01": status,
            "VERDICT": result_verdict,
            "PREDICTIVE_VALUE": (
                "INSUFFICIENT_PRIMARY_N: sample too small for a verdict"
                if status == "INSUFFICIENT_PRIMARY_N"
                else "directional evidence only; not validated"
            ),
            "VALIDATED": False,
            "PROMOTED": False,
        },
        "OUTCOME_AWARE_CONTRACT_CHANGE": False,
        "THRESHOLD_SEARCH": False,
        "SUBGROUP_RESCUE": False,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "f22-outcome-validation-v01.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "f22-outcome-validation-v01.md").write_text(render_report(result), encoding="utf-8")
    return result


def render_report(result: dict) -> str:
    lines = [
        "# F22 B2 HUGE UPPER SHADOW VOLUME OUTCOME VALIDATION V01 — 预注册验证报告",
        "",
        f"- F22 CONTRACT = FROZEN / CLOSED（AUTHORITY {result['CONTRACT_HEAD']}，Sol audit PASS）",
        f"- 函数：factor_lab.b2_huge_upper_shadow_volume（IMPLEMENTATION HEAD {result['IMPLEMENTATION_HEAD']}）",
        f"- 预注册：{result['PREREG_HEAD']}（PASS / FROZEN / CLOSED）",
        f"- population：{result['POPULATION_DEFINITION']}",
        f"- episodes SHA: {result['EPISODES_SHA256']}；daily SHA: {result['DAILY_SHA256']}",
        f"- ACCOUNTING_MATCH = {result['ACCOUNTING_MATCH']}",
        "",
        "## MATERIALIZATION ACCOUNTING（frozen 3b）",
        f"- POPULATION_N = {result['POPULATION_N']}；DEFINED_TRUE_N = {result['DEFINED_TRUE_N']}；"
        f"DEFINED_FALSE_N = {result['DEFINED_FALSE_N']}；UNDEFINED_N = {result['UNDEFINED_N']}",
        f"- UNDEFINED_REASONS = {result['UNDEFINED_REASONS']}",
        f"- 守恒：DEFINED_TRUE_N + DEFINED_FALSE_N + UNDEFINED_N == POPULATION_N（fail closed）",
        "",
        "## PRIMARY（H22A 布尔双 metric gate，frozen）",
        f"- PRIMARY_TRUE_N = {result['PRIMARY_TRUE_N']}；PRIMARY_FALSE_N = {result['PRIMARY_FALSE_N']}",
        f"- WIN_S1_TRUE = {result['WIN_S1_TRUE']}；LOSS_INVALID_TRUE = {result['LOSS_INVALID_TRUE']}；"
        f"WIN_S1_FALSE = {result['WIN_S1_FALSE']}；LOSS_INVALID_FALSE = {result['LOSS_INVALID_FALSE']}",
        f"- FAIL_RATE_TRUE = {result['FAIL_RATE_TRUE']}；FAIL_RATE_FALSE = {result['FAIL_RATE_FALSE']}",
        f"- DELTA_FAIL_RATE = {result['DELTA_FAIL_RATE']}；OR_FAILURE = {result['OR_FAILURE']}",
        f"- PRIMARY_SMALL_CELL = {result['PRIMARY_SMALL_CELL']}；PRIMARY_METRIC_UNDEFINED = {result['PRIMARY_METRIC_UNDEFINED']}",
        f"- **STATUS = {result['STATUS']}；VERDICT = {result['VERDICT']}**（规则：{result['VERDICT_RULE']}；"
        "SUPPORTED_DIRECTIONALLY != statistical significance != VALIDATED != PROMOTED）",
        "",
        "## GROUP DESCRIPTIVE（仅描述，不改变 verdict）",
        "| group | N | STRICT_N | WIN_S1 | LOSS_INVALID | CANCEL_GAP_INVALID | strict_win_rate | FAIL_RATE | R_DEFINED_N | P(R>0) | mean_R | median_R |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["GROUPS"]:
        lines.append(
            f"| {row['group']} | {row['N']} | {row['STRICT_N']} | {row['WIN_S1']} | {row['LOSS_INVALID']} | "
            f"{row['CANCEL_GAP_INVALID']} | {row['strict_win_rate']} | {row['FAIL_RATE']} | {row['R_DEFINED_N']} | "
            f"{row['P(R>0)']} | {row['mean_R']} | {row['median_R']} |"
        )
    lines += ["", f"- F22_TRUE 事件频率（defined 内）= {result['F22_TRUE_FREQUENCY']}"]
    if result.get("DIRECTION_REVERSAL_OBSERVATION"):
        lines += ["", f"- **OBSERVATION（prereg §6 要求记录）**：{result['DIRECTION_REVERSAL_OBSERVATION']}"]
    for name, rows in (("STAGE", result["STAGE_STRATA"]), ("TIMING", result["TIMING_STRATA"])):
        lines += ["", f"## {name} COMPOSITION（SMALL_CELL 排除方向解释；只报告，不改变 primary verdict）"]
        for row in rows:
            flags = " SMALL_CELL" if row["SMALL_CELL"] else ""
            lines.append(
                f"- {row['stratum']}: N={row['N']}；TRUE: STRICT_N={row['TRUE_STRICT_N']} FAIL_RATE={row['TRUE_FAIL_RATE']} "
                f"P(R>0)={row['TRUE_P_R_POSITIVE']}；FALSE: STRICT_N={row['FALSE_STRICT_N']} FAIL_RATE={row['FALSE_FAIL_RATE']} "
                f"P(R>0)={row['FALSE_P_R_POSITIVE']}{flags}"
            )
    lines += [
        "",
        "## R TAIL（H4B right-tail caveat，非 gate）",
        f"- {result['R_TAIL']}",
        "",
        "## CONCLUSION（frozen validation V01 最终记录）",
        f"- F22 OUTCOME VALIDATION V01 = {result['CONCLUSION']['F22_OUTCOME_VALIDATION_V01']}（VERDICT = {result['CONCLUSION']['VERDICT']}）",
        f"- PREDICTIVE_VALUE: {result['CONCLUSION']['PREDICTIVE_VALUE']}",
        f"- VALIDATED = {result['CONCLUSION']['VALIDATED']}；PROMOTED = {result['CONCLUSION']['PROMOTED']}",
        "- stage / timing 观察仅作 OBSERVATION / NEW HYPOTHESIS，不升级为规则",
        "",
        "## LIMITATIONS",
        "- GitHub 无 CI；本报告为作者本地验证（SHA 门禁通过）",
        "- SUPPORTED_DIRECTIONALLY 不代表 statistical significance（预注册未冻结 p-value/CI/alpha）",
        "- CANCEL_GAP_INVALID 不进入 strict binary denominator，仅 accounting",
        "- R 仅定义于 WIN_S1/LOSS_INVALID 且 r_multiple 数值化的子集；P(R>0) 在该子集上计算",
        f"- NEW_HYPOTHESES = {result['NEW_HYPOTHESES']}",
        "- OUTCOME_AWARE_CONTRACT_CHANGE = False；THRESHOLD_SEARCH = False；SUBGROUP_RESCUE = False",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    main(
        episodes_path=root / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet",
        daily_path=root / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet",
        out_dir=root / "research/factor-lab/runs/f22-outcome-validation-v01",
    )
    print("OK")
    sys.exit(0)
