"""Descriptive B1 R-tail and B2 gap checks over frozen episodes.

The module consumes one existing ``episodes.parquet`` artifact.  It does not
invoke the strategy engine or any provider and has no effect on strategy
semantics.  All reported rates, returns, and quantiles are derived with
``Decimal`` arithmetic.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import resource
import sys
from time import perf_counter
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

from .diagnosis import (
    BASELINE_EPISODES_SHA256,
    _decimal,
    _execution_eligible,
    _fmt,
    _is_actionable,
    _mean,
    _median,
    _quantize,
    _ratio,
    _stats,
    verify_episode_artifact,
)


MODE = "DESCRIPTIVE TAIL / GAP CHECK"
GUARDRAILS = ("NOT STRATEGY OPTIMIZATION", "NOT OUT-OF-SAMPLE VALIDATION")
YEARS = (2024, 2025, 2026)
QUANTILES = (
    ("p50", Decimal("0.50")),
    ("p75", Decimal("0.75")),
    ("p90", Decimal("0.90")),
    ("p95", Decimal("0.95")),
    ("p99", Decimal("0.99")),
)
CAPS = (Decimal("3"), Decimal("5"), Decimal("10"))
TAIL_COHORTS = {
    "B1_READY_ALL": "setup_stage == B1_READY and is_entry_candidate == true",
    "B1_READY_SETUP_GE_80": (
        "setup_stage == B1_READY and is_entry_candidate == true and setup_quality_score >= 80"
    ),
    "B1_READY_ENTRY_GE_80": (
        "setup_stage == B1_READY and is_entry_candidate == true and entry_quality_score >= 80"
    ),
}


def _year(row: Mapping[str, Any]) -> int | None:
    value = row.get("signal_date")
    if value in (None, ""):
        return None
    try:
        return int(str(value)[:4])
    except ValueError:
        return None


def _cohort_matches(row: Mapping[str, Any], name: str) -> bool:
    if row.get("setup_stage") != "B1_READY" or not _is_actionable(row):
        return False
    if name == "B1_READY_ALL":
        return True
    field = "setup_quality_score" if "SETUP" in name else "entry_quality_score"
    score = _decimal(row.get(field))
    return score is not None and score >= Decimal("80")


def _strict_values(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if _execution_eligible(row)]
    wins = [row for row in eligible if row.get("outcome") == "WIN_S1"]
    losses = [row for row in eligible if row.get("outcome") == "LOSS_INVALID"]
    strict = [
        value
        for row in [*wins, *losses]
        if (value := _decimal(row.get("r_multiple"))) is not None
    ]
    winner_values = [
        value
        for row in wins
        if (value := _decimal(row.get("r_multiple"))) is not None
    ]
    return {
        "eligible": eligible,
        "wins": wins,
        "losses": losses,
        "strict": strict,
        "winner_values": winner_values,
    }


def _quantile(values: Sequence[Decimal], probability: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return _quantize(ordered[0])
    position = probability * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    value = ordered[lower] + fraction * (ordered[upper] - ordered[lower])
    return _quantize(value)


def _quantiles(values: Sequence[Decimal]) -> dict[str, str | None]:
    return {name: _fmt(_quantile(values, probability)) for name, probability in QUANTILES} | {
        "max": _fmt(max(values) if values else None),
    }


def _capped_expectancy(values: Sequence[Decimal], cap: Decimal) -> str | None:
    capped = [min(value, cap) if value > 0 else value for value in values]
    return _fmt(_mean(capped))


def _risk_reward(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    geometry: list[tuple[Mapping[str, Any], Decimal, Decimal]] = []
    for row in rows:
        if not _execution_eligible(row) or row.get("fill_status") != "FILLED":
            continue
        fill = _decimal(row.get("fill_price"))
        invalid = _decimal(row.get("invalid_price"))
        s1 = _decimal(row.get("s1_price"))
        if fill is None or invalid is None or s1 is None or fill == 0:
            continue
        risk = _quantize((fill - invalid) / fill)
        reward = _quantize((s1 - fill) / fill)
        geometry.append((row, risk, reward))

    winners = [
        (row, risk)
        for row, risk, _ in geometry
        if row.get("outcome") == "WIN_S1"
    ]
    large = [risk for row, risk in winners if (_decimal(row.get("r_multiple")) or 0) >= 10]
    normal = [risk for row, risk in winners if (_decimal(row.get("r_multiple")) or 0) < 10]
    risks = [risk for _, risk, _ in geometry]
    rewards = [reward for _, _, reward in geometry]
    return {
        "episodes": len(geometry),
        "median_risk_pct": _fmt(_median(risks)),
        "p10_risk_pct": _fmt(_quantile(risks, Decimal("0.10"))),
        "p25_risk_pct": _fmt(_quantile(risks, Decimal("0.25"))),
        "median_reward_pct": _fmt(_median(rewards)),
        "R_GE_10_winners": {
            "count": len(large),
            "median_risk_pct": _fmt(_median(large)),
        },
        "normal_winners_R_LT_10": {
            "count": len(normal),
            "median_risk_pct": _fmt(_median(normal)),
        },
        "definition": "risk=(fill_price-invalid_price)/fill_price; reward=(s1_price-fill_price)/fill_price; filled execution-eligible rows",
    }


def _tail_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    stats = _stats(rows)
    parts = _strict_values(rows)
    strict = parts["strict"]
    return {
        "episodes": len(rows),
        "filled": stats["filled"],
        "strict_resolved": stats["strict_resolved"],
        "wins": stats["wins"],
        "losses": stats["losses"],
        "sample_flags": stats["sample_flags"],
        "winner_R": _quantiles(parts["winner_values"]),
        "all_strict_resolved_R": _quantiles(strict),
        "raw_E_R": _fmt(_mean(strict)),
        "cap_3R_E_R": _capped_expectancy(strict, CAPS[0]),
        "cap_5R_E_R": _capped_expectancy(strict, CAPS[1]),
        "cap_10R_E_R": _capped_expectancy(strict, CAPS[2]),
        "risk_geometry": _risk_reward(rows),
    }


def _b1_tail(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {"definitions": TAIL_COHORTS, "cohorts": {}}
    for name in TAIL_COHORTS:
        cohort = [row for row in rows if _cohort_matches(row, name)]
        output["cohorts"][name] = {
            "overall": _tail_metrics(cohort),
            "years": {
                str(year): _tail_metrics(
                    [row for row in cohort if _year(row) == year]
                )
                for year in YEARS
            },
        }
    return output


def _exploratory_b1(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cohort = [
        row
        for row in rows
        if row.get("setup_stage") == "B1_READY"
        and _is_actionable(row)
        and (_decimal(row.get("setup_quality_score")) or Decimal("-1")) >= Decimal("80")
        and (_decimal(row.get("entry_quality_score")) or Decimal("-1")) >= Decimal("80")
    ]
    return {
        "definition": "setup_stage == B1_READY and is_entry_candidate == true and setup_quality_score >= 80 and entry_quality_score >= 80",
        "overall": _tail_metrics(cohort),
        "years": {str(year): _tail_metrics([row for row in cohort if _year(row) == year]) for year in YEARS},
    }


def _b2_gap_temporal(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cohort = [
        row
        for row in rows
        if row.get("setup_stage") == "B2_READY"
        and _is_actionable(row)
        and row.get("fill_type") == "BREAKOUT_GAP_FILL"
    ]
    return {
        "scope": "actionable B2_READY rows with fill_type BREAKOUT_GAP_FILL",
        "overall": _stats(cohort),
        "years": {str(year): _stats([row for row in cohort if _year(row) == year]) for year in YEARS},
    }


def _b2_trigger_candidate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ambiguous = [
        row
        for row in rows
        if row.get("setup_stage") == "B2_READY"
        and _is_actionable(row)
        and row.get("fill_type") == "BREAKOUT_TRIGGER_FILL"
        and _execution_eligible(row)
        and row.get("outcome") == "AMBIGUOUS_INTRADAY"
    ]
    years: dict[str, int] = {}
    for row in ambiguous:
        key = str(_year(row)) if _year(row) is not None else "UNKNOWN"
        years[key] = years.get(key, 0) + 1
    return {
        "scope": "actionable B2_READY BREAKOUT_TRIGGER_FILL ambiguous episodes",
        "ambiguous_count": len(ambiguous),
        "signal_years": {key: years[key] for key in sorted(years)},
        "unique_codes": len({str(row.get("code")) for row in ambiguous}),
    }


def _episode_tail(winners: Sequence[tuple[str, str, str, Decimal]]) -> dict[str, Any]:
    ordered = sorted(winners, key=lambda item: (-item[3], item[0], item[1], item[2]))
    denominator = sum((item[3] for item in ordered), Decimal("0"))
    result: dict[str, Any] = {
        "winner_episode_count": len(ordered),
        "denominator": _fmt(denominator),
        "denominator_definition": "sum of positive r_multiple across all WIN_S1 episodes in cohort",
    }
    for label, fraction in (("top_1pct", Decimal("0.01")), ("top_5pct", Decimal("0.05")), ("top_10pct", Decimal("0.10"))):
        count = int((Decimal(len(ordered)) * fraction).to_integral_value(rounding=ROUND_CEILING)) if ordered else 0
        top_sum = sum((item[3] for item in ordered[:count]), Decimal("0"))
        result[label] = {
            "count": count,
            "contribution": _fmt(top_sum / denominator) if denominator else None,
            "top_R_sum": _fmt(top_sum),
        }
    return result


def _code_concentration(rows: Sequence[Mapping[str, Any]], score_field: str) -> dict[str, Any]:
    cohort = [
        row
        for row in rows
        if row.get("setup_stage") == "B1_READY"
        and _is_actionable(row)
        and (_decimal(row.get(score_field)) or Decimal("-1")) >= Decimal("80")
    ]
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in cohort:
        grouped.setdefault(str(row.get("code") or "UNKNOWN"), []).append(row)

    code_means: dict[str, Decimal] = {}
    for code, code_rows in grouped.items():
        values = _strict_values(code_rows)["strict"]
        if values:
            code_means[code] = _mean(values) or Decimal("0")
    positive = sum(1 for value in code_means.values() if value > 0)
    winners = []
    for row in cohort:
        if not _execution_eligible(row) or row.get("outcome") != "WIN_S1":
            continue
        value = _decimal(row.get("r_multiple"))
        if value is not None and value > 0:
            winners.append((str(row.get("code") or "UNKNOWN"), str(row.get("signal_date") or ""), str(row.get("setup_id") or ""), value))
    return {
        "score_field": score_field,
        "episodes": len(cohort),
        "unique_codes": len(grouped),
        "resolved_unique_codes": len(code_means),
        "positive_expectancy_codes": positive,
        "positive_expectancy_code_share": _fmt(_ratio(positive, len(code_means))),
        "positive_expectancy_code_share_denominator": "resolved unique codes with at least one strict WIN_S1 or LOSS_INVALID",
        "episode_tail_concentration": _episode_tail(winners),
    }


def analyze_tail_gap(rows: Sequence[Mapping[str, Any]], *, artifact_sha256: str | None = None) -> dict[str, Any]:
    return {
        "title": MODE,
        "guardrails": list(GUARDRAILS),
        "evaluate_strategy_calls": 0,
        "quantile_method": "linear_interpolation_type_7",
        "artifact": {"sha256": artifact_sha256, "episode_count": len(rows)},
        "b1_r_tail_sanity": _b1_tail(rows),
        "b1_exploratory_setup_and_entry_ge_80": _exploratory_b1(rows),
        "b2_gap_temporal_stability": _b2_gap_temporal(rows),
        "b2_trigger_5m_candidate": _b2_trigger_candidate(rows),
        "concentration": {
            "B1_SETUP_GE_80": _code_concentration(rows, "setup_quality_score"),
            "B1_ENTRY_GE_80": _code_concentration(rows, "entry_quality_score"),
        },
    }


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _seconds(value: float) -> str:
    return f"{value:.4f}"


def _fmt_metric(value: Any) -> str:
    return "" if value is None else str(value)


def render_tail_gap_markdown(payload: Mapping[str, Any]) -> str:
    lines = [MODE, *GUARDRAILS, "", "## Artifact and runtime", ""]
    lines.extend([
        f"- episodes SHA-256: {payload['artifact']['sha256']}",
        f"- episode count: {payload['artifact']['episode_count']}",
        f"- evaluate_strategy_calls: {payload['evaluate_strategy_calls']}",
    ])
    timing = payload.get("timing", {})
    for key in ("load_seconds", "analysis_seconds", "write_seconds", "total_seconds", "peak_rss_bytes"):
        if key in timing:
            lines.append(f"- {key}: {timing[key]}")

    lines.extend(["", "## B1 R-tail sanity", ""])
    for name, result in payload["b1_r_tail_sanity"]["cohorts"].items():
        lines.extend([f"### {name}", "", "| period | strict resolved | wins | losses | raw E[R] | cap3 | cap5 | cap10 |", "|---|---:|---:|---:|---:|---:|---:|---:|"])
        for period, stats in [("overall", result["overall"]), *sorted(result["years"].items())]:
            lines.append(f"| {period} | {stats['strict_resolved']} | {stats['wins']} | {stats['losses']} | {stats['raw_E_R']} | {stats['cap_3R_E_R']} | {stats['cap_5R_E_R']} | {stats['cap_10R_E_R']} |")
        lines.append("")

        lines.extend(["| period | winner p50 | p75 | p90 | p95 | p99 | max | all strict p50 | p75 | p90 | p95 | p99 | max |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
        for period, stats in [("overall", result["overall"]), *sorted(result["years"].items())]:
            winner = stats["winner_R"]
            strict = stats["all_strict_resolved_R"]
            lines.append(f"| {period} | {winner['p50']} | {winner['p75']} | {winner['p90']} | {winner['p95']} | {winner['p99']} | {winner['max']} | {strict['p50']} | {strict['p75']} | {strict['p90']} | {strict['p95']} | {strict['p99']} | {strict['max']} |")
        lines.append("")

        lines.extend(["| period | median risk | p10 risk | p25 risk | median reward | R>=10 winner risk | normal winner risk |", "|---|---:|---:|---:|---:|---:|---:|"])
        for period, stats in [("overall", result["overall"]), *sorted(result["years"].items())]:
            geometry = stats["risk_geometry"]
            lines.append(f"| {period} | {geometry['median_risk_pct']} | {geometry['p10_risk_pct']} | {geometry['p25_risk_pct']} | {geometry['median_reward_pct']} | {geometry['R_GE_10_winners']['median_risk_pct']} | {geometry['normal_winners_R_LT_10']['median_risk_pct']} |")
        lines.append("")

    exploratory = payload["b1_exploratory_setup_and_entry_ge_80"]
    lines.extend(["## B1 exploratory setup>=80 AND entry>=80", "", "| period | strict resolved | wins | losses | raw E[R] | cap3 | cap5 | cap10 | sample flags |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"])
    for period, stats in [("overall", exploratory["overall"]), *sorted(exploratory["years"].items())]:
        lines.append(f"| {period} | {stats['strict_resolved']} | {stats['wins']} | {stats['losses']} | {stats['raw_E_R']} | {stats['cap_3R_E_R']} | {stats['cap_5R_E_R']} | {stats['cap_10R_E_R']} | {','.join(stats['sample_flags']) or 'NONE'} |")

    lines.extend(["## B2 GAP temporal stability", "", "| period | filled | strict resolved | ambiguous | strict win rate | average win R | average loss R | strict E[R] | conservative E[R] | median MFE | median MAE | sample flags |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"])
    gap = payload["b2_gap_temporal_stability"]
    for period, stats in [("overall", gap["overall"]), *sorted(gap["years"].items())]:
        lines.append(f"| {period} | {stats['filled']} | {stats['strict_resolved']} | {stats['ambiguous']} | {stats['strict_win_rate']} | {stats['average_win_R']} | {stats['average_loss_R']} | {stats['strict_resolved_expectancy_R']} | {stats['conservative_resolved_expectancy_R']} | {stats['median_MFE']} | {stats['median_MAE']} | {','.join(stats['sample_flags']) or 'NONE'} |")

    trigger = payload["b2_trigger_5m_candidate"]
    lines.extend(["", "## B2 TRIGGER 5M candidate", "", f"- ambiguous count: {trigger['ambiguous_count']}", f"- signal years: {json.dumps(trigger['signal_years'], sort_keys=True)}", f"- unique codes: {trigger['unique_codes']}"])

    lines.extend(["", "## Concentration", "", "| cohort | unique codes | positive code share | top 1% winning episodes | top 5% | top 10% |", "|---|---:|---:|---:|---:|---:|"])
    for name, result in payload["concentration"].items():
        tail = result["episode_tail_concentration"]
        lines.append(f"| {name} | {result['unique_codes']} | {result['positive_expectancy_code_share']} | {tail['top_1pct']['contribution']} | {tail['top_5pct']['contribution']} | {tail['top_10pct']['contribution']} |")
    lines.extend([
        "",
        "- positive-expectancy code share denominator: resolved unique codes with at least one strict WIN_S1 or LOSS_INVALID",
        "- episode-tail contribution denominator: sum of positive r_multiple across all WIN_S1 episodes in the cohort",
    ])
    return "\n".join(lines) + "\n"


def run_tail_gap_check(
    episodes_path: Path,
    *,
    output_dir: Path | None = None,
    expected_sha256: str | None = BASELINE_EPISODES_SHA256,
) -> dict[str, Any]:
    started = perf_counter()
    load_started = perf_counter()
    digest = verify_episode_artifact(
        episodes_path,
        expected_sha256=BASELINE_EPISODES_SHA256 if expected_sha256 is None else expected_sha256,
    )
    rows = pq.read_table(episodes_path).to_pylist()
    load_seconds = perf_counter() - load_started
    analysis_started = perf_counter()
    payload = analyze_tail_gap(rows, artifact_sha256=digest)
    analysis_seconds = perf_counter() - analysis_started
    destination = output_dir or episodes_path.parent
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "tail_gap_check.json"
    markdown_path = destination / "tail_gap_check.md"
    payload["timing"] = {
        "load_seconds": _seconds(load_seconds),
        "analysis_seconds": _seconds(analysis_seconds),
        "write_seconds": "0.0000",
        "total_seconds": "0.0000",
        "peak_rss_bytes": _peak_rss_bytes(),
    }
    payload["output_files"] = {"json": str(json_path), "markdown": str(markdown_path)}
    write_started = perf_counter()
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_tail_gap_markdown(payload), encoding="utf-8")
    payload["timing"]["write_seconds"] = _seconds(perf_counter() - write_started)
    payload["timing"]["total_seconds"] = _seconds(perf_counter() - started)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_tail_gap_markdown(payload), encoding="utf-8")
    return payload


__all__ = [
    "analyze_tail_gap",
    "render_tail_gap_markdown",
    "run_tail_gap_check",
]
