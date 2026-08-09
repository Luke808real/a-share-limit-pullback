"""Frozen R9 V02 contract only; it never creates prospective observations.

This module records the preconditions and pure guards required before any R9
accumulation implementation may exist.  In particular, the historical R1
candidate population and an administrative TTL are unresolved at this commit,
so any attempt to create a prospective setup is fail-closed.
"""

from __future__ import annotations

import csv
import hashlib
import os
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from limit_pullback.strategy.engine import make_setup_id


REPO_ROOT = Path(__file__).resolve().parents[3]

PROTOCOL_VERSION = "R9_PROSPECTIVE_V02"
PROTOCOL_STATUS = "BLOCKED_R9_POPULATION_SEMANTIC_GAP"

R1_PROVENANCE_STATUS = "INTERIM_PARTIAL_PROVENANCE"
R1_FORWARD_AUTHORITY = False
LEGACY_LABEL_ROLE = "SECONDARY_DIAGNOSTIC_ONLY_NOT_R9_PRIMARY_ENDPOINT"

# R1 V01/V01A applied future_sessions_available >= 3 before keeping the first
# candidate per setup.  No outcome-blind replacement is authoritative here.
R9_POPULATION_STATUS = "BLOCKED_R9_POPULATION_SEMANTIC_GAP"
R9_SETUP_ID_RULE = (
    "make_setup_id(symbol, anchor_date, anchor_price, price_tick); "
    "strategy_version is provenance, not part of the historical-compatible key"
)
R9_OBSERVATION_TTL_STATUS = "BLOCKED_TTL_UNRESOLVED"
R9_OBSERVATION_TTL: int | None = None

FIRST_S1_TOUCH_EVENT = "FIRST_S1_TOUCH_EVENT"
REPEAT_CONFIRMATION_CREATES_NEW_EVENT = False

R9_PRIMARY_CHECKPOINT = "10:30"
LOCKED_SENSITIVITY_CHECKPOINTS = ("09:45", "10:00", "11:30")
PRIMARY_INTRADAY_FEATURE = "breakout_hold_ratio"
PRIMARY_INTRADAY_EXPECTED_DIRECTION = "POSITIVE"
SECONDARY_INTRADAY_FEATURES = (
    ("retest_depth", "POSITIVE"),
    ("false_break_duration", "NEGATIVE"),
    ("vwap_acceptance_ratio", "POSITIVE"),
)

R7_MODEL_REGISTRY_SHA = (
    "828a31484df655a02cb4c34452c26e70a954eb9221a517b5c5c098513677341f"
)
R7_COEFFICIENTS_SHA = (
    "39de709f424194be1a28d7e8e21be24c09824abc734027b29299a4b0452749ed"
)
R7_COEFFICIENTS_PATH = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r7b_multivariate_coefficients_v01.csv"
)
R7_MODEL_REGISTRY_PATH = (
    REPO_ROOT / "research" / "second_launch" / "factors_v01"
    / "r7a_multivariate_model_registry_v01.csv"
)
M0_PREDICTORS = ("B4", "B5", "B6", "B7")
M1_PREDICTORS = M0_PREDICTORS + ("median_range_ratio",)
PRIMARY_DAILY_COMPARISON = "M1_vs_M0"
M2_ROLE = "SECONDARY_LOCKED_NO_REFIT"
M0_M1_SCORE_SEMANTICS = (
    "outcome_3d CORE_LADDER raw-coefficient rank-linear score; published "
    "coefficient CSV intentionally omits intercept, which does not affect "
    "Spearman rank; no refit, standardization, calibration, or probability"
)

DECISION_REFERENCE_TIME = "10:30 completed 5m bar"
DECISION_REFERENCE_PRICE = "10:30 completed 5m close"
PRIMARY_ENDPOINT = "FWD3_CLOSE_RETURN"
SENSITIVITY_ENDPOINT = "FWD5_CLOSE_RETURN"
RISK_PATH_DIAGNOSTICS = ("MFE_NEXT_3_SESSIONS", "MAE_NEXT_3_SESSIONS")
OPTIONAL_BINARY_DIAGNOSTIC = "FWD3_POSITIVE = FWD3_CLOSE_RETURN > 0"

SYMBOL_CLUSTER_BOOTSTRAP = "SYMBOL_CLUSTER_BOOTSTRAP"
TRADE_WEEK_BLOCK_BOOTSTRAP = "TRADE_WEEK_BLOCK_BOOTSTRAP"
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260809
UNCERTAINTY_DATA_LIMITED = "UNCERTAINTY_STATUS=DATA_LIMITED"

