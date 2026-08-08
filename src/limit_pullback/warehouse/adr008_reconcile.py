"""Whole-row ADR-008 reconciliation: TDX primary, Tencent confirmation.

Hard constraint: NO_FIELD_LEVEL_PROVIDER_MERGE.  A candidate row is the TDX
row in its entirety; Tencent only confirms or conflicts with it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from limit_pullback.providers.tencent_daily import detect_tencent_volume_unit
from limit_pullback.warehouse.reconciliation import (
    CONFIRMED,
    CONFLICTED,
    PROVISIONAL,
    ReconciliationPolicy,
)


def _price_close(left: Decimal, right: Decimal, policy: ReconciliationPolicy) -> bool:
    difference = abs(left - right)
    scale = max(abs(left), abs(right))
    return difference <= max(
        policy.price_absolute,
        policy.price_relative * scale,
    )


def _volume_close(left: Decimal, right: Decimal, policy: ReconciliationPolicy) -> bool:
    scale = max(abs(left), abs(right))
    if scale == 0:
        return left == right
    return abs(left - right) <= policy.volume_relative * scale


def _unique_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, bool]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        unique[str(row["raw_hash"])] = dict(row)
    if len(unique) == 1:
        return next(iter(unique.values())), True
    return None, False


def reconcile_adr008_rows(
    tdx_rows: Sequence[Mapping[str, Any]],
    tencent_rows: Sequence[Mapping[str, Any]],
    *,
    policy: ReconciliationPolicy | None = None,
) -> list[dict[str, Any]]:
    """Reconcile TDX (primary) against Tencent (confirmation), whole-row.

    Returns one candidate row per (code, date) with a TDX row.  Statuses:
    CONFIRMED (TDX + Tencent + OHLC/volume/amount agreement), PROVISIONAL
    (TDX only), or CONFLICTED (both present but agreement failed or a provider
    emitted duplicate rows for the same key).
    """

    policy = policy or ReconciliationPolicy()
    tdx_by_key: dict[tuple[str, date], list[dict[str, Any]]] = {}
    tx_by_key: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for row in tdx_rows:
        tdx_by_key.setdefault((row["code"], row["trade_date"]), []).append(
            dict(row)
        )
    for row in tencent_rows:
        tx_by_key.setdefault((row["code"], row["trade_date"]), []).append(
            dict(row)
        )

    candidates: list[dict[str, Any]] = []
    for key in sorted(set(tdx_by_key) | set(tx_by_key)):
        code, trade_date = key
        tdx_row, tdx_unique = _unique_rows(tdx_by_key.get(key, ()))
        tx_row, tx_unique = _unique_rows(tx_by_key.get(key, ()))
        if tdx_row is None:
            continue  # staging service emits INCOMPLETE rows for the universe

        candidate = dict(tdx_row)
        candidate["selected_provider"] = "TDX"
        candidate["selected_source_hash"] = tdx_row["raw_hash"]
        candidate["confirmation_provider"] = None
        candidate["confirmation_source_hash"] = None
        candidate["tencent_volume_unit"] = None
        candidate["reconciliation_detail"] = None

        if tx_row is None:
            candidate["reconciliation_status"] = PROVISIONAL
            candidates.append(candidate)
            continue
        if not tdx_unique or not tx_unique:
            candidate["reconciliation_status"] = CONFLICTED
            candidate["reconciliation_detail"] = "PROVIDER_INTERNAL_CONFLICT"
            candidates.append(candidate)
            continue

        unit, tx_shares, _ratio = detect_tencent_volume_unit(
            tx_row["volume_raw"],
            tdx_row["volume"],
            volume_relative_tolerance=policy.volume_relative,
        )
        ohlc_ok = all(
            _price_close(
                Decimal(str(tdx_row[field])),
                Decimal(str(tx_row[field])),
                policy,
            )
            for field in ("open", "high", "low", "close")
        )
        volume_ok = unit != "UNKNOWN" and tx_shares is not None
        amount_ok = _volume_close(
            Decimal(str(tdx_row["amount"])),
            Decimal(str(tx_row["amount"])),
            policy,
        )
        candidate["tencent_volume_unit"] = unit
        if ohlc_ok and volume_ok and amount_ok:
            candidate["reconciliation_status"] = CONFIRMED
            candidate["confirmation_provider"] = "TENCENT"
            candidate["confirmation_source_hash"] = tx_row["raw_hash"]
        else:
            candidate["reconciliation_status"] = CONFLICTED
            candidate["reconciliation_detail"] = (
                f"OHLC={ohlc_ok};VOLUME_UNIT={unit};AMOUNT={amount_ok}"
            )
        candidates.append(candidate)

    candidates.sort(key=lambda row: (row["code"], row["trade_date"]))
    return candidates
