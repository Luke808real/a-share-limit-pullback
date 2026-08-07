"""Phase-1B shadow strategy validation harness (READ-ONLY) - review-fix round 1.

Compares LEGACY frozen canonical vs ASL-adapter daily facts through the SAME
production strategy engine (``screen.engine.screen_code`` with an empty
limit-up pool => PRICE_ONLY), for the frozen Phase-2D0 universe over the
bounded shadow window.

Review-fix-round-1 semantics (independent ChatGPT review of Draft PR #27):

* Coverage: a trailing mutual absence (legacy AND ASL both lack a session)
  no longer discards the code\'s history: the ASL slice is truncated to the
  last mutually available session and the code is still processed.  Skipped
  codes are never counted as evaluated; any unexplained skip sets
  BLOCKED_DATA.  Coverage counts are code-date rows, not distinct dates.
* Input classification: every per-date mismatch ends as exactly one proven
  class or UNKNOWN_INPUT_DIVERGENCE (reachable; e.g. a preclose mismatch
  without code-specific corporate-action evidence).
* ASSOCIATED_INPUT_CLASS (window-based association for broad historical
  reporting) is documented separately from PROVEN_ROOT_CAUSE
  (counterfactual ablation, only for decision-relevant AS_OF differences).
* trade_status is compared as a HARD field on every common row.
* ST semantics use ASL status provenance (``asl_status_trust``): trusted ST /
  trusted normal / ST coverage unknown / legacy non-PIT snapshot.  A true
  PIT upgrade requires trusted ASL provenance; legacy ST=True -> ASL None is
  ST_COVERAGE_UNKNOWN and blocks the gate when decision-relevant.
* A non-vacuous COMMON-CALENDAR CONTROL replay runs the same production
  screen_code over both backends\' OHLCV on the shared row membership, with
  sequentially rebuilt preclose, ST neutralized to the same value, and
  trade_status required equal.
* Episodes are keyed by setup_id with transition dates and score evidence.
* Success/control cases are compared at their frozen candidate_date.
* The final screen reports ACTIONABLE_STAGE_N and ENTRY_CANDIDATE_N; Top20
  ranks the is_entry_candidate==True population deterministically.
* AS_OF decision differences get bounded counterfactual ablations; any
  UNKNOWN root cause blocks.
* Volume-only mismatches are hard inside any evaluation window; outside
  every window they are explicitly classified
  OUTSIDE_EVAL_HISTORY_VOLUME_DIVERGENCE with strategy-inert reasoning.
* Resource gate uses an aggregate parent+children RSS sampler (psutil);
  harness wall time excludes ASL backfill.
* ONE authoritative PHASE1B_GATE drives exit code and summary.

No production wiring.  No fork of strategy logic.  No turnover, no pool
enrichment, no minute bars.  No ASL lake rebuild.

Exit codes: 0 = PASS, 2 = BLOCKED_PARITY, 3 = BLOCKED_DATA,
4 = BLOCKED_RESOURCE.

Usage:
    PYTHONPATH=src python research/asl_phase1b/shadow.py \
        --legacy-snapshot /path/snap-2026-08-06-e798f88ff67b.parquet \
        --asl-root /tmp/asl_phase1b_lake \
        --universe /tmp/frozen_universe_phase2d0.json \
        --workers 4
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import os
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

from limit_pullback.config import load_strategy_config
from limit_pullback.models.enums import SetupStage
from limit_pullback.models.market import DailyBar
from limit_pullback.screen.engine import screen_code
from limit_pullback.warehouse.asl_adapter import (
    AslAdapterError,
    load_asl_daily_slice,
)

try:
    import psutil as _psutil
except ImportError:  # pragma: no cover - environment fallback
    _psutil = None

# Phase-1B boundary (frozen).
WINDOW_START = date(2026, 4, 1)
AS_OF = date(2026, 8, 6)
#: History start: legacy canonical coverage begins 2024-01-02; the adapter's
#: first VALID row per code starts 2024-01-03 (chain seeded by 01-02 close).
#: First session with complete ASL bar coverage for the frozen universe
#: (2 frozen codes were suspended until 2024-01-10 / 2024-01-16 at the start
#: of the backfill window; legacy canonical agrees on both).  Provides
#: ~540 trading bars of history before the first eval point, exceeding the
#: required 250-bar lookback.
HISTORY_START = date(2024, 1, 16)

#: Frozen strategy max lookback: MA250 (moving_average_windows), position
#: window 120, resistance lookbacks 60.  250 bars is the maximum dependency.
REQUIRED_HISTORY_BARS = 250

# Phase-1A hard field tolerances.
PRICE_ABS = Decimal("0.01")
PRICE_REL = Decimal("0.001")
VOLUME_REL = Decimal("0.005")
AMOUNT_REL = Decimal("0.005")
PCT_ABS = Decimal("0.05")

GATE_PASS = "PASS"
GATE_BLOCKED_PARITY = "BLOCKED_PARITY"
GATE_BLOCKED_DATA = "BLOCKED_DATA"
GATE_BLOCKED_RESOURCE = "BLOCKED_RESOURCE"

FIXED_GENERATED_AT = datetime(2026, 8, 6, 23, 59, 59, tzinfo=timezone.utc)

STAGE_ORDER = {stage.value: index for index, stage in enumerate(SetupStage)}

ACTIONABLE_STAGES = ("B1_READY", "B2_READY", "B2_CONFIRMED")

#: Exhaustive input-class vocabulary.  Per-date classification emits every
#: class except OUTSIDE_EVAL_HISTORY_VOLUME_DIVERGENCE (eval-level only);
#: VOLUME_DIVERGENCE is per-date only.  Every mismatch ends as exactly one
#: proven class or UNKNOWN_INPUT_DIVERGENCE.
INPUT_CLASSES = (
    "INPUT_EQUIVALENT",
    "LEGACY_HOLE_REPAIRED_BY_ASL",
    "LEGACY_ONLY",
    "LEGACY_PRECLOSE_ERA_DIVERGENCE",
    "VOLUME_DIVERGENCE",
    "OUTSIDE_EVAL_HISTORY_VOLUME_DIVERGENCE",
    "PIT_ST_DATA_UPGRADE",
    "TRUSTED_ASL_NORMAL",
    "ST_COVERAGE_UNKNOWN",
    "LEGACY_NON_PIT_TO_ASL_UNKNOWN",
    "HARD_FIELD_CONFLICT",
    "UNKNOWN_INPUT_DIVERGENCE",
)

ST_CLASSES = (
    "EXACT_STATUS_MATCH",
    "TRUSTED_ASL_ST",
    "TRUSTED_ASL_NORMAL",
    "ST_COVERAGE_UNKNOWN",
    "LEGACY_NON_PIT_TO_ASL_UNKNOWN",
)

EPISODE_CLASSES = (
    "EXACT_EPISODE",
    "LEGACY_HOLE_CHANGED_EPISODE",
    "PIT_ST_CHANGED_EPISODE",
    "ST_COVERAGE_UNKNOWN_EPISODE",
    "TRUSTED_ASL_NORMAL_EPISODE",
    "LEGACY_PRECLOSE_ERA_CHANGED_EPISODE",
    "ASL_NEW_VALID_EPISODE",
    "LEGACY_ONLY_EPISODE",
    "UNKNOWN_EPISODE_DIVERGENCE",
)

#: Trust kinds that can sit on a VALID adapter row (DERIVED_GAP_SUSPENDED
#: sessions are not emitted as bars; if it ever appears on a bar it is an
#: ASL trusted-status internal conflict -> hard).
TRUSTED_ROW_KINDS = frozenset({"BAOSTOCK_ST", "EASTMONEY_SAME_DAY"})

#: Window-association precedence for eval points (highest wins).  This is
#: ASSOCIATED_INPUT_CLASS, NOT proven root cause.
_WINDOW_PRECEDENCE = {
    "HARD_FIELD_CONFLICT": 12,
    "UNKNOWN_INPUT_DIVERGENCE": 11,
    "LEGACY_ONLY": 10,
    "ST_COVERAGE_UNKNOWN": 9,
    "PIT_ST_DATA_UPGRADE": 8,
    "TRUSTED_ASL_NORMAL": 7,
    "LEGACY_PRECLOSE_ERA_DIVERGENCE": 6,
    "LEGACY_HOLE_REPAIRED_BY_ASL": 5,
    "LEGACY_NON_PIT_TO_ASL_UNKNOWN": 4,
    "OUTSIDE_EVAL_HISTORY_VOLUME_DIVERGENCE": 1,
    "INPUT_EQUIVALENT": 0,
}


def compute_phase1b_gate(
    *,
    data_blocked: bool,
    resource_ok: bool,
    hard_field_conflict_n: int,
    unknown_input_divergence_n: int,
    strategy_engine_parity_failures_n: int,
    control_equivalent_eval_point_n: int,
    control_strategy_mismatch_n: int,
    unknown_episode_divergence_n: int,
    as_of_root_cause_unknown_n: int,
    decision_relevant_st_unknown_n: int,
) -> str:
    """THE single authoritative Phase-1B decision.

    BLOCKED_DATA > BLOCKED_RESOURCE > BLOCKED_PARITY > PASS.

    The control is non-vacuous: PASS requires at least one genuinely
    equivalent eval point (CONTROL_EQUIVALENT_EVAL_POINT_N > 0) with zero
    control mismatches.
    """

    if data_blocked:
        return GATE_BLOCKED_DATA
    if not resource_ok:
        return GATE_BLOCKED_RESOURCE
    if (
        hard_field_conflict_n > 0
        or unknown_input_divergence_n > 0
        or strategy_engine_parity_failures_n > 0
        or control_strategy_mismatch_n > 0
        or control_equivalent_eval_point_n <= 0
        or unknown_episode_divergence_n > 0
        or as_of_root_cause_unknown_n > 0
        or decision_relevant_st_unknown_n > 0
    ):
        return GATE_BLOCKED_PARITY
    return GATE_PASS


def exit_code_for_gate(gate: str) -> int:
    return {
        GATE_PASS: 0,
        GATE_BLOCKED_PARITY: 2,
        GATE_BLOCKED_DATA: 3,
        GATE_BLOCKED_RESOURCE: 4,
    }[gate]


def _rel(a: Decimal, b: Decimal) -> Decimal:
    scale = max(abs(a), abs(b))
    if scale == 0:
        return Decimal("0")
    return abs(a - b) / scale


def _price_ok(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= PRICE_ABS or _rel(a, b) <= PRICE_REL


def _vol_ok(a: Decimal, b: Decimal) -> bool:
    return _rel(a, b) <= VOLUME_REL


def _to_bar(row: Mapping[str, Any]) -> DailyBar:
    return DailyBar(
        trade_date=row["trade_date"],
        code=str(row["code"]),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        preclose=Decimal(str(row["preclose"])),
        volume=Decimal(str(row["volume"])),
        amount=Decimal(str(row["amount"])),
        turnover_rate=None,
        pct_change=None,
        trade_status=bool(row.get("trade_status", True)),
        is_st=(
            bool(row["is_st"]) if row.get("is_st") is not None else None
        ),
        source="SHADOW",
        fetched_at=FIXED_GENERATED_AT,
    )


def load_legacy_canonical(
    path: Path, codes: set[str], start: date, as_of: date
) -> dict[str, list[dict[str, Any]]]:
    """CONFIRMED legacy rows per code in [start, as_of] (compact dicts).

    Uses pyarrow predicate pushdown on ``code`` so only the requested codes
    are materialized (memory-bounded for large universes).
    """

    table = pq.read_table(
        path,
        filters=[("code", "in", sorted(codes))],
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in table.to_pylist():
        code = str(row["code"])
        if code not in codes:
            continue
        if row["reconciliation_status"] != "CONFIRMED":
            continue
        if not (start <= row["trade_date"] <= as_of):
            continue
        out.setdefault(code, []).append(
            {
                "trade_date": row["trade_date"],
                "code": code,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "preclose": row["preclose"],
                "volume": row["volume"],
                "amount": row["amount"],
                "trade_status": bool(row.get("trade_status", True)),
                "is_st": row.get("is_st"),
            }
        )
    for rows in out.values():
        rows.sort(key=lambda row: row["trade_date"])
    return out


def load_asl_facts(
    asl_root: Path, codes: Sequence[str], start: date, as_of: date
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """ASL adapter daily facts per code (VALID rows only) + status provenance
    counts from the returned slice (never silently assumed)."""

    slice_ = load_asl_daily_slice(
        asl_root,
        as_of=as_of,
        start=start,
        codes=list(codes),
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in slice_.rows:
        if row.row_status != "VALID_ROW":
            continue
        out.setdefault(row.code, []).append(
            {
                "trade_date": row.trade_date,
                "code": row.code,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "preclose": row.preclose,
                "volume": row.volume,
                "amount": row.amount,
                "trade_status": row.trade_status,
                "is_st": row.is_st,
                "asl_status_trust": row.asl_status_trust,
            }
        )
    for rows in out.values():
        rows.sort(key=lambda row: row["trade_date"])
    coverage = slice_.status_coverage
    counts = {
        "trusted_baostock_n": coverage.trusted_baostock_n,
        "trusted_derived_gap_n": coverage.trusted_derived_gap_n,
        "trusted_eastmoney_same_day_n": coverage.trusted_eastmoney_same_day_n,
        "non_pit_eastmoney_ignored_n": coverage.non_pit_eastmoney_ignored_n,
        "unknown_status_n": coverage.unknown_status_n,
    }
    return out, counts


def strategy_signature(item: Any) -> tuple:
    """Deterministic signature from one ReplayTimelineItem."""

    anchor = item.anchor_snapshot
    return (
        item.setup_stage.value,
        anchor.anchor_date.isoformat() if anchor is not None else None,
        str(anchor.anchor_price) if anchor is not None else None,
        item.score_profile.value,
        str(item.normalized_score),
        str(item.setup_quality_score),
        str(item.entry_quality_score) if item.entry_quality_score is not None else None,
        item.is_entry_candidate,
        item.review_group.value,
        tuple(sorted(flag.value for flag in item.event_flags)),
        tuple(sorted(item.invalidation_reasons)),
        item.primary_pattern.value if item.primary_pattern is not None else None,
    )


class AggregateRssSampler:
    """Samples parent + live child process RSS periodically and reports the
    maximum SUM in MiB (concurrent pool footprint, not ``max(RUSAGE)``).

    Returns None when psutil is unavailable -> resource gate cannot pass.
    """

    def __init__(self, interval_seconds: float = 2.0):
        self.interval = interval_seconds
        self._peak = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if _psutil is None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        proc = _psutil.Process()
        while not self._stop.wait(self.interval):
            try:
                total = proc.memory_info().rss
                for child in proc.children(recursive=True):
                    try:
                        total += child.memory_info().rss
                    except _psutil.NoSuchProcess:
                        pass
            except _psutil.Error:
                continue
            self._peak = max(self._peak, total)

    def stop(self) -> float | None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        if _psutil is None:
            return None
        return self._peak / (1024.0 * 1024.0)


def build_timeline(
    rows: Sequence[Mapping[str, Any]],
    config: Any,
    start_date: date,
    as_of: date,
) -> tuple[list[Any], Any]:
    """Production screen_code (PRICE_ONLY: empty pool) over the rows."""

    bars = [_to_bar(row) for row in rows]
    if not bars:
        return [], None
    items, final_signal = screen_code(
        code=str(rows[0]["code"]),
        bars=bars,
        pool_records=(),
        config=config,
        start_date=start_date,
        as_of=as_of,
        generated_at=FIXED_GENERATED_AT,
    )
    return list(items), final_signal


def _frozen_pct(row: Mapping[str, Any]) -> Decimal | None:
    """Frozen pct_change rule: (close-preclose)/preclose*100, quantized 0.0001."""

    preclose = Decimal(str(row["preclose"]))
    if preclose <= 0:
        return None
    return (
        (Decimal(str(row["close"])) - preclose) / preclose * Decimal("100")
    ).quantize(Decimal("0.0001"))


def _st_classification(
    legacy_st: bool | None,
    asl_st: bool | None,
    asl_trust: str | None,
) -> tuple[str, str | None]:
    """ST semantics per common row, provenance-aware.

    Returns (st_class, divergence_class_or_None).  A divergence class is
    emitted ONLY when the two backends differ in a strategy-relevant way:

    * asl trusted ST (BAOSTOCK_ST / EASTMONEY_SAME_DAY st):
        legacy True -> exact; legacy None/False -> PIT_ST_DATA_UPGRADE.
    * asl trusted normal (EASTMONEY_SAME_DAY normal):
        legacy False -> exact; legacy True/None -> TRUSTED_ASL_NORMAL delta.
    * no trusted ASL status row (asl is_st=None):
        legacy None -> exact; legacy True -> ST_COVERAGE_UNKNOWN;
        legacy False -> LEGACY_NON_PIT_TO_ASL_UNKNOWN (strategy-inert).
    """

    if asl_trust == "DERIVED_GAP_SUSPENDED":
        # A suspended session must never be emitted as a VALID bar; this
        # would be an ASL trusted-status internal contradiction.
        return "ASL_TRUSTED_STATUS_INTERNAL_CONFLICT", "HARD_FIELD_CONFLICT"
    if asl_trust in TRUSTED_ROW_KINDS:
        if asl_st is True:
            if legacy_st is True:
                return "TRUSTED_ASL_ST", None
            return "TRUSTED_ASL_ST", "PIT_ST_DATA_UPGRADE"
        # trusted normal
        if legacy_st is False:
            return "TRUSTED_ASL_NORMAL", None
        return "TRUSTED_ASL_NORMAL", "TRUSTED_ASL_NORMAL"
    # No trusted status row -> adapter emits is_st=None ("unknown remains
    # unknown").  None == None is EXACT_STATUS_MATCH; known->unknown is a
    # documented semantic delta.
    if legacy_st is True:
        return "ST_COVERAGE_UNKNOWN", "ST_COVERAGE_UNKNOWN"
    if legacy_st is None:
        return "EXACT_STATUS_MATCH", None
    return "LEGACY_NON_PIT_TO_ASL_UNKNOWN", "LEGACY_NON_PIT_TO_ASL_UNKNOWN"


def ca_era_preclose(
    legacy_row: Mapping[str, Any],
    asl_row: Mapping[str, Any],
    legacy_prev_close: Decimal | None,
    asl_prev_close: Decimal | None,
) -> bool:
    """The known CA-era preclose pattern: legacy preclose differs from the
    legacy previous close while ASL preclose equals the ASL previous close
    (the frozen sequential contract).  Pattern alone is NOT proof: code-
    specific corporate-action evidence is required by the caller."""

    # The frozen contract requires EXACT preclose reproduction: relative
    # tolerance would hide dividend-sized differences at high prices
    # (e.g. 100.81 vs 100.91 on a 100-yuan stock).
    legacy_pre = Decimal(str(legacy_row["preclose"]))
    asl_pre = Decimal(str(asl_row["preclose"]))
    if legacy_pre == asl_pre:
        return False
    if legacy_prev_close is None or asl_prev_close is None:
        return False
    legacy_diverges = legacy_pre != legacy_prev_close
    asl_sequential = asl_pre == asl_prev_close
    return legacy_diverges and asl_sequential


def classify_code_inputs(
    code: str,
    legacy_rows: Sequence[Mapping[str, Any]],
    asl_rows: Sequence[Mapping[str, Any]],
    ca_ex_dates: set[tuple[str, date]],
) -> dict[str, Any]:
    """Per-code per-date input classes over [HISTORY_START, AS_OF].

    Every mismatch ends as exactly one proven class or
    UNKNOWN_INPUT_DIVERGENCE (never defaulted to a known class because a
    known difference exists somewhere else in the window).
    """

    legacy_by_date = {row["trade_date"]: row for row in legacy_rows}
    asl_by_date = {row["trade_date"]: row for row in asl_rows}
    all_dates = sorted(set(legacy_by_date) | set(asl_by_date))

    per_date_class: dict[date, str] = {}
    per_date_detail: dict[date, str] = {}
    hard_conflicts: list[dict[str, Any]] = []
    volume_divergences: list[dict[str, Any]] = []
    st_class_counts: dict[str, int] = {cls: 0 for cls in ST_CLASSES}
    legacy_prev_close: Decimal | None = None
    asl_prev_close: Decimal | None = None
    legacy_prev_date: date | None = None
    asl_prev_date: date | None = None

    for day in all_dates:
        legacy = legacy_by_date.get(day)
        asl = asl_by_date.get(day)
        divergence: str | None = None
        detail: str | None = None
        if legacy is not None and asl is not None:
            prices_ok = all(
                _price_ok(
                    Decimal(str(legacy[field])), Decimal(str(asl[field]))
                )
                for field in ("open", "high", "low", "close")
            )
            amount_ok = _vol_ok(
                Decimal(str(legacy["amount"])), Decimal(str(asl["amount"]))
            )
            volume_ok = _vol_ok(
                Decimal(str(legacy["volume"])), Decimal(str(asl["volume"]))
            )
            legacy_ts = bool(legacy.get("trade_status", True))
            asl_ts = bool(asl.get("trade_status", True))
            if not prices_ok or not amount_ok:
                divergence = "HARD_FIELD_CONFLICT"
                detail = "OHLC/amount outside Phase-1A tolerance"
                hard_conflicts.append(
                    {"code": code, "date": day.isoformat(), "detail": detail}
                )
            elif legacy_ts != asl_ts:
                # trade_status is a HARD field (frozen Phase-1A contract).
                divergence = "HARD_FIELD_CONFLICT"
                detail = (
                    f"trade_status legacy={legacy_ts} vs ASL={asl_ts}"
                )
                hard_conflicts.append(
                    {"code": code, "date": day.isoformat(), "detail": detail}
                )
            elif not volume_ok:
                # Volume outside tolerance is HARD by default.  Whether it is
                # strategy-inert is decided per eval point (window check); it
                # is recorded here as a plain VOLUME_DIVERGENCE.
                divergence = "VOLUME_DIVERGENCE"
                detail = (
                    f"volume legacy={legacy['volume']} asl={asl['volume']} "
                    f"(OHLC/amount within tolerance is NOT proof of inertness)"
                )
                volume_divergences.append(
                    {
                        "code": code,
                        "date": day.isoformat(),
                        "legacy_volume": str(legacy["volume"]),
                        "asl_volume": str(asl["volume"]),
                        "detail": detail,
                    }
                )
            else:
                # Prices / amount / volume / trade_status agree; check the
                # preclose contract, then ST.
                legacy_pre = Decimal(str(legacy["preclose"]))
                asl_pre = Decimal(str(asl["preclose"]))
                if legacy_pre != asl_pre:
                    if (
                        (code, day) in ca_ex_dates
                        and ca_era_preclose(
                            legacy, asl, legacy_prev_close, asl_prev_close
                        )
                    ):
                        # Code-specific CA evidence on THIS date + the known
                        # legacy exchange-precLose pattern.
                        divergence = "LEGACY_PRECLOSE_ERA_DIVERGENCE"
                        detail = (
                            f"legacy exchange-precLose vs ASL sequential on "
                            f"corporate-action ex-date {day} for {code}"
                        )
                    elif (
                        legacy_prev_close is not None
                        and asl_prev_close is not None
                        and legacy_prev_date is not None
                        and asl_prev_date is not None
                        and legacy_pre == legacy_prev_close
                        and asl_pre == asl_prev_close
                        # EXPLICIT membership evidence, never date-divergence
                        # alone: the ASL predecessor session is ASL-only (a
                        # legacy-hole-repaired session) and the legacy
                        # predecessor is a common row.
                        and asl_prev_date not in legacy_by_date
                        and legacy_prev_date in asl_by_date
                    ):
                        # Both chains are sequential (preclose == own previous
                        # close); the preclose difference is the membership
                        # consequence of the ASL-only predecessor session.
                        # PROVEN, not an unknown.
                        divergence = "LEGACY_HOLE_REPAIRED_BY_ASL"
                        detail = (
                            f"sequential preclose consequence of repaired "
                            f"legacy session {asl_prev_date.isoformat()} "
                            f"(ASL-only predecessor, close {asl_prev_close}) "
                            f"vs legacy predecessor "
                            f"{legacy_prev_date.isoformat()} (common row, "
                            f"close {legacy_prev_close}); both chains "
                            f"sequential, delta fully membership-explained"
                        )
                    else:
                        # Unproven preclose divergence: no code-specific CA
                        # evidence and no membership proof -> UNKNOWN, never
                        # silently assumed CA-era.
                        divergence = "UNKNOWN_INPUT_DIVERGENCE"
                        detail = (
                            f"preclose legacy={legacy_pre} asl={asl_pre} "
                            f"without code-specific corporate-action evidence "
                            f"or predecessor-membership proof"
                        )
                else:
                    st_class, st_divergence = _st_classification(
                        legacy.get("is_st"),
                        asl.get("is_st"),
                        asl.get("asl_status_trust"),
                    )
                    st_class_counts[st_class] += 1
                    if st_divergence is not None:
                        divergence = st_divergence
                        detail = (
                            f"ST: legacy is_st={legacy.get('is_st')} vs "
                            f"ASL is_st={asl.get('is_st')} "
                            f"trust={asl.get('asl_status_trust')} "
                            f"({st_class})"
                        )
        elif legacy is not None:
            divergence = "LEGACY_ONLY"
            detail = "legacy CONFIRMED row without ASL bar"
        else:
            divergence = "LEGACY_HOLE_REPAIRED_BY_ASL"
            detail = "ASL bar without legacy CONFIRMED row"

        per_date_class[day] = divergence or "INPUT_EQUIVALENT"
        if divergence is not None:
            per_date_detail[day] = detail or divergence
        if legacy is not None and Decimal(str(legacy["close"])) > 0:
            legacy_prev_close = Decimal(str(legacy["close"]))
            legacy_prev_date = day
        if asl is not None and Decimal(str(asl["close"])) > 0:
            asl_prev_close = Decimal(str(asl["close"]))
            asl_prev_date = day

    first_divergence = None
    for day in all_dates:
        cls = per_date_class[day]
        if cls != "INPUT_EQUIVALENT" and first_divergence is None:
            first_divergence = {
                "date": day.isoformat(),
                "input_class": cls,
                "detail": per_date_detail.get(day, cls),
            }
            break
    return {
        "code": code,
        "first_divergence": first_divergence,
        "per_date_class": per_date_class,
        "per_date_detail": per_date_detail,
        "hard_conflicts": hard_conflicts,
        "volume_divergences": volume_divergences,
        "st_class_counts": st_class_counts,
        "common_dates": sorted(set(legacy_by_date) & set(asl_by_date)),
        "legacy_only_code_dates": sorted(
            set(legacy_by_date) - set(asl_by_date)
        ),
        "asl_only_code_dates": sorted(
            set(asl_by_date) - set(legacy_by_date)
        ),
    }


def _window_class(
    per_date_class: Mapping[date, str],
    ordered: Sequence[date],
    window_dates: Sequence[date],
    has_volume_divergence: bool,
) -> str:
    """Associated class for ONE eval window (the last ``window_dates``)."""

    counts: dict[str, int] = {}
    for day in window_dates:
        cls = per_date_class.get(day, "INPUT_EQUIVALENT")
        counts[cls] = counts.get(cls, 0) + 1
    if counts.get("HARD_FIELD_CONFLICT", 0):
        return "HARD_FIELD_CONFLICT"
    if counts.get("UNKNOWN_INPUT_DIVERGENCE", 0):
        return "UNKNOWN_INPUT_DIVERGENCE"
    if counts.get("VOLUME_DIVERGENCE", 0):
        # A volume divergence inside the strategy lookback is hard.
        return "HARD_FIELD_CONFLICT"
    best = "INPUT_EQUIVALENT"
    best_rank = 0
    for cls, count in counts.items():
        if count > 0 and cls != "INPUT_EQUIVALENT":
            rank = _WINDOW_PRECEDENCE[cls]
            if rank > best_rank:
                best, best_rank = cls, rank
    if best == "INPUT_EQUIVALENT" and has_volume_divergence:
        # Volume divergence exists but is outside this eval window: proven
        # strategy-inert for this evaluation point (recorded with reasoning).
        return "OUTSIDE_EVAL_HISTORY_VOLUME_DIVERGENCE"
    return best


def eval_point_classes(
    per_date_class: Mapping[date, str],
    timeline_dates: Sequence[date],
    eval_dates: Sequence[date],
    window_bars: int = REQUIRED_HISTORY_BARS,
) -> tuple[dict[date, str], dict[date, tuple[date, ...]]]:
    """ASSOCIATED eval-point classes via a sliding window.

    For eval date D the window is the last ``window_bars`` timeline dates
    <= D.  The class is the highest-precedence divergence inside the window
    (INPUT_EQUIVALENT when clean); a VOLUME_DIVERGENCE inside the window is
    HARD_FIELD_CONFLICT; a volume divergence outside every window yields
    OUTSIDE_EVAL_HISTORY_VOLUME_DIVERGENCE.  Also returns each eval date's
    window dates (for volume-inertness reasoning).

    This is ASSOCIATED_INPUT_CLASS, NOT proven root cause.
    """

    ordered = sorted(timeline_dates)
    has_volume_divergence = any(
        cls == "VOLUME_DIVERGENCE" for cls in per_date_class.values()
    )
    left = 0
    out: dict[date, str] = {}
    windows: dict[date, tuple[date, ...]] = {}
    eval_set = set(eval_dates)
    window_counts: dict[str, int] = {}
    for right, day in enumerate(ordered):
        cls = per_date_class.get(day, "INPUT_EQUIVALENT")
        window_counts[cls] = window_counts.get(cls, 0) + 1
        while right - left + 1 > window_bars:
            old_cls = per_date_class.get(ordered[left], "INPUT_EQUIVALENT")
            window_counts[old_cls] -= 1
            if window_counts[old_cls] <= 0:
                window_counts.pop(old_cls, None)
            left += 1
        if day not in eval_set:
            continue
        window_dates = tuple(ordered[left : right + 1])
        windows[day] = window_dates
        # Per-eval reconstruction keeps the volume-in-window logic exact
        # (window is <= 250 dates; cheap).
        out[day] = _window_class(
            per_date_class, ordered, window_dates, has_volume_divergence
        )
    return out, windows


def derive_episodes(items: Sequence[Any]) -> list[dict[str, Any]]:
    """Episodes keyed by the production setup_id (primary identity), with
    transition dates and deterministic transition score evidence."""

    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def close(episode: dict[str, Any]) -> None:
        episode["end_date"] = episode.get("end_date") or episode["start_date"]

    for item in items:
        anchor = item.anchor_snapshot
        if anchor is not None:
            sid = item.setup_id
            if current is not None and current["setup_id"] == sid:
                pass  # same episode continues
            else:
                if current is not None:
                    close(current)
                    episodes.append(current)
                current = {
                    "setup_id": sid,
                    "anchor_date": anchor.anchor_date.isoformat(),
                    "anchor_price": str(anchor.anchor_price),
                    "start_date": item.trade_date.isoformat(),
                    "end_date": None,
                    "max_stage": item.setup_stage.value,
                    "final_stage": item.setup_stage.value,
                    "first_b1_date": None,
                    "first_b2_ready_date": None,
                    "first_b2_confirmed_date": None,
                    "invalidation_date": None,
                    "b1_normalized_score": None,
                    "end_normalized_score": None,
                }
            cur = current
            stage = item.setup_stage.value
            cur["final_stage"] = stage
            cur["end_date"] = item.trade_date.isoformat()
            cur["end_normalized_score"] = str(item.normalized_score)
            if stage == "B1_READY" and cur["first_b1_date"] is None:
                cur["first_b1_date"] = item.trade_date.isoformat()
                cur["b1_normalized_score"] = str(item.normalized_score)
            if stage == "B2_READY" and cur["first_b2_ready_date"] is None:
                cur["first_b2_ready_date"] = item.trade_date.isoformat()
            if stage == "B2_CONFIRMED" and cur["first_b2_confirmed_date"] is None:
                cur["first_b2_confirmed_date"] = item.trade_date.isoformat()
            if stage == "INVALID" and cur["invalidation_date"] is None:
                cur["invalidation_date"] = item.trade_date.isoformat()
            if STAGE_ORDER[stage] > STAGE_ORDER[cur["max_stage"]]:
                cur["max_stage"] = stage
        else:
            # NORMAL item (no anchor): closes any open episode; a new setup
            # only starts on a later anchored item.
            if current is not None:
                close(current)
                episodes.append(current)
                current = None
    if current is not None:
        close(current)
        episodes.append(current)
    return episodes


def episode_signature(episode: dict[str, Any]) -> tuple:
    return (
        episode["setup_id"],
        episode["anchor_date"],
        episode["anchor_price"],
        episode["start_date"],
        episode["first_b1_date"],
        episode["first_b2_ready_date"],
        episode["first_b2_confirmed_date"],
        episode["invalidation_date"],
        episode["end_date"],
        episode["max_stage"],
        episode["final_stage"],
        episode["b1_normalized_score"],
        episode["end_normalized_score"],
    )


_EPISODE_BUCKET = {
    "LEGACY_HOLE_REPAIRED_BY_ASL": "LEGACY_HOLE_CHANGED_EPISODE",
    "LEGACY_ONLY": "LEGACY_HOLE_CHANGED_EPISODE",
    "PIT_ST_DATA_UPGRADE": "PIT_ST_CHANGED_EPISODE",
    "ST_COVERAGE_UNKNOWN": "ST_COVERAGE_UNKNOWN_EPISODE",
    "TRUSTED_ASL_NORMAL": "TRUSTED_ASL_NORMAL_EPISODE",
    "LEGACY_PRECLOSE_ERA_DIVERGENCE": "LEGACY_PRECLOSE_ERA_CHANGED_EPISODE",
}


def common_calendar_control(
    code: str,
    legacy_rows: Sequence[Mapping[str, Any]],
    asl_rows: Sequence[Mapping[str, Any]],
    config: Any,
) -> dict[str, Any]:
    """Non-vacuous engine-parity control.

    Takes only code-date rows present on BOTH backends, builds two series
    with the SAME calendar membership (legacy OHLCV/amount on one side, ASL
    on the other), rebuilds sequential preclose on that same common
    calendar, neutralizes is_st to the SAME value on both paths, requires
    trade_status equality, and runs the SAME production screen_code.

    Diagnostic only: this is not production data.
    """

    legacy_by = {row["trade_date"]: row for row in legacy_rows}
    asl_by = {row["trade_date"]: row for row in asl_rows}
    common = sorted(set(legacy_by) & set(asl_by))
    ts_conflicts: list[str] = []
    usable: list[date] = []
    for day in common:
        lt = bool(legacy_by[day].get("trade_status", True))
        at = bool(asl_by[day].get("trade_status", True))
        if lt != at:
            ts_conflicts.append(day.isoformat())
        else:
            usable.append(day)

    def series(by_date: Mapping[date, Mapping[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        prev_close: Decimal | None = None
        for day in usable:
            row = dict(by_date[day])
            if prev_close is not None:
                row["preclose"] = prev_close
            close = Decimal(str(row["close"]))
            if close > 0:
                prev_close = close
            # Neutralize ST to the SAME value on both control paths.
            row["is_st"] = legacy_by[day].get("is_st")
            out.append(row)
        return out

    legacy_ctl = series(legacy_by)
    asl_ctl = series(asl_by)
    if not legacy_ctl:
        return {
            "control_code_date_n": len(common),
            "equivalent_eval_point_n": 0,
            "mismatch_n": 0,
            "mismatches": [],
            "trade_status_conflict_dates": ts_conflicts,
        }
    legacy_items, _ = build_timeline(legacy_ctl, config, WINDOW_START, AS_OF)
    asl_items, _ = build_timeline(asl_ctl, config, WINDOW_START, AS_OF)
    legacy_sigs = {item.trade_date: strategy_signature(item) for item in legacy_items}
    asl_sigs = {item.trade_date: strategy_signature(item) for item in asl_items}
    eval_dates = sorted(set(legacy_sigs) | set(asl_sigs))
    mismatches = [
        {"date": day.isoformat()}
        for day in eval_dates
        if legacy_sigs.get(day) != asl_sigs.get(day)
    ]
    return {
        "control_code_date_n": len(common),
        "equivalent_eval_point_n": len(eval_dates) - len(mismatches),
        "mismatch_n": len(mismatches),
        "mismatches": mismatches[:20],
        "trade_status_conflict_dates": ts_conflicts,
    }


def _associated_class_at(
    per_date_class: Mapping[date, str],
    ordered: Sequence[date],
    target: date,
    window_bars: int = REQUIRED_HISTORY_BARS,
) -> str:
    """Associated class for the 250-bar window ending at *target*."""

    window = [day for day in ordered if day <= target][-window_bars:]
    has_volume = any(
        cls == "VOLUME_DIVERGENCE" for cls in per_date_class.values()
    )
    return _window_class(per_date_class, ordered, window, has_volume)


def process_code(
    code: str,
    legacy_rows: Sequence[Mapping[str, Any]],
    asl_rows: Sequence[Mapping[str, Any]],
    config: Any,
    ca_ex_dates: set[tuple[str, date]],
    case_dates: Sequence[date],
) -> dict[str, Any]:
    """Full per-code shadow comparison (main path + control + case sigs)."""

    result: dict[str, Any] = {"code": code}
    if not legacy_rows and not asl_rows:
        result["skip"] = "NO_BARS_EITHER_SIDE"
        return result
    if not legacy_rows:
        result["skip"] = "NO_LEGACY_BARS"
        return result
    if not asl_rows:
        result["skip"] = "NO_ASL_BARS"
        return result

    legacy_items, _ = build_timeline(legacy_rows, config, WINDOW_START, AS_OF)
    asl_items, _ = build_timeline(asl_rows, config, WINDOW_START, AS_OF)
    legacy_sigs = {
        item.trade_date: strategy_signature(item) for item in legacy_items
    }
    asl_sigs = {
        item.trade_date: strategy_signature(item) for item in asl_items
    }
    legacy_episodes = derive_episodes(legacy_items)
    asl_episodes = derive_episodes(asl_items)
    del legacy_items, asl_items
    gc.collect()
    eval_dates = sorted(set(legacy_sigs) | set(asl_sigs))

    input_info = classify_code_inputs(code, legacy_rows, asl_rows, ca_ex_dates)
    unknown_divergences = [
        {
            "code": code,
            "date": day.isoformat(),
            "detail": input_info["per_date_detail"].get(day, cls),
        }
        for day, cls in sorted(input_info["per_date_class"].items())
        if cls == "UNKNOWN_INPUT_DIVERGENCE"
    ]
    per_date_counts = {cls: 0 for cls in INPUT_CLASSES}
    for cls in input_info["per_date_class"].values():
        per_date_counts[cls] += 1
    all_history_dates = sorted(input_info["per_date_class"])
    point_classes, eval_windows = eval_point_classes(
        input_info["per_date_class"],
        all_history_dates,
        eval_dates,
    )

    equivalent_mismatches: list[dict[str, Any]] = []
    diverged_but_matching = 0
    diverged_and_mismatching = 0
    diverged_mismatch_by_class: dict[str, int] = {
        cls: 0 for cls in INPUT_CLASSES
    }
    first_result_divergence: dict[str, Any] | None = None
    associated_counts: dict[str, int] = {cls: 0 for cls in INPUT_CLASSES}
    equivalent_matching = 0
    for day in eval_dates:
        item_class = point_classes.get(day, "INPUT_EQUIVALENT")
        associated_counts[item_class] += 1
        legacy_sig = legacy_sigs.get(day)
        asl_sig = asl_sigs.get(day)
        if legacy_sig == asl_sig:
            if item_class == "INPUT_EQUIVALENT" and legacy_sig is not None:
                equivalent_matching += 1
            elif legacy_sig is not None or asl_sig is not None:
                diverged_but_matching += 1
            continue
        if item_class == "INPUT_EQUIVALENT":
            equivalent_mismatches.append(
                {
                    "date": day.isoformat(),
                    "legacy": legacy_sig,
                    "asl": asl_sig,
                }
            )
        else:
            diverged_and_mismatching += 1
            diverged_mismatch_by_class[item_class] += 1
            if first_result_divergence is None:
                first_result_divergence = {
                    "date": day.isoformat(),
                    "associated_input_class": item_class,
                    "legacy_stage": (
                        legacy_sig[0] if legacy_sig is not None else None
                    ),
                    "asl_stage": (
                        asl_sig[0] if asl_sig is not None else None
                    ),
                }

    # Volume divergence inertness proof (per row, against ALL eval windows).
    volume_rows: list[dict[str, Any]] = []
    volume_in_eval_window_n = 0
    for item in input_info["volume_divergences"]:
        row = dict(item)
        row_date = date.fromisoformat(item["date"])
        inside = any(
            row_date in window for window in eval_windows.values()
        )
        row["inside_any_eval_window"] = inside
        row["reason"] = (
            "inside a required strategy lookback -> HARD_FIELD_CONFLICT"
            if inside
            else (
                "all volume-divergence rows predate every eval-point window "
                "(250 bars); strategy-inert for every evaluation point"
            )
        )
        volume_rows.append(row)
        if inside:
            volume_in_eval_window_n += 1

    # Episode classification (setup_id keyed).
    legacy_ep_by_anchor = {ep["anchor_date"]: ep for ep in legacy_episodes}
    asl_ep_by_anchor = {ep["anchor_date"]: ep for ep in asl_episodes}
    episode_classes: dict[str, int] = {cls: 0 for cls in EPISODE_CLASSES}
    episode_details: list[dict[str, Any]] = []
    for anchor_date in sorted(
        set(legacy_ep_by_anchor) | set(asl_ep_by_anchor)
    ):
        legacy_ep = legacy_ep_by_anchor.get(anchor_date)
        asl_ep = asl_ep_by_anchor.get(anchor_date)
        if legacy_ep is not None and asl_ep is not None:
            if episode_signature(legacy_ep) == episode_signature(asl_ep):
                episode_classes["EXACT_EPISODE"] += 1
            else:
                start_date = min(
                    date.fromisoformat(legacy_ep["start_date"]),
                    date.fromisoformat(asl_ep["start_date"]),
                )
                cls = point_classes.get(start_date, "INPUT_EQUIVALENT")
                bucket = _EPISODE_BUCKET.get(
                    cls, "UNKNOWN_EPISODE_DIVERGENCE"
                )
                episode_classes[bucket] += 1
                episode_details.append(
                    {
                        "anchor_date": anchor_date,
                        "setup_ids": [legacy_ep["setup_id"], asl_ep["setup_id"]],
                        "start_date": start_date.isoformat(),
                        "associated_class": cls,
                        "bucket": bucket,
                    }
                )
        elif asl_ep is not None:
            episode_classes["ASL_NEW_VALID_EPISODE"] += 1
            start_date = date.fromisoformat(asl_ep["start_date"])
            cls = point_classes.get(start_date, "INPUT_EQUIVALENT")
            episode_details.append(
                {
                    "anchor_date": anchor_date,
                    "side": "ASL_ONLY",
                    "setup_id": asl_ep["setup_id"],
                    "start_date": asl_ep["start_date"],
                    "associated_class": cls,
                    "bucket": "ASL_NEW_VALID_EPISODE",
                }
            )
        else:
            episode_classes["LEGACY_ONLY_EPISODE"] += 1
            start_date = date.fromisoformat(legacy_ep["start_date"])
            cls = point_classes.get(start_date, "INPUT_EQUIVALENT")
            episode_details.append(
                {
                    "anchor_date": anchor_date,
                    "side": "LEGACY_ONLY",
                    "setup_id": legacy_ep["setup_id"],
                    "start_date": legacy_ep["start_date"],
                    "associated_class": cls,
                    "bucket": "LEGACY_ONLY_EPISODE",
                }
            )

    # Common-calendar control (non-vacuous engine test).
    control = common_calendar_control(code, legacy_rows, asl_rows, config)

    # Frozen success/control case signatures at candidate_date.
    case_signatures: dict[str, dict[str, Any]] = {}
    case_eval_classes: dict[str, str] = {}
    for day in case_dates:
        iso = day.isoformat()
        case_signatures[iso] = {
            "legacy": legacy_sigs.get(day),
            "asl": asl_sigs.get(day),
        }
        case_eval_classes[iso] = point_classes.get(day, "INPUT_EQUIVALENT")

    st_unknown_eval_dates = [
        day.isoformat()
        for day in eval_dates
        if point_classes.get(day) == "ST_COVERAGE_UNKNOWN"
    ]
    episode_st_unknown = any(
        ep["associated_class"] == "ST_COVERAGE_UNKNOWN"
        for ep in episode_details
    )
    case_st_unknown = any(
        case_eval_classes[iso] == "ST_COVERAGE_UNKNOWN"
        and case_signatures[iso]["legacy"] != case_signatures[iso]["asl"]
        for iso in case_signatures
    )

    result.update(
        {
            "eval_points": len(eval_dates),
            "associated_input_class_counts": associated_counts,
            "equivalent_mismatches": equivalent_mismatches,
            "equivalent_matching": equivalent_matching,
            "diverged_but_matching": diverged_but_matching,
            "diverged_and_mismatching": diverged_and_mismatching,
            "diverged_mismatch_by_class": diverged_mismatch_by_class,
            "first_result_divergence": first_result_divergence,
            "first_input_divergence": input_info["first_divergence"],
            "per_date_class_counts": per_date_counts,
            "hard_conflicts": input_info["hard_conflicts"],
            "unknown_divergences": unknown_divergences,
            "volume_divergences": volume_rows,
            "volume_in_eval_window_n": volume_in_eval_window_n,
            "st_class_counts": input_info["st_class_counts"],
            "legacy_only_code_dates": [
                d.isoformat() for d in input_info["legacy_only_code_dates"]
            ],
            "asl_only_code_dates": [
                d.isoformat() for d in input_info["asl_only_code_dates"]
            ],
            "episode_classes": episode_classes,
            "episode_details": episode_details,
            "legacy_episode_n": len(legacy_episodes),
            "asl_episode_n": len(asl_episodes),
            "control": control,
            "case_signatures": case_signatures,
            "case_eval_classes": case_eval_classes,
            "st_unknown_eval_dates": st_unknown_eval_dates,
            "episode_st_unknown": episode_st_unknown,
            "case_st_unknown": case_st_unknown,
            "final_legacy": legacy_sigs.get(AS_OF),
            "final_asl": asl_sigs.get(AS_OF),
            "associated_class_at_asof": point_classes.get(
                AS_OF, "INPUT_EQUIVALENT"
            ),
        }
    )
    return result


def _parse_missing_bar(exc: AslAdapterError) -> tuple[str, date] | None:
    """Parse ``MISSING_REQUIRED_BAR:<code>:<date>:...`` from an error."""

    parts = str(exc).split(":")
    if (
        len(parts) >= 3
        and parts[0] == "MISSING_REQUIRED_BAR"
        and len(parts[1]) == 6
    ):
        try:
            return parts[1], date.fromisoformat(parts[2])
        except ValueError:
            return None
    return None


def _load_code_truncated(
    asl_root: Path,
    code: str,
    start: date,
    as_of: date,
    legacy_rows: Sequence[Mapping[str, Any]],
    max_steps: int = 12,
) -> tuple[dict[str, list[dict[str, Any]]] | None, list[str], list[dict[str, Any]], dict[str, int]]:
    """Load ONE code's ASL facts; on a TRAILING MUTUAL absence, truncate the
    slice to the last mutually available session and keep the earlier history
    (the code is still evaluated).  Any other failure is returned as an
    error (fail-closed)."""

    hi = as_of
    coverage: dict[str, int] = {}
    explained: list[dict[str, Any]] = []
    for _step in range(max_steps):
        try:
            rows, cov = load_asl_facts(asl_root, [code], start, hi)
            for key, value in cov.items():
                coverage[key] = coverage.get(key, 0) + value
            return rows, [], explained, coverage
        except AslAdapterError as exc:
            parsed = _parse_missing_bar(exc)
            if parsed is None:
                return None, [f"{type(exc).__name__}: {exc}"], explained, coverage
            _code, session = parsed
            if _code != code:
                return None, [f"{type(exc).__name__}: {exc}"], explained, coverage
            legacy_has = any(
                row["trade_date"] == session for row in legacy_rows
            )
            legacy_after = any(
                row["trade_date"] > session for row in legacy_rows
            )
            if legacy_has or legacy_after:
                # Not a trailing mutual absence: either legacy has the row
                # (ASL missing data) or the gap is mid-series.  Fail closed.
                return (
                    None,
                    [f"{type(exc).__name__}: {exc}"],
                    explained,
                    coverage,
                )
            explained.append(
                {
                    "code": code,
                    "session": session.isoformat(),
                    "detail": (
                        "trailing mutual absence: legacy canonical also has "
                        "no CONFIRMED row at/after this session; ASL slice "
                        f"truncated to {hi.isoformat()} (last mutually "
                        "available session kept)"
                    ),
                }
            )
            hi = session - timedelta(days=1)
            if hi < start:
                return None, [], explained, coverage
            continue
    return (
        None,
        [f"truncation did not converge for {code}"],
        explained,
        coverage,
    )


def _load_asl_recursive(
    asl_root: Path,
    codes: Sequence[str],
    start: date,
    as_of: date,
    legacy: dict[str, list[dict[str, Any]]],
) -> tuple[
    dict[str, list[dict[str, Any]]] | None,
    list[str],
    list[dict[str, Any]],
    dict[str, int],
]:
    """Load ASL facts for *codes*; on AslAdapterError bisect to isolate the
    failing codes so healthy codes still get evaluated (fail-closed report).
    Single failing codes go through trailing-mutual-absence truncation."""

    try:
        rows, coverage = load_asl_facts(asl_root, codes, start, as_of)
        return rows, [], [], coverage
    except AslAdapterError:
        if len(codes) <= 1:
            code = codes[0]
            return _load_code_truncated(
                asl_root, code, start, as_of, legacy.get(code, [])
            )
        mid = len(codes) // 2
        left_rows, left_errs, left_expl, left_cov = _load_asl_recursive(
            asl_root, codes[:mid], start, as_of, legacy
        )
        right_rows, right_errs, right_expl, right_cov = _load_asl_recursive(
            asl_root, codes[mid:], start, as_of, legacy
        )
        rows: dict[str, list[dict[str, Any]]] = {}
        if left_rows:
            rows.update(left_rows)
        if right_rows:
            rows.update(right_rows)
        coverage = {}
        for key in set(left_cov) | set(right_cov):
            coverage[key] = left_cov.get(key, 0) + right_cov.get(key, 0)
        return (
            (rows if rows else None),
            left_errs + right_errs,
            left_expl + right_expl,
            coverage,
        )


def _worker(chunk: dict[str, Any]) -> dict[str, Any]:
    """Worker entry: load data for one code chunk and process each code."""

    config = load_strategy_config(chunk["config_path"])
    codes = chunk["codes"]
    legacy = load_legacy_canonical(
        Path(chunk["legacy_snapshot"]), set(codes), HISTORY_START, AS_OF
    )
    asl, data_errors, explained, coverage = _load_asl_recursive(
        Path(chunk["asl_root"]), codes, HISTORY_START, AS_OF, legacy
    )
    if asl is None:
        asl = {}
    ca_ex_dates = set()
    for item in chunk["ca_ex_dates"]:
        code, iso = item.split("|", 1)
        ca_ex_dates.add((code, date.fromisoformat(iso)))
    case_dates = {
        code: [date.fromisoformat(iso) for iso in dates]
        for code, dates in chunk.get("case_dates", {}).items()
    }
    results = []
    for code in codes:
        results.append(
            process_code(
                code,
                legacy.get(code, []),
                asl.get(code, []),
                config,
                ca_ex_dates,
                case_dates.get(code, []),
            )
        )
    return {
        "results": results,
        "data_errors": data_errors,
        "explained_absences": explained,
        "status_coverage": coverage,
    }


def load_ca_ex_dates(
    asl_root: Path, codes: set[str]
) -> set[tuple[str, date]]:
    """ASL corporate_actions (code, ex_date) pairs for the universe inside
    [HISTORY_START, AS_OF].  Symbol-aware: a CA on another stock on the same
    day can never explain this code's preclose difference."""

    ca_root = asl_root / "curated" / "corporate_actions"
    out: set[tuple[str, date]] = set()
    if not ca_root.exists():
        return out
    for path in sorted(ca_root.rglob("*.parquet")):
        table = pq.ParquetFile(path).read(
            columns=["symbol", "ex_date"]
        )
        for symbol, ex_date in zip(
            table.column("symbol").to_pylist(),
            table.column("ex_date").to_pylist(),
            strict=True,
        ):
            code = str(symbol).split(".")[0].zfill(6)
            if code not in codes or not isinstance(ex_date, date):
                continue
            if HISTORY_START <= ex_date <= AS_OF:
                out.add((code, ex_date))
    return out


