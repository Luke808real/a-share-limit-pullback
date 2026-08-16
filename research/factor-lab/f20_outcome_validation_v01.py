"""F20 B2 VOLUME VS 20D MEAN OUTCOME VALIDATION V01 — pre-registered outcome validation.

Frozen inputs (SHA gate, fail closed):
  episodes: data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/
            corrected-b2-trigger-outcome/episodes.parquet   (66d5943f...)
  daily:    data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet (e7243dee...)

F20 authority: factor_lab.b2_volume_vs_20d_mean (F20 CONTRACT FROZEN / CLOSED, HEAD ff4ea77,
Sol audit PASS). b2 event date := signal_date for B2-stage episodes (frozen semantics).

Pre-registered design (runs/f20-outcome-prereg-v01/f20-outcome-prereg-v01.md, commit 758768e):
  Primary H5A gate: rho_strict > 0 AND rho_R_positive > 0 -> SUPPORTED_DIRECTIONALLY else REJECT.
  - rho_strict: Spearman(F20, strict binary) on strict-defined population
    (WIN_S1=1, LOSS_INVALID=0; CANCEL_GAP_INVALID excluded from strict denominator)
  - rho_R_positive: Spearman(F20, 1[R>0]) on R-defined population (WIN_S1 + LOSS_INVALID)
  Quartile Q1-Q4 descriptive only; stage/timing composition reports direction only
  (SMALL_CELL N<20 excluded); NO threshold mining; undefined F20 only accounted.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

# Deterministic import: always use THIS checkout's src.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from limit_pullback import factor_lab as fl
from limit_pullback.models.market import DailyBar

EPISODES_SHA = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
DAILY_SHA = "e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514"
EPISODES_TOTAL = 31422
RESOLVED_N = 9625
RESOLVED_OUTCOMES = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")
B2_STAGES = ("B2_READY", "B2_CONFIRMED")
F20_CONTRACT_HEAD = "ff4ea77a80c2144fda181b6e412a795b6c1952d9"
PREREG_COMMIT = "758768e1dc0db16fa0d9d75a6c25652d2d789671"
TZ = timezone(timedelta(hours=8))
STRICT_OUTCOMES = ("WIN_S1", "LOSS_INVALID")


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
        source="F20_VALIDATION",
        fetched_at=datetime.combine(row["trade_date"], time(16, 0), tzinfo=TZ),
    )


def group_daily(daily: pd.DataFrame) -> dict[str, pd.DataFrame]:
    visible = daily[daily["trade_status"] == True]  # noqa: E712
    return {code: grp.sort_values("trade_date") for code, grp in visible.groupby("code", sort=False)}


def bars_pit_f20(grp: pd.DataFrame, as_of: date) -> list[DailyBar]:
    """All visible sessions with trade_date <= as_of for one code (PIT hygiene;
    F20 itself only ever touches trade_date < b2_date internally)."""
    return [to_daily_bar(row) for _, row in grp[grp["trade_date"] <= as_of].iterrows()]


def compute_f20(groups: dict[str, pd.DataFrame], episode: dict) -> tuple[Decimal | None, str | None]:
    """PIT materialization of F20 for one frozen B2-stage episode.

    b2 event date := signal_date (frozen semantics). Returns (f20, reason);
    reason in {NO_BARS, OTHER_ERROR:...} or None when defined (F20 None ->
    "F20_UNDEFINED", e.g. PRE20_N < 20 or zero window mean).
    """
    anchor = date.fromisoformat(episode["anchor_date"])
    b2 = date.fromisoformat(episode["signal_date"])
    grp = groups.get(str(episode["code"]))
    if grp is None:
        return None, "NO_BARS"
    bars = bars_pit_f20(grp, b2)
    if not bars:
        return None, "NO_BARS"
    try:
        value = fl.b2_volume_vs_20d_mean(bars, anchor, b2)
    except Exception as exc:  # noqa: BLE001 - any error is a fail-closed OTHER_ERROR
        return None, f"OTHER_ERROR:{type(exc).__name__}"
    if value is None:
        return None, "F20_UNDEFINED"
    return value, None


def timing_bucket(days_since_anchor: int) -> str:
    if days_since_anchor <= 2:
        return "T1-2"
    if days_since_anchor == 3:
        return "T3"
    if days_since_anchor <= 5:
        return "T4-5"
    return "T6-10"


def _round(value: float) -> float | None:
    if value is None or (isinstance(value, float) and (value != value or value in (float("inf"), float("-inf")))):
        return None
    return round(float(value), 6)


def group_metrics(outcomes: pd.Series, r: pd.Series) -> dict:
    """Descriptive metrics for one group (strict_win_rate on strict denominator;
    R metrics on R-defined subset only)."""
    win = int((outcomes == "WIN_S1").sum())
    loss = int((outcomes == "LOSS_INVALID").sum())
    cancel_gap = int((outcomes == "CANCEL_GAP_INVALID").sum())
    total = int(outcomes.size)
    r_num = pd.to_numeric(r, errors="coerce")
    r_defined = r_num.dropna()
    r_def = int(r_defined.size)
    denominator = win + loss
    strict_win_rate = win / denominator if denominator > 0 else float("nan")
    return {
        "N": total,
        "WIN_S1": win,
        "LOSS_INVALID": loss,
        "CANCEL_GAP_INVALID": cancel_gap,
        "strict_win_rate": _round(strict_win_rate),
        "R_DEFINED_N": r_def,
        "P(R>0)": _round(float((r_defined > 0).mean())) if r_def else None,
        "mean_R": _round(float(r_defined.mean())) if r_def else None,
        "median_R": _round(float(r_defined.median())) if r_def else None,
    }


def spearman_block(f20: pd.Series, y: pd.Series, label: str) -> dict:
    """Pre-registered Spearman block: rho / N / direction (p informational, NOT a gate)."""
    x = pd.to_numeric(f20, errors="coerce")
    yy = pd.to_numeric(y, errors="coerce")
    mask = x.notna() & yy.notna()
    n = int(mask.sum())
    if n < 2:
        return {"metric": label, "rho": None, "N": n, "direction": None, "p": None}
    rho, p = spearmanr(x[mask], yy[mask])
    return {
        "metric": label,
        "rho": _round(float(rho)),
        "N": n,
        "direction": "positive" if rho > 0 else ("nonpositive" if rho <= 0 else None),
        "p": _round(float(p)),
    }


def quartile_rows(df: pd.DataFrame) -> list[dict]:
    """Fixed quartile descriptive buckets (boundaries from F20's own distribution;
    descriptive only, never a threshold rule)."""
    f20 = pd.to_numeric(df["f20"], errors="coerce").dropna()
    if f20.empty:
        return []
    q1, q2, q3 = float(f20.quantile(0.25)), float(f20.quantile(0.50)), float(f20.quantile(0.75))
    labels = {0: "Q1", 1: "Q2", 2: "Q3", 3: "Q4"}
    bucket = []
    for v in f20:
        if v <= q1:
            bucket.append(0)
        elif v <= q2:
            bucket.append(1)
        elif v <= q3:
            bucket.append(2)
        else:
            bucket.append(3)
    df = df.copy()
    df["quartile"] = bucket
    rows = []
    for q in range(4):
        sub = df[df["quartile"] == q]
        if sub.empty:
            continue
        m = group_metrics(sub["outcome"], sub["r_multiple"])
        rows.append({
            "quartile": labels[q],
            "bounds": (None if q == 0 else _round([q1, q2, q3][q - 1])),
            "N": m["N"],
            "strict_win_rate": m["strict_win_rate"],
            "P(R>0)": m["P(R>0)"],
            "mean_R": m["mean_R"],
            "median_R": m["median_R"],
        })
    return rows


def robust_f20_distribution(f20: pd.Series) -> dict:
    num = pd.to_numeric(f20, errors="coerce").dropna()
    if num.empty:
        return {k: None for k in ("p10", "p25", "p50", "p75", "p90", "p95", "p99", "max")}
    return {
        "p10": _round(float(num.quantile(0.10))),
        "p25": _round(float(num.quantile(0.25))),
        "p50": _round(float(num.quantile(0.50))),
        "p75": _round(float(num.quantile(0.75))),
        "p90": _round(float(num.quantile(0.90))),
        "p95": _round(float(num.quantile(0.95))),
        "p99": _round(float(num.quantile(0.99))),
        "max": _round(float(num.max())),
    }


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


def composition_rows(df: pd.DataFrame, strata: list[str], key: str) -> list[dict]:
    rows = []
    for s in strata:
        sub = df[df[key] == s]
        if sub.empty:
            continue
        strict_sub = sub[sub["outcome"].isin(STRICT_OUTCOMES)]
        strict_block = spearman_block(strict_sub["f20"], (strict_sub["outcome"] == "WIN_S1").astype(int), "strict")
        rdef = strict_sub[strict_sub["r_multiple"].notna()]
        rpos_block = spearman_block(rdef["f20"], (rdef["r_multiple"] > 0).astype(int), "R>0")
        small = strict_block["N"] < 20 or rpos_block["N"] < 20
        rows.append({
            "stratum": s,
            "N": int(len(sub)),
            "rho_strict": strict_block["rho"],
            "N_strict": strict_block["N"],
            "rho_R_positive": rpos_block["rho"],
            "N_R_positive": rpos_block["N"],
            "eligible": not small,
            "SMALL_CELL": small,
        })
    return rows


def composition_direction(rows: list[dict]) -> dict:
    strict_pos = sum(1 for r in rows if r["eligible"] and r["rho_strict"] is not None and r["rho_strict"] > 0)
    strict_elig = sum(1 for r in rows if r["eligible"] and r["rho_strict"] is not None)
    rpos_pos = sum(1 for r in rows if r["eligible"] and r["rho_R_positive"] is not None and r["rho_R_positive"] > 0)
    rpos_elig = sum(1 for r in rows if r["eligible"] and r["rho_R_positive"] is not None)
    return {
        "STRICT_DIRECTION_POSITIVE_K": strict_pos,
        "STRICT_ELIGIBLE_K": strict_elig,
        "RPOS_DIRECTION_POSITIVE_K": rpos_pos,
        "RPOS_ELIGIBLE_K": rpos_elig,
    }


def verdict(rho_strict: float | None, rho_r_positive: float | None) -> str:
    """Pre-registered H5A verdict (single gate, no metric substitution)."""
    if rho_strict is not None and rho_r_positive is not None:
        if rho_strict > 0 and rho_r_positive > 0:
            return "SUPPORTED_DIRECTIONALLY"
    return "REJECT"


def check_accounting(resolved_n: int, defined_n: int, undefined_n: int, strict_n: int,
                     r_defined_n: int, cancel_gap_n: int) -> dict:
    if defined_n + undefined_n != resolved_n:
        raise RuntimeError(
            f"ACCOUNTING INVARIANT FAILED: F20_DEFINED_N({defined_n}) + F20_UNDEFINED_N({undefined_n}) != RESOLVED_N({resolved_n})"
        )
    if strict_n + cancel_gap_n != defined_n:
        raise RuntimeError(
            f"ACCOUNTING INVARIANT FAILED: STRICT_N({strict_n}) + CANCEL_GAP_N({cancel_gap_n}) != F20_DEFINED_N({defined_n})"
        )
    return {
        "RESOLVED_N": resolved_n,
        "F20_DEFINED_N": defined_n,
        "F20_UNDEFINED_N": undefined_n,
        "STRICT_N": strict_n,
        "R_DEFINED_N": r_defined_n,
        "CANCEL_GAP_ACCOUNTING_N": cancel_gap_n,
    }


def main(episodes_path: Path, daily_path: Path, out_dir: Path) -> dict:
    """Full pre-registered pipeline. Returns the result dict (and writes JSON + MD).

    No input bypass: episodes and daily are ALWAYS loaded through their SHA
    gates inside this function.
    """
    episodes = load_episodes(episodes_path)
    daily = load_daily(daily_path)
    groups = group_daily(daily)

    resolved = episodes[episodes["outcome"].isin(RESOLVED_OUTCOMES)].copy()
    if len(resolved) != RESOLVED_N:
        raise RuntimeError(f"RESOLVED_N mismatch: {len(resolved)} != {RESOLVED_N}")

    f20_vals: list[Decimal | None] = []
    reasons: list[str | None] = []
    errors: list[str] = []
    for _, ep in resolved.iterrows():
        if ep["setup_stage"] not in B2_STAGES:
            f20_vals.append(None)
            reasons.append("NON_B2_STAGE")
            continue
        value, reason = compute_f20(groups, ep.to_dict())
        f20_vals.append(value)
        reasons.append(reason)
        if reason is not None and reason.startswith("OTHER_ERROR"):
            errors.append(f"{ep['setup_id']}: {reason}")
    if errors:
        raise RuntimeError(f"OTHER_ERROR count > 0: {errors[:5]}")

    resolved["f20"] = f20_vals
    resolved["undefined_reason"] = reasons
    resolved["r_multiple"] = pd.to_numeric(resolved["r_multiple"], errors="coerce")

    defined = resolved[resolved["f20"].notna()].copy()
    undefined = resolved[resolved["f20"].isna()]
    strict = defined[defined["outcome"].isin(STRICT_OUTCOMES)].copy()
    r_defined = defined[defined["outcome"].isin(STRICT_OUTCOMES)].copy()
    r_defined = r_defined[r_defined["r_multiple"].notna()]
    cancel_gap = defined[defined["outcome"] == "CANCEL_GAP_INVALID"]

    strict["strict_binary"] = (strict["outcome"] == "WIN_S1").astype(int)
    r_defined["r_positive"] = (r_defined["r_multiple"] > 0).astype(int)

    accounting = check_accounting(
        resolved_n=len(resolved),
        defined_n=len(defined),
        undefined_n=len(undefined),
        strict_n=len(strict),
        r_defined_n=len(r_defined),
        cancel_gap_n=len(cancel_gap),
    )

    strict_block = spearman_block(strict["f20"], strict["strict_binary"], "strict")
    rpos_block = spearman_block(r_defined["f20"], r_defined["r_positive"], "R>0")
    result_verdict = verdict(strict_block["rho"], rpos_block["rho"])

    stage_rows = composition_rows(defined, list(B2_STAGES), "setup_stage")
    defined["timing"] = defined["days_since_anchor"].apply(timing_bucket)
    timing_rows = composition_rows(defined, ["T1-2", "T3", "T4-5", "T6-10"], "timing")

    reason_counts = {}
    for k, v in resolved["undefined_reason"].value_counts(dropna=False).items():
        key = "DEFINED" if k is None or (isinstance(k, float) and k != k) else str(k)
        reason_counts[key] = int(v)

    result = {
        "PROVENANCE": {
            "episodes_sha": EPISODES_SHA,
            "daily_sha": DAILY_SHA,
            "episodes_total": len(episodes),
            "resolved_n": len(resolved),
            "f20_contract_head": F20_CONTRACT_HEAD,
            "prereg_commit": PREREG_COMMIT,
            "f20_function": "factor_lab.b2_volume_vs_20d_mean",
            "b2_date_semantics": "signal_date for B2-stage episodes (frozen)",
            "as_of": "signal_date",
            "defined_population": "B2-stage episodes with PRE20_N == 20 and nonzero window mean",
        },
        "ACCOUNTING": {
            "RESOLVED_N": accounting["RESOLVED_N"],
            "F20_DEFINED_N": accounting["F20_DEFINED_N"],
            "F20_UNDEFINED_N": accounting["F20_UNDEFINED_N"],
            "STRICT_N": accounting["STRICT_N"],
            "R_DEFINED_N": accounting["R_DEFINED_N"],
            "CANCEL_GAP_ACCOUNTING_N": accounting["CANCEL_GAP_ACCOUNTING_N"],
            "UNDEFINED_REASONS": reason_counts,
        },
        "PRIMARY": {
            "STRICT": strict_block,
            "R_POSITIVE": rpos_block,
            "VERDICT": result_verdict,
            "VERDICT_RULE": "rho_strict > 0 AND rho_R_positive > 0 -> SUPPORTED_DIRECTIONALLY else REJECT",
        },
        "QUARTILES": quartile_rows(defined),
        "ROBUST": {
            "F20_DISTRIBUTION": robust_f20_distribution(defined["f20"]),
            "R_TAIL": robust_r_diagnostics(r_defined["r_multiple"]),
        },
        "STAGE_STRATA": stage_rows,
        "TIMING_STRATA": timing_rows,
        "COMPOSITION_DIRECTION": {
            "STAGE": composition_direction(stage_rows),
            "TIMING": composition_direction(timing_rows),
        },
        "CONCLUSION": {
            "F20_OUTCOME_VALIDATION_V01": result_verdict,
            "PREDICTIVE_VALUE": (
                "global main effect not supported" if result_verdict == "REJECT"
                else "directional evidence only; not validated"
            ),
            "VALIDATED": False,
            "PROMOTED": False,
        },
        "NEW_HYPOTHESES": [],
        "OUTCOME_AWARE_CONTRACT_CHANGE": False,
        "THRESHOLD_SEARCH": False,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "f20-outcome-validation-v01.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "f20-outcome-validation-v01.md").write_text(render_report(result), encoding="utf-8")
    return result


def render_report(result: dict) -> str:
    p = result["PROVENANCE"]
    a = result["ACCOUNTING"]
    prim = result["PRIMARY"]
    lines = [
        "# F20 B2 VOLUME VS 20D MEAN OUTCOME VALIDATION V01 — 预注册验证报告",
        "",
        f"- F20 CONTRACT = FROZEN / CLOSED（HEAD {p['f20_contract_head']}，Sol audit PASS）",
        f"- 函数：{p['f20_function']}；预注册：commit {p['prereg_commit']}",
        f"- b2 event date := {p['b2_date_semantics']}；as_of = {p['as_of']}",
        f"- episodes SHA: {p['episodes_sha']}；daily SHA: {p['daily_sha']}",
        f"- EPISODES_TOTAL = {p['episodes_total']}；RESOLVED_N = {p['resolved_n']}",
        "",
        "## ACCOUNTING",
        f"- RESOLVED_N = {a['RESOLVED_N']}；F20_DEFINED_N = {a['F20_DEFINED_N']}；F20_UNDEFINED_N = {a['F20_UNDEFINED_N']}",
        f"- STRICT_N = {a['STRICT_N']}；R_DEFINED_N = {a['R_DEFINED_N']}；CANCEL_GAP_ACCOUNTING_N = {a['CANCEL_GAP_ACCOUNTING_N']}",
        f"- UNDEFINED_REASONS = {a['UNDEFINED_REASONS']}",
        "",
        "## PRIMARY（H5A 连续 Spearman 双 gate）",
        f"- rho_strict = {prim['STRICT']['rho']}（N={prim['STRICT']['N']}，direction={prim['STRICT']['direction']}，p={prim['STRICT']['p']}，p 非 gate）",
        f"- rho_R_positive = {prim['R_POSITIVE']['rho']}（N={prim['R_POSITIVE']['N']}，direction={prim['R_POSITIVE']['direction']}，p={prim['R_POSITIVE']['p']}，p 非 gate）",
        f"- **H5A = {prim['VERDICT']}**（规则：{prim['VERDICT_RULE']}；SUPPORTED_DIRECTIONALLY != VALIDATED != PROMOTED）",
        "",
        "## QUARTILE DESCRIPTIVE（仅描述，不得作为 threshold rule）",
        "| Q | 上界 | N | strict_win_rate | P(R>0) | mean_R | median_R |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["QUARTILES"]:
        lines.append(
            f"| {row['quartile']} | {row['bounds']} | {row['N']} | {row['strict_win_rate']} | "
            f"{row['P(R>0)']} | {row['mean_R']} | {row['median_R']} |"
        )
    lines += [
        "",
        "## ROBUSTNESS（非 verdict gate）",
        f"- F20 分布（defined population）：{result['ROBUST']['F20_DISTRIBUTION']}",
        f"- R 尾部（R-defined，H4B right-tail caveat）：{result['ROBUST']['R_TAIL']}",
    ]
    for name, rows in (("STAGE", result["STAGE_STRATA"]), ("TIMING", result["TIMING_STRATA"])):
        lines += ["", f"## {name} COMPOSITION（SMALL_CELL 排除；只报告方向，不改变 primary verdict）"]
        for row in rows:
            lines.append(
                f"- {row['stratum']}: N={row['N']}，rho_strict={row['rho_strict']}（N={row['N_strict']}），"
                f"rho_R_positive={row['rho_R_positive']}（N={row['N_R_positive']}）"
                f"{' SMALL_CELL' if row['SMALL_CELL'] else ''}"
            )
        lines.append(f"- 方向汇总：{result['COMPOSITION_DIRECTION'][name]}")
    lines += [
        "",
        "## CONCLUSION（frozen validation V01 最终记录）",
        f"- F20 OUTCOME VALIDATION V01 = {result['CONCLUSION']['F20_OUTCOME_VALIDATION_V01']}",
        f"- PREDICTIVE_VALUE: {result['CONCLUSION']['PREDICTIVE_VALUE']}",
        f"- VALIDATED = {result['CONCLUSION']['VALIDATED']}；PROMOTED = {result['CONCLUSION']['PROMOTED']}",
        "- quartile / stage / timing 观察仅作 OBSERVATION / NEW HYPOTHESIS，不升级为规则",
        "",
        "## LIMITATIONS",
        "- GitHub 无 CI；本报告为作者本地验证（SHA 门禁通过）",
        "- mean_R 受 H4B 已确认的极端右尾风险影响，不作为 primary gate；见 R_TAIL",
        "- CANCEL_GAP_INVALID 不进入 strict binary denominator，仅 accounting",
        "- R 仅定义于 WIN_S1/LOSS_INVALID 子集；P(R>0) 在该子集上计算",
        "- F20 为合同冻结后首次 outcome 验证；SUPPORTED_DIRECTIONALLY 仅属 research evidence",
        f"- NEW_HYPOTHESES = {result['NEW_HYPOTHESES']}",
        "- OUTCOME_AWARE_CONTRACT_CHANGE = False；THRESHOLD_SEARCH = False",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    main(
        episodes_path=root / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet",
        daily_path=root / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet",
        out_dir=root / "research/factor-lab/runs/f20-outcome-validation-v01",
    )
    print("OK")
    sys.exit(0)
