"""Minimal R9 prospective intraday observation accumulator.

Records exactly one intraday primary observation per eligible Gate 2A setup
on its candidate event session, under the frozen R9 protocol contract.  It
reuses ``r9_protocol_v02``, ``r9_ttl_event_eligibility_v01``, and the existing
R8A intraday contract; it never redefines a formula, threshold, checkpoint,
or FIRST_S1_TOUCH semantics, and it never reads minute data from disk.

The caller supplies an immutable setup-ledger row / parsed setup authority
(including the Gate 2A first-observation stage, which the frozen setup-ledger
schema does not carry) plus an already-validated right-labeled 5m session and
its provenance manifest.  Real publication is exercised only by synthetic
tests.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import r9_protocol_v02 as protocol
import r9_ttl_event_eligibility_v01 as ttl
from r9_asl_pit_data_adapter_v01 import _candidate_code
from r8a_intraday_contract_v01 import (
    acceptance_window_bars,
    breakout_hold_ratio,
    completed_bars_through,
    false_break_duration,
    first_s1_touch_bar,
    retest_depth,
    vwap_acceptance_ratio,
    vwap_of,
)

PRIMARY_CHECKPOINT = protocol.R9_PRIMARY_CHECKPOINT
FEATURE_OBSERVABLE = "FEATURE_OBSERVABLE"


class IntradayAccumulatorBlocked(protocol.ProtocolBlocked):
    """A frozen intraday contract is missing or has been violated."""


def _canonical_clock(value: str | datetime | time) -> str:
    return protocol.canonical_clock(value)


def _canonical_manifest(value: object) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise IntradayAccumulatorBlocked(
            "minute_manifest_hash must be a sha256 hex digest"
        )
    return digest


def _decimal(value: object, *, field: str) -> Decimal:
    if value is None:
        raise IntradayAccumulatorBlocked(f"missing {field}")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise IntradayAccumulatorBlocked(f"invalid {field}") from exc
    if not parsed.is_finite():
        raise IntradayAccumulatorBlocked(f"non-finite {field}")
    return parsed


def _serialize_value(value: object) -> str:
    """Frozen CSV convention shared with r9_setup_accumulator_v01."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _row_sort_key(row: Mapping[str, object]) -> tuple[str, str]:
    return str(row["event_id"]), str(row["setup_id"])


# ---------------------------------------------------------------------------
# Setup authority (parsed immutable setup-ledger row plus S1 reconciliation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntradaySetupAuthority:
    """The immutable daily-side authority an intraday observation attaches to.

    ``s1_price`` is supplied by the caller's exact daily/minute reconciliation
    authority; it is never re-derived from minute bars here.
    """

    setup_id: str
    symbol: str
    t0_date: date
    candidate_date: date
    ttl_end_date: date
    first_observation_stage: str
    intraday_primary_eligible: bool
    intraday_ineligible_reason: str | None
    event_search_start: date | None
    event_search_end: date | None
    s1_price: Decimal | str
    price_tick: Decimal | str
    minute_s1_price: Decimal | str | None = None


# ---------------------------------------------------------------------------
# Minute session input gate
# ---------------------------------------------------------------------------