def corporate_action_intersection(
    asl_root: Path,
    legacy_snapshot: Path,
    codes: set[str],
    config: Any,
    max_cases: int = 20,
) -> dict[str, Any]:
    """REAL ex-date intersection evidence.

    For every selected (code, ex_date) where ASL corporate_actions, the ASL
    daily bar AND a legacy CONFIRMED row all exist, compare the exact
    ex-date row: legacy OHLC/preclose/recomputed pct/limit-close vs ASL
    OHLC/preclose/recomputed pct/limit-close.  CA_MATCH_FOR_CODE_DATE=True
    is recorded per case.  Honest NOT_PROVEN when absent; ASL load failures
    are data blockers.
    """

    from limit_pullback.strategy.structure import is_limit_close

    ca_root = asl_root / "curated" / "corporate_actions"
    if not ca_root.exists():
        return {"status": "NO_CORPORATE_ACTIONS_DATASET"}
    ca_map: dict[tuple[str, date], list[tuple[str, str]]] = {}
    for path in sorted(ca_root.rglob("*.parquet")):
        table = pq.ParquetFile(path).read(
            columns=["symbol", "ex_date", "action_type", "cash_dividend"]
        )
        for symbol, ex_date, action_type, dividend in zip(
            table.column("symbol").to_pylist(),
            table.column("ex_date").to_pylist(),
            table.column("action_type").to_pylist(),
            table.column("cash_dividend").to_pylist(),
            strict=True,
        ):
            code = str(symbol).split(".")[0].zfill(6)
            if code not in codes or not isinstance(ex_date, date):
                continue
            if not (WINDOW_START <= ex_date <= AS_OF):
                continue
            ca_map.setdefault((code, ex_date), []).append(
                (str(action_type), str(dividend))
            )
    if not ca_map:
        return {
            "status": "REAL_EX_DATE_INTERSECTION_PARITY_NOT_PROVEN",
            "reason": "no ASL corporate-action ex-date inside the window",
        }
    candidate_codes = {item[0] for item in ca_map}
    legacy = load_legacy_canonical(
        legacy_snapshot, candidate_codes, WINDOW_START, AS_OF
    )
    legacy_by = {
        (code, row["trade_date"]): row
        for code, rows in legacy.items()
        for row in rows
    }
    cases: list[dict[str, Any]] = []
    data_errors: list[str] = []
    for (code, ex_date), actions in sorted(ca_map.items()):
        legacy_row = legacy_by.get((code, ex_date))
        if legacy_row is None:
            continue
        try:
            asl_rows, _cov = load_asl_facts(
                asl_root, [code], HISTORY_START, AS_OF
            )
        except AslAdapterError as exc:
            data_errors.append(
                f"CA intersection ASL load failed: {code}:{ex_date}: {exc}"
            )
            continue
        asl_by = {row["trade_date"]: row for row in asl_rows.get(code, [])}
        asl_row = asl_by.get(ex_date)
        if asl_row is None:
            continue
        legacy_pct = _frozen_pct(legacy_row)
        asl_pct = _frozen_pct(asl_row)
        legacy_limit = bool(is_limit_close(_to_bar(legacy_row), config))
        asl_limit = bool(is_limit_close(_to_bar(asl_row), config))
        cases.append(
            {
                "code": code,
                "ex_date": ex_date.isoformat(),
                "action_type": actions[0][0],
                "cash_dividend": actions[0][1],
                "CA_MATCH_FOR_CODE_DATE": True,
                "LEGACY": {
                    "open": str(legacy_row["open"]),
                    "high": str(legacy_row["high"]),
                    "low": str(legacy_row["low"]),
                    "close": str(legacy_row["close"]),
                    "preclose": str(legacy_row["preclose"]),
                    "pct": str(legacy_pct),
                    "limit_close": legacy_limit,
                },
                "ASL": {
                    "open": str(asl_row["open"]),
                    "high": str(asl_row["high"]),
                    "low": str(asl_row["low"]),
                    "close": str(asl_row["close"]),
                    "preclose": str(asl_row["preclose"]),
                    "pct": str(asl_pct),
                    "limit_close": asl_limit,
                },
                "preclose_exact": Decimal(str(legacy_row["preclose"]))
                == Decimal(str(asl_row["preclose"])),
                "pct_exact": legacy_pct == asl_pct,
                "limit_close_match": legacy_limit == asl_limit,
            }
        )
        if len(cases) >= max_cases:
            break
    if not cases:
        return {
            "status": "REAL_EX_DATE_INTERSECTION_PARITY_NOT_PROVEN",
            "reason": (
                "no window (code, ex_date) with legacy CONFIRMED row AND "
                "ASL bar"
            ),
        }
    return {
        "status": "INTERSECTION_FOUND",
        "case_count": len(cases),
        "cases": cases,
        "data_errors": data_errors,
    }


