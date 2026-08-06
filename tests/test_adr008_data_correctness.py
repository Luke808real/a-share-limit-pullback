"""PR-B ADR-008 data correctness + lineage regression tests."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from limit_pullback.providers.errors import (
    ProviderConnectionError,
    ProviderMalformedRowError,
    ProviderUnexpectedError,
)
from limit_pullback.providers.tdx_daily import (
    TDX_DAILY_VOLUME_MULTIPLIER,
    normalize_tdx_daily_row,
)
from limit_pullback.providers.tencent_daily import (
    detect_tencent_volume_unit,
    fetch_tencent_daily,
    normalize_tencent_daily_row,
)
from limit_pullback.warehouse.adr008_reconcile import reconcile_adr008_rows
from limit_pullback.warehouse.continuity import (
    MISSING_PREDECESSOR,
    OK as PRECLOSE_OK,
    build_sequential_preclose,
)
from limit_pullback.warehouse.failure_registry import (
    ProviderFailureRegistry,
    read_failure_registry,
)
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.parquet import sha256_file, write_rows_atomic
from limit_pullback.warehouse.snapshot import SnapshotUsabilityError
from limit_pullback.warehouse.staging import (
    run_adr008_staging,
    staging_candidate_schema,
)
from tests.test_screen import _build_warehouse


def _tdx_row(
    code: str,
    day: date,
    *,
    close: str,
    volume_lots: int,
    raw_hash: str,
    open_price: str | None = None,
) -> dict:
    price = Decimal(close)
    return {
        "code": code,
        "trade_date": day,
        "open": float(open_price or close),
        "high": float(price + Decimal("0.01")),
        "low": float(price - Decimal("0.01")),
        "close": float(price),
        "volume_lots": float(volume_lots),
        "amount": float(price * volume_lots * 100),
        "raw_hash": raw_hash,
    }


def _tx_row(
    code: str,
    day: date,
    *,
    close: str,
    volume_lots: int,
    raw_hash: str,
    unit: str = "LOTS",
) -> dict:
    price = Decimal(close)
    raw_volume = volume_lots if unit == "LOTS" else volume_lots * 100
    return {
        "code": code,
        "trade_date": day,
        "open": float(close),
        "high": float(price + Decimal("0.01")),
        "low": float(price - Decimal("0.01")),
        "close": float(price),
        "volume_shares": float(raw_volume),
        "amount": float(price * volume_lots * 100),
        "raw_hash": raw_hash,
    }


def _new_sessions(dates: list[date], count: int = 3) -> list[date]:
    out: list[date] = []
    current = dates[-1]
    while len(out) < count:
        current += timedelta(days=1)
        if current.weekday() < 5:
            out.append(current)
    return out


def _run_staging(
    layout,
    seed_snapshot_id: str,
    sessions: list[date],
    tdx_rows,
    tx_rows,
    *,
    run_id: str = "test-adr008",
    tdx_artifact_path=None,
    tencent_artifact_path=None,
):
    return run_adr008_staging(
        layout,
        run_id=run_id,
        seed_snapshot_id=seed_snapshot_id,
        sessions=sessions,
        tdx_raw_rows=tdx_rows,
        tencent_raw_rows=tx_rows,
        tdx_artifact_path=tdx_artifact_path,
        tencent_artifact_path=tencent_artifact_path,
    )


def test_adr008_sequential_preclose_three_sessions():
    sessions = [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)]
    rows = {
        ("000001", sessions[0]): {"close": Decimal("11.62")},
        ("000001", sessions[1]): {"close": Decimal("11.44")},
        ("000001", sessions[2]): {"close": Decimal("11.25")},
    }
    staged = build_sequential_preclose(
        rows,
        seed_previous_close={"000001": Decimal("11.63")},
        ordered_sessions=sessions,
    )
    assert staged[("000001", sessions[0])]["preclose"] == Decimal("11.63")
    assert staged[("000001", sessions[1])]["preclose"] == Decimal("11.62")
    assert staged[("000001", sessions[2])]["preclose"] == Decimal("11.44")
    assert all(
        staged[key]["preclose_status"] == PRECLOSE_OK
        for key in staged
    )


def test_adr008_weekend_previous_session():
    friday = date(2026, 7, 31)
    monday = date(2026, 8, 3)
    rows = {
        ("000001", monday): {"close": Decimal("12.00")},
    }
    staged = build_sequential_preclose(
        rows,
        seed_previous_close={"000001": Decimal("11.50")},
        ordered_sessions=[friday, monday],
    )
    assert staged[("000001", monday)]["preclose"] == Decimal("11.50")


def test_adr008_real_000001_regression():
    sessions = [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)]
    rows = {
        ("000001", sessions[0]): {"close": Decimal("11.62")},
        ("000001", sessions[1]): {"close": Decimal("11.44")},
        ("000001", sessions[2]): {"close": Decimal("11.25")},
    }
    staged = build_sequential_preclose(
        rows,
        seed_previous_close={"000001": Decimal("11.63")},
        ordered_sessions=sessions,
    )
    assert staged[("000001", sessions[2])]["preclose"] == Decimal("11.44")
    assert staged[("000001", sessions[2])]["pct_change"] == Decimal("-1.6608")


def test_adr008_existing_continuity_validator_is_called(tmp_path, monkeypatch):
    layout, dates, sid = _build_warehouse(tmp_path)
    sessions = _new_sessions(dates, 2)
    calls: list[dict] = []
    import limit_pullback.warehouse.staging as staging_mod
    from limit_pullback.warehouse.validate import preclose_continuity_issues as real

    def spy(rows, *, previous_close_index, provider_label):
        calls.append(
            {"rows": len(rows), "provider": provider_label}
        )
        return real(rows, previous_close_index=previous_close_index, provider_label=provider_label)

    monkeypatch.setattr(staging_mod, "preclose_continuity_issues", spy)
    tdx = [
        _tdx_row("603318", sessions[0], close="11.00", volume_lots=1000, raw_hash="t1"),
    ]
    _run_staging(layout, sid, sessions, tdx, [])
    assert calls and calls[0]["provider"] == "TDX"


def test_adr008_continuity_failure_blocks_publish_eligibility(tmp_path, monkeypatch):
    layout, dates, sid = _build_warehouse(tmp_path)
    sessions = _new_sessions(dates, 3)
    tdx = [
        _tdx_row("603318", sessions[0], close="11.00", volume_lots=1000, raw_hash="t1"),
        _tdx_row("603318", sessions[1], close="11.20", volume_lots=1100, raw_hash="t2"),
        _tdx_row("603318", sessions[2], close="11.30", volume_lots=1200, raw_hash="t3"),
    ]
    import limit_pullback.warehouse.staging as staging_mod

    def bad_builder(rows_by_code_session, *, seed_previous_close, ordered_sessions):
        fixed = dict(seed_previous_close)
        out = {}
        for (code, day), row in rows_by_code_session.items():
            copied = dict(row)
            copied["preclose"] = fixed.get(code)
            copied["preclose_status"] = (
                PRECLOSE_OK if code in fixed else MISSING_PREDECESSOR
            )
            copied["pct_change"] = None
            out[(code, day)] = copied
        return out

    monkeypatch.setattr(staging_mod, "build_sequential_preclose", bad_builder)
    result = _run_staging(layout, sid, sessions, tdx, [])
    assert result.preclose_continuity_mismatch_n >= 2
    assert result.publish_eligible is False
    assert result.stage_status == "VALIDATION_FAILED"


def test_adr008_mutation_seed_reuse_detected(tmp_path, monkeypatch):
    """Adversarial: reusing the seed close for every session must go red."""

    layout, dates, sid = _build_warehouse(tmp_path)
    sessions = _new_sessions(dates, 3)
    tdx = [
        _tdx_row("603318", sessions[0], close="11.00", volume_lots=1000, raw_hash="t1"),
        _tdx_row("603318", sessions[1], close="11.20", volume_lots=1100, raw_hash="t2"),
        _tdx_row("603318", sessions[2], close="11.30", volume_lots=1200, raw_hash="t3"),
    ]
    import limit_pullback.warehouse.staging as staging_mod

    def fixed_seed_preclose_for_all_sessions(
        rows_by_code_session, *, seed_previous_close, ordered_sessions
    ):
        out = {}
        for (code, day), row in rows_by_code_session.items():
            copied = dict(row)
            copied["preclose"] = seed_previous_close.get(code)
            copied["preclose_status"] = (
                PRECLOSE_OK if code in seed_previous_close else MISSING_PREDECESSOR
            )
            copied["pct_change"] = None
            out[(code, day)] = copied
        return out

    monkeypatch.setattr(
        staging_mod,
        "build_sequential_preclose",
        fixed_seed_preclose_for_all_sessions,
    )
    result = _run_staging(layout, sid, sessions, tdx, [])
    assert result.preclose_continuity_mismatch_n == 2
    assert result.publish_eligible is False


def test_tdx_volume_normalization():
    raw = {
        "code": "000001",
        "trade_date": "2026-08-05",
        "open": 11.41,
        "high": 11.50,
        "low": 11.18,
        "close": 11.25,
        "volume_lots": 1511509,
        "amount": 1703942528.0,
        "raw_hash": "abc",
    }
    row = normalize_tdx_daily_row(raw)
    assert row["volume"] == Decimal("151150900")
    assert row["volume"] == Decimal(str(raw["volume_lots"])) * TDX_DAILY_VOLUME_MULTIPLIER
    assert row["source_unit"] == "LOTS"
    assert row["normalized_unit"] == "SHARES"
    assert row["price_domain"] == "RAW_UNADJUSTED"


def test_tencent_volume_unit_normalization():
    raw = {
        "code": "000001",
        "trade_date": "2026-08-05",
        "open": 11.41,
        "high": 11.50,
        "low": 11.18,
        "close": 11.25,
        "volume_shares": 1511510.0,
        "amount": 1703942500.0,
        "raw_hash": "def",
    }
    row = normalize_tencent_daily_row(raw)
    assert row["volume_unit"] is None
    assert row["adjust"] == ""
    shares, _, _ = detect_tencent_volume_unit(
        row["volume_raw"],
        Decimal("151151000"),
    )
    assert shares == "LOTS"
    shares_direct, _, _ = detect_tencent_volume_unit(
        Decimal("151151000"),
        Decimal("151151000"),
    )
    assert shares_direct == "SHARES"
    unknown, _, _ = detect_tencent_volume_unit(
        Decimal("999999"),
        Decimal("151151000"),
    )
    assert unknown == "UNKNOWN"


def test_no_field_level_provider_merge():
    day = date(2026, 8, 5)
    tdx = [
        normalize_tdx_daily_row(
            _tdx_row(
                "000001",
                day,
                close="11.25",
                volume_lots=1000,
                raw_hash="tdx-1",
            )
        )
    ]
    tx = [
        normalize_tencent_daily_row(
            _tx_row(
                "000001",
                day,
                close="11.26",  # within 0.01 tolerance of TDX close
                volume_lots=1000,
                raw_hash="tx-1",
            )
        )
    ]
    rows = reconcile_adr008_rows(tdx, tx)
    assert rows[0]["reconciliation_status"] == "CONFIRMED"
    assert rows[0]["selected_provider"] == "TDX"
    assert rows[0]["confirmation_provider"] == "TENCENT"
    assert rows[0]["close"] == Decimal("11.25")
    assert rows[0]["selected_source_hash"] == "tdx-1"
    assert rows[0]["confirmation_source_hash"] == "tx-1"

    # Volume disagreement must conflict, never blend volumes.
    bad_tx = [
        normalize_tencent_daily_row(
            _tx_row(
                "000001",
                day,
                close="11.25",
                volume_lots=2000,
                raw_hash="tx-2",
            )
        )
    ]
    conflicted = reconcile_adr008_rows(tdx, bad_tx)
    assert conflicted[0]["reconciliation_status"] == "CONFLICTED"
    assert conflicted[0]["volume"] == Decimal("100000")


def test_provider_failure_registry(tmp_path):
    registry = ProviderFailureRegistry(
        run_id="r1",
        path=tmp_path / "failures.jsonl",
    )
    registry.record(
        provider="TDX",
        error=ProviderConnectionError(
            "connect refused",
            provider="TDX",
            requested_from=date(2026, 8, 3),
            requested_to=date(2026, 8, 5),
            attempt=1,
        ),
        code="000001",
    )
    registry.record(
        provider="TENCENT",
        failure_class="ProviderUnexpectedError",
        failure_message="boom",
        code="000002",
    )
    path = registry.write()
    assert path is not None
    records = read_failure_registry(path)
    assert len(records) == 2
    assert records[0]["run_id"] == "r1"
    assert records[0]["retryable"] is True
    assert records[1]["failure_class"] == "ProviderUnexpectedError"
    assert registry.unclassified_count() == 1


def test_unknown_provider_exception_not_swallowed():
    def raiser(code: str):
        raise RuntimeError("boom")

    rows, failures = fetch_tencent_daily(
        ["000001"],
        sessions=[date(2026, 8, 5)],
        workers=1,
        fetch_one=raiser,
    )
    assert rows == []
    assert len(failures) == 1
    assert isinstance(failures[0], ProviderUnexpectedError)
    assert failures[0].original_type == "RuntimeError"
    assert failures[0].provider == "TENCENT"


def test_tdx_server_failover_same_provider():
    class FakeApi:
        def __init__(self, fail_first: bool) -> None:
            self.fail_first = fail_first

        def connect(self, *args, **kwargs):
            if self.fail_first:
                return False
            return True

        def get_security_bars(self, *args, **kwargs):
            return []

        def disconnect(self):
            pass

    from limit_pullback.providers.tdx_daily import fetch_tdx_daily

    factories = iter([FakeApi(fail_first=True), FakeApi(fail_first=False)])
    rows, failures = fetch_tdx_daily(
        ["000001"],
        sessions=[date(2026, 8, 5)],
        servers=[("a", 1), ("b", 2)],
        api_factory=lambda: next(factories),
    )
    assert failures == []
    assert rows == []


def test_unclassified_failure_blocks_publish_eligibility(tmp_path, monkeypatch):
    layout, dates, sid = _build_warehouse(tmp_path)
    sessions = _new_sessions(dates, 1)
    import limit_pullback.warehouse.staging as staging_mod

    def broken_normalize(raw, **kwargs):
        raise RuntimeError("unexpected boom")

    monkeypatch.setattr(staging_mod, "normalize_tdx_daily_row", broken_normalize)
    tdx = [
        _tdx_row("603318", sessions[0], close="11.00", volume_lots=1000, raw_hash="t1"),
    ]
    result = _run_staging(layout, sid, sessions, tdx, [])
    assert result.unclassified_failure_n == 1
    assert result.publish_eligible is False
    assert result.stage_status == "FAILED"


def test_staging_manifest_has_no_absolute_paths(tmp_path):
    layout, dates, sid = _build_warehouse(tmp_path)
    sessions = _new_sessions(dates, 1)
    tdx_path = layout.root / "tmp" / "tdx-raw.parquet"
    tx_path = layout.root / "tmp" / "tx-raw.parquet"
    tdx = [_tdx_row("603318", sessions[0], close="11.00", volume_lots=1000, raw_hash="t1")]
    tx = [_tx_row("603318", sessions[0], close="11.00", volume_lots=1000, raw_hash="x1")]
    write_rows_atomic(
        [
            {
                "code": row["code"],
                "trade_date": row["trade_date"],
                "close": row["close"],
                "raw_hash": row["raw_hash"],
            }
            for row in tdx
        ],
        _small_schema(),
        tdx_path,
    )
    write_rows_atomic(
        [
            {
                "code": row["code"],
                "trade_date": row["trade_date"],
                "close": row["close"],
                "raw_hash": row["raw_hash"],
            }
            for row in tx
        ],
        _small_schema(),
        tx_path,
    )
    result = _run_staging(
        layout,
        sid,
        sessions,
        tdx,
        tx,
        run_id="manifest-no-abs",
        tdx_artifact_path=tdx_path,
        tencent_artifact_path=tx_path,
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    text = json.dumps(manifest)
    assert "/Users/" not in text
    assert manifest["source_artifacts"]["TDX"]["logical_uri"].startswith("raw://tdx/")
    assert manifest["source_artifacts"]["TDX"]["relative_path"].startswith("tmp/")
    assert manifest["production_snapshot_published"] is False


def _small_schema():
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("code", pa.string()),
            pa.field("trade_date", pa.date32()),
            pa.field("close", pa.float64()),
            pa.field("raw_hash", pa.string()),
        ]
    )


def test_bad_snapshot_stays_quarantined(tmp_path):
    layout, _, sid = _build_warehouse(tmp_path)
    with WarehouseMetadata(layout.duckdb_path) as metadata:
        metadata.set_snapshot_status(
            snapshot_id=sid,
            status="QUARANTINED",
            reason="PRECLOSE_CONTINUITY_FAILURE_20260804_20260805",
            audit_report_sha256="2f535cd3537460c552564f2123f01be369f39d9ae897d095613e02d7dbceb0f0",
        )
    sessions = [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)]
    with pytest.raises(SnapshotUsabilityError) as exc_info:
        run_adr008_staging(
            layout,
            run_id="blocked",
            seed_snapshot_id=sid,
            sessions=sessions,
            tdx_raw_rows=[],
            tencent_raw_rows=[],
        )
    assert exc_info.value.code == "SNAPSHOT_NOT_SCREEN_READY"


def test_adr008_traceability_sample(tmp_path):
    layout, dates, sid = _build_warehouse(tmp_path)
    sessions = _new_sessions(dates, 2)
    tdx = [
        _tdx_row("603318", sessions[0], close="11.00", volume_lots=1000, raw_hash="tdx-a"),
        _tdx_row("603318", sessions[1], close="11.20", volume_lots=1100, raw_hash="tdx-b"),
    ]
    tx = [
        _tx_row("603318", sessions[0], close="11.00", volume_lots=1000, raw_hash="tx-a"),
        _tx_row("603318", sessions[1], close="11.20", volume_lots=1100, raw_hash="tx-b"),
    ]
    result = _run_staging(layout, sid, sessions, tdx, tx)
    import pyarrow.parquet as pq

    rows = pq.read_table(result.candidate_path).to_pylist()
    confirmed = [row for row in rows if row["reconciliation_status"] == "CONFIRMED"]
    assert len(confirmed) == 2
    expected_tdx = {sessions[0]: "tdx-a", sessions[1]: "tdx-b"}
    expected_tx = {sessions[0]: "tx-a", sessions[1]: "tx-b"}
    for row in confirmed:
        assert row["selected_source_hash"] == expected_tdx[row["trade_date"]]
        assert row["confirmation_source_hash"] == expected_tx[row["trade_date"]]


def test_adr008_missing_predecessor_not_confirmed(tmp_path):
    layout, dates, sid = _build_warehouse(tmp_path)
    sessions = _new_sessions(dates, 1)
    tdx = [
        _tdx_row("999999", sessions[0], close="11.00", volume_lots=1000, raw_hash="t1"),
    ]
    result = _run_staging(layout, sid, sessions, tdx, [])
    import pyarrow.parquet as pq

    rows = pq.read_table(result.candidate_path).to_pylist()
    row = next(row for row in rows if row["code"] == "999999")
    assert row["preclose_status"] == MISSING_PREDECESSOR
    assert row["reconciliation_status"] == "INCOMPLETE"


def test_adr008_pct_change_recomputed():
    rows = {
        ("000001", date(2026, 8, 5)): {"close": Decimal("11.25")},
    }
    staged = build_sequential_preclose(
        rows,
        seed_previous_close={"000001": Decimal("11.44")},
        ordered_sessions=[date(2026, 8, 5)],
    )
    expected = ((Decimal("11.25") - Decimal("11.44")) / Decimal("11.44") * 100).quantize(
        Decimal("0.0001")
    )
    assert staged[("000001", date(2026, 8, 5))]["pct_change"] == expected
