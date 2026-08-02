"""Descriptive robustness checks for the frozen corrected episodes artifact.

This module is intentionally read-only with respect to the strategy system. It
loads one existing ``episodes.parquet`` file, performs fixed-cohort summaries,
and never calls providers, replay, screen, finalize, or ``evaluate_strategy``.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import resource
import sys
from time import perf_counter
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

from .diagnosis import (
    BASELINE_EPISODES_SHA256,
    ENTRY_ROOM_STATES,
    QUALITY_BUCKETS,
    STAGES,
    _bucket,
    _decimal,
    _execution_eligible,
    _fmt,
    _is_actionable,
    _mean,
    _median,
    _stats,
    _quantize,
    _ratio,
    verify_episode_artifact,
)


ROBUSTNESS_MODE = "DESCRIPTIVE ROBUSTNESS CHECK"
STRATEGY_GUARDRAIL = "NOT STRATEGY OPTIMIZATION"
VALIDATION_GUARDRAIL = "NOT OUT-OF-SAMPLE VALIDATION"
YEARS = (2024, 2025, 2026)
FIXED_SCORE_BUCKETS = ("<60", "60-70", "70-80", ">=80")
AMBIGUOUS_MEAN_R_SCENARIOS = (
    Decimal("-1"),
    Decimal("-0.5"),
    Decimal("0"),
    Decimal("0.25"),
    Decimal("0.5"),
    Decimal("1"),
)
B2_FILL_TYPES = ("BREAKOUT_GAP_FILL", "BREAKOUT_TRIGGER_FILL")


def _year(row: Mapping[str, Any]) -> int | None:
    value = row.get("signal_date")
    if value in (None, ""):
        return None
    try:
        return int(str(value)[:4])
    except ValueError:
        return None


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the existing diagnosis statistics plus explicit mean aliases."""

    stats = dict(_stats(rows))
    stats["strict_mean_R"] = stats["strict_resolved_expectancy_R"]
    stats["conservative_mean_R"] = stats[
        "conservative_resolved_expectancy_R"
    ]
    stats["unique_codes"] = len(
        {str(row.get("code")) for row in rows if row.get("code") not in (None, "")}
    )
    return stats


def _temporal_cohorts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    definitions = {
        "B1_READY_ALL": "setup_stage == B1_READY",
        "B1_READY_SETUP_GE_80": (
            "setup_stage == B1_READY and setup_quality_score >= 80"
        ),
        "B1_READY_ENTRY_GE_80": (
            "setup_stage == B1_READY and entry_quality_score >= 80"
        ),
        "B2_READY_ALL": "setup_stage == B2_READY",
        "B2_READY_SETUP_70_80": (
            "setup_stage == B2_READY and 70 <= setup_quality_score < 80"
        ),
    }

    def matches(row: Mapping[str, Any], name: str) -> bool:
        stage = row.get("setup_stage")
        setup = _decimal(row.get("setup_quality_score"))
        entry = _decimal(row.get("entry_quality_score"))
        if name == "B1_READY_ALL":
            return stage == "B1_READY"
        if name == "B1_READY_SETUP_GE_80":
            return stage == "B1_READY" and setup is not None and setup >= 80
        if name == "B1_READY_ENTRY_GE_80":
            return stage == "B1_READY" and entry is not None and entry >= 80
        if name == "B2_READY_ALL":
            return stage == "B2_READY"
        if name == "B2_READY_SETUP_70_80":
            return (
                stage == "B2_READY"
                and setup is not None
                and Decimal("70") <= setup < Decimal("80")
            )
        raise KeyError(name)

    by_year: dict[str, dict[str, dict[str, Any]]] = {}
    for year in YEARS:
        year_rows = [row for row in rows if _year(row) == year]
        by_year[str(year)] = {
            name: _summary([row for row in year_rows if matches(row, name)])
            for name in definitions
        }
    return {"definitions": definitions, "years": by_year}


