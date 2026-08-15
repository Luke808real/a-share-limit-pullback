"""F18 SUPPORT CONFLUENCE OUTCOME VALIDATION V01 — pre-registered outcome validation.

Frozen inputs (SHA gate, fail closed):
  episodes: data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/
            corrected-b2-trigger-outcome/episodes.parquet   (66d5943f...)
  daily:    data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet (e7243dee...)

F18 authority: factor_lab.support_confluence_max_count (F18 CONTRACT FROZEN, HEAD e37c57b).
Pre-registered contrast: CONFLUENCE (F18 >= 2) vs NON_CONFLUENCE (F18 <= 1).
Hypothesis H4C: delta_strict_win_rate > 0 AND delta_p_r_gt_0 > 0 -> SUPPORTED_DIRECTIONALLY
else REJECT. No outcome-aware factor changes, no threshold search, no full-market regeneration.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

# Deterministic import: always use THIS checkout's src (pytest relies on
# pythonpath=["src"]; plain `python research/...py` must not pick up a
# stale editable install of limit_pullback).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from limit_pullback import factor_lab as fl
from limit_pullback.models.market import DailyBar

EPISODES_SHA = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
DAILY_SHA = "e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514"
EPISODES_TOTAL = 31422
RESOLVED_OUTCOMES = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")
TZ = timezone(timedelta(hours=8))
PRIMARY_CONTRAST = "F18 >= 2 vs F18 <= 1"


def sha256(path: Path) -> str:
    """SHA-256 of a file, hex digest."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_episodes(path: Path, expected_sha: str = EPISODES_SHA, expected_total: int = EPISODES_TOTAL) -> pd.DataFrame:
    """Load frozen episodes with SHA/total gate; fail closed on mismatch."""
    if sha256(path) != expected_sha:
        raise RuntimeError(f"episodes SHA mismatch: {path}")
    df = pd.read_parquet(path)
    if len(df) != expected_total:
        raise RuntimeError(f"episodes total mismatch: {len(df)} != {expected_total}")
    return df


def load_daily(path: Path, expected_sha: str = DAILY_SHA) -> pd.DataFrame:
    """Load frozen canonical daily bars with SHA gate; fail closed on mismatch."""
    if sha256(path) != expected_sha:
        raise RuntimeError(f"daily SHA mismatch: {path}")
    return pd.read_parquet(path)


def _dec(value: object) -> Decimal | None:
    """Parse a decimal text cell; NaN/None -> None."""
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return None
    return Decimal(text)


def to_daily_bar(row: pd.Series) -> DailyBar:
    """Convert one canonical daily row to the frozen DailyBar model.

    Suspended rows (trade_status False) must be filtered out by the caller
    so only visible trading sessions reach the F18 factor.
    """
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
        source="F18_VALIDATION",
        fetched_at=datetime.combine(row["trade_date"], time(16, 0), tzinfo=TZ),
    )


