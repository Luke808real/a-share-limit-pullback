"""Typed provider errors shared by every ADR-008 provider adapter.

The ADR-008 active path never swallows provider failures: every failure is
either raised as a typed ``ProviderError`` subclass or returned as a typed
failure record so the run-level report can answer why a row is missing.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProviderError(RuntimeError):
    """Base class for typed provider failures."""

    code = "PROVIDER_ERROR"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        code: str | None = None,
        requested_from: date | None = None,
        requested_to: date | None = None,
        attempt: int = 1,
        run_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.error_code = code or self.code
        self.requested_from = requested_from
        self.requested_to = requested_to
        self.attempt = attempt
        self.run_id = run_id
        self.failure_class = type(self).__name__
        super().__init__(f"{self.error_code}:{provider}:{message}")


class ProviderTimeoutError(ProviderError):
    code = "PROVIDER_TIMEOUT"
    retryable = True


class ProviderConnectionError(ProviderError):
    code = "PROVIDER_CONNECTION"
    retryable = True


class ProviderSchemaError(ProviderError):
    code = "PROVIDER_SCHEMA"
    retryable = False


class ProviderEmptyResultError(ProviderError):
    code = "PROVIDER_EMPTY_RESULT"
    retryable = False


class ProviderMalformedRowError(ProviderError):
    code = "PROVIDER_MALFORMED_ROW"
    retryable = False


class ProviderCoverageError(ProviderError):
    code = "PROVIDER_COVERAGE"
    retryable = False


class ProviderUnexpectedError(ProviderError):
    """Wrapper for unknown exceptions; never swallowed, always attributable."""

    code = "PROVIDER_UNEXPECTED"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        original_type: str,
        requested_from: date | None = None,
        requested_to: date | None = None,
        attempt: int = 1,
        run_id: str | None = None,
    ) -> None:
        self.original_type = original_type
        super().__init__(
            message,
            provider=provider,
            requested_from=requested_from,
            requested_to=requested_to,
            attempt=attempt,
            run_id=run_id,
        )

    @classmethod
    def wrap(
        cls,
        exc: BaseException,
        *,
        provider: str,
        requested_from: date | None = None,
        requested_to: date | None = None,
        attempt: int = 1,
        run_id: str | None = None,
    ) -> "ProviderUnexpectedError":
        return cls(
            str(exc),
            provider=provider,
            original_type=type(exc).__name__,
            requested_from=requested_from,
            requested_to=requested_to,
            attempt=attempt,
            run_id=run_id,
        )


def provider_failure_record(
    *,
    run_id: str,
    provider: str,
    error: ProviderError,
    code: str | None,
    final_status: str,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Convert a typed error into the portable failure-registry record shape."""

    return {
        "run_id": run_id,
        "provider": provider,
        "code": code,
        "requested_from": (
            error.requested_from.isoformat() if error.requested_from else None
        ),
        "requested_to": (
            error.requested_to.isoformat() if error.requested_to else None
        ),
        "attempt": error.attempt,
        "failure_class": error.failure_class,
        "failure_message": str(error),
        "retryable": bool(error.retryable),
        "final_status": final_status,
        "observed_at": (observed_at or _utc_now()).isoformat(timespec="seconds"),
    }