def _b2_ambiguity_sensitivity(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cohort = [
        row
        for row in rows
        if row.get("setup_stage") == "B2_READY" and _is_actionable(row)
    ]
    eligible = [row for row in cohort if _execution_eligible(row)]
    ambiguous = [
        row for row in eligible if row.get("outcome") == "AMBIGUOUS_INTRADAY"
    ]
    strict_values = [
        value
        for row in eligible
        if row.get("outcome") in {"WIN_S1", "LOSS_INVALID"}
        and (value := _decimal(row.get("r_multiple"))) is not None
    ]
    strict_sum = sum(strict_values, Decimal("0"))
    ambiguous_count = len(ambiguous)
    break_even = (
        _quantize(-strict_sum / Decimal(ambiguous_count))
        if ambiguous_count
        else None
    )
    strict_mean = _mean(strict_values)
    scenarios: dict[str, dict[str, Any]] = {}
    for assigned in AMBIGUOUS_MEAN_R_SCENARIOS:
        denominator = len(strict_values) + ambiguous_count
        total = strict_sum + assigned * Decimal(ambiguous_count)
        expectancy = (
            _quantize(total / Decimal(denominator)) if denominator else None
        )
        key = format(assigned, "f")
        scenarios[key] = {
            "ambiguous_mean_R": key,
            "strict_known_count": len(strict_values),
            "ambiguous_count": ambiguous_count,
            "resolved_count": denominator,
            "expectancy_R": _fmt(expectancy),
            "delta_vs_strict_R": (
                _fmt(expectancy - strict_mean)
                if expectancy is not None and strict_mean is not None
                else None
            ),
        }
    return {
        "scope": "B2_READY and is_entry_candidate == true and execution eligible",
        "episodes": len(cohort),
        "eligible": len(eligible),
        "strict_known_count": len(strict_values),
        "ambiguous_count": ambiguous_count,
        "strict_mean_R": _fmt(strict_mean),
        "AMBIGUOUS_BREAK_EVEN_MEAN_R": _fmt(break_even),
        "scenarios": scenarios,
    }


def _b2_fill_type(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cohort = [
        row
        for row in rows
        if row.get("setup_stage") == "B2_READY" and _is_actionable(row)
    ]
    return {
        "scope": "B2_READY and is_entry_candidate == true",
        "fill_types": {
            fill_type: _summary(
                [row for row in cohort if row.get("fill_type") == fill_type]
            )
            for fill_type in B2_FILL_TYPES
        },
    }


def _concentration(
    rows: Sequence[Mapping[str, Any]],
    *,
    name: str,
    score_field: str,
) -> dict[str, Any]:
    cohort = []
    for row in rows:
        if row.get("setup_stage") != "B1_READY":
            continue
        score = _decimal(row.get(score_field))
        if score is not None and score >= Decimal("80"):
            cohort.append(row)

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in cohort:
        code = str(row.get("code") or "UNKNOWN")
        grouped.setdefault(code, []).append(row)

    code_stats: list[dict[str, Any]] = []
    for code, code_rows in grouped.items():
        eligible = [row for row in code_rows if _execution_eligible(row)]
        values = [
            value
            for row in eligible
            if row.get("outcome") in {"WIN_S1", "LOSS_INVALID"}
            and (value := _decimal(row.get("r_multiple"))) is not None
        ]
        r_sum = sum(values, Decimal("0"))
        code_stats.append(
            {
                "code": code,
                "episodes": len(code_rows),
                "eligible": len(eligible),
                "strict_resolved": len(values),
                "r_sum": _fmt(r_sum),
                "mean_R": _fmt(_mean(values)),
                "absolute_r_sum": _fmt(abs(r_sum)),
            }
        )
    code_stats.sort(
        key=lambda item: (
            -abs(_decimal(item["r_sum"]) or Decimal("0")),
            item["code"],
        )
    )
    total_absolute_r = sum(
        (abs(_decimal(item["r_sum"]) or Decimal("0")) for item in code_stats),
        Decimal("0"),
    )
    total_episodes = len(cohort)
    top_contribution: dict[str, str | None] = {}
    episode_share: dict[str, str] = {}
    for limit in (1, 5, 10):
        top = code_stats[:limit]
        top_absolute_r = sum(
            (abs(_decimal(item["r_sum"]) or Decimal("0")) for item in top),
            Decimal("0"),
        )
        top_contribution[f"top{limit}"] = (
            _fmt(top_absolute_r / total_absolute_r)
            if total_absolute_r
            else None
        )
        episode_share[f"top{limit}"] = _fmt(
            _ratio(sum(item["episodes"] for item in top), total_episodes)
        ) or "0.0000"
    means = [
        value
        for item in code_stats
        if (value := _decimal(item["mean_R"])) is not None
    ]
    return {
        "score_field": score_field,
        "scope": "B1_READY rows with score >= 80",
        "episodes": len(cohort),
        "unique_codes": len(grouped),
        "resolved_unique_codes": sum(
            1 for item in code_stats if item["strict_resolved"]
        ),
        "contribution_definition": (
            "top-k share of absolute strict R sum by code; codes sorted by absolute R sum desc, code asc"
        ),
        "top1_contribution": top_contribution["top1"],
        "top5_contribution": top_contribution["top5"],
        "top10_contribution": top_contribution["top10"],
        "top1_episode_share": episode_share["top1"],
        "top5_episode_share": episode_share["top5"],
        "top10_episode_share": episode_share["top10"],
        "median_code_mean_R": _fmt(_median(means)),
        "top_codes": code_stats[:10],
    }


def _monotonic(values: Sequence[str | None]) -> bool | None:
    decimals = [_decimal(value) for value in values if value is not None]
    decimals = [value for value in decimals if value is not None]
    if len(decimals) < 2:
        return None
    return all(left <= right for left, right in zip(decimals, decimals[1:]))


def _score_monotonicity(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cohort = [
        row
        for row in rows
        if row.get("setup_stage") in STAGES and _is_actionable(row)
    ]
    by_score: dict[str, Any] = {}
    by_stage: dict[str, Any] = {}
    for field in ("setup_quality_score", "entry_quality_score"):
        cells = {
            bucket: _summary(
                [row for row in cohort if _bucket(row.get(field)) == bucket]
            )
            for bucket in FIXED_SCORE_BUCKETS
        }
        sequence = [cells[bucket]["strict_mean_R"] for bucket in FIXED_SCORE_BUCKETS]
        by_score[field] = {
            "buckets": list(FIXED_SCORE_BUCKETS),
            "cells": cells,
            "strict_mean_R_sequence": sequence,
            "non_decreasing": _monotonic(sequence),
        }
        by_stage[field] = {
            stage: {
                bucket: _summary(
                    [
                        row
                        for row in cohort
                        if row.get("setup_stage") == stage
                        and _bucket(row.get(field)) == bucket
                    ]
                )
                for bucket in FIXED_SCORE_BUCKETS
            }
            for stage in STAGES
        }
    return {
        "scope": "actionable B1_READY/B2_READY/B2_CONFIRMED rows",
        "fixed_buckets": list(FIXED_SCORE_BUCKETS),
        "by_score": by_score,
        "by_stage": by_stage,
    }


def analyze_robustness(
    rows: Sequence[Mapping[str, Any]],
    *,
    artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Analyze one frozen artifact without invoking any strategy computation."""

    return {
        "title": ROBUSTNESS_MODE,
        "guardrails": [STRATEGY_GUARDRAIL, VALIDATION_GUARDRAIL],
        "evaluate_strategy_calls": 0,
        "artifact": {
            "sha256": artifact_sha256,
            "episode_count": len(rows),
        },
        "temporal_stability": _temporal_cohorts(rows),
        "b2_ambiguity_sensitivity": _b2_ambiguity_sensitivity(rows),
        "b2_fill_type": _b2_fill_type(rows),
        "concentration": {
            "B1_READY_SETUP_GE_80": _concentration(
                rows,
                name="B1_READY_SETUP_GE_80",
                score_field="setup_quality_score",
            ),
            "B1_READY_ENTRY_GE_80": _concentration(
                rows,
                name="B1_READY_ENTRY_GE_80",
                score_field="entry_quality_score",
            ),
        },
        "score_monotonicity": _score_monotonicity(rows),
    }


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _seconds(value: float) -> str:
    return f"{value:.4f}"


def render_robustness_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        ROBUSTNESS_MODE,
        STRATEGY_GUARDRAIL,
        VALIDATION_GUARDRAIL,
        "",
        "All results are descriptive observations over the supplied frozen artifact.",
        "",
        "## Artifact and runtime",
        "",
        f"- episodes SHA-256: {payload['artifact']['sha256']}",
        f"- episode count: {payload['artifact']['episode_count']}",
        f"- evaluate_strategy_calls: {payload['evaluate_strategy_calls']}",
    ]
    timing = payload.get("timing", {})
    for key in ("load_seconds", "analysis_seconds", "write_seconds", "total_seconds", "peak_rss_bytes"):
        if key in timing:
            lines.append(f"- {key}: {timing[key]}")

    lines.extend(["", "## Temporal stability", ""])
    lines.append("| year | cohort | episodes | eligible | filled | strict E[R] | conservative E[R] |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|")
    for year, cohorts in payload["temporal_stability"]["years"].items():
        for cohort, stats in cohorts.items():
            lines.append(
                f"| {year} | {cohort} | {stats['episodes']} | {stats['eligible']} | "
                f"{stats['filled']} | {stats['strict_mean_R']} | {stats['conservative_mean_R']} |"
            )

    ambiguity = payload["b2_ambiguity_sensitivity"]
    lines.extend(
        [
            "",
            "## B2 ambiguity sensitivity",
            "",
            f"- scope: {ambiguity['scope']}",
            f"- episodes={ambiguity['episodes']}; eligible={ambiguity['eligible']}; "
            f"strict_known={ambiguity['strict_known_count']}; ambiguous={ambiguity['ambiguous_count']}",
            f"- AMBIGUOUS_BREAK_EVEN_MEAN_R={ambiguity['AMBIGUOUS_BREAK_EVEN_MEAN_R']}",
            "",
            "| assigned ambiguous mean R | resolved | expectancy R | delta vs strict R |",
            "|---:|---:|---:|---:|",
        ]
    )
    for key, scenario in ambiguity["scenarios"].items():
        lines.append(
            f"| {key} | {scenario['resolved_count']} | {scenario['expectancy_R']} | "
            f"{scenario['delta_vs_strict_R']} |"
        )

    lines.extend(["", "## B2 fill type", "", "| fill type | episodes | filled | strict E[R] | conservative E[R] |", "|---|---:|---:|---:|---:|"])
    for fill_type, stats in payload["b2_fill_type"]["fill_types"].items():
        lines.append(
            f"| {fill_type} | {stats['episodes']} | {stats['filled']} | "
            f"{stats['strict_mean_R']} | {stats['conservative_mean_R']} |"
        )

    lines.extend(
        [
            "",
            "## Concentration",
            "",
            "Top-k contribution is the share of absolute strict R sum by code; episode shares are also shown.",
            "",
            "| cohort | unique codes | top1 contribution | top5 contribution | top10 contribution | median code mean R |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for cohort, result in payload["concentration"].items():
        lines.append(
            f"| {cohort} | {result['unique_codes']} | {result['top1_contribution']} | "
            f"{result['top5_contribution']} | {result['top10_contribution']} | "
            f"{result['median_code_mean_R']} |"
        )

    lines.extend(["", "## Score monotonicity", ""])
    for field, result in payload["score_monotonicity"]["by_score"].items():
        lines.append(f"### {field}")
        lines.append("")
        lines.append("| bucket | episodes | eligible | strict E[R] |")
        lines.append("|---|---:|---:|---:|")
        for bucket in FIXED_SCORE_BUCKETS:
            stats = result["cells"][bucket]
            lines.append(
                f"| {bucket} | {stats['episodes']} | {stats['eligible']} | {stats['strict_mean_R']} |"
            )
        lines.append("")
        lines.append(f"- non_decreasing={result['non_decreasing']}")
    return "\n".join(lines) + "\n"


def run_robustness(
    episodes_path: Path,
    *,
    output_dir: Path | None = None,
    expected_sha256: str | None = BASELINE_EPISODES_SHA256,
) -> dict[str, Any]:
    """Verify, analyze, and write ``robustness.json`` and ``robustness.md``."""

    started = perf_counter()
    load_started = perf_counter()
    digest = verify_episode_artifact(
        episodes_path,
        expected_sha256=(
            BASELINE_EPISODES_SHA256 if expected_sha256 is None else expected_sha256
        ),
    )
    rows = pq.read_table(episodes_path).to_pylist()
    load_seconds = perf_counter() - load_started
    analysis_started = perf_counter()
    payload = analyze_robustness(rows, artifact_sha256=digest)
    analysis_seconds = perf_counter() - analysis_started
    destination = output_dir or episodes_path.parent
    destination.mkdir(parents=True, exist_ok=True)
    robustness_json = destination / "robustness.json"
    robustness_md = destination / "robustness.md"
    timing = {
        "load_seconds": _seconds(load_seconds),
        "analysis_seconds": _seconds(analysis_seconds),
        "write_seconds": "0.0000",
        "total_seconds": "0.0000",
        "peak_rss_bytes": _peak_rss_bytes(),
    }
    payload["timing"] = timing
    payload["output_files"] = {
        "robustness_json": str(robustness_json),
        "robustness_md": str(robustness_md),
    }
    write_started = perf_counter()
    robustness_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    robustness_md.write_text(render_robustness_markdown(payload), encoding="utf-8")
    write_seconds = perf_counter() - write_started
    timing["write_seconds"] = _seconds(write_seconds)
    timing["total_seconds"] = _seconds(perf_counter() - started)
    payload["timing"] = timing
    robustness_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    robustness_md.write_text(render_robustness_markdown(payload), encoding="utf-8")
    return payload


__all__ = [
    "AMBIGUOUS_MEAN_R_SCENARIOS",
    "BASELINE_EPISODES_SHA256",
    "FIXED_SCORE_BUCKETS",
    "analyze_robustness",
    "render_robustness_markdown",
    "run_robustness",
]
