from enum import StrEnum


class SetupStage(StrEnum):
    NORMAL = "NORMAL"
    LIMIT_ANCHOR = "LIMIT_ANCHOR"
    WATCH_PULLBACK = "WATCH_PULLBACK"
    B1_READY = "B1_READY"
    B2_READY = "B2_READY"
    B2_CONFIRMED = "B2_CONFIRMED"
    INVALID = "INVALID"


class EventFlag(StrEnum):
    NEAR_S1 = "NEAR_S1"
    S1_BREAKOUT = "S1_BREAKOUT"
    S2_EXHAUSTED = "S2_EXHAUSTED"
    SUPPORT_WARNING = "SUPPORT_WARNING"


class ReviewGroup(StrEnum):
    STANDARD = "STANDARD"
    OPEN_SPACE = "OPEN_SPACE"


class DataQuality(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    UNUSABLE = "UNUSABLE"


class EvaluationMode(StrEnum):
    STATELESS_INSPECT = "STATELESS_INSPECT"
    POINT_IN_TIME_REPLAY = "POINT_IN_TIME_REPLAY"


class ScoreProfile(StrEnum):
    FULL = "FULL"
    PRICE_ONLY = "PRICE_ONLY"


class PatternType(StrEnum):
    AIR_REFUEL = "AIR_REFUEL"
    BEARISH_PULLBACK = "BEARISH_PULLBACK"


class EntryRoomState(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    THIN = "THIN"
    NONE = "NONE"
    OPEN_SPACE = "OPEN_SPACE"


class SetupTerminationReason(StrEnum):
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED_BY_NEW_ANCHOR = "SUPERSEDED_BY_NEW_ANCHOR"
    EXPIRED = "EXPIRED"


class ExecutionLabel(StrEnum):
    """Post-close execution label; not a setup lifecycle state."""

    B1_PREP = "B1_PREP"
    B1_READY = "B1_READY"
    B2_READY = "B2_READY"
    B2_CONFIRMED = "B2_CONFIRMED"
    WATCH_ONLY = "WATCH_ONLY"


class OutcomeStatus(StrEnum):
    """Research-only outcome labels; they do not alter strategy semantics."""

    NO_FILL = "NO_FILL"
    CANCEL_GAP_INVALID = "CANCEL_GAP_INVALID"
    WIN_S1 = "WIN_S1"
    LOSS_INVALID = "LOSS_INVALID"
    TIMEOUT = "TIMEOUT"
    AMBIGUOUS_INTRADAY = "AMBIGUOUS_INTRADAY"
    CENSORED = "CENSORED"


class FillStatus(StrEnum):
    """Research-only first-session fill status."""

    NO_FILL = "NO_FILL"
    CANCEL_GAP_INVALID = "CANCEL_GAP_INVALID"
    FILLED = "FILLED"
    CENSORED = "CENSORED"


class PatternOutcome(StrEnum):
    """Direction-only pattern result, separate from trade outcome."""

    S1_BEFORE_INVALID = "S1_BEFORE_INVALID"
    INVALID_BEFORE_S1 = "INVALID_BEFORE_S1"
    NEITHER = "NEITHER"
    AMBIGUOUS = "AMBIGUOUS"
    CENSORED = "CENSORED"
