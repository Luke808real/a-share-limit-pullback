"""Explicit cross-provider reconciliation and canonical selection."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from pydantic import Field

from limit_pullback.models.base import DecimalValue, DomainModel
from limit_pullback.warehouse.models import (
    QuarantineRecord,
    ReconciliationRecord,
)

PROVISIONAL = "PROVISIONAL"
CONFIRMED = "CONFIRMED"
INCOMPLETE = "INCOMPLETE"
CONFLICTED = "CONFLICTED"
QUARANTINED = "QUARANTINED"


class ReconciliationPolicy(DomainModel):
    """Tolerances only absorb formatting/unit micro-differences."""

    price_relative: DecimalValue = Decimal("0.001")
    price_absolute: DecimalValue = Decimal("0.01")
    volume_relative: DecimalValue = Decimal("0.005")
    policy_version: str = Field(default="phase-2c2a-r1", min_length=1)


def _identifier(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _close(left: Decimal, right: Decimal, policy: ReconciliationPolicy) -> bool:
    difference = abs(left - right)
    scale = max(abs(left), abs(right))
    return difference <= max(policy.price_absolute, policy.price_relative * scale)


def _close_volume(
    left: Decimal, right: Decimal, policy: ReconciliationPolicy
) -> bool:
    scale = max(abs(left), abs(right))
    if scale == 0:
        return left == right
    return abs(left - right) <= policy.volume_relative * scale


def _group_by_key(
    rows_by_provider: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[tuple[str, date], dict[str, list[dict[str, Any]]]]:
    grouped: dict[tuple[str, date], dict[str, list[dict[str, Any]]]] = {}
    for provider, rows in rows_by_provider.items():
        for row in rows:
            key = (str(row["code"]), row["trade_date"])
            grouped.setdefault(key, {}).setdefault(provider, []).append(dict(row))
    return grouped


def _prices_match(left: Mapping[str, Any], right: Mapping[str, Any], policy: ReconciliationPolicy) -> bool:
    for field in ("open", "high", "low", "close", "preclose"):
        left_value = left.get(field)
        right_value = right.get(field)
        if left_value is None or right_value is None:
            continue
        if not _close(Decimal(left_value), Decimal(right_value), policy):
            return False
    for field in ("volume", "amount"):
        if not _close_volume(Decimal(left[field]), Decimal(right[field]), policy):
            return False
    return True


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def reconcile_daily_rows(
    rows_by_provider: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    policy: ReconciliationPolicy | None = None,
    snapshot_id: str | None = None,
    clock=None,
) -> tuple[list[dict[str, Any]], list[ReconciliationRecord], list[QuarantineRecord]]:
    """Return (canonical rows, reconciliation records, quarantine records).

    Canonical rows are emitted only for CONFIRMED pairs. Conflicts are
    quarantined and never published. Rows are never merged field-by-field
    across providers.
    """

    policy = policy or ReconciliationPolicy()
    now = (clock or _now_utc)()
    canonical: list[dict[str, Any]] = []
    reconciliations: list[ReconciliationRecord] = []
    quarantines: list[QuarantineRecord] = []

    for (code, trade_date), provider_rows in _group_by_key(rows_by_provider).items():
        usable: dict[str, dict[str, Any]] = {}
        for provider, rows in provider_rows.items():
            unique: dict[str, dict[str, Any]] = {}
            for row in rows:
                unique[row["row_hash"]] = row
            if len(unique) == 1:
                usable[provider] = next(iter(unique.values()))
            else:
                reason = "PROVIDER_INTERNAL_CONFLICT"
                quarantines.append(
                    QuarantineRecord(
                        record_id=_identifier(code, trade_date, provider, reason),
                        code=code,
                        trade_date=trade_date,
                        providers=(provider,),
                        reason=reason,
                        payload=json.dumps(rows, ensure_ascii=False, default=str, sort_keys=True),
                        created_at=now,
                    )
                )
                reconciliations.append(
                    ReconciliationRecord(
                        reconciliation_id=_identifier(
                            code, trade_date, provider, QUARANTINED, snapshot_id or ""
                        ),
                        code=code,
                        trade_date=trade_date,
                        providers=(provider,),
                        status=QUARANTINED,
                        notes=reason,
                        created_at=now,
                        snapshot_id=snapshot_id,
                    )
                )

        providers = tuple(sorted(usable))
        if not providers:
            continue

        conflict: str | None = None
        provider_list = list(usable)
        for index in range(len(provider_list)):
            for other in provider_list[index + 1 :]:
                if not _prices_match(usable[provider_list[index]], usable[other], policy):
                    conflict = f"OHLC_CONFLICT:{provider_list[index]}vs{other}"
                    break
            if conflict:
                break

        if conflict is not None:
            payload = {provider: row for provider, row in usable.items()}
            quarantines.append(
                QuarantineRecord(
                    record_id=_identifier(code, trade_date, conflict),
                    code=code,
                    trade_date=trade_date,
                    providers=providers,
                    reason=conflict,
                    payload=json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True),
                    created_at=now,
                )
            )
            reconciliations.append(
                ReconciliationRecord(
                    reconciliation_id=_identifier(
                        code, trade_date, providers, CONFLICTED, snapshot_id or ""
                    ),
                    code=code,
                    trade_date=trade_date,
                    providers=providers,
                    status=CONFLICTED,
                    selected_provider=None,
                    notes=conflict,
                    created_at=now,
                    snapshot_id=snapshot_id,
                )
            )
            continue

        if "TUSHARE" in usable and "AKSHARE" in usable:
            status = CONFIRMED
            selected = "TUSHARE"
            notes: list[str] = ["TUSHARE_AKSHARE_AGREEMENT"]
            if "BAOSTOCK" not in usable:
                notes.append("BAOSTOCK_LAGGING")
        elif len(providers) == 1:
            status = PROVISIONAL
            selected = providers[0]
            notes = ["SINGLE_SOURCE"]
        else:
            status = PROVISIONAL
            selected = (
                "TUSHARE" if "TUSHARE" in usable else "AKSHARE" if "AKSHARE" in usable else "BAOSTOCK"
            )
            notes = ["PARTIAL_CROSS_VALIDATION"]

        source = usable[selected]
        canonical_row = dict(source)
        canonical_row["selected_provider"] = selected
        canonical_row["reconciliation_status"] = status
        canonical_row["source_row_hash"] = source["row_hash"]
        canonical.append(canonical_row)
        reconciliations.append(
            ReconciliationRecord(
                reconciliation_id=_identifier(
                    code, trade_date, providers, status, snapshot_id or ""
                ),
                code=code,
                trade_date=trade_date,
                providers=providers,
                status=status,
                selected_provider=selected,
                notes=";".join(notes),
                created_at=now,
                snapshot_id=snapshot_id,
            )
        )

    canonical.sort(key=lambda row: (row["code"], row["trade_date"]))
    return canonical, reconciliations, quarantines


def reconcile_limit_up_pool(
    rows: Sequence[Mapping[str, Any]],
    *,
    snapshot_id: str | None = None,
    clock=None,
) -> tuple[list[dict[str, Any]], list[ReconciliationRecord], list[QuarantineRecord]]:
    """The limit-up pool is AKShare-owned; rows stay whole and PROVISIONAL.

    Distinct rows for the same (code, date) are a same-source conflict and go
    to quarantine instead of being silently resolved.
    """

    now = (clock or _now_utc)()
    canonical: list[dict[str, Any]] = []
    records: list[ReconciliationRecord] = []
    quarantines: list[QuarantineRecord] = []
    grouped: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["code"]), row["trade_date"]), []).append(dict(row))
    for (code, trade_date), group in sorted(grouped.items()):
        unique = {row["row_hash"]: row for row in group}
        if len(unique) > 1:
            reason = "PROVIDER_INTERNAL_CONFLICT"
            quarantines.append(
                QuarantineRecord(
                    record_id=_identifier(code, trade_date, "AKSHARE", reason),
                    code=code,
                    trade_date=trade_date,
                    providers=("AKSHARE",),
                    reason=reason,
                    payload=json.dumps(group, ensure_ascii=False, default=str, sort_keys=True),
                    created_at=now,
                )
            )
            records.append(
                ReconciliationRecord(
                    reconciliation_id=_identifier(
                        code, trade_date, "AKSHARE", QUARANTINED, snapshot_id or ""
                    ),
                    code=code,
                    trade_date=trade_date,
                    providers=("AKSHARE",),
                    status=QUARANTINED,
                    selected_provider="AKSHARE",
                    notes=reason,
                    created_at=now,
                    snapshot_id=snapshot_id,
                )
            )
            continue
        row = next(iter(unique.values()))
        canonical_row = dict(row)
        canonical_row["selected_provider"] = "AKSHARE"
        canonical_row["reconciliation_status"] = PROVISIONAL
        canonical_row["source_row_hash"] = row["row_hash"]
        canonical.append(canonical_row)
        records.append(
            ReconciliationRecord(
                reconciliation_id=_identifier(
                    code, trade_date, "AKSHARE", PROVISIONAL, snapshot_id or ""
                ),
                code=code,
                trade_date=trade_date,
                providers=("AKSHARE",),
                status=PROVISIONAL,
                selected_provider="AKSHARE",
                notes="SINGLE_SOURCE_LIMIT_POOL",
                created_at=now,
                snapshot_id=snapshot_id,
            )
        )
    canonical.sort(key=lambda item: (item["code"], item["trade_date"]))
    return canonical, records, quarantines