def group_daily(daily: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Pre-group visible trading sessions by code (one pass; PIT slicing per episode cheap)."""
    visible = daily[daily["trade_status"] == True]  # noqa: E712
    return {code: grp.sort_values("trade_date") for code, grp in visible.groupby("code", sort=False)}


def bars_pit(grp: pd.DataFrame, code: str, as_of: date, anchor: date) -> list[DailyBar]:
    """Visible trading sessions for one code with trade_date <= as_of,
    trimmed to the PIT window needed by F18 (anchor - 15 sessions .. as_of).
    `grp` must be the pre-grouped per-code frame (see group_daily)."""
    grp = grp[grp["trade_date"] <= as_of]
    if anchor is not None:
        anchor_pos = grp.index[grp["trade_date"] <= anchor]
        if anchor_pos.empty:
            return []
        lo = max(0, len(anchor_pos) - 16)
        grp = grp.iloc[lo:]
    return [to_daily_bar(row) for _, row in grp.iterrows()]


def compute_f18(groups: dict[str, pd.DataFrame], episode: dict) -> tuple[int | None, str | None]:
    """PIT materialization of F18 for one frozen episode (as_of = signal_date).

    Returns (f18, undefined_reason); undefined_reason in
    {MISSING_SUPPORT, NO_DEFINED_MA10, OTHER_ERROR} or None when defined.
    """
    support_low = _dec(episode.get("support_low"))
    support_high = _dec(episode.get("support_high"))
    if support_low is None or support_high is None:
        return None, "MISSING_SUPPORT"
    anchor = date.fromisoformat(episode["anchor_date"])
    as_of = date.fromisoformat(episode["signal_date"])
    grp = groups.get(str(episode["code"]))
    if grp is None:
        return None, "NO_DEFINED_MA10"
    bars = bars_pit(grp, str(episode["code"]), as_of, anchor)
    if not bars:
        return None, "NO_DEFINED_MA10"
    try:
        f18 = fl.support_confluence_max_count(bars, anchor, as_of, support_low, support_high)
    except Exception as exc:  # noqa: BLE001 - any error is a fail-closed OTHER_ERROR
        return None, f"OTHER_ERROR:{type(exc).__name__}"
    if f18 is None:
        return None, "NO_DEFINED_MA10"
    return int(f18), None


def timing_bucket(days_since_anchor: int) -> str:
    """Frozen TIMING strata: T1-2 / T3 / T4-5 / T6-10."""
    if days_since_anchor <= 2:
        return "T1-2"
    if days_since_anchor == 3:
        return "T3"
    if days_since_anchor <= 5:
        return "T4-5"
    return "T6-10"


def group_metrics(outcomes: pd.Series, r: pd.Series) -> dict:
    """Primary metrics for one group.

    strict_win_rate = WIN_S1 / (WIN_S1 + LOSS_INVALID). R sign never called
    WIN/LOSS; R metrics use only R-defined episodes (WIN_S1 + LOSS_INVALID).
    """
    win = int((outcomes == "WIN_S1").sum())
    loss = int((outcomes == "LOSS_INVALID").sum())
    cancel_gap = int((outcomes == "CANCEL_GAP_INVALID").sum())
    total = int(outcomes.size)
    r_num = pd.to_numeric(r, errors="coerce")
    r_defined = r_num.dropna()
    r_def = int(r_defined.size)
    denominator = win + loss
    strict_win_rate = win / denominator if denominator > 0 else float("nan")
    win_share = win / total if total > 0 else float("nan")
    return {
        "N": total,
        "WIN_S1": win,
        "LOSS_INVALID": loss,
        "CANCEL_GAP_INVALID": cancel_gap,
        "win_share": _round(win_share),
        "strict_win_rate": _round(strict_win_rate),
        "R_DEFINED_N": r_def,
        "mean_R": _round(float(r_defined.mean())) if r_def else None,
        "median_R": _round(float(r_defined.median())) if r_def else None,
        "P(R>0)": _round(float((r_defined > 0).mean())) if r_def else None,
        "P(R>=2)": _round(float((r_defined >= 2).mean())) if r_def else None,
    }


def robust_r_diagnostics(r: pd.Series) -> dict:
    """Fixed robust R diagnostics (H4B right-tail caveat); never a verdict gate."""
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


def depth_table(df: pd.DataFrame) -> list[dict]:
    """Descriptive raw depth table by F18 level (no threshold selection)."""
    rows = []
    for depth in (0, 1, 2, 3):
        sub = df[df["f18"] == depth]
        m = group_metrics(sub["outcome"], sub["r_multiple"]) if not sub.empty else {"N": 0}
        rows.append({
            "F18": depth,
            "N": m["N"],
            "strict_win_rate": m["strict_win_rate"],
            "P(R>0)": m["P(R>0)"],
            "mean_R": m["mean_R"],
            "median_R": m["median_R"],
            "SMALL_CELL": m["N"] < 20,
        })
    return rows


def composition_direction(rows: list[dict]) -> dict:
    """Sum direction signs over eligible strata (SMALL_CELL excluded)."""
    strict_pos = sum(1 for r in rows if r["eligible"] and r["delta_strict_win_rate"] is not None and r["delta_strict_win_rate"] > 0)
    strict_elig = sum(1 for r in rows if r["eligible"] and r["delta_strict_win_rate"] is not None)
    rpos_pos = sum(1 for r in rows if r["eligible"] and r["delta_p_r_gt_0"] is not None and r["delta_p_r_gt_0"] > 0)
    rpos_elig = sum(1 for r in rows if r["eligible"] and r["delta_p_r_gt_0"] is not None)
    return {
        "STRICT_DIRECTION_POSITIVE_K": strict_pos,
        "ELIGIBLE_K": strict_elig,
        "RPOS_DIRECTION_POSITIVE_K": rpos_pos,
        "RPOS_ELIGIBLE_K": rpos_elig,
    }


def verdict(delta_strict_win_rate: float, delta_p_r_gt_0: float) -> str:
    """Pre-registered H4C verdict (no metric substitution)."""
    if delta_strict_win_rate is not None and delta_p_r_gt_0 is not None:
        if delta_strict_win_rate > 0 and delta_p_r_gt_0 > 0:
            return "SUPPORTED_DIRECTIONALLY"
    return "REJECT"


def _round(value: float) -> float | None:
    if value is None or (isinstance(value, float) and (value != value or value in (float("inf"), float("-inf")))):
        return None
    return round(float(value), 6)


def main(episodes_path: Path, daily_path: Path, out_dir: Path, daily: pd.DataFrame | None = None) -> dict:
    """Full pre-registered pipeline. Returns the result dict (and writes JSON + MD)."""
    episodes = load_episodes(episodes_path)
    if daily is None:
        daily = load_daily(daily_path)

    groups = group_daily(daily)
    resolved = episodes[episodes["outcome"].isin(RESOLVED_OUTCOMES)].copy()
    if len(resolved) != 9625:
        raise RuntimeError(f"RESOLVED_N mismatch: {len(resolved)} != 9625")

    f18_vals: list[int | None] = []
    reasons: list[str | None] = []
    errors: list[str] = []
    for _, ep in resolved.iterrows():
        f, reason = compute_f18(groups, ep.to_dict())
        f18_vals.append(f)
        reasons.append(reason)
        if reason is not None and reason.startswith("OTHER_ERROR"):
            errors.append(f"{ep['setup_id']}: {reason}")
    if errors:
        raise RuntimeError(f"OTHER_ERROR count > 0: {errors[:5]}")

    resolved["f18"] = f18_vals
    resolved["undefined_reason"] = reasons
    resolved["r_multiple_num"] = pd.to_numeric(resolved["r_multiple"], errors="coerce")
    resolved["group"] = resolved["f18"].apply(lambda v: "CONFLUENCE" if v is not None and v >= 2 else "NON_CONFLUENCE")

    con = resolved[resolved["group"] == "CONFLUENCE"]
    non = resolved[resolved["group"] == "NON_CONFLUENCE"]
    con_m = group_metrics(con["outcome"], con["r_multiple_num"])
    non_m = group_metrics(non["outcome"], non["r_multiple_num"])

    def delta(a, b):
        if a is None or b is None:
            return None
        return _round(a - b)

    delta_swr = delta(con_m["strict_win_rate"], non_m["strict_win_rate"])
    delta_pr = delta(con_m["P(R>0)"], non_m["P(R>0)"])
    delta_mean = delta(con_m["mean_R"], non_m["mean_R"])
    delta_median = delta(con_m["median_R"], non_m["median_R"])

    stage_rows = []
    for stage in ("B1_READY", "B2_READY", "B2_CONFIRMED"):
        sub = resolved[resolved["setup_stage"] == stage]
        c = sub[sub["group"] == "CONFLUENCE"]
        n = sub[sub["group"] == "NON_CONFLUENCE"]
        cm, nm = group_metrics(c["outcome"], c["r_multiple_num"]), group_metrics(n["outcome"], n["r_multiple_num"])
        small = cm["N"] < 20 or nm["N"] < 20
        stage_rows.append({
            "stratum": stage,
            "N_CONFLUENCE": cm["N"],
            "N_NON_CONFLUENCE": nm["N"],
            "delta_strict_win_rate": None if small else delta(cm["strict_win_rate"], nm["strict_win_rate"]),
            "delta_p_r_gt_0": None if small else delta(cm["P(R>0)"], nm["P(R>0)"]),
            "eligible": not small,
            "SMALL_CELL": small,
        })
    timing_rows = []
    for bucket in ("T1-2", "T3", "T4-5", "T6-10"):
        sub = resolved[resolved["days_since_anchor"].apply(timing_bucket) == bucket]
        c = sub[sub["group"] == "CONFLUENCE"]
        n = sub[sub["group"] == "NON_CONFLUENCE"]
        cm, nm = group_metrics(c["outcome"], c["r_multiple_num"]), group_metrics(n["outcome"], n["r_multiple_num"])
        small = cm["N"] < 20 or nm["N"] < 20
        timing_rows.append({
            "stratum": bucket,
            "N_CONFLUENCE": cm["N"],
            "N_NON_CONFLUENCE": nm["N"],
            "delta_strict_win_rate": None if small else delta(cm["strict_win_rate"], nm["strict_win_rate"]),
            "delta_p_r_gt_0": None if small else delta(cm["P(R>0)"], nm["P(R>0)"]),
            "eligible": not small,
            "SMALL_CELL": small,
        })

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
            "f18_contract_head": "e37c57be4f65e314ed8a45763bb56d893be88289",
            "f18_function": "factor_lab.support_confluence_max_count",
            "primary_contrast": PRIMARY_CONTRAST,
            "as_of": "signal_date",
        },
        "ACCOUNTING": {
            "F18_DEFINED_N": int(resolved["f18"].notna().sum()),
            "F18_UNDEFINED_N": int(resolved["f18"].isna().sum()),
            "UNDEFINED_REASONS": reason_counts,
        },
        "PRIMARY_CONTRAST": {
            "CONFLUENCE": con_m,
            "NON_CONFLUENCE": non_m,
            "DELTA_STRICT_WIN_RATE": delta_swr,
            "DELTA_P_R_GT_0": delta_pr,
            "DELTA_MEAN_R": delta_mean,
            "DELTA_MEDIAN_R": delta_median,
        },
        "ROBUST_R": {
            "CONFLUENCE": robust_r_diagnostics(con["r_multiple_num"]),
            "NON_CONFLUENCE": robust_r_diagnostics(non["r_multiple_num"]),
        },
        "RAW_DEPTH_TABLE": depth_table(resolved),
        "STAGE_STRATA": stage_rows,
        "TIMING_STRATA": timing_rows,
        "COMPOSITION_DIRECTION": {
            "STAGE": composition_direction(stage_rows),
            "TIMING": composition_direction(timing_rows),
        },
        "VERDICT": verdict(delta_swr, delta_pr),
        "NEW_HYPOTHESES": [],
        "OUTCOME_AWARE_CONTRACT_CHANGE": False,
        "THRESHOLD_SEARCH": False,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "f18-validation-v01.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "f18-validation-report-v01.md").write_text(render_report(result), encoding="utf-8")
    return result


def render_report(result: dict) -> str:
    """Render the markdown report from the result dict."""
    p = result["PROVENANCE"]
    a = result["ACCOUNTING"]
    c = result["PRIMARY_CONTRAST"]["CONFLUENCE"]
    n = result["PRIMARY_CONTRAST"]["NON_CONFLUENCE"]
    lines = [
        "# F18 SUPPORT CONFLUENCE OUTCOME VALIDATION V01 — 预注册验证报告",
        "",
        f"- F18 CONTRACT = FROZEN（HEAD {p['f18_contract_head']}，Sol audit PASS）",
        f"- 函数：{p['f18_function']}；primary contrast：{p['primary_contrast']}",
        f"- episodes SHA: {p['episodes_sha']}；daily SHA: {p['daily_sha']}",
        f"- EPISODES_TOTAL = {p['episodes_total']}；RESOLVED_N = {p['resolved_n']}（WIN_S1+LOSS_INVALID+CANCEL_GAP_INVALID）",
        "",
        "## ACCOUNTING",
        f"- F18_DEFINED_N = {a['F18_DEFINED_N']}；F18_UNDEFINED_N = {a['F18_UNDEFINED_N']}",
        f"- UNDEFINED_REASONS = {a['UNDEFINED_REASONS']}",
        "",
        "## PRIMARY CONTRAST（CONFLUENCE F18>=2 vs NON_CONFLUENCE F18<=1）",
        "| 指标 | CONFLUENCE | NON_CONFLUENCE | Δ |",
        "| --- | --- | --- | --- |",
    ]
    for key, label in (("N", "N"), ("WIN_S1", "WIN_S1"), ("LOSS_INVALID", "LOSS_INVALID"),
                       ("CANCEL_GAP_INVALID", "CANCEL_GAP_INVALID"), ("strict_win_rate", "strict_win_rate"),
                       ("R_DEFINED_N", "R_DEFINED_N"), ("mean_R", "mean_R"), ("median_R", "median_R"),
                       ("P(R>0)", "P(R>0)"), ("P(R>=2)", "P(R>=2)")):
        cv, nv = c.get(key), n.get(key)
        dv = result["PRIMARY_CONTRAST"].get({
            "strict_win_rate": "DELTA_STRICT_WIN_RATE", "P(R>0)": "DELTA_P_R_GT_0",
            "mean_R": "DELTA_MEAN_R", "median_R": "DELTA_MEDIAN_R",
        }.get(key))
        lines.append(f"| {label} | {cv} | {nv} | {dv if dv is not None else ''} |")
    lines += [
        "",
        "## ROBUST R DIAGNOSTICS（非 verdict gate）",
        f"- CONFLUENCE: {result['ROBUST_R']['CONFLUENCE']}",
        f"- NON_CONFLUENCE: {result['ROBUST_R']['NON_CONFLUENCE']}",
        "",
        "## RAW DEPTH TABLE（描述性，N<20 标 SMALL_CELL，不做强解释）",
        "| F18 | N | strict_win_rate | P(R>0) | mean_R | median_R |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["RAW_DEPTH_TABLE"]:
        lines.append(f"| {row['F18']} | {row['N']} | {row['strict_win_rate']} | {row['P(R>0)']} | {row['mean_R']} | {row['median_R']} |{' SMALL_CELL' if row['SMALL_CELL'] else ''}")
    for name, rows in (("STAGE", result["STAGE_STRATA"]), ("TIMING", result["TIMING_STRATA"])):
        lines += ["", f"## {name} COMPOSITION（SMALL_CELL 排除）"]
        for row in rows:
            lines.append(f"- {row['stratum']}: N 双方 {row['N_CONFLUENCE']}/{row['N_NON_CONFLUENCE']}，Δstrict_win_rate={row['delta_strict_win_rate']}，ΔP(R>0)={row['delta_p_r_gt_0']}{' SMALL_CELL' if row['SMALL_CELL'] else ''}")
        d = result["COMPOSITION_DIRECTION"][name]
        lines.append(f"- 方向汇总：{d}")
    lines += [
        "",
        f"## VERDICT（预注册 H4C）",
        f"- delta_strict_win_rate = {result['PRIMARY_CONTRAST']['DELTA_STRICT_WIN_RATE']}",
        f"- delta_p_r_gt_0 = {result['PRIMARY_CONTRAST']['DELTA_P_R_GT_0']}",
        f"- **H4C = {result['VERDICT']}**（SUPPORTED_DIRECTIONALLY != VALIDATED != PROMOTED）",
        "",
        "## LIMITATIONS",
        "- GitHub 无 CI；本报告为作者本地验证（SHA 门禁通过）",
        "- mean_R 受 H4B 已确认的极端右尾风险影响，不作为 primary gate；见 ROBUST R",
        "- CANCEL_GAP_INVALID 为数据中单一合并桶（无独立 GAP/INVALID 分类）",
        "- R 仅定义于 WIN_S1/LOSS_INVALID 子集；P(R>0)/P(R>=2) 在该子集上计算",
        "- F18 为合同冻结后首次 outcome 验证；SUPPORTED_DIRECTIONALLY 仅属 research evidence",
        f"- NEW_HYPOTHESES = {result['NEW_HYPOTHESES']}",
        "- OUTCOME_AWARE_CONTRACT_CHANGE = False；THRESHOLD_SEARCH = False",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parents[1]
    main(
        episodes_path=root / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet",
        daily_path=root / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet",
        out_dir=root / "research/factor-lab/runs/f18-support-confluence-validation-v01",
    )
    print("OK")
    sys.exit(0)