def read_success_control_cases(
    path: Path, universe: set[str]
) -> list[dict[str, Any]]:
    """Frozen v01b success/control cases with candidate_date inside the
    window (data cutoff 2026-07-31 as frozen)."""

    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            code = str(row["symbol"]).zfill(6)
            if code not in universe:
                continue
            try:
                candidate = date.fromisoformat(row["candidate_date"])
            except ValueError:
                continue
            if not (WINDOW_START <= candidate <= date(2026, 7, 31)):
                continue
            out.append(
                {
                    "code": code,
                    "candidate_date": candidate,
                    "candidate_state": row.get("candidate_state"),
                    "outcome": row.get("outcome"),
                }
            )
    return out


def aggregate_success_control(
    cases: Sequence[dict[str, Any]],
    result_by_code: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compare the ACTUAL strategy signature ON candidate_date (not the
    AS_OF final signature).  Outcomes are never relabeled."""

    rows: list[dict[str, Any]] = []
    inclusion_changed = 0
    anchor_changed = 0
    stage_changed = 0
    legacy_only_sig = 0
    asl_only_sig = 0
    for case in cases:
        result = result_by_code.get(case["code"])
        if result is None:
            continue
        iso = case["candidate_date"].isoformat()
        sigs = result.get("case_signatures", {}).get(iso)
        if sigs is None:
            continue
        legacy_sig = sigs.get("legacy")
        asl_sig = sigs.get("asl")
        cls = result.get("case_eval_classes", {}).get(
            iso, "INPUT_EQUIVALENT"
        )
        rows.append(
            {
                "code": case["code"],
                "candidate_date": iso,
                "frozen_state": case.get("candidate_state"),
                "frozen_outcome": case.get("outcome"),
                "legacy_sig": legacy_sig,
                "asl_sig": asl_sig,
                "associated_class": cls,
            }
        )
        if legacy_sig is not None and asl_sig is not None:
            legacy_actionable = legacy_sig[0] in ACTIONABLE_STAGES
            asl_actionable = asl_sig[0] in ACTIONABLE_STAGES
            if legacy_actionable != asl_actionable:
                inclusion_changed += 1
            if legacy_sig[1] != asl_sig[1]:
                anchor_changed += 1
            if legacy_sig[0] != asl_sig[0]:
                stage_changed += 1
        elif legacy_sig is not None:
            legacy_only_sig += 1
        elif asl_sig is not None:
            asl_only_sig += 1
    return {
        "frozen_case_n": len(cases),
        "compared_case_n": len(rows),
        "inclusion_changed_n": inclusion_changed,
        "anchor_changed_n": anchor_changed,
        "stage_changed_n": stage_changed,
        "legacy_only_sig_n": legacy_only_sig,
        "asl_only_sig_n": asl_only_sig,
        "note": (
            "signature compared AT candidate_date; frozen outcomes NOT "
            "relabeled; inclusion/anchor/stage only"
        ),
        "cases": rows,
    }


def _rebuild_sequential_preclose(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rebuild preclose = previous row's close over the given (already
    membership-filtered) series; the first row keeps its own preclose."""

    out: list[dict[str, Any]] = []
    prev_close: Decimal | None = None
    for row in rows:
        rebuilt = dict(row)
        if prev_close is not None:
            rebuilt["preclose"] = prev_close
        close = Decimal(str(row["close"]))
        if close > 0:
            prev_close = close
        out.append(rebuilt)
    return out


def _screen_final_sig(
    rows: Sequence[Mapping[str, Any]], config: Any
) -> tuple | None:
    items, _ = build_timeline(rows, config, WINDOW_START, AS_OF)
    sigs = {item.trade_date: strategy_signature(item) for item in items}
    return sigs.get(AS_OF)


def run_counterfactuals(
    code: str,
    legacy_rows: Sequence[Mapping[str, Any]],
    asl_rows: Sequence[Mapping[str, Any]],
    config: Any,
    ca_ex_dates: set[tuple[str, date]],
    legacy_final: tuple | None,
) -> dict[str, Any]:
    """Bounded counterfactual ablations for decision-relevant AS_OF codes.

    Each ablation reverts ONE documented input class to the legacy condition
    on the ASL series and re-runs the production screen.  The first ablation
    restoring the legacy final signature names the PROVEN_ROOT_CAUSE;
    otherwise PROVEN_ROOT_CAUSE = UNKNOWN (blocks Phase 1B).
    """

    if legacy_final == _screen_final_sig(asl_rows, config):
        # No decision difference at all: identical final signatures.
        return {
            "code": code,
            "associated_class_at_asof": "INPUT_EQUIVALENT",
            "proven_root_cause": "NO_DECISION_DIFFERENCE",
            "ablations": [],
        }
    legacy_by = {row["trade_date"]: row for row in legacy_rows}
    info = classify_code_inputs(code, legacy_rows, asl_rows, ca_ex_dates)
    per_date = info["per_date_class"]
    associated_at_asof = _associated_class_at(
        per_date, sorted(per_date), AS_OF
    )
    ca_era_dates = {
        day
        for day, cls in per_date.items()
        if cls == "LEGACY_PRECLOSE_ERA_DIVERGENCE"
    }
    has_hole = any(
        cls == "LEGACY_HOLE_REPAIRED_BY_ASL" for cls in per_date.values()
    )
    has_st_delta = any(
        cls
        in (
            "ST_COVERAGE_UNKNOWN",
            "PIT_ST_DATA_UPGRADE",
            "TRUSTED_ASL_NORMAL",
            "LEGACY_NON_PIT_TO_ASL_UNKNOWN",
        )
        for cls in per_date.values()
    )

    ablations: list[dict[str, Any]] = []
    restored: str | None = None

    def _decision_sig(sig: tuple | None) -> tuple | None:
        """Decision-relevant signature: stage / entry-candidate / anchor.
        Exact-score equality is recorded separately (value-level noise)."""

        if sig is None:
            return None
        return (sig[0], sig[7], sig[1], sig[2])

    legacy_decision = _decision_sig(legacy_final)

    def attempt(name: str, rows: Sequence[Mapping[str, Any]]) -> None:
        nonlocal restored
        sig = _screen_final_sig(rows, config)
        decision_ok = _decision_sig(sig) == legacy_decision
        exact_ok = sig == legacy_final
        ablations.append(
            {
                "ablation": name,
                "restored_legacy_final": decision_ok,
                "exact_signature_match": exact_ok,
                "final_stage": sig[0] if sig is not None else None,
                "final_entry_candidate": sig[7] if sig is not None else None,
                "final_anchor_date": sig[1] if sig is not None else None,
            }
        )
        if decision_ok and restored is None:
            restored = name

    if has_hole:
        masked = [row for row in asl_rows if row["trade_date"] in legacy_by]
        attempt("MASK_LEGACY_HOLE_ROWS", _rebuild_sequential_preclose(masked))
    if has_st_delta:
        neutral = [dict(row) for row in asl_rows]
        for row in neutral:
            legacy_row = legacy_by.get(row["trade_date"])
            if legacy_row is not None:
                row["is_st"] = legacy_row.get("is_st")
        attempt("NEUTRALIZE_STATUS_TO_LEGACY", neutral)
    if ca_era_dates:
        restored_pre = [dict(row) for row in asl_rows]
        for row in restored_pre:
            legacy_row = legacy_by.get(row["trade_date"])
            if (
                legacy_row is not None
                and row["trade_date"] in ca_era_dates
            ):
                row["preclose"] = legacy_row["preclose"]
        attempt("RESTORE_LEGACY_PRECLOSE_CA_ERA", restored_pre)

    # Last-resort diagnostic: substitute ALL legacy values on common rows.
    # Restores ONLY when the difference is a within-tolerance common-row
    # value delta (e.g. volume/amount representation), which is a PROVEN
    # (non-class) cause, not UNKNOWN.
    substituted = [dict(row) for row in asl_rows]
    for row in substituted:
        legacy_row = legacy_by.get(row["trade_date"])
        if legacy_row is not None:
            for field in (
                "open", "high", "low", "close", "preclose",
                "volume", "amount", "trade_status", "is_st",
            ):
                row[field] = legacy_row[field]
    attempt("SUBSTITUTE_LEGACY_VALUES_COMMON_ROWS", substituted)
    value_restored = any(
        a["ablation"] == "SUBSTITUTE_LEGACY_VALUES_COMMON_ROWS"
        and a["restored_legacy_final"]
        for a in ablations
    )
    if restored is None and value_restored:
        restored = "OTHER_PROVEN_CAUSE"
        value_note = (
            "only full legacy value substitution on common rows restored "
            "the legacy decision; difference is a within-tolerance common-row "
            "value delta (volume/amount representation), not an input class"
        )
    else:
        value_note = None

    decision_restored_not_exact = any(
        a["restored_legacy_final"] and not a["exact_signature_match"]
        for a in ablations
    )
    if decision_restored_not_exact:
        residual_note = (
            "decision fields (stage/entry/anchor) restored by an input-class "
            "ablation; residual score/flag delta comes from within-tolerance "
            "volume/amount value differences on common rows"
        )
    else:
        residual_note = None

    return {
        "code": code,
        "legacy_final_signature": legacy_final,
        "asl_final_signature": _screen_final_sig(asl_rows, config),
        "associated_class_at_asof": associated_at_asof,
        "proven_root_cause": restored if restored is not None else "UNKNOWN",
        "value_level_delta_note": value_note,
        "residual_score_delta_note": residual_note,
        "ablations": ablations,
    }


def _worker_cf(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    """Counterfactual pass: load rows for the affected codes only."""

    config = load_strategy_config(chunk["config_path"])
    codes = chunk["codes"]
    legacy = load_legacy_canonical(
        Path(chunk["legacy_snapshot"]), set(codes), HISTORY_START, AS_OF
    )
    asl, _errors, _explained, _coverage = _load_asl_recursive(
        Path(chunk["asl_root"]), codes, HISTORY_START, AS_OF, legacy
    )
    if asl is None:
        asl = {}
    ca_ex_dates = set()
    for item in chunk["ca_ex_dates"]:
        code, iso = item.split("|", 1)
        ca_ex_dates.add((code, date.fromisoformat(iso)))
    out = []
    for code in codes:
        out.append(
            run_counterfactuals(
                code,
                legacy.get(code, []),
                asl.get(code, []),
                config,
                ca_ex_dates,
                chunk["legacy_finals"].get(code),
            )
        )
    return out


def _screen_stats(side: dict[str, tuple]) -> dict[str, Any]:
    """Actionable-stage vs entry-candidate populations and a deterministic
    Top20 ranking of the entry-candidate population.

    Frozen deterministic shadow ranking: normalized_score DESC,
    setup_quality_score DESC, entry_quality_score DESC (None last), code ASC.
    """

    actionable = {
        code: sig
        for code, sig in side.items()
        if sig[0] in ACTIONABLE_STAGES
    }
    entry = {code: sig for code, sig in side.items() if sig[7] is True}
    stage_dist: dict[str, int] = {}
    for sig in actionable.values():
        stage_dist[sig[0]] = stage_dist.get(sig[0], 0) + 1

    def key(item: tuple[str, tuple]) -> tuple:
        code, sig = item
        entry_score = (
            float(sig[6]) if sig[6] is not None else float("-inf")
        )
        return (
            -float(sig[4]),
            -float(sig[5]),
            -entry_score,
            code,
        )

    ranked = sorted(entry.items(), key=key)
    return {
        "actionable_stage_n": len(actionable),
        "entry_candidate_n": len(entry),
        "stage_distribution": stage_dist,
        "top20_population": "is_entry_candidate == True",
        "top20_ranking": (
            "normalized_score DESC, setup_quality_score DESC, "
            "entry_quality_score DESC (None last), code ASC"
        ),
        "top20": [code for code, _sig in ranked[:20]],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-snapshot", required=True, type=Path)
    parser.add_argument("--asl-root", required=True, type=Path)
    parser.add_argument("--universe", required=True, type=Path)
    parser.add_argument("--config", default="config/strategy.yaml", type=Path)
    parser.add_argument("--workers", default=4, type=int)
    parser.add_argument(
        "--summary-out",
        default="research/asl_phase1b/shadow_summary.json",
        type=Path,
    )
    parser.add_argument(
        "--full-out",
        default="research/asl_phase1b/artifacts/shadow_full.json",
        type=Path,
    )
    args = parser.parse_args(argv)

    started = time.time()
    universe = json.loads(args.universe.read_text())
    members = universe["members"]
    frozen_n = universe["n"]
    frozen_hash = universe["hash"]
    config = load_strategy_config(args.config)

    ca_ex_dates = load_ca_ex_dates(args.asl_root, set(members))

    # Frozen success/control case map (candidate-date signatures).
    cases_path = Path("research/intraday/success_control_cases_v01b.csv")
    frozen_cases = read_success_control_cases(cases_path, set(members))
    case_map: dict[str, list[date]] = {}
    for case in frozen_cases:
        case_map.setdefault(case["code"], []).append(case["candidate_date"])
    case_map = {code: sorted(set(dates)) for code, dates in case_map.items()}

    chunk_size = 300
    chunks = [
        {
            "codes": members[index : index + chunk_size],
            "legacy_snapshot": str(args.legacy_snapshot),
            "asl_root": str(args.asl_root),
            "config_path": str(args.config),
            "ca_ex_dates": [
                f"{code}|{day.isoformat()}"
                for code, day in sorted(ca_ex_dates)
            ],
            "case_dates": {
                code: [day.isoformat() for day in dates]
                for code, dates in case_map.items()
                if code in set(members[index : index + chunk_size])
            },
        }
        for index in range(0, len(members), chunk_size)
    ]

    sampler = AggregateRssSampler(interval_seconds=2.0)
    sampler.start()
    all_results: list[dict[str, Any]] = []
    data_blocked: list[str] = []
    explained_absences: list[dict[str, Any]] = []
    status_coverage: dict[str, int] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for outcome in pool.map(_worker, chunks):
            data_blocked.extend(outcome.get("data_errors", []))
            explained_absences.extend(outcome.get("explained_absences", []))
            for key, value in outcome.get("status_coverage", {}).items():
                status_coverage[key] = status_coverage.get(key, 0) + value
            all_results.extend(outcome["results"])
    aggregate_peak_rss = sampler.stop()
    harness_wall_seconds = time.time() - started

    ca_intersection = corporate_action_intersection(
        args.asl_root, args.legacy_snapshot, set(members), config
    )
    data_blocked.extend(ca_intersection.get("data_errors", []))

    # Coverage contract: processed + skipped == frozen; skips are blocking.
    processed = [r for r in all_results if "skip" not in r]
    skipped = [r for r in all_results if "skip" in r]
    skipped_reasons: dict[str, list[str]] = {}
    for r in skipped:
        skipped_reasons.setdefault(r["skip"], []).append(r["code"])
    coverage_contract_ok = (
        len(processed) + len(skipped) == frozen_n
    ) and not skipped

    eval_points = 0
    associated_input_class_counts: dict[str, int] = {
        cls: 0 for cls in INPUT_CLASSES
    }
    per_date_class_counts: dict[str, int] = {cls: 0 for cls in INPUT_CLASSES}
    st_class_counts: dict[str, int] = {cls: 0 for cls in ST_CLASSES}
    equivalent_mismatches: list[dict[str, Any]] = []
    hard_conflicts: list[dict[str, Any]] = []
    unknown_divergences: list[dict[str, Any]] = []
    volume_rows: list[dict[str, Any]] = []
    volume_in_eval_window_n = 0
    legacy_only_code_dates: list[str] = []
    asl_only_code_dates: list[str] = []
    first_result_divergences: list[dict[str, Any]] = []
    first_input_divergences: list[dict[str, Any]] = []
    diverged_but_matching = 0
    diverged_and_mismatching = 0
    diverged_mismatch_by_class: dict[str, int] = {
        cls: 0 for cls in INPUT_CLASSES
    }
    control_equivalent_eval_point_n = 0
    control_strategy_mismatch_n = 0
    control_trade_status_conflict_dates: list[str] = []
    episode_classes: dict[str, int] = {cls: 0 for cls in EPISODE_CLASSES}
    screens: dict[str, dict[str, Any]] = {"LEGACY": {}, "ASL": {}}
    result_by_code: dict[str, dict[str, Any]] = {}
    for result in processed:
        result_by_code[result["code"]] = result
        eval_points += result["eval_points"]
        for cls, count in result["associated_input_class_counts"].items():
            associated_input_class_counts[cls] += count
        for cls, count in result.get("per_date_class_counts", {}).items():
            per_date_class_counts[cls] += count
        for cls, count in result.get("st_class_counts", {}).items():
            st_class_counts[cls] += count
        equivalent_mismatches.extend(result["equivalent_mismatches"])
        hard_conflicts.extend(result["hard_conflicts"])
        unknown_divergences.extend(result["unknown_divergences"])
        volume_rows.extend(result["volume_divergences"])
        volume_in_eval_window_n += result["volume_in_eval_window_n"]
        legacy_only_code_dates.extend(result["legacy_only_code_dates"])
        asl_only_code_dates.extend(result["asl_only_code_dates"])
        diverged_but_matching += result["diverged_but_matching"]
        diverged_and_mismatching += result["diverged_and_mismatching"]
        for cls, count in result["diverged_mismatch_by_class"].items():
            diverged_mismatch_by_class[cls] += count
        if result["first_result_divergence"] is not None:
            first_result_divergences.append(
                {"code": result["code"], **result["first_result_divergence"]}
            )
        if result["first_input_divergence"] is not None:
            first_input_divergences.append(
                {"code": result["code"], **result["first_input_divergence"]}
            )
        control = result["control"]
        control_equivalent_eval_point_n += control["equivalent_eval_point_n"]
        control_strategy_mismatch_n += control["mismatch_n"]
        control_trade_status_conflict_dates.extend(
            control["trade_status_conflict_dates"]
        )
        for cls, count in result["episode_classes"].items():
            episode_classes[cls] += count
        if result["final_legacy"] is not None:
            screens["LEGACY"][result["code"]] = result["final_legacy"]
        if result["final_asl"] is not None:
            screens["ASL"][result["code"]] = result["final_asl"]

    legacy_screen = _screen_stats(screens["LEGACY"])
    asl_screen = _screen_stats(screens["ASL"])
    top20_common = sorted(
        set(legacy_screen["top20"]) & set(asl_screen["top20"])
    )
    top20_exact_position = sum(
        1
        for left, right in zip(
            legacy_screen["top20"], asl_screen["top20"], strict=False
        )
        if left == right
    )
    legacy_actionable = {
        code for code, sig in screens["LEGACY"].items()
        if sig[0] in ACTIONABLE_STAGES
    }
    asl_actionable = {
        code for code, sig in screens["ASL"].items()
        if sig[0] in ACTIONABLE_STAGES
    }
    added_candidates = sorted(asl_actionable - legacy_actionable)
    removed_candidates = sorted(legacy_actionable - asl_actionable)

    # Decision-relevant codes for causal attribution: added/removed
    # actionable candidates + Top20 membership/position changes only
    # (codes in both Top20s at the same position have no decision change).
    legacy_rank = {code: index for index, code in enumerate(legacy_screen["top20"])}
    asl_rank = {code: index for index, code in enumerate(asl_screen["top20"])}
    top20_changed = sorted(
        (set(legacy_rank) ^ set(asl_rank))
        | {
            code
            for code in set(legacy_rank) & set(asl_rank)
            if legacy_rank[code] != asl_rank[code]
        }
    )
    affected_codes = sorted(
        set(added_candidates)
        | set(removed_candidates)
        | set(top20_changed)
    )

    # Bounded counterfactual ablations for affected codes only.
    counterfactuals: list[dict[str, Any]] = []
    if affected_codes:
        cf_chunks = [
            {
                "codes": affected_codes[index : index + 100],
                "legacy_snapshot": str(args.legacy_snapshot),
                "asl_root": str(args.asl_root),
                "config_path": str(args.config),
                "ca_ex_dates": [
                    f"{code}|{day.isoformat()}"
                    for code, day in sorted(ca_ex_dates)
                ],
                "legacy_finals": {
                    code: screens["LEGACY"].get(code) for code in affected_codes
                },
            }
            for index in range(0, len(affected_codes), 100)
        ]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for outcome in pool.map(_worker_cf, cf_chunks):
                counterfactuals.extend(outcome)
    as_of_root_cause_unknown = [
        cf for cf in counterfactuals if cf["proven_root_cause"] == "UNKNOWN"
    ]
    proven_root_cause_counts: dict[str, int] = {}
    for cf in counterfactuals:
        cause = cf["proven_root_cause"]
        proven_root_cause_counts[cause] = proven_root_cause_counts.get(cause, 0) + 1

    # Decision-relevant ST_COVERAGE_UNKNOWN (fix 9): ST unknown associated
    # with AS_OF decision, episode, or success/control differences.
    decision_relevant_st_unknown: list[str] = []
    for code, result in result_by_code.items():
        has_st_unknown = bool(result["st_unknown_eval_dates"])
        if not has_st_unknown:
            continue
        in_asof_decision = (
            code in set(affected_codes)
            and result["associated_class_at_asof"] == "ST_COVERAGE_UNKNOWN"
        )
        if (
            in_asof_decision
            or result["episode_st_unknown"]
            or result["case_st_unknown"]
        ):
            decision_relevant_st_unknown.append(code)
    decision_relevant_st_unknown.sort()

    # Success/control cases at candidate_date.
    success_control = aggregate_success_control(frozen_cases, result_by_code)

    unknown_input_divergence_n = per_date_class_counts[
        "UNKNOWN_INPUT_DIVERGENCE"
    ]
    hard_field_conflict_n = len(hard_conflicts) + volume_in_eval_window_n
    strategy_engine_parity_failures_n = len(equivalent_mismatches)
    unknown_episode_divergence_n = episode_classes[
        "UNKNOWN_EPISODE_DIVERGENCE"
    ]
    as_of_root_cause_unknown_n = len(as_of_root_cause_unknown)
    decision_relevant_st_unknown_n = len(decision_relevant_st_unknown)

    # Resource gate (aggregate RSS; NOT_MEASURED cannot pass).
    ram_mb = (
        os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    )
    budget_mb = min(4 * 1024, int(ram_mb * 0.25))
    if aggregate_peak_rss is None:
        aggregate_peak_rss_mb = "NOT_MEASURED"
        resource_ok = False
    else:
        aggregate_peak_rss_mb = round(aggregate_peak_rss)
        resource_ok = aggregate_peak_rss_mb <= budget_mb

    data_blocked_final = bool(data_blocked) or bool(skipped)
    if not coverage_contract_ok:
        data_blocked_final = True

    phase1b_gate = compute_phase1b_gate(
        data_blocked=data_blocked_final,
        resource_ok=resource_ok,
        hard_field_conflict_n=hard_field_conflict_n,
        unknown_input_divergence_n=unknown_input_divergence_n,
        strategy_engine_parity_failures_n=strategy_engine_parity_failures_n,
        control_equivalent_eval_point_n=control_equivalent_eval_point_n,
        control_strategy_mismatch_n=control_strategy_mismatch_n,
        unknown_episode_divergence_n=unknown_episode_divergence_n,
        as_of_root_cause_unknown_n=as_of_root_cause_unknown_n,
        decision_relevant_st_unknown_n=decision_relevant_st_unknown_n,
    )

    summary = {
        "contract": "VFLASH_ASL_PHASE1B_SHADOW_SUMMARY_V2",
        "phase1b_gate": phase1b_gate,
        "gate_components": {
            "data_blocked": data_blocked_final,
            "resource_ok": resource_ok,
            "hard_field_conflict_n": hard_field_conflict_n,
            "unknown_input_divergence_n": unknown_input_divergence_n,
            "strategy_engine_parity_failures_n": strategy_engine_parity_failures_n,
            "control_equivalent_eval_point_n": control_equivalent_eval_point_n,
            "control_strategy_mismatch_n": control_strategy_mismatch_n,
            "unknown_episode_divergence_n": unknown_episode_divergence_n,
            "as_of_root_cause_unknown_n": as_of_root_cause_unknown_n,
            "decision_relevant_st_unknown_n": decision_relevant_st_unknown_n,
        },
        "as_of": AS_OF.isoformat(),
        "window": {
            "comparison": {
                "start": WINDOW_START.isoformat(),
                "end": AS_OF.isoformat(),
            },
            "history_start": HISTORY_START.isoformat(),
            "required_history_bars": REQUIRED_HISTORY_BARS,
            "extension_reason": (
                "MA250 (moving_average_windows) plus position window 120 and "
                "resistance lookbacks 60 require >=250 trading bars of "
                "history; legacy canonical coverage starts 2024-01-02, so "
                "the ASL shadow lake was backfilled from 2024-01-02"
            ),
        },
        "frozen_universe": {
            "n": frozen_n,
            "hash": frozen_hash,
        },
        "asl_build": {
            "tested_compat_revision": "ba5681a",
            "commands": [
                "asl backfill instruments --config shadow.toml",
                "asl backfill trading_calendar --config shadow.toml --start 2024-01-02 --end 2026-08-06",
                "asl backfill daily_bars --config shadow.toml --start 2024-01-02 --end 2026-08-06",
                "asl backfill trading_status --config shadow.toml",
                "asl derive trading_status --config shadow.toml --start 2024-01-02 --end 2026-08-06",
                "asl backfill corporate_actions --config shadow.toml --start 2026-04-01 --end 2026-08-06",
            ],
            "manual_asl_data_edits": 0,
            "data_reused": True,
            "data_reuse_note": (
                "no lake rebuild in review-fix round 1; existing Phase-1B "
                "lake reused read-only"
            ),
        },
        "resource_usage": {
            "aggregate_peak_rss_mb": aggregate_peak_rss_mb,
            "measurement": (
                "psutil parent + live children RSS sum, max over samples"
            ),
            "budget_mb": budget_mb,
            "resource_ok": resource_ok,
            "harness_wall_seconds": round(harness_wall_seconds, 1),
            "workers": args.workers,
        },
        "coverage": {
            "frozen_universe_n": frozen_n,
            "processed_code_n": len(processed),
            "skipped_code_n": len(skipped),
            "skipped_code_reasons": skipped_reasons,
            "asl_code_covered_n": len(processed),
            "coverage_contract_ok": coverage_contract_ok,
            "eval_points": eval_points,
            "legacy_only_code_date_n": len(legacy_only_code_dates),
            "legacy_only_codes_n": len(set(legacy_only_code_dates)),
            "asl_only_code_date_n": len(asl_only_code_dates),
            "asl_only_codes_n": len(set(asl_only_code_dates)),
            "hard_field_conflict_n": hard_field_conflict_n,
            "hard_field_conflicts": hard_conflicts[:50],
            "unknown_input_divergence_rows": unknown_divergences[:50],
            "volume_divergence_rows_n": len(volume_rows),
            "volume_in_eval_window_n": volume_in_eval_window_n,
            "volume_outside_eval_history_n": sum(
                1 for row in volume_rows if not row["inside_any_eval_window"]
            ),
            "volume_divergences": volume_rows,
            "explained_mutual_terminal_absences_n": len(explained_absences),
            "explained_mutual_terminal_absences": explained_absences,
        },
        "per_date_class_counts": per_date_class_counts,
        "associated_input_class_counts": associated_input_class_counts,
        "st_coverage": {
            "st_class_counts": st_class_counts,
            "trusted_asl_st_n": st_class_counts["TRUSTED_ASL_ST"],
            "trusted_asl_normal_n": st_class_counts["TRUSTED_ASL_NORMAL"],
            "st_coverage_unknown_n": st_class_counts["ST_COVERAGE_UNKNOWN"],
            "legacy_non_pit_to_asl_unknown_n": st_class_counts[
                "LEGACY_NON_PIT_TO_ASL_UNKNOWN"
            ],
            "decision_relevant_st_unknown_n": decision_relevant_st_unknown_n,
            "decision_relevant_st_unknown_codes": decision_relevant_st_unknown,
            "note": (
                "ST semantic delta is NOT exact parity; a true PIT upgrade "
                "requires trusted ASL provenance (asl_status_trust)"
            ),
        },
        "status_provenance": status_coverage,
        "input_classification_note": (
            "per-date classes are exhaustive and mutually exclusive; "
            "UNKNOWN_INPUT_DIVERGENCE is reachable (e.g. unproven preclose "
            "divergence without code-specific corporate-action evidence). "
            "Eval-point classes are ASSOCIATED_INPUT_CLASS (window-based), "
            "NOT proven root cause; proven root cause is only claimed for "
            "decision-relevant AS_OF differences via counterfactual ablation."
        ),
        "input_equivalence_note": (
            "INPUT_EQUIVALENT eval points are structurally rare: the legacy "
            "canonical has ~6% CONFIRMED-session holes, so most 250-bar "
            "strategy lookback windows contain at least one legacy hole. "
            "Engine parity is therefore proven by the non-vacuous "
            "COMMON-CALENDAR CONTROL (control_equivalent_eval_point_n > 0 "
            "with zero control mismatches), not by vacuous window counts."
        ),
        "strategy": {
            "strategy_engine_parity_failures_n": strategy_engine_parity_failures_n,
            "control_equivalent_eval_point_n": control_equivalent_eval_point_n,
            "control_strategy_mismatch_n": control_strategy_mismatch_n,
            "control_trade_status_conflict_dates": (
                control_trade_status_conflict_dates[:20]
            ),
            "unknown_input_divergence_n": unknown_input_divergence_n,
            "unknown_episode_divergence_n": unknown_episode_divergence_n,
            "diverged_but_matching_n": diverged_but_matching,
            "diverged_and_mismatching_n": diverged_and_mismatching,
            "diverged_mismatch_by_associated_class": (
                diverged_mismatch_by_class
            ),
            "episode_classes": episode_classes,
            "first_result_divergence_n": len(first_result_divergences),
            "first_input_divergence_n": len(first_input_divergences),
        },
        "screen_20260806": {
            "legacy": legacy_screen,
            "asl": asl_screen,
            "TOP20_EXACT_POSITION_N": top20_exact_position,
            "TOP20_COMMON_N": len(top20_common),
            "LEGACY_ONLY_TOP20": [
                code for code in legacy_screen["top20"]
                if code not in asl_screen["top20"]
            ],
            "ASL_ONLY_TOP20": [
                code for code in asl_screen["top20"]
                if code not in legacy_screen["top20"]
            ],
            "added_candidates_n": len(added_candidates),
            "removed_candidates_n": len(removed_candidates),
            "added_candidates": added_candidates,
            "removed_candidates": removed_candidates,
            "population_note": (
                "ACTIONABLE_STAGE_N = stage-only set (B1_READY/B2_READY/"
                "B2_CONFIRMED); ENTRY_CANDIDATE_N = is_entry_candidate==True; "
                "Top20 ranks the entry-candidate population only"
            ),
        },
        "as_of_causal_attribution": {
            "affected_codes_n": len(affected_codes),
            "affected_codes": affected_codes,
            "proven_root_cause_counts": proven_root_cause_counts,
            "unknown_root_cause_n": as_of_root_cause_unknown_n,
            "unknown_root_cause_codes": [
                cf["code"] for cf in as_of_root_cause_unknown
            ],
            "note": (
                "ASSOCIATED_INPUT_CLASS is window-based; PROVEN_ROOT_CAUSE "
                "is counterfactual-ablated for affected AS_OF codes only"
            ),
        },
        "success_control_cases": {
            key: value
            for key, value in success_control.items()
            if key != "cases"
        },
        "corporate_action_intersection": {
            key: value
            for key, value in ca_intersection.items()
            if key != "cases"
        },
        "data_blocked": data_blocked[:50],
    }
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    args.summary_out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    args.full_out.parent.mkdir(parents=True, exist_ok=True)
    args.full_out.write_text(
        json.dumps(
            {
                "summary": summary,
                "first_input_divergences": first_input_divergences,
                "first_result_divergences": first_result_divergences,
                "equivalent_mismatches": equivalent_mismatches,
                "hard_conflicts": hard_conflicts,
                "unknown_input_divergences": unknown_divergences,
                "success_control_cases": success_control.get("cases", []),
                "corporate_action_intersection": ca_intersection,
                "counterfactuals": counterfactuals,
                "explained_mutual_absences": explained_absences,
                "skipped_codes": skipped,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return exit_code_for_gate(phase1b_gate)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
