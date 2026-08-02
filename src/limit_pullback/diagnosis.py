"""Read-only descriptive diagnosis for the frozen Phase 2D.0 episodes.

This module intentionally consumes only an existing episodes.parquet. It
never calls the strategy engine, providers, replay, screen, or warehouse
pipeline. The output is diagnostic evidence, not an optimization surface.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import resource
import sys
from time import perf_counter
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq


BASELINE_EPISODES_SHA256 = (
    "23d3ff935cb44d523288c744c39abc231ce2c19a486b56ddfe057aa0809130af"
)
DIAGNOSIS_MODE = "DESCRIPTIVE DIAGNOSIS ONLY"
GUARDRAIL = "NOT STRATEGY OPTIMIZATION"
STAGES = ("B1_READY", "B2_READY", "B2_CONFIRMED")
QUALITY_BUCKETS = ("<60", "60-70", "70-80", ">=80", "UNKNOWN")
DAYS_BUCKETS = ("D+1", "D+2", "D+3", "D+4", "D+5+", "UNKNOWN")
ENTRY_ROOM_STATES = ("NONE", "THIN", "SUFFICIENT", "OPEN_SPACE", "UNKNOWN")
PATTERN_HORIZONS = ("1d", "3d", "5d", "10d")
RATIO_QUANTUM = Decimal("0.0001")
ZERO = Decimal("0")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP)


def _fmt(value: Decimal | None) -> str | None:
    return None if value is None else format(_quantize(value), "f")


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return ZERO
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return _quantize(sum(values, ZERO) / Decimal(len(values)))


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return _quantize(ordered[middle])
    return _quantize((ordered[middle - 1] + ordered[middle]) / Decimal("2"))


def _bucket(value: Any) -> str:
    score = _decimal(value)
    if score is None:
        return "UNKNOWN"
    if score < Decimal("60"):
        return "<60"
    if score < Decimal("70"):
        return "60-70"
    if score < Decimal("80"):
        return "70-80"
    return ">=80"


def _days_bucket(value: Any) -> str:
    if value is None or value == "":
        return "UNKNOWN"
    days = int(value)
    return f"D+{days}" if days <= 4 else "D+5+"


def _entry_room(value: Any) -> str:
    if value is None or value == "":
        return "UNKNOWN"
    text = str(value)
    return text if text in ENTRY_ROOM_STATES else "UNKNOWN"


def _is_actionable(row: Mapping[str, Any]) -> bool:
    value = row.get("is_entry_candidate", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _parse_quality_flags(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [value]
    else:
        parsed = value
    if isinstance(parsed, (list, tuple)):
        return [str(item) for item in parsed if str(item)]
    return [str(parsed)]


def _ordered_counts(values: Sequence[str]) -> dict[str, int]:
    counts = Counter(values)
    return {key: counts[key] for key in sorted(counts)}


def _sample_flags(resolved: int) -> list[str]:
    flags: list[str] = []
    if resolved < 30:
        flags.append("SMALL_SAMPLE")
    if resolved < 100:
        flags.append("LOW_CONFIDENCE")
    return flags


def _stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    wins = [row for row in rows if row.get("outcome") == "WIN_S1"]
    losses = [row for row in rows if row.get("outcome") == "LOSS_INVALID"]
    ambiguous = [
        row for row in rows if row.get("outcome") == "AMBIGUOUS_INTRADAY"
    ]
    timeout = [row for row in rows if row.get("outcome") == "TIMEOUT"]
    censored = [row for row in rows if row.get("outcome") == "CENSORED"]
    filled = [row for row in rows if row.get("fill_status") == "FILLED"]
    no_fill = [row for row in rows if row.get("outcome") == "NO_FILL"]
    cancelled = [
        row for row in rows if row.get("outcome") == "CANCEL_GAP_INVALID"
    ]
    eligible = [
        row
        for row in rows
        if all(
            row.get(field) not in (None, "")
            for field in ("preferred_entry", "invalid_price", "s1_price")
        )
    ]
    strict_r = [
        value
        for row in [*wins, *losses]
        if (value := _decimal(row.get("r_multiple"))) is not None
    ]
    win_r = [
        value
        for row in wins
        if (value := _decimal(row.get("r_multiple"))) is not None
    ]
    loss_r = [
        value
        for row in losses
        if (value := _decimal(row.get("r_multiple"))) is not None
    ]
    conservative_r = [
        value
        for row in [*wins, *losses, *ambiguous]
        if (value := _decimal(row.get("conservative_r_multiple"))) is not None
    ]
    resolved = len(wins) + len(losses) + len(ambiguous) + len(timeout)
    strict_resolved = len(wins) + len(losses)
    conservative_resolved = strict_resolved + len(ambiguous)
    mfe = [
        value
        for row in filled
        if (value := _decimal(row.get("mfe_pct"))) is not None
    ]
    mae = [
        value
        for row in filled
        if (value := _decimal(row.get("mae_pct"))) is not None
    ]
    return {
        "episodes": len(rows),
        "raw_signal_days": sum(int(row.get("raw_signal_days", 1)) for row in rows),
        "eligible": len(eligible),
        "no_fill": len(no_fill),
        "cancel_gap_invalid": len(cancelled),
        "filled": len(filled),
        "resolved": resolved,
        "wins": len(wins),
        "losses": len(losses),
        "ambiguous": len(ambiguous),
        "timeout": len(timeout),
        "censored": len(censored),
        "fill_rate": _fmt(_ratio(len(filled), len(eligible))),
        "strict_win_rate": _fmt(_ratio(len(wins), strict_resolved)),
        "conservative_win_rate": _fmt(
            _ratio(len(wins), conservative_resolved)
        ),
        "strict_resolved": strict_resolved,
        "conservative_resolved": conservative_resolved,
        "average_win_R": _fmt(_mean(win_r)),
        "average_loss_R": _fmt(_mean(loss_r)),
        "strict_resolved_expectancy_R": _fmt(_mean(strict_r)),
        "conservative_resolved_expectancy_R": _fmt(
            _mean(conservative_r)
        ),
        "median_MFE": _fmt(_median(mfe)),
        "median_MAE": _fmt(_median(mae)),
        "sample_flags": _sample_flags(resolved),
    }


def _decomposition(stats: Mapping[str, Any]) -> dict[str, Any]:
    strict_resolved = int(stats["strict_resolved"])
    wins = int(stats["wins"])
    losses = int(stats["losses"])
    win_rate = (
        Decimal(wins) / Decimal(strict_resolved)
        if strict_resolved
        else None
    )
    loss_rate = (
        Decimal(losses) / Decimal(strict_resolved)
        if strict_resolved
        else None
    )
    average_win = _decimal(stats.get("average_win_R"))
    average_loss = _decimal(stats.get("average_loss_R"))
    win_contribution = (
        _quantize(win_rate * average_win)
        if win_rate is not None and average_win is not None
        else None
    )
    loss_contribution = (
        _quantize(loss_rate * abs(average_loss))
        if loss_rate is not None and average_loss is not None
        else None
    )
    expectancy = _decimal(stats.get("strict_resolved_expectancy_R"))
    if expectancy is None or expectancy >= ZERO:
        diagnosis = "NONE"
    elif average_win is None or average_loss is None:
        diagnosis = "LOW_WIN_RATE"
    else:
        weak_win_rate = wins <= losses
        insufficient_payoff = average_win <= abs(average_loss)
        if weak_win_rate and insufficient_payoff:
            diagnosis = "BOTH"
        elif insufficient_payoff:
            diagnosis = "INSUFFICIENT_PAYOFF"
        else:
            diagnosis = "LOW_WIN_RATE"
    return {
        "win_rate": _fmt(win_rate),
        "loss_rate": _fmt(loss_rate),
        "win_contribution": _fmt(win_contribution),
        "loss_contribution": _fmt(loss_contribution),
        "expectancy_R": _fmt(expectancy),
        "diagnosis": diagnosis,
    }


def _cell(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = _stats(rows)
    result.update(_decomposition(result))
    return result


def _grid(
    rows: Sequence[Mapping[str, Any]],
    *,
    score_field: str,
) -> dict[str, dict[str, dict[str, Any]]]:
    actionable = [row for row in rows if _is_actionable(row)]
    return {
        stage: {
            bucket: _cell(
                [
                    row
                    for row in actionable
                    if row.get("setup_stage") == stage
                    and _bucket(row.get(score_field)) == bucket
                ]
            )
            for bucket in QUALITY_BUCKETS
        }
        for stage in STAGES
    }


def _entry_room_by_stage(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    actionable = [row for row in rows if _is_actionable(row)]
    return {
        stage: {
            state: _cell(
                [
                    row
                    for row in actionable
                    if row.get("setup_stage") == stage
                    and _entry_room(row.get("entry_room_state")) == state
                ]
            )
            for state in ENTRY_ROOM_STATES
        }
        for stage in STAGES
    }


def _distribution(
    rows: Sequence[Mapping[str, Any]],
    value_fn,
    expected: Sequence[str],
) -> dict[str, int]:
    counts = Counter(value_fn(row) for row in rows)
    result = {key: counts[key] for key in expected}
    extras = sorted(key for key in counts if key not in result)
    result.update({key: counts[key] for key in extras})
    return result


def _pattern_success(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for horizon in PATTERN_HORIZONS:
        field = f"pattern_{horizon}"
        values = [
            str(row[field]) if row.get(field) not in (None, "") else "UNKNOWN"
            for row in rows
        ]
        result[horizon] = _ordered_counts(values)
    return result


def _b2_ready_split(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    b2_rows = [row for row in rows if row.get("setup_stage") == "B2_READY"]
    result: dict[str, dict[str, Any]] = {}
    for name, actionable in (("ACTIONABLE", True), ("NON_ACTIONABLE", False)):
        cohort = [
            row for row in b2_rows if _is_actionable(row) is actionable
        ]
        result[name] = {
            "stats": _cell(cohort),
            "entry_room_distribution": _distribution(
                cohort,
                lambda row: _entry_room(row.get("entry_room_state")),
                ENTRY_ROOM_STATES,
            ),
            "setup_quality_distribution": _distribution(
                cohort,
                lambda row: _bucket(row.get("setup_quality_score")),
                QUALITY_BUCKETS,
            ),
            "entry_quality_distribution": _distribution(
                cohort,
                lambda row: _bucket(row.get("entry_quality_score")),
                QUALITY_BUCKETS,
            ),
            "days_since_anchor_distribution": _distribution(
                cohort,
                lambda row: _days_bucket(row.get("days_since_anchor")),
                DAYS_BUCKETS,
            ),
            "pattern_success": _pattern_success(cohort),
            "quality_flags": _ordered_counts(
                [
                    flag
                    for row in cohort
                    for flag in (
                        _parse_quality_flags(row.get("quality_flags"))
                        or ["NONE"]
                    )
                ]
            ),
            "eligibility_reasons": _ordered_counts(
                [
                    str(row.get("eligibility_reason"))
                    if row.get("eligibility_reason") not in (None, "")
                    else "NONE"
                    for row in cohort
                ]
            ),
        }
    return result


def _decomposition_grid(
    grid: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    fields = (
        "win_rate",
        "loss_rate",
        "win_contribution",
        "loss_contribution",
        "expectancy_R",
        "diagnosis",
        "sample_flags",
        "resolved",
    )
    return {
        group: {
            bucket: {field: cell[field] for field in fields}
            for bucket, cell in buckets.items()
        }
        for group, buckets in grid.items()
    }


def analyze_episodes(
    rows: Sequence[Mapping[str, Any]],
    *,
    artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Return deterministic diagnosis data for already-loaded frozen rows."""

    setup_grid = _grid(rows, score_field="setup_quality_score")
    entry_grid = _grid(rows, score_field="entry_quality_score")
    stage_cells = {
        stage: _cell(
            [
                row
                for row in rows
                if row.get("setup_stage") == stage and _is_actionable(row)
            ]
        )
        for stage in STAGES
    }
    structural_b2_rows = [
        row for row in rows if row.get("setup_stage") == "B2_READY"
    ]
    return {
        "diagnosis_mode": DIAGNOSIS_MODE,
        "guardrail": GUARDRAIL,
        "artifact": {
            "sha256": artifact_sha256,
            "episode_count": len(rows),
        },
        "stage_setup_quality": setup_grid,
        "stage_entry_quality": entry_grid,
        "b2_ready_actionable_vs_non_actionable": _b2_ready_split(rows),
        "b2_ready_structural_reference": _cell(structural_b2_rows),
        "entry_room_by_stage": _entry_room_by_stage(rows),
        "expectancy_decomposition": {
            "stage": {
                stage: {
                    **_decomposition(stage_cells[stage]),
                    "resolved": stage_cells[stage]["resolved"],
                    "sample_flags": stage_cells[stage]["sample_flags"],
                }
                for stage in STAGES
            },
            "stage_setup_quality": _decomposition_grid(setup_grid),
            "stage_entry_quality": _decomposition_grid(entry_grid),
        },
    }


