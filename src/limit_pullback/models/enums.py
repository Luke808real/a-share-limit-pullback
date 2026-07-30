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


class ScoreProfile(StrEnum):
    FULL = "FULL"
    PRICE_ONLY = "PRICE_ONLY"


class PatternType(StrEnum):
    AIR_REFUEL = "AIR_REFUEL"
    BEARISH_PULLBACK = "BEARISH_PULLBACK"
