"""Frozen R9 V02 contract only; it never creates prospective observations.

This module records the preconditions and pure guards required before any R9
accumulation implementation may exist. Gate 2A and Gate 2B are frozen, but
this module does not itself create an OOS row or run R9 accumulation.
"""

from __future__ import annotations

import csv
import hashlib
import os
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from limit_pullback.strategy.engine import make_setup_id
from r9_ttl_event_eligibility_v01 import (
    OOS_START,
    PROTOCOL_FREEZE_CALENDAR_ARTIFACT,
    PROTOCOL_FREEZE_CALENDAR_MANIFEST_HASH,
    PROTOCOL_FREEZE_CALENDAR_VERSION,
    PROTOCOL_FREEZE_DATE,
    R9_RUN_CALENDAR_ARTIFACT,
    R9_RUN_CALENDAR_AUTHORITY_ARTIFACT,
    R9_RUN_CALENDAR_AUTHORITY_VERSION,
    R9_RUN_CALENDAR_MANIFEST_HASH,
    R9_RUN_CALENDAR_SOURCE_COMMIT,
    R9_RUN_CALENDAR_SOURCE_GIT_BLOB_SHA,
    R9_RUN_CALENDAR_VERSION,
    R9_ADMINISTRATIVE_TTL_VERSION,
    R9_OBSERVATION_TTL as OWNER_FROZEN_TTL_SESSIONS,
    STRUCTURAL_INVALIDATION_STATUS,
    TTL_ANCHOR,
    TTL_SELECTION_BASIS,
    TTL_UNIT,
    TTL_WINDOW,
    FrozenAshareTradingCalendar,
    Gate2BBlocked,
    RIGHT_LABELED_5M_GRID,
    assert_clean_oos_candidate_date,
    canonical_clock as canonical_gate2b_clock,
    validate_run_calendar,
)


REPO_ROOT = Path(__file__).resolve().parents[3]

PROTOCOL_VERSION = "R9_PROSPECTIVE_V02"
PROTOCOL_STATUS = "GO_PRE_R9_AUTHORIZED_NO_OOS_ROWS"
PRE_R9_STATUS = "GO"
R9_RECOMMENDATION = "AUTHORIZED_TO_FREEZE_AND_ACCUMULATE"
R9_ACCUMULATION_AUTHORIZED = True
R9_OOS_ROWS_WRITTEN = 0
PROTOCOL_FREEZE_RECEIPT_TAG = "r9-protocol-freeze-v03"
R9_ACCUMULATION_WRITE_AUTHORITY = "POST_COMMIT_RECEIPT_REQUIRED"

FROZEN_PROTOCOL_ARTIFACTS = (
    "research/second_launch/walk_forward_v01/r9_protocol_v02.py",
    "research/second_launch/walk_forward_v01/r9_ttl_event_eligibility_v01.py",
    "research/second_launch/walk_forward_v01/r9_protocol_registry_v02.csv",
    "research/second_launch/walk_forward_v01/r9_protocol_freeze_calendar_v01.csv",
    "research/second_launch/walk_forward_v01/r9_run_calendar_v01.csv",
    "research/second_launch/walk_forward_v01/r9_run_calendar_authority_v01.json",
)

R1_PROVENANCE_STATUS = "INTERIM_PARTIAL_PROVENANCE"
R1_FORWARD_AUTHORITY = False
LEGACY_LABEL_ROLE = "SECONDARY_DIAGNOSTIC_ONLY_NOT_R9_PRIMARY_ENDPOINT"