NO_EARLY_STOP_FOR_PERFORMANCE = True
INITIAL_OBSERVATION_WINDOW_A_SHARE_SESSIONS = 60
DAILY_MATURED_SETUP_MIN = 120
INTRADAY_10_30_FEATURE_OBSERVABLE_MIN = 40

ASL_CODE_SHA = "04bd94936587b35cae55c833627260866d025184"
ASL_STATUS = "RESEARCH_CANDIDATE_NOT_ASL_ACTIVE"
R9_ASL_DATA_ROOT = "/Users/luke808/AI/asl-r9-prospective-research-v01"
R9_DATA_ROOT_PROPERTIES = ("APPEND_ONLY", "RESEARCH_ONLY", "NOT_PRODUCTION")

ATOMIC_PUBLICATION_STEPS = (
    "WRITE_TEMPORARY_ARTIFACT",
    "SCHEMA_CHECK",
    "HASH",
    "PIT_CHECK",
    "RECONCILIATION",
    "ATOMIC_RENAME_OR_PROMOTION",
)
R9_ROW_ORIGIN = "R9_PROSPECTIVE"
HISTORICAL_ORIGINS = frozenset({"R1_8682_DEVELOPMENT", "R8_146_DEVELOPMENT"})

SETUP_LEDGER_COLUMNS = (
    "setup_id", "symbol", "t0_date", "candidate_date", "setup_created_as_of",
    "ttl_end_date", "daily_feature_hash", "B4", "B5", "B6", "B7",
    "median_range_ratio", "quiet_days_n", "M0_score", "M1_score", "M2_score",
    "activation_status", "event_id", "source_manifest_hash",
)
INTRADAY_LEDGER_COLUMNS = (
    "event_id", "setup_id", "event_date", "checkpoint", "activation_time",
    "post_activation_bar_n", "breakout_hold_ratio", "retest_depth",
    "false_break_duration", "vwap_acceptance_ratio", "reference_price_10_30",
    "minute_manifest_hash", "feature_hash",
)
ENDPOINT_LEDGER_COLUMNS = (
    "event_id", "fwd3_close_return", "fwd5_close_return", "mfe_next_3_sessions",
    "mae_next_3_sessions", "3d_mature_at", "5d_mature_at", "endpoint_source_hash",
    "label_status",
)
REQUIRED_DAILY_MINUTE_RECONCILIATION = (
    "daily_symbol", "minute_symbol", "daily_trade_date", "minute_trade_date",
    "daily_s1_price", "minute_s1_price", "price_tick",
)
REQUIRED_MINUTE_MANIFEST_FIELDS = (
    "ASL_CODE_SHA", "source", "schema_version", "partition_list",
    "partition_hashes", "units", "timezone", "bar_label_semantics", "ingested_at",
)


class ProtocolBlocked(RuntimeError):
    """A frozen R9 contract is missing or has been violated."""