def _bar_records(
    minute_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in minute_rows:
        try:
            bar_time = _canonical_clock(str(row["bar_time"]))
        except KeyError as exc:
            raise IntradayAccumulatorBlocked(
                "minute row missing bar_time"
            ) from exc
        for field in ("symbol", "trade_date", "open", "high", "low", "close",
                      "volume", "amount"):
            if field not in row:
                raise IntradayAccumulatorBlocked(
                    f"minute row missing {field}"
                )
        records.append({
            "symbol": str(row["symbol"]),
            "trade_date": row["trade_date"],
            "bar_time": bar_time,
            # R8A formulas operate on numeric float series; prices are
            # validated for finite decimals before conversion.
            "open": float(_decimal(row["open"], field="open")),
            "high": float(_decimal(row["high"], field="high")),
            "low": float(_decimal(row["low"], field="low")),
            "close": float(_decimal(row["close"], field="close")),
            "volume": float(_decimal(row["volume"], field="volume")),
            "amount": float(_decimal(row["amount"], field="amount")),
        })
    return records


def minute_manifest_hash(manifest: Mapping[str, Any]) -> str:
    """Deterministic canonical hash of the validated minute provenance."""
    return hashlib.sha256(
        json.dumps(
            {key: manifest[key] for key in sorted(manifest)},
            ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validate_minute_session(
    *,
    minute_rows: Sequence[Mapping[str, Any]],
    minute_manifest: Mapping[str, Any],
    right_label_verified: bool,
    event_date: date,
) -> tuple[tuple[dict[str, Any], ...], str]:
    """Frozen minute provenance + ingestion gates; returns (records, manifest_hash)."""
    protocol.validate_minute_manifest(minute_manifest)
    protocol.validate_minute_ingestion(
        minute_rows, right_label_verified=right_label_verified
    )
    if not right_label_verified:
        raise IntradayAccumulatorBlocked("right-label fixture not verified")
    records = tuple(_bar_records(minute_rows))
    dates = {r["trade_date"] for r in records}
    if len(dates) != 1 or date.fromisoformat(str(next(iter(dates)))) != event_date:
        raise IntradayAccumulatorBlocked(
            "minute session trade_date does not match event_date"
        )
    return records, minute_manifest_hash(minute_manifest)


# ---------------------------------------------------------------------------
# R8A feature reuse (no formula redefinition)
# ---------------------------------------------------------------------------


def _to_frame(records: tuple[dict[str, Any], ...]):
    import pandas as pd
    frame = pd.DataFrame(list(records))
    # R8A contract consumes the right-labeled bar clock under ``bar_end``.
    return frame.rename(columns={"bar_time": "bar_end"})


# ---------------------------------------------------------------------------
# Public accumulation entry point
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntradayAccumulationResult:
    """One setup's intraday outcome: a single immutable ledger row or a refusal."""

    row: dict[str, str | None] | None
    status: str
    event_id: str | None
    feature_hash: str | None


def _eligibility_from_authority(
    authority: IntradaySetupAuthority,
    calendar: ttl.FrozenAshareTradingCalendar,
) -> ttl.FirstObservationEligibility:
    eligibility = ttl.first_observation_eligibility(
        setup_id=authority.setup_id,
        anchor_date=authority.t0_date,
        candidate_date=authority.candidate_date,
        first_observation_stage=authority.first_observation_stage,
        calendar=calendar,
    )
    if eligibility.ttl_end_date != authority.ttl_end_date:
        raise IntradayAccumulatorBlocked(
            "setup authority ttl_end_date drift vs frozen eligibility"
        )
    if (
        eligibility.intraday_primary_eligible
        != authority.intraday_primary_eligible
    ):
        raise IntradayAccumulatorBlocked(
            "setup authority intraday eligibility drift vs frozen eligibility"
        )
    if (
        eligibility.intraday_ineligible_reason
        != authority.intraday_ineligible_reason
    ):
        raise IntradayAccumulatorBlocked(
            "setup authority intraday ineligible reason drift"
        )
    return eligibility


def accumulate_intraday_observation(
    *,
    authority: IntradaySetupAuthority,
    minute_rows: Sequence[Mapping[str, Any]],
    minute_manifest: Mapping[str, Any],
    right_label_verified: bool,
    event_date: date,
    existing_events: Mapping[str, ttl.FirstS1TouchEvent],
    existing_feature_hashes: Mapping[tuple[str, str, str], str],
    calendar: ttl.FrozenAshareTradingCalendar,
    structural_invalidation_date: date | None = None,
) -> IntradayAccumulationResult:
    """Record exactly one intraday primary observation under frozen gates."""

    if not authority.intraday_primary_eligible:
        return IntradayAccumulationResult(
            row=None,
            status=f"INELIGIBLE_{authority.intraday_ineligible_reason or 'UNSPECIFIED'}",
            event_id=None,
            feature_hash=None,
        )
    records, manifest_hash = _validate_minute_session(
        minute_rows=minute_rows,
        minute_manifest=minute_manifest,
        right_label_verified=right_label_verified,
        event_date=event_date,
    )
    s1 = _decimal(authority.s1_price, field="s1_price")
    tick = _decimal(authority.price_tick, field="price_tick")

    # Exact daily/minute S1 + tick reconciliation, inside the accumulator
    # (frozen contract; never a test-side helper substitute).
    minute_symbols = {str(r["symbol"]) for r in records}
    if len(minute_symbols) != 1:
        raise IntradayAccumulatorBlocked(
            "unique minute session symbol N must be 1"
        )
    minute_symbol = next(iter(minute_symbols))
    minute_dates = {r["trade_date"] for r in records}
    if len(minute_dates) != 1:
        raise IntradayAccumulatorBlocked(
            "unique minute session trade_date must be 1"
        )
    minute_trade_date = next(iter(minute_dates))
    if authority.minute_s1_price is None:
        raise IntradayAccumulatorBlocked(
            "STATUS=BLOCKED_PRICE_RECONCILIATION: "
            "independent minute_s1_price authority is required"
        )
    minute_s1 = _decimal(authority.minute_s1_price, field="minute_s1_price")
    protocol.validate_exact_tick_reconciliation({
        "daily_symbol": _candidate_code(authority.symbol),
        "minute_symbol": _candidate_code(minute_symbol),
        "daily_trade_date": event_date.isoformat(),
        "minute_trade_date": str(minute_trade_date),
        "daily_s1_price": str(s1),
        "minute_s1_price": str(minute_s1),
        "price_tick": str(tick),
    })

    eligibility = _eligibility_from_authority(authority, calendar)

    # FIRST_S1_TOUCH is located on the FULL right-labeled session; the
    # feature view is strictly the primary checkpoint window.
    full_frame = _to_frame(records)
    touch = first_s1_touch_bar(full_frame, float(s1))
    if touch is None:
        return IntradayAccumulationResult(
            row=None, status="NO_S1_TOUCH", event_id=None, feature_hash=None,
        )
    touch_time = _canonical_clock(str(touch["bar_end"]))
    primary_view = completed_bars_through(full_frame, PRIMARY_CHECKPOINT)
    primary_view_ids = list(primary_view["bar_end"])

    if touch_time > PRIMARY_CHECKPOINT:
        # Late touch: event exists but is not observable at the primary
        # checkpoint; no 10:35+ bar may enter any feature.
        primary_anchor_idx = None
        post_activation_bar_n = 0
    else:
        if touch["bar_end"] not in primary_view_ids:
            raise IntradayAccumulatorBlocked(
                "touch <= 10:30 must exist inside primary view"
            )
        primary_anchor_idx = primary_view_ids.index(touch["bar_end"])
        primary_post_window = primary_view.iloc[primary_anchor_idx + 1:]
        post_activation_bar_n = int(len(primary_post_window))

    # Frozen Gate 2B event registration (never a reconfirmation).  A frozen
    # refusal (out-of-window, TTL, structural invalidation, repeat drift) is
    # translated to a no-row result; the rejection is never bypassed.
    try:
        event = ttl.register_first_eligible_s1_touch(
            existing=existing_events,
            eligibility=eligibility,
            calendar=calendar,
            event_date=event_date,
            first_touch_time=touch_time,
            post_activation_bar_n=post_activation_bar_n,
            right_labeled_grid_verified=True,
            structural_invalidation_date=structural_invalidation_date,
        )
    except ttl.Gate2BBlocked as exc:
        return IntradayAccumulationResult(
            row=None,
            status=f"EVENT_REJECTED_{exc}",
            event_id=None,
            feature_hash=None,
        )
    status = protocol.intraday_observation_status(
        touch_time, post_activation_bar_n
    )

    if status == FEATURE_OBSERVABLE:
        # Session VWAP through the primary checkpoint (R8B semantics):
        # sum(PRIMARY_VIEW.amount) / sum(PRIMARY_VIEW.volume), never a
        # post-touch-window-only VWAP.
        session_vwap_1030 = vwap_of(
            primary_view["amount"].to_numpy(),
            primary_view["volume"].to_numpy(),
        )
        features = {
            "breakout_hold_ratio": Decimal(str(
                breakout_hold_ratio(primary_post_window, float(s1)))),
            "retest_depth": Decimal(str(
                retest_depth(primary_post_window, float(s1)))),
            "false_break_duration": Decimal(str(
                false_break_duration(primary_post_window, float(s1)))),
            "vwap_acceptance_ratio": Decimal(str(
                vwap_acceptance_ratio(primary_post_window, session_vwap_1030))),
        }
        reference_price = Decimal(str(primary_view.iloc[-1]["close"]))
    else:
        # Non-observable statuses never fabricate zeros; frozen CSV convention
        # serializes None as an empty field (shared with setup accumulator).
        features = {
            "breakout_hold_ratio": None,
            "retest_depth": None,
            "false_break_duration": None,
            "vwap_acceptance_ratio": None,
        }
        reference_price = None

    payload = {
        "setup_id": authority.setup_id,
        "event_id": event.event_id,
        "checkpoint": PRIMARY_CHECKPOINT,
        "minute_manifest_hash": manifest_hash,
        "intraday_primary_feature_status": status,
        **{key: (None if value is None else str(value))
           for key, value in features.items()},
        "reference_price_10_30": (
            None if reference_price is None else str(reference_price)
        ),
    }
    feature_hash = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    append_status = protocol.assert_append_only_feature(
        existing_hashes=existing_feature_hashes,
        setup_id=authority.setup_id,
        event_id=event.event_id,
        checkpoint=PRIMARY_CHECKPOINT,
        feature_hash=feature_hash,
    )

    if append_status != "APPEND":
        # ALREADY_RECORDED never emits a new row (mirrors the setup
        # accumulator: status != APPEND -> no new row).
        return IntradayAccumulationResult(
            row=None, status=append_status, event_id=event.event_id,
            feature_hash=feature_hash,
        )

    row: dict[str, str | None] = {
        "event_id": event.event_id,
        "setup_id": authority.setup_id,
        "event_date": event_date.isoformat(),
        "checkpoint": PRIMARY_CHECKPOINT,
        "activation_time": event.first_touch_time,
        "post_activation_bar_n": str(post_activation_bar_n),
        "intraday_primary_feature_status": status,
        "breakout_hold_ratio": (
            None if features["breakout_hold_ratio"] is None
            else str(features["breakout_hold_ratio"])
        ),
        "retest_depth": (
            None if features["retest_depth"] is None
            else str(features["retest_depth"])
        ),
        "false_break_duration": (
            None if features["false_break_duration"] is None
            else str(features["false_break_duration"])
        ),
        "vwap_acceptance_ratio": (
            None if features["vwap_acceptance_ratio"] is None
            else str(features["vwap_acceptance_ratio"])
        ),
        "reference_price_10_30": (
            None if reference_price is None else str(reference_price)
        ),
        "minute_manifest_hash": manifest_hash,
        "feature_hash": feature_hash,
    }
    return IntradayAccumulationResult(
        row=row, status=append_status, event_id=event.event_id,
        feature_hash=feature_hash,
    )


# ---------------------------------------------------------------------------
# Deterministic serialization + artifact validation + atomic publication
# ---------------------------------------------------------------------------


def serialize_intraday_ledger_rows(
    rows: Sequence[Mapping[str, object]],
) -> bytes:
    """Serialize rows with the exact frozen intraday header and stable bytes."""
    fieldnames = tuple(protocol.INTRADAY_LEDGER_COLUMNS)
    normalized_rows = sorted(rows, key=_row_sort_key)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for row in normalized_rows:
        if set(row) != set(fieldnames):
            raise IntradayAccumulatorBlocked("intraday ledger schema mismatch")
        writer.writerow({
            field: _serialize_value(row[field])
            for field in fieldnames
        })
    return output.getvalue().encode("utf-8")


def validate_intraday_ledger_artifact(path: Path) -> None:
    """Validate the temporary artifact before atomic publication."""
    try:
        payload = path.read_bytes()
        if not payload.endswith(b"\n"):
            raise IntradayAccumulatorBlocked(
                "intraday ledger must end with a newline"
            )
        rows = list(csv.reader(payload.decode("utf-8").splitlines()))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise IntradayAccumulatorBlocked(
            "intraday ledger artifact is unreadable"
        ) from exc
    if not rows or rows[0] != list(protocol.INTRADAY_LEDGER_COLUMNS):
        raise IntradayAccumulatorBlocked("intraday ledger header mismatch")
    expected_width = len(protocol.INTRADAY_LEDGER_COLUMNS)
    seen: set[str] = set()
    for row in rows[1:]:
        if len(row) != expected_width:
            raise IntradayAccumulatorBlocked("intraday ledger row schema mismatch")
        identity = row[0]
        if identity in seen:
            raise IntradayAccumulatorBlocked("duplicate intraday event identity")
        seen.add(identity)


def publish_intraday_ledger(
    destination: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    protocol_repo_root: Path = protocol.REPO_ROOT,
) -> str:
    """Publish one immutable versioned artifact through the frozen guard."""
    protocol.validate_atomic_publication_contract(
        protocol.ATOMIC_PUBLICATION_STEPS
    )
    payload = serialize_intraday_ledger_rows(rows)
    return protocol.atomic_publish_bytes(
        destination,
        payload,
        validate_temporary=validate_intraday_ledger_artifact,
        protocol_repo_root=protocol_repo_root,
    )