# R1 V01/V01A applied future_sessions_available >= 3 before keeping the first
# candidate per setup.  The separate Gate 2A generator is a new prospective
# contract; it does not claim historical final-cohort equivalence.
R9_POPULATION_STATUS = "PASS_NEW_PROSPECTIVE_V01"
R9_SETUP_ID_RULE = (
    "make_setup_id(symbol, anchor_date, anchor_price, price_tick); "
    "strategy_version is provenance, not part of the historical-compatible key"
)
R9_OBSERVATION_TTL_STATUS = "PASS_OWNER_FROZEN_V01"
R9_OBSERVATION_TTL: int = OWNER_FROZEN_TTL_SESSIONS
R9_TTL_ANCHOR = TTL_ANCHOR
R9_TTL_SELECTION_BASIS = TTL_SELECTION_BASIS
R9_TTL_UNIT = TTL_UNIT
R9_TTL_WINDOW = TTL_WINDOW
R9_STRUCTURAL_INVALIDATION_STATUS = STRUCTURAL_INVALIDATION_STATUS
R9_PROSPECTIVE_EVENT_ELIGIBILITY_STATUS = "PASS_OWNER_FROZEN_V01"
R9_OOS_START = OOS_START

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
M2_PREDICTORS = M1_PREDICTORS + ("quiet_days_n",)
PRIMARY_DAILY_COMPARISON = "M1_vs_M0"
M2_ROLE = "SECONDARY_LOCKED_NO_REFIT"
M2_SCORE_SEMANTICS = "SECONDARY_ONLY_RAW_COEFFICIENT_RANK_SCORE"
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
    "ttl_end_date", "administrative_ttl_version", "ttl_anchor",
    "ttl_calendar_manifest_hash", "setup_status", "r9_active_population",
    "daily_population_eligible", "intraday_primary_eligible",
    "intraday_ineligible_reason", "event_search_start", "event_search_end",
    "daily_feature_hash", "B4", "B5", "B6", "B7",
    "median_range_ratio", "quiet_days_n", "M0_score", "M1_score", "M2_score",
    "activation_status", "event_id", "source_manifest_hash",
)
INTRADAY_LEDGER_COLUMNS = (
    "event_id", "setup_id", "event_date", "checkpoint", "activation_time",
    "post_activation_bar_n", "intraday_primary_feature_status",
    "breakout_hold_ratio", "retest_depth",
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


@dataclass(frozen=True)
class ProtocolFreezeReceipt:
    """The external annotated-tag receipt for this immutable freeze commit."""

    tag: str
    tag_object: str
    protocol_freeze_commit: str
    tag_target_commit: str
    message: str


def _is_full_git_commit(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_protocol_freeze_receipt(receipt: ProtocolFreezeReceipt) -> None:
    """Require an annotated-tag receipt that pins the exact freeze commit."""

    if receipt.tag != PROTOCOL_FREEZE_RECEIPT_TAG:
        raise ProtocolBlocked("unexpected protocol freeze receipt tag")
    if not _is_full_git_commit(receipt.tag_object):
        raise ProtocolBlocked("protocol freeze receipt requires a full tag-object SHA")
    if not _is_full_git_commit(receipt.protocol_freeze_commit):
        raise ProtocolBlocked("protocol freeze receipt requires a full commit SHA")
    if receipt.tag_target_commit != receipt.protocol_freeze_commit:
        raise ProtocolBlocked("protocol freeze receipt tag target mismatch")
    expected_fields = {
        "PROTOCOL_FREEZE_COMMIT": receipt.protocol_freeze_commit,
        "PROTOCOL_FREEZE_DATE": PROTOCOL_FREEZE_DATE.isoformat(),
        "OOS_START": R9_OOS_START.isoformat(),
        "PROTOCOL_FREEZE_CALENDAR_HASH": PROTOCOL_FREEZE_CALENDAR_MANIFEST_HASH,
    }
    found_fields: dict[str, str] = {}
    for line in receipt.message.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in expected_fields:
            if key in found_fields:
                raise ProtocolBlocked("protocol freeze receipt has duplicate message field")
            found_fields[key] = value
    if found_fields != expected_fields:
        raise ProtocolBlocked("protocol freeze receipt message mismatch")


def _git_output(repo_root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repo_root), *arguments),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ProtocolBlocked("Git is required to verify the protocol freeze receipt") from exc
    if completed.returncode != 0:
        raise ProtocolBlocked("protocol freeze receipt Git verification failed")
    return completed.stdout.rstrip("\n")


def _git_blob_bytes(repo_root: Path, commit: str, relative_path: str) -> bytes:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repo_root), "cat-file", "blob", f"{commit}:{relative_path}"),
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise ProtocolBlocked("Git is required to verify frozen protocol artifacts") from exc
    if completed.returncode != 0:
        raise ProtocolBlocked(
            f"STATUS=BLOCKED_PROTOCOL_DRIFT: frozen artifact is absent: {relative_path}"
        )
    return completed.stdout