class FeatureDriftBlocked(ProtocolBlocked):
    """An immutable feature key was recomputed with a different hash."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_clock(value: str | datetime | time) -> str:
    """Return exact HH:MM for a first-touch clock; reject ambiguous input."""
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    text = str(value).strip()
    for parser in (datetime.fromisoformat,):
        try:
            return parser(text).strftime("%H:%M")
        except ValueError:
            pass
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M")
        except ValueError:
            pass
    raise ProtocolBlocked(f"invalid first-touch clock: {value!r}")


def r9_setup_id(
    symbol: str,
    anchor_date: date,
    anchor_price: Decimal,
    price_tick: Decimal = Decimal("0.01"),
) -> str:
    """Use the existing authoritative setup key; do not add a new version suffix."""
    return make_setup_id(str(symbol).zfill(6), anchor_date, anchor_price, price_tick)


def r9_event_id(setup_id: str, event_date: date, first_touch_time: str | datetime | time) -> str:
    clock = canonical_clock(first_touch_time)
    return f"{setup_id}:S1:{event_date:%Y%m%d}:{clock.replace(':', '')}"


@dataclass(frozen=True)
class FirstS1TouchEvent:
    setup_id: str
    event_date: date
    first_touch_time: str

    @property
    def event_id(self) -> str:
        return r9_event_id(self.setup_id, self.event_date, self.first_touch_time)


def register_first_s1_touch(
    existing: Mapping[str, FirstS1TouchEvent], candidate: FirstS1TouchEvent,
) -> FirstS1TouchEvent:
    """Return an identical prior event, otherwise reject a second event per setup."""
    prior = existing.get(candidate.setup_id)
    if prior is None:
        return candidate
    if prior == candidate:
        return prior
    raise ProtocolBlocked("REPEAT_CONFIRMATION_CREATES_NEW_EVENT=FALSE")


def intraday_observation_status(
    first_touch_time: str | datetime | time,
    post_activation_bar_n: int,
) -> str:
    """Retain late touches without falsely scoring them at the primary checkpoint."""
    if canonical_clock(first_touch_time) > R9_PRIMARY_CHECKPOINT:
        return "POST_CHECKPOINT_NOT_OBSERVABLE"
    if post_activation_bar_n <= 0:
        return "NO_POST_ACTIVATION_BAR"
    return "FEATURE_OBSERVABLE"


def require_population_and_ttl_authority() -> None:
    if R9_POPULATION_STATUS != "PASS":
        raise ProtocolBlocked(R9_POPULATION_STATUS)
    if R9_OBSERVATION_TTL_STATUS != "PASS" or R9_OBSERVATION_TTL is None:
        raise ProtocolBlocked(R9_OBSERVATION_TTL_STATUS)


def assert_non_activation_is_retained(activation_status: str) -> None:
    if activation_status != "NO_ACTIVATION_WITHIN_TTL":
        raise ProtocolBlocked("non-activation must remain in prospective population")


def _frozen_coefficient_rows(model_id: str) -> tuple[tuple[str, Decimal], ...]:
    if sha256_file(R7_COEFFICIENTS_PATH) != R7_COEFFICIENTS_SHA:
        raise ProtocolBlocked("R7 coefficient SHA mismatch")
    if sha256_file(R7_MODEL_REGISTRY_PATH) != R7_MODEL_REGISTRY_SHA:
        raise ProtocolBlocked("R7 model registry SHA mismatch")
    expected = M0_PREDICTORS if model_id == "M0" else M1_PREDICTORS
    with R7_COEFFICIENTS_PATH.open(newline="") as handle:
        rows = [
            row for row in csv.DictReader(handle)
            if row["target"] == "outcome_3d"
            and row["sample_family"] == "CORE_LADDER"
            and row["model_id"] == model_id
        ]
    predictors = tuple(row["predictor"] for row in rows)
    if predictors != expected:
        raise ProtocolBlocked(f"frozen {model_id} predictor vector mismatch: {predictors}")
    return tuple((row["predictor"], Decimal(row["coefficient"])) for row in rows)


def frozen_daily_score(model_id: str, values: Mapping[str, Decimal | int | float]) -> Decimal:
    """Calculate frozen raw-coefficient rank score; no model fit/calibration occurs."""
    if model_id not in {"M0", "M1"}:
        raise ProtocolBlocked("only M0/M1 are permitted for the primary comparison")
    score = Decimal("0")
    for predictor, coefficient in _frozen_coefficient_rows(model_id):
        if predictor not in values:
            raise ProtocolBlocked(f"missing frozen score input: {predictor}")
        try:
            value = Decimal(str(values[predictor]))
        except (InvalidOperation, ValueError) as exc:
            raise ProtocolBlocked(f"invalid frozen score input: {predictor}") from exc
        score += coefficient * value
    return score


@dataclass(frozen=True)
class SubsequentSession:
    trade_date: date
    close: Decimal | None


def forward_close_return(
    *,
    event_date: date,
    reference_price: Decimal,
    subsequent_sessions: Sequence[SubsequentSession],
    horizon: int,
) -> tuple[str, Decimal | None]:
    """Use exactly E+N calendar sessions; never skip a missing stock close."""
    if horizon not in {3, 5}:
        raise ProtocolBlocked("only frozen 3D/5D endpoint horizons are allowed")
    if reference_price <= 0:
        raise ProtocolBlocked("decision reference price must be positive")
    if len(subsequent_sessions) < horizon:
        return "PENDING", None
    used = tuple(subsequent_sessions[:horizon])
    dates = tuple(session.trade_date for session in used)
    if any(day <= event_date for day in dates) or tuple(sorted(dates)) != dates or len(set(dates)) != len(dates):
        raise ProtocolBlocked("subsequent sessions must be strict ordered A-share sessions after event day")
    close = used[-1].close
    if close is None:
        return "DATA_UNAVAILABLE", None
    return "MATURED", close / reference_price - Decimal("1")


def validate_bootstrap_contract() -> None:
    if (SYMBOL_CLUSTER_BOOTSTRAP != "SYMBOL_CLUSTER_BOOTSTRAP"
            or TRADE_WEEK_BLOCK_BOOTSTRAP != "TRADE_WEEK_BLOCK_BOOTSTRAP"
            or N_BOOTSTRAP != 2000
            or BOOTSTRAP_SEED != 20260809):
        raise ProtocolBlocked("bootstrap contract drift")


def validate_atomic_publication_contract(steps: Sequence[str]) -> None:
    if tuple(steps) != ATOMIC_PUBLICATION_STEPS:
        raise ProtocolBlocked("atomic publication contract drift")


def atomic_publish_bytes(
    destination: Path,
    payload: bytes,
    *,
    validate_temporary: Callable[[Path], None],
) -> str:
    """Publish a new immutable artifact only after all supplied QA succeeds.

    This is deliberately byte-oriented: a future R9 writer must serialize its
    complete versioned ledger first, validate the temporary artifact, then call
    this function. Existing ledger files are never overwritten.
    """
    if destination.exists():
        raise ProtocolBlocked("append-only publication refuses existing destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        validate_temporary(temporary)
        digest = sha256_file(temporary)
        os.replace(temporary, destination)
        return digest
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def assert_append_only_feature(
    existing_hashes: Mapping[tuple[str, str, str], str],
    *,
    setup_id: str,
    event_id: str,
    checkpoint: str,
    feature_hash: str,
) -> str:
    key = (setup_id, event_id, checkpoint)
    prior = existing_hashes.get(key)
    if prior is None:
        return "APPEND"
    if prior == feature_hash:
        return "ALREADY_RECORDED"
    raise FeatureDriftBlocked("STATUS=BLOCKED_FEATURE_DRIFT")


def assert_prospective_origin(
    *,
    origin: str,
    row_date: date,
    protocol_freeze_date: date,
) -> None:
    if origin in HISTORICAL_ORIGINS or origin != R9_ROW_ORIGIN:
        raise ProtocolBlocked("historical development rows are forbidden in R9 ledger")
    if row_date <= protocol_freeze_date:
        raise ProtocolBlocked("pre-freeze rows are forbidden in clean R9")


def validate_exact_tick_reconciliation(values: Mapping[str, Any]) -> None:
    missing = [key for key in REQUIRED_DAILY_MINUTE_RECONCILIATION if key not in values]
    if missing:
        raise ProtocolBlocked(f"missing reconciliation fields: {missing}")
    if (str(values["daily_symbol"]).zfill(6) != str(values["minute_symbol"]).zfill(6)
            or values["daily_trade_date"] != values["minute_trade_date"]):
        raise ProtocolBlocked("STATUS=BLOCKED_PRICE_RECONCILIATION")
    try:
        tick = Decimal(str(values["price_tick"]))
        daily_s1 = Decimal(str(values["daily_s1_price"]))
        minute_s1 = Decimal(str(values["minute_s1_price"]))
    except InvalidOperation as exc:
        raise ProtocolBlocked("STATUS=BLOCKED_PRICE_RECONCILIATION") from exc
    if tick <= 0 or daily_s1 != daily_s1.quantize(tick) or minute_s1 != minute_s1.quantize(tick):
        raise ProtocolBlocked("STATUS=BLOCKED_PRICE_RECONCILIATION")
    if daily_s1 != minute_s1:
        raise ProtocolBlocked("STATUS=BLOCKED_PRICE_RECONCILIATION")


def validate_minute_manifest(manifest: Mapping[str, Any]) -> None:
    missing = [key for key in REQUIRED_MINUTE_MANIFEST_FIELDS if not manifest.get(key)]
    if missing:
        raise ProtocolBlocked(f"missing minute provenance: {missing}")
    if manifest["ASL_CODE_SHA"] != ASL_CODE_SHA:
        raise ProtocolBlocked("unexpected ASL code SHA")


def r9_full_session_grid() -> tuple[str, ...]:
    morning = tuple([*(f"09:{minute:02d}" for minute in range(35, 60, 5)),
                     *(f"10:{minute:02d}" for minute in range(0, 60, 5)),
                     *(f"11:{minute:02d}" for minute in range(0, 35, 5))])
    afternoon = tuple([*(f"13:{minute:02d}" for minute in range(5, 60, 5)),
                       *(f"14:{minute:02d}" for minute in range(0, 60, 5)), "15:00"])
    return morning + afternoon


def validate_minute_ingestion(
    rows: Sequence[Mapping[str, Any]], *, right_label_verified: bool,
) -> None:
    """Fail closed on duplicate, physical-order, grid, or label-semantics drift."""
    if not right_label_verified:
        raise ProtocolBlocked("right-label fixture not verified")
    grouped: dict[tuple[str, str], list[str]] = {}
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        try:
            symbol = str(row["symbol"])
            trade_date = str(row["trade_date"])
            bar_time = canonical_clock(str(row["bar_time"]))
        except KeyError as exc:
            raise ProtocolBlocked("missing minute ingestion identity") from exc
        key = (symbol, trade_date, bar_time)
        if key in seen:
            raise ProtocolBlocked("duplicate(symbol, trade_date, bar_time)")
        seen.add(key)
        grouped.setdefault((symbol, trade_date), []).append(bar_time)
    expected = r9_full_session_grid()
    for key, physical_times in grouped.items():
        if tuple(sorted(physical_times)) != tuple(physical_times):
            raise ProtocolBlocked(f"physical bar disorder: {key}")
        if tuple(physical_times) != expected:
            raise ProtocolBlocked(f"session-grid mismatch: {key}")


def protocol_registry_rows() -> list[dict[str, str]]:
    """The committed CSV must match these frozen contract rows exactly."""
    return [
        {"section": "authority", "key": "R1_PROVENANCE_STATUS", "value": R1_PROVENANCE_STATUS, "status": "PASS"},
        {"section": "authority", "key": "R1_FORWARD_AUTHORITY", "value": "FALSE", "status": "PASS"},
        {"section": "authority", "key": "LEGACY_LABEL_ROLE", "value": LEGACY_LABEL_ROLE, "status": "PASS"},
        {"section": "population", "key": "R9_SETUP_ID", "value": R9_SETUP_ID_RULE, "status": "BLOCKED"},
        {"section": "population", "key": "R9_POPULATION_STATUS", "value": R9_POPULATION_STATUS, "status": "BLOCKED"},
        {"section": "population", "key": "R9_OBSERVATION_TTL", "value": "UNRESOLVED", "status": "BLOCKED"},
        {"section": "event", "key": "FIRST_S1_TOUCH_EVENT", "value": FIRST_S1_TOUCH_EVENT, "status": "PASS"},
        {"section": "event", "key": "REPEAT_CONFIRMATION_CREATES_NEW_EVENT", "value": "FALSE", "status": "PASS"},
        {"section": "intraday", "key": "R9_PRIMARY_CHECKPOINT", "value": R9_PRIMARY_CHECKPOINT, "status": "PASS"},
        {"section": "intraday", "key": "PRIMARY_INTRADAY_FEATURE", "value": PRIMARY_INTRADAY_FEATURE, "status": "PASS"},
        {"section": "daily", "key": "PRIMARY_DAILY_COMPARISON", "value": PRIMARY_DAILY_COMPARISON, "status": "PASS"},
        {"section": "daily", "key": "R7_COEFFICIENTS_SHA", "value": R7_COEFFICIENTS_SHA, "status": "PASS"},
        {"section": "endpoint", "key": "PRIMARY_ENDPOINT", "value": PRIMARY_ENDPOINT, "status": "PASS"},
        {"section": "endpoint", "key": "SENSITIVITY_ENDPOINT", "value": SENSITIVITY_ENDPOINT, "status": "PASS"},
        {"section": "uncertainty", "key": "SYMBOL_CLUSTER_BOOTSTRAP", "value": str(N_BOOTSTRAP), "status": "PASS"},
        {"section": "uncertainty", "key": "TRADE_WEEK_BLOCK_BOOTSTRAP", "value": str(N_BOOTSTRAP), "status": "PASS"},
        {"section": "stopping", "key": "INITIAL_WINDOW_A_SHARE_SESSIONS", "value": str(INITIAL_OBSERVATION_WINDOW_A_SHARE_SESSIONS), "status": "PASS"},
        {"section": "provenance", "key": "ASL_CODE_SHA", "value": ASL_CODE_SHA, "status": "PASS"},
        {"section": "provenance", "key": "R9_ASL_DATA_ROOT", "value": R9_ASL_DATA_ROOT, "status": "PASS"},
        {"section": "publication", "key": "ATOMIC_PUBLICATION_STEPS", "value": " -> ".join(ATOMIC_PUBLICATION_STEPS), "status": "PASS"},
        {"section": "gate", "key": "GATE_1_R1_AUTHORITY_BOUNDARY", "value": "PASS", "status": "PASS"},
        {"section": "gate", "key": "GATE_2_POPULATION_EVENT_TTL", "value": "BLOCKED", "status": "BLOCKED"},
        {"section": "gate", "key": "GATE_3_INDEPENDENT_ENDPOINT", "value": "PASS", "status": "PASS"},
        {"section": "gate", "key": "GATE_4_MULTIPLICITY_UNCERTAINTY", "value": "PASS", "status": "PASS"},
        {"section": "gate", "key": "GATE_5_ASL_PROVENANCE_ATOMICITY", "value": "PASS", "status": "PASS"},
    ]