def verify_episode_artifact(
    episodes_path: Path,
    *,
    expected_sha256: str = BASELINE_EPISODES_SHA256,
) -> str:
    """Verify the immutable diagnosis input before reading it."""

    if not episodes_path.is_file():
        raise FileNotFoundError(f"episodes artifact not found: {episodes_path}")
    digest = hashlib.sha256()
    with episodes_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if expected_sha256 and actual != expected_sha256:
        raise ValueError(
            f"episodes artifact hash mismatch: expected {expected_sha256}, got {actual}"
        )
    return actual


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _seconds(value: float) -> str:
    return f"{value:.4f}"


def render_diagnosis_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        DIAGNOSIS_MODE,
        "",
        GUARDRAIL,
        "",
        "All findings below are OBSERVATION only. No threshold or strategy change is implied.",
        "",
        "## Artifact and runtime",
        "",
        f"- episodes SHA-256: {payload['artifact']['sha256']}",
        f"- episode count: {payload['artifact']['episode_count']}",
    ]
    timing = payload.get("timing", {})
    for key in (
        "load_seconds",
        "analysis_seconds",
        "write_seconds",
        "total_seconds",
        "peak_rss_bytes",
    ):
        if key in timing:
            lines.append(f"- {key}: {timing[key]}")

    def append_grid(
        title: str,
        grid: Mapping[str, Mapping[str, Mapping[str, Any]]],
    ) -> None:
        lines.extend(
            [
                "",
                f"## {title}",
                "",
                "| stage | bucket | episodes | eligible | filled | resolved | wins | losses | ambiguous | fill rate | strict win | conservative win | avg win R | avg loss R | strict E[R] | conservative E[R] | median MFE | median MAE | sample |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for stage in STAGES:
            for bucket in QUALITY_BUCKETS:
                cell = grid[stage][bucket]
                flags = ",".join(cell["sample_flags"]) or "OK"
                lines.append(
                    "| {stage} | {bucket} | {episodes} | {eligible} | {filled} | "
                    "{resolved} | {wins} | {losses} | {ambiguous} | {fill_rate} | "
                    "{strict_win_rate} | {conservative_win_rate} | {average_win_R} | "
                    "{average_loss_R} | {strict_resolved_expectancy_R} | "
                    "{conservative_resolved_expectancy_R} | {median_MFE} | "
                    "{median_MAE} | {flags} |".format(
                        stage=stage,
                        bucket=bucket,
                        flags=flags,
                        **cell,
                    )
                )

        positive = []
        near_zero = []
        for stage in STAGES:
            for bucket in QUALITY_BUCKETS:
                cell = grid[stage][bucket]
                value = _decimal(cell["strict_resolved_expectancy_R"])
                if value is not None and value > ZERO:
                    positive.append(
                        f"{stage} + {bucket}: E[R]={cell['strict_resolved_expectancy_R']} (resolved={cell['resolved']})"
                    )
                if value is not None and abs(value) < Decimal("0.01"):
                    near_zero.append(
                        f"{stage} + {bucket}: E[R]={cell['strict_resolved_expectancy_R']} (resolved={cell['resolved']})"
                    )
        lines.extend(["", "Positive strict E[R] observations:"])
        lines.extend([f"- {item}" for item in positive] or ["- none"])
        lines.extend(
            ["", "Near-zero strict E[R] observations (absolute value < 0.01):"]
        )
        lines.extend([f"- {item}" for item in near_zero] or ["- none"])

    append_grid("STAGE × SETUP QUALITY (ACTIONABLE)", payload["stage_setup_quality"])
    append_grid("STAGE × ENTRY QUALITY (ACTIONABLE)", payload["stage_entry_quality"])

    lines.extend(
        [
            "",
            "## B2_READY ACTIONABLE VS NON_ACTIONABLE",
            "",
            "| cohort | count | eligible | filled | fill rate | strict win | avg win R | avg loss R | strict E[R] | MFE | MAE | sample |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    split = payload["b2_ready_actionable_vs_non_actionable"]
    for cohort in ("ACTIONABLE", "NON_ACTIONABLE"):
        stats = split[cohort]["stats"]
        lines.append(
            f"| {cohort} | {stats['episodes']} | {stats['eligible']} | {stats['filled']} | "
            f"{stats['fill_rate']} | {stats['strict_win_rate']} | {stats['average_win_R']} | "
            f"{stats['average_loss_R']} | {stats['strict_resolved_expectancy_R']} | "
            f"{stats['median_MFE']} | {stats['median_MAE']} | "
            f"{','.join(stats['sample_flags']) or 'OK'} |"
        )
        lines.append("")
        lines.append(f"**{cohort} distributions**")
        for key in (
            "entry_room_distribution",
            "setup_quality_distribution",
            "entry_quality_distribution",
            "days_since_anchor_distribution",
            "quality_flags",
            "eligibility_reasons",
            "pattern_success",
        ):
            lines.append(
                f"- {key}: {json.dumps(split[cohort][key], ensure_ascii=False, sort_keys=True)}"
            )

    structural = payload["b2_ready_structural_reference"]
    lines.extend(
        [
            "",
            "**STRUCTURAL B2_READY reference (descriptive only)**",
            "",
            f"- count={structural['episodes']}, strict win={structural['strict_win_rate']}, "
            f"average win R={structural['average_win_R']}, "
            f"strict E[R]={structural['strict_resolved_expectancy_R']}, "
            f"resolved={structural['resolved']}",
        ]
    )

    lines.extend(
        [
            "",
            "## EXPECTANCY DECOMPOSITION",
            "",
            "| group | bucket | win rate | loss rate | win contribution | loss contribution | expectancy R | diagnosis | sample |",
            "|---|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    decomposition = payload["expectancy_decomposition"]
    for stage in STAGES:
        cell = decomposition["stage"][stage]
        lines.append(
            f"| {stage} | ALL | {cell['win_rate']} | {cell['loss_rate']} | "
            f"{cell['win_contribution']} | {cell['loss_contribution']} | "
            f"{cell['expectancy_R']} | {cell['diagnosis']} | "
            f"{','.join(cell['sample_flags']) or 'OK'} |"
        )
    for group_name in ("stage_setup_quality", "stage_entry_quality"):
        for stage in STAGES:
            for bucket in QUALITY_BUCKETS:
                cell = decomposition[group_name][stage][bucket]
                lines.append(
                    f"| {group_name} | {stage} + {bucket} | {cell['win_rate']} | "
                    f"{cell['loss_rate']} | {cell['win_contribution']} | "
                    f"{cell['loss_contribution']} | {cell['expectancy_R']} | "
                    f"{cell['diagnosis']} | {','.join(cell['sample_flags']) or 'OK'} |"
                )

    lines.extend(["", "## ENTRY ROOM BY STAGE", ""])
    for stage in STAGES:
        counts = {
            state: payload["entry_room_by_stage"][stage][state]["episodes"]
            for state in ENTRY_ROOM_STATES
        }
        lines.append(f"- {stage}: {json.dumps(counts, ensure_ascii=False)}")

    lines.extend(
        [
            "",
            "## ASHARE-LAKE REFERENCE (NOT INTEGRATED)",
            "",
            "- DatasetSpec-style semantics: by_date / snapshot / PIT / backfill_source / history_horizon",
            "- Historical universe: instruments + delisted backfill + trading_status",
            "- Future Phase 2D.1 candidate: 5m minute bars to reduce daily OHLC ambiguity",
            "- Future Daily Runner reference: watermark / catchup / retry / non-trading-day skip / audit",
            "",
            "These are external references only. ashare-lake is not integrated; no dependency, provider, warehouse, or data was added.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_diagnosis(
    episodes_path: Path,
    *,
    output_dir: Path | None = None,
    expected_sha256: str | None = BASELINE_EPISODES_SHA256,
) -> dict[str, Any]:
    """Verify, read, analyze, and write the two lightweight diagnosis files."""

    started = perf_counter()
    load_started = perf_counter()
    digest = verify_episode_artifact(
        episodes_path,
        expected_sha256=(
            BASELINE_EPISODES_SHA256
            if expected_sha256 is None
            else expected_sha256
        ),
    )
    rows = pq.read_table(episodes_path).to_pylist()
    load_seconds = perf_counter() - load_started
    analysis_started = perf_counter()
    payload = analyze_episodes(rows, artifact_sha256=digest)
    analysis_seconds = perf_counter() - analysis_started
    destination = output_dir or episodes_path.parent
    destination.mkdir(parents=True, exist_ok=True)
    diagnosis_json = destination / "diagnosis.json"
    diagnosis_md = destination / "diagnosis.md"
    timing = {
        "load_seconds": _seconds(load_seconds),
        "analysis_seconds": _seconds(analysis_seconds),
        "write_seconds": "0.0000",
        "total_seconds": "0.0000",
        "peak_rss_bytes": _peak_rss_bytes(),
    }
    payload["timing"] = timing
    payload["output_files"] = {
        "diagnosis_json": str(diagnosis_json),
        "diagnosis_md": str(diagnosis_md),
    }
    write_started = perf_counter()
    diagnosis_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    diagnosis_md.write_text(
        render_diagnosis_markdown(payload),
        encoding="utf-8",
    )
    write_seconds = perf_counter() - write_started
    timing["write_seconds"] = _seconds(write_seconds)
    timing["total_seconds"] = _seconds(perf_counter() - started)
    payload["timing"] = timing
    diagnosis_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    diagnosis_md.write_text(
        render_diagnosis_markdown(payload),
        encoding="utf-8",
    )
    return payload


__all__ = [
    "BASELINE_EPISODES_SHA256",
    "analyze_episodes",
    "render_diagnosis_markdown",
    "run_diagnosis",
    "verify_episode_artifact",
]