def _is_commit_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    try:
        completed = subprocess.run(
            (
                "git", "-C", str(repo_root), "merge-base", "--is-ancestor",
                ancestor, descendant,
            ),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ProtocolBlocked("Git is required to verify protocol freeze ancestry") from exc
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    raise ProtocolBlocked("protocol freeze ancestry verification failed")


def validate_frozen_artifact_integrity(
    receipt: ProtocolFreezeReceipt,
    *,
    repo_root: Path = REPO_ROOT,
) -> None:
    """Require current protocol artifacts to match the freeze commit byte-for-byte."""

    for relative_path in FROZEN_PROTOCOL_ARTIFACTS:
        current_path = repo_root / relative_path
        if not current_path.is_file():
            raise ProtocolBlocked(
                f"STATUS=BLOCKED_PROTOCOL_DRIFT: frozen artifact is absent: {relative_path}"
            )
        frozen_hash = hashlib.sha256(
            _git_blob_bytes(repo_root, receipt.protocol_freeze_commit, relative_path)
        ).hexdigest()
        current_hash = sha256_file(current_path)
        if current_hash != frozen_hash:
            raise ProtocolBlocked(
                f"STATUS=BLOCKED_PROTOCOL_DRIFT: frozen artifact changed: {relative_path}"
            )


def read_protocol_freeze_receipt(repo_root: Path = REPO_ROOT) -> ProtocolFreezeReceipt:
    """Read the actual annotated tag object; never accept caller-supplied claims."""

    reference = f"refs/tags/{PROTOCOL_FREEZE_RECEIPT_TAG}"
    tag_object = _git_output(repo_root, "rev-parse", "--verify", reference)
    if not _is_full_git_commit(tag_object):
        raise ProtocolBlocked("protocol freeze receipt tag object is not a full SHA")
    if _git_output(repo_root, "cat-file", "-t", tag_object) != "tag":
        raise ProtocolBlocked("protocol freeze receipt must be an annotated tag")
    contents = _git_output(repo_root, "cat-file", "-p", tag_object)
    header, separator, message = contents.partition("\n\n")
    if not separator:
        raise ProtocolBlocked("protocol freeze receipt tag has no message")
    header_values: dict[str, str] = {}
    for line in header.splitlines():
        key, value_separator, value = line.partition(" ")
        if key in {"object", "type", "tag"}:
            if not value_separator or key in header_values:
                raise ProtocolBlocked("protocol freeze receipt tag header mismatch")
            header_values[key] = value
    if header_values.get("type") != "commit" or header_values.get("tag") != PROTOCOL_FREEZE_RECEIPT_TAG:
        raise ProtocolBlocked("protocol freeze receipt tag header mismatch")
    tag_target_commit = _git_output(repo_root, "rev-parse", "--verify", f"{reference}^{{commit}}")
    if (
        not _is_full_git_commit(tag_target_commit)
        or header_values.get("object") != tag_target_commit
    ):
        raise ProtocolBlocked("protocol freeze receipt tag target mismatch")
    receipt = ProtocolFreezeReceipt(
        tag=PROTOCOL_FREEZE_RECEIPT_TAG,
        tag_object=tag_object,
        protocol_freeze_commit=tag_target_commit,
        tag_target_commit=tag_target_commit,
        message=message,
    )
    validate_protocol_freeze_receipt(receipt)
    return receipt


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_clock(value: str | datetime | time) -> str:
    """Use Gate 2B's timezone-aware right-labeled five-minute clock guard."""
    try:
        return canonical_gate2b_clock(value)
    except Gate2BBlocked as exc:
        raise ProtocolBlocked(str(exc)) from exc


def r9_setup_id(
    symbol: str,
    anchor_date: date,
    anchor_price: Decimal,
    price_tick: Decimal = Decimal("0.01"),
) -> str:
    """Use the existing authoritative setup key; do not add a new version suffix."""
    return make_setup_id(str(symbol).zfill(6), anchor_date, anchor_price, price_tick)


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
    if R9_POPULATION_STATUS not in {"PASS", "PASS_NEW_PROSPECTIVE_V01"}:
        raise ProtocolBlocked(R9_POPULATION_STATUS)
    if (
        R9_OBSERVATION_TTL_STATUS != "PASS_OWNER_FROZEN_V01"
        or R9_OBSERVATION_TTL != OWNER_FROZEN_TTL_SESSIONS
    ):
        raise ProtocolBlocked(R9_OBSERVATION_TTL_STATUS)


def require_r9_accumulation_write_authority(
    *,
    repo_root: Path = REPO_ROOT,
) -> ProtocolFreezeReceipt:
    """Block every future append until the actual annotated tag is verified."""
    require_population_and_ttl_authority()
    if not R9_ACCUMULATION_AUTHORIZED:
        raise ProtocolBlocked("R9 accumulation is not authorized")
    if R9_ACCUMULATION_WRITE_AUTHORITY != "POST_COMMIT_RECEIPT_REQUIRED":
        raise ProtocolBlocked("R9 accumulation write-authority contract drift")
    receipt = read_protocol_freeze_receipt(repo_root)
    expected_commit = _git_output(repo_root, "rev-parse", "--verify", "HEAD")
    if not _is_full_git_commit(expected_commit):
        raise ProtocolBlocked("expected protocol freeze commit must be a full SHA")
    if not _is_commit_ancestor(
        repo_root,
        receipt.protocol_freeze_commit,
        expected_commit,
    ):
        raise ProtocolBlocked("protocol freeze commit is not an ancestor of current HEAD")
    validate_frozen_artifact_integrity(receipt, repo_root=repo_root)
    return receipt


def assert_non_activation_is_retained(activation_status: str) -> None:
    if activation_status != "NO_ACTIVATION_WITHIN_TTL":
        raise ProtocolBlocked("non-activation must remain in prospective population")


def _frozen_coefficient_rows(model_id: str) -> tuple[tuple[str, Decimal], ...]:
    if sha256_file(R7_COEFFICIENTS_PATH) != R7_COEFFICIENTS_SHA:
        raise ProtocolBlocked("R7 coefficient SHA mismatch")
    if sha256_file(R7_MODEL_REGISTRY_PATH) != R7_MODEL_REGISTRY_SHA:
        raise ProtocolBlocked("R7 model registry SHA mismatch")
    if model_id == "M0":
        expected = M0_PREDICTORS
    elif model_id == "M1":
        expected = M1_PREDICTORS
    elif model_id == "M2":
        expected = M2_PREDICTORS
    else:
        raise ProtocolBlocked("only M0/M1/M2 are permitted for frozen daily scores")
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
    """Calculate a frozen raw-coefficient score; no fit or calibration occurs."""
    if model_id not in {"M0", "M1", "M2"}:
        raise ProtocolBlocked("only M0/M1/M2 are permitted for frozen daily scores")
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
    run_calendar: FrozenAshareTradingCalendar,
    subsequent_sessions: Sequence[SubsequentSession],
    horizon: int,
) -> tuple[str, Decimal | None]:
    """Use exactly E+N exchange sessions; never shift a missing close."""
    if horizon not in {3, 5}:
        raise ProtocolBlocked("only frozen 3D/5D endpoint horizons are allowed")
    if reference_price <= 0:
        raise ProtocolBlocked("decision reference price must be positive")
    try:
        validate_run_calendar(run_calendar)
    except Gate2BBlocked as exc:
        raise ProtocolBlocked(str(exc)) from exc
    try:
        event_index = run_calendar.sessions.index(event_date)
    except ValueError as exc:
        raise ProtocolBlocked("event date is absent from R9 run calendar") from exc
    dates = tuple(session.trade_date for session in subsequent_sessions)
    if (
        any(day <= event_date for day in dates)
        or tuple(sorted(dates)) != dates
        or len(set(dates)) != len(dates)
    ):
        raise ProtocolBlocked("subsequent sessions must be strict ordered A-share sessions after event day")
    expected_dates = run_calendar.sessions[event_index + 1:event_index + 1 + horizon]
    if len(subsequent_sessions) < horizon:
        if dates != expected_dates[:len(dates)]:
            raise ProtocolBlocked("endpoint sessions do not match exact exchange-session horizon")
        return "PENDING", None
    used = tuple(subsequent_sessions[:horizon])
    if tuple(session.trade_date for session in used) != expected_dates:
        raise ProtocolBlocked("endpoint sessions do not match exact exchange-session horizon")
    if any(session.close is None for session in used):
        return "DATA_UNAVAILABLE", None
    return "MATURED", used[-1].close / reference_price - Decimal("1")


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
    protocol_repo_root: Path = REPO_ROOT,
) -> str:
    """Publish a new immutable artifact only after all supplied QA succeeds.

    This is deliberately byte-oriented: a future R9 writer must serialize its
    complete versioned ledger first, validate the temporary artifact, then call
    this function. Existing ledger files are never overwritten.
    """
    require_r9_accumulation_write_authority(
        repo_root=protocol_repo_root,
    )
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
    protocol_freeze_date: date = PROTOCOL_FREEZE_DATE,
    run_calendar: FrozenAshareTradingCalendar | None = None,
    frozen_calendar: FrozenAshareTradingCalendar | None = None,
    oos_start: date | None = None,
) -> None:
    if origin in HISTORICAL_ORIGINS or origin != R9_ROW_ORIGIN:
        raise ProtocolBlocked("historical development rows are forbidden in R9 ledger")
    if protocol_freeze_date != PROTOCOL_FREEZE_DATE:
        raise ProtocolBlocked("protocol freeze date override is forbidden")
    if row_date <= PROTOCOL_FREEZE_DATE:
        raise ProtocolBlocked("pre-freeze rows are forbidden in clean R9")
    if frozen_calendar is not None:
        raise ProtocolBlocked("freeze boundary calendar cannot validate future R9 rows")
    if run_calendar is None:
        raise ProtocolBlocked("explicit R9 run calendar is required")
    if oos_start is not None and oos_start != R9_OOS_START:
        raise ProtocolBlocked("OOS start override is forbidden")
    try:
        validate_run_calendar(run_calendar)
        if row_date not in run_calendar.sessions:
            raise Gate2BBlocked("date is absent from R9 run calendar")
        assert_clean_oos_candidate_date(
            candidate_date=row_date,
            protocol_freeze_date=PROTOCOL_FREEZE_DATE,
            calendar=run_calendar,
            oos_start=R9_OOS_START,
        )
    except Gate2BBlocked as exc:
        raise ProtocolBlocked(str(exc)) from exc


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
    return RIGHT_LABELED_5M_GRID


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
        {"section": "population", "key": "R9_SETUP_ID", "value": R9_SETUP_ID_RULE, "status": "PASS"},
        {"section": "population", "key": "R9_POPULATION_STATUS", "value": R9_POPULATION_STATUS, "status": "PASS"},
        {"section": "ttl", "key": "R9_ADMINISTRATIVE_TTL_VERSION", "value": R9_ADMINISTRATIVE_TTL_VERSION, "status": "PASS"},
        {"section": "ttl", "key": "TTL_SELECTION_BASIS", "value": R9_TTL_SELECTION_BASIS, "status": "PASS"},
        {"section": "ttl", "key": "R9_OBSERVATION_TTL", "value": f"{R9_OBSERVATION_TTL}_{R9_TTL_UNIT}", "status": "PASS"},
        {"section": "ttl", "key": "TTL_ANCHOR", "value": R9_TTL_ANCHOR, "status": "PASS"},
        {"section": "ttl", "key": "TTL_WINDOW", "value": R9_TTL_WINDOW, "status": "PASS"},
        {"section": "ttl", "key": "STRUCTURAL_INVALIDATION_STATUS", "value": R9_STRUCTURAL_INVALIDATION_STATUS, "status": "PASS"},
        {"section": "event", "key": "FIRST_S1_TOUCH_EVENT", "value": FIRST_S1_TOUCH_EVENT, "status": "PASS"},
        {"section": "event", "key": "REPEAT_CONFIRMATION_CREATES_NEW_EVENT", "value": "FALSE", "status": "PASS"},
        {"section": "event", "key": "PROSPECTIVE_EVENT_ELIGIBILITY", "value": R9_PROSPECTIVE_EVENT_ELIGIBILITY_STATUS, "status": "PASS"},
        {"section": "intraday", "key": "R9_PRIMARY_CHECKPOINT", "value": R9_PRIMARY_CHECKPOINT, "status": "PASS"},
        {"section": "intraday", "key": "PRIMARY_INTRADAY_FEATURE", "value": PRIMARY_INTRADAY_FEATURE, "status": "PASS"},
        {"section": "daily", "key": "PRIMARY_DAILY_COMPARISON", "value": PRIMARY_DAILY_COMPARISON, "status": "PASS"},
        {"section": "daily", "key": "M2_ROLE", "value": M2_ROLE, "status": "PASS"},
        {"section": "daily", "key": "M2_SCORE_SEMANTICS", "value": M2_SCORE_SEMANTICS, "status": "PASS"},
        {"section": "daily", "key": "R7_COEFFICIENTS_SHA", "value": R7_COEFFICIENTS_SHA, "status": "PASS"},
        {"section": "endpoint", "key": "PRIMARY_ENDPOINT", "value": PRIMARY_ENDPOINT, "status": "PASS"},
        {"section": "endpoint", "key": "SENSITIVITY_ENDPOINT", "value": SENSITIVITY_ENDPOINT, "status": "PASS"},
        {"section": "uncertainty", "key": "SYMBOL_CLUSTER_BOOTSTRAP", "value": str(N_BOOTSTRAP), "status": "PASS"},
        {"section": "uncertainty", "key": "TRADE_WEEK_BLOCK_BOOTSTRAP", "value": str(N_BOOTSTRAP), "status": "PASS"},
        {"section": "stopping", "key": "INITIAL_WINDOW_A_SHARE_SESSIONS", "value": str(INITIAL_OBSERVATION_WINDOW_A_SHARE_SESSIONS), "status": "PASS"},
        {"section": "provenance", "key": "ASL_CODE_SHA", "value": ASL_CODE_SHA, "status": "PASS"},
        {"section": "provenance", "key": "R9_ASL_DATA_ROOT", "value": R9_ASL_DATA_ROOT, "status": "PASS"},
        {"section": "provenance", "key": "PROTOCOL_FREEZE_DATE", "value": PROTOCOL_FREEZE_DATE.isoformat(), "status": "PASS"},
        {"section": "provenance", "key": "PROTOCOL_FREEZE_CALENDAR_VERSION", "value": PROTOCOL_FREEZE_CALENDAR_VERSION, "status": "PASS"},
        {"section": "provenance", "key": "PROTOCOL_FREEZE_CALENDAR_ARTIFACT", "value": PROTOCOL_FREEZE_CALENDAR_ARTIFACT, "status": "PASS"},
        {"section": "provenance", "key": "PROTOCOL_FREEZE_CALENDAR_HASH", "value": PROTOCOL_FREEZE_CALENDAR_MANIFEST_HASH, "status": "PASS"},
        {"section": "provenance", "key": "OOS_START", "value": R9_OOS_START.isoformat(), "status": "PASS"},
        {"section": "provenance", "key": "R9_RUN_CALENDAR_AUTHORITY_VERSION", "value": R9_RUN_CALENDAR_AUTHORITY_VERSION, "status": "PASS"},
        {"section": "provenance", "key": "R9_RUN_CALENDAR_AUTHORITY_ARTIFACT", "value": R9_RUN_CALENDAR_AUTHORITY_ARTIFACT, "status": "PASS"},
        {"section": "provenance", "key": "R9_RUN_CALENDAR_VERSION", "value": R9_RUN_CALENDAR_VERSION, "status": "PASS"},
        {"section": "provenance", "key": "R9_RUN_CALENDAR_ARTIFACT", "value": R9_RUN_CALENDAR_ARTIFACT, "status": "PASS"},
        {"section": "provenance", "key": "R9_RUN_CALENDAR_MANIFEST_HASH", "value": R9_RUN_CALENDAR_MANIFEST_HASH, "status": "PASS"},
        {"section": "provenance", "key": "R9_RUN_CALENDAR_ASL_COMMIT", "value": R9_RUN_CALENDAR_SOURCE_COMMIT, "status": "PASS"},
        {"section": "provenance", "key": "R9_RUN_CALENDAR_ASL_BLOB_SHA", "value": R9_RUN_CALENDAR_SOURCE_GIT_BLOB_SHA, "status": "PASS"},
        {"section": "provenance", "key": "PROTOCOL_FREEZE_RECEIPT_TAG", "value": PROTOCOL_FREEZE_RECEIPT_TAG, "status": "PASS"},
        {"section": "authorization", "key": "R9_ACCUMULATION_WRITE_AUTHORITY", "value": R9_ACCUMULATION_WRITE_AUTHORITY, "status": "PASS"},
        {"section": "publication", "key": "ATOMIC_PUBLICATION_STEPS", "value": " -> ".join(ATOMIC_PUBLICATION_STEPS), "status": "PASS"},
        {"section": "gate", "key": "GATE_1_R1_AUTHORITY_BOUNDARY", "value": "PASS", "status": "PASS"},
        {"section": "gate", "key": "GATE_2A_PROSPECTIVE_POPULATION", "value": "PASS", "status": "PASS"},
        {"section": "gate", "key": "GATE_2B_OBSERVATION_TTL", "value": "PASS_OWNER_FROZEN_V01", "status": "PASS"},
        {"section": "gate", "key": "GATE_2_POPULATION_EVENT_TTL", "value": "PASS", "status": "PASS"},
        {"section": "gate", "key": "GATE_3_INDEPENDENT_ENDPOINT", "value": "PASS", "status": "PASS"},
        {"section": "gate", "key": "GATE_4_MULTIPLICITY_UNCERTAINTY", "value": "PASS", "status": "PASS"},
        {"section": "gate", "key": "GATE_5_ASL_PROVENANCE_ATOMICITY", "value": "PASS", "status": "PASS"},
        {"section": "authorization", "key": "PRE_R9_STATUS", "value": PRE_R9_STATUS, "status": "PASS"},
        {"section": "authorization", "key": "R9_RECOMMENDATION", "value": R9_RECOMMENDATION, "status": "PASS"},
        {"section": "authorization", "key": "R9_OOS_ROWS_WRITTEN", "value": str(R9_OOS_ROWS_WRITTEN), "status": "PASS"},
    ]
