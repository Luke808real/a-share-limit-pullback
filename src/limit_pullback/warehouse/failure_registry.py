"""Typed provider-failure registry for ADR-008 staging runs.

Every provider failure is persisted as a portable JSONL record so the
run-level report can answer why a specific symbol/date is not CONFIRMED.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from limit_pullback.providers.errors import (
    ProviderError,
    provider_failure_record,
)

UNCLASSIFIED_CLASSES = frozenset(
    {"ProviderUnexpectedError", "ProviderError", "Exception"}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProviderFailureRegistry:
    """Collects and serializes typed provider failures for one run."""

    def __init__(self, *, run_id: str, path: Path | None = None) -> None:
        self.run_id = run_id
        self.path = path
        self._records: list[dict[str, Any]] = []

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._records)

    def record(
        self,
        *,
        provider: str,
        error: ProviderError | None = None,
        code: str | None = None,
        requested_from: date | None = None,
        requested_to: date | None = None,
        attempt: int = 1,
        failure_class: str = "ProviderUnexpectedError",
        failure_message: str = "",
        retryable: bool = False,
        final_status: str = "FAILED",
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        if error is not None:
            record = provider_failure_record(
                run_id=self.run_id,
                provider=provider,
                error=error,
                code=code,
                final_status=final_status,
                observed_at=observed_at,
            )
        else:
            record = {
                "run_id": self.run_id,
                "provider": provider,
                "code": code,
                "requested_from": (
                    requested_from.isoformat() if requested_from else None
                ),
                "requested_to": (
                    requested_to.isoformat() if requested_to else None
                ),
                "attempt": attempt,
                "failure_class": failure_class,
                "failure_message": failure_message,
                "retryable": bool(retryable),
                "final_status": final_status,
                "observed_at": (observed_at or _utc_now()).isoformat(
                    timespec="seconds"
                ),
            }
        self._records.append(record)
        return record

    def count(self, *, provider: str | None = None) -> int:
        return sum(
            1
            for record in self._records
            if provider is None or record["provider"] == provider
        )

    def unclassified_count(self) -> int:
        return sum(
            1
            for record in self._records
            if record["failure_class"] in UNCLASSIFIED_CLASSES
        )

    def write(self) -> Path | None:
        if self.path is None:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as stream:
            for record in self._records:
                stream.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
        return self.path

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self._records:
            counts[record["failure_class"]] = (
                counts.get(record["failure_class"], 0) + 1
            )
        return dict(sorted(counts.items()))


def read_failure_registry(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                records.append(json.loads(line))
    return tuple(records)
