"""Pure contract tests for the blocked-until-authorized R9 V02 protocol."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "walk_forward_v01"))

import r9_protocol_v02 as r9  # noqa: E402
from limit_pullback.strategy.engine import make_setup_id  # noqa: E402


pytestmark = pytest.mark.cloud_ci


def _git(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo_root), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.rstrip("\n")


def _receipt_message(commit: str) -> str:
    return (
        "R9 V01 protocol freeze receipt\n\n"
        f"PROTOCOL_FREEZE_COMMIT={commit}\n"
        f"PROTOCOL_FREEZE_DATE={r9.PROTOCOL_FREEZE_DATE.isoformat()}\n"
        f"OOS_START={r9.R9_OOS_START.isoformat()}\n"
        f"PROTOCOL_FREEZE_CALENDAR_HASH={r9.PROTOCOL_FREEZE_CALENDAR_MANIFEST_HASH}"
    )


def _annotated_protocol_receipt_repo(tmp_path: Path, *, message: str | None = None) -> Path:
    repo_root = tmp_path / "protocol-receipt-repo"
    repo_root.mkdir(parents=True)
    _git(repo_root, "init")
    _git(repo_root, "config", "user.email", "r9-test@example.invalid")
    _git(repo_root, "config", "user.name", "R9 protocol test")
    (repo_root / "freeze.txt").write_text("freeze\n")
    _git(repo_root, "add", "freeze.txt")
    _git(repo_root, "commit", "-m", "freeze")
    commit = _git(repo_root, "rev-parse", "HEAD")
    _git(
        repo_root,
        "tag",
        "-a",
        r9.PROTOCOL_FREEZE_RECEIPT_TAG,
        "-m",
        message or _receipt_message(commit),
    )
    return repo_root


def test_r1_forward_authority_and_legacy_label_boundary_are_frozen():
    assert r9.R1_PROVENANCE_STATUS == "INTERIM_PARTIAL_PROVENANCE"
    assert r9.R1_FORWARD_AUTHORITY is False
    assert r9.LEGACY_LABEL_ROLE == "SECONDARY_DIAGNOSTIC_ONLY_NOT_R9_PRIMARY_ENDPOINT"
    assert r9.PRIMARY_ENDPOINT != "SUCCESS"
    assert r9.PRIMARY_ENDPOINT != "FAILED_BREAKOUT"


def test_population_and_owner_frozen_ttl_authority_are_explicit():
    assert r9.R9_POPULATION_STATUS == "PASS_NEW_PROSPECTIVE_V01"
    assert r9.R9_OBSERVATION_TTL_STATUS == "PASS_OWNER_FROZEN_V01"
    assert r9.R9_OBSERVATION_TTL == 7
    r9.require_population_and_ttl_authority()


def test_accumulation_write_authority_requires_an_actual_annotated_head_tag(tmp_path):
    repo_root = _annotated_protocol_receipt_repo(tmp_path)
    head = _git(repo_root, "rev-parse", "HEAD")
    assert r9.R9_ACCUMULATION_WRITE_AUTHORITY == "POST_COMMIT_RECEIPT_REQUIRED"
    receipt = r9.require_r9_accumulation_write_authority(repo_root=repo_root)
    assert receipt.protocol_freeze_commit == head
    assert receipt.tag_target_commit == head
    assert receipt.tag_object != head
    _git(repo_root, "commit", "--allow-empty", "-m", "later")
    with pytest.raises(r9.ProtocolBlocked, match="does not target expected HEAD"):
        r9.require_r9_accumulation_write_authority(repo_root=repo_root)


def test_receipt_reader_rejects_lightweight_or_duplicate_message_field_tags(tmp_path):
    repo_root = _annotated_protocol_receipt_repo(tmp_path)
    _git(repo_root, "tag", "-d", r9.PROTOCOL_FREEZE_RECEIPT_TAG)
    _git(repo_root, "tag", r9.PROTOCOL_FREEZE_RECEIPT_TAG)
    with pytest.raises(r9.ProtocolBlocked, match="annotated tag"):
        r9.read_protocol_freeze_receipt(repo_root)

    duplicate_root = _annotated_protocol_receipt_repo(
        tmp_path / "duplicate",
        message=(
            "R9 V01 protocol freeze receipt\n\n"
            f"PROTOCOL_FREEZE_COMMIT={'0' * 40}\n"
            f"PROTOCOL_FREEZE_COMMIT={'0' * 40}\n"
            f"PROTOCOL_FREEZE_DATE={r9.PROTOCOL_FREEZE_DATE.isoformat()}\n"
            f"OOS_START={r9.R9_OOS_START.isoformat()}\n"
            f"PROTOCOL_FREEZE_CALENDAR_HASH={r9.PROTOCOL_FREEZE_CALENDAR_MANIFEST_HASH}"
        ),
    )
    with pytest.raises(r9.ProtocolBlocked, match="duplicate message field"):
        r9.read_protocol_freeze_receipt(duplicate_root)

    wrong_value_root = _annotated_protocol_receipt_repo(
        tmp_path / "wrong-value",
        message=(
            "R9 V01 protocol freeze receipt\n\n"
            f"PROTOCOL_FREEZE_COMMIT={'0' * 40}\n"
            f"PROTOCOL_FREEZE_DATE={r9.PROTOCOL_FREEZE_DATE.isoformat()}\n"
            f"OOS_START={r9.R9_OOS_START.isoformat()}\n"
            f"PROTOCOL_FREEZE_CALENDAR_HASH={r9.PROTOCOL_FREEZE_CALENDAR_MANIFEST_HASH}"
        ),
    )
    with pytest.raises(r9.ProtocolBlocked, match="message mismatch"):
        r9.read_protocol_freeze_receipt(wrong_value_root)


def test_setup_identity_is_deterministic_and_matches_authoritative_engine_key():
    anchor_day = date(2026, 8, 10)
    expected = make_setup_id("600000", anchor_day, Decimal("11.00"), Decimal("0.01"))
    assert r9.r9_setup_id("600000", anchor_day, Decimal("11.00")) == expected
    assert r9.r9_setup_id("600000", anchor_day, Decimal("11.00")) == "600000:20260810:1100"
    assert r9.r9_setup_id("600000", anchor_day, Decimal("11.01")) != expected


def test_legacy_event_registration_bypass_is_not_exposed():
    assert not hasattr(r9, "FirstS1TouchEvent")
    assert not hasattr(r9, "register_first_s1_touch")
    with pytest.raises(r9.ProtocolBlocked, match="right-labeled"):
        r9.canonical_clock("09:31")


def test_non_activation_is_retained_and_late_touch_is_not_backfilled_at_1030():
    r9.assert_non_activation_is_retained("NO_ACTIVATION_WITHIN_TTL")
    with pytest.raises(r9.ProtocolBlocked):
        r9.assert_non_activation_is_retained("DROPPED")
    assert r9.intraday_observation_status("10:35", 2) == "POST_CHECKPOINT_NOT_OBSERVABLE"
    assert r9.intraday_observation_status("10:30", 0) == "NO_POST_ACTIVATION_BAR"
    assert r9.intraday_observation_status("10:00", 3) == "FEATURE_OBSERVABLE"


def test_primary_checkpoint_features_and_no_threshold_or_composite_are_frozen():
    assert r9.R9_PRIMARY_CHECKPOINT == "10:30"
    assert r9.PRIMARY_INTRADAY_FEATURE == "breakout_hold_ratio"
    assert r9.PRIMARY_INTRADAY_EXPECTED_DIRECTION == "POSITIVE"
    assert r9.SECONDARY_INTRADAY_FEATURES == (
        ("retest_depth", "POSITIVE"),
        ("false_break_duration", "NEGATIVE"),
        ("vwap_acceptance_ratio", "POSITIVE"),
    )
    assert not hasattr(r9, "PRIMARY_RETURN_THRESHOLD")
    assert not hasattr(r9, "COMPOSITE_SCORE")


def test_m0_m1_are_full_frozen_raw_coefficient_rank_scores_without_refit():
    assert r9.PRIMARY_DAILY_COMPARISON == "M1_vs_M0"
    assert r9._frozen_coefficient_rows("M0") == (
        ("B4", Decimal("0.1769807503017533")),
        ("B5", Decimal("0.42476592422692655")),
        ("B6", Decimal("0.6260624988723054")),
        ("B7", Decimal("-0.0020930635721119212")),
    )
    assert tuple(name for name, _ in r9._frozen_coefficient_rows("M1")) == r9.M1_PREDICTORS
    assert r9._frozen_coefficient_rows("M1")[0][1] != r9._frozen_coefficient_rows("M0")[0][1]
    values = {"B4": 1, "B5": 1, "B6": 1, "B7": 0, "median_range_ratio": Decimal("0.5")}
    assert r9.frozen_daily_score("M1", values) != r9.frozen_daily_score("M0", values)
    with pytest.raises(r9.ProtocolBlocked):
        r9.frozen_daily_score("M2", values)


def test_primary_endpoint_is_strictly_after_event_day_and_never_uses_eod_acceptance():
    event_day = date(2026, 8, 10)
    sessions = (
        r9.SubsequentSession(date(2026, 8, 11), Decimal("101")),
        r9.SubsequentSession(date(2026, 8, 12), Decimal("102")),
        r9.SubsequentSession(date(2026, 8, 13), Decimal("103")),
        r9.SubsequentSession(date(2026, 8, 14), Decimal("104")),
        r9.SubsequentSession(date(2026, 8, 17), Decimal("105")),
    )
    status, result = r9.forward_close_return(
        event_date=event_day, reference_price=Decimal("100"),
        subsequent_sessions=sessions, horizon=3,
    )
    assert (status, result) == ("MATURED", Decimal("0.03"))
    status_5d, result_5d = r9.forward_close_return(
        event_date=event_day, reference_price=Decimal("100"),
        subsequent_sessions=sessions, horizon=5,
    )
    assert (status_5d, result_5d) == ("MATURED", Decimal("0.05"))
    with pytest.raises(r9.ProtocolBlocked):
        r9.forward_close_return(
            event_date=event_day, reference_price=Decimal("100"),
            subsequent_sessions=(r9.SubsequentSession(event_day, Decimal("101")), *sessions),
            horizon=3,
        )
    assert r9.OPTIONAL_BINARY_DIAGNOSTIC == "FWD3_POSITIVE = FWD3_CLOSE_RETURN > 0"


def test_missing_close_does_not_silently_skip_to_a_later_stock_bar():
    sessions = (
        r9.SubsequentSession(date(2026, 8, 11), Decimal("101")),
        r9.SubsequentSession(date(2026, 8, 12), Decimal("102")),
        r9.SubsequentSession(date(2026, 8, 13), None),
        r9.SubsequentSession(date(2026, 8, 14), Decimal("104")),
    )
    assert r9.forward_close_return(
        event_date=date(2026, 8, 10), reference_price=Decimal("100"),
        subsequent_sessions=sessions, horizon=3,
    ) == ("DATA_UNAVAILABLE", None)


def test_multiplicity_uncertainty_and_stopping_contracts_are_frozen():
    r9.validate_bootstrap_contract()
    assert r9.SYMBOL_CLUSTER_BOOTSTRAP == "SYMBOL_CLUSTER_BOOTSTRAP"
    assert r9.TRADE_WEEK_BLOCK_BOOTSTRAP == "TRADE_WEEK_BLOCK_BOOTSTRAP"
    assert r9.NO_EARLY_STOP_FOR_PERFORMANCE is True
    assert r9.INITIAL_OBSERVATION_WINDOW_A_SHARE_SESSIONS == 60
    assert r9.DAILY_MATURED_SETUP_MIN == 120
    assert r9.INTRADAY_10_30_FEATURE_OBSERVABLE_MIN == 40


def test_append_only_feature_hash_drift_fails_closed():
    key = ("s", "e", "10:30")
    assert r9.assert_append_only_feature({}, setup_id="s", event_id="e", checkpoint="10:30", feature_hash="h1") == "APPEND"
    assert r9.assert_append_only_feature({key: "h1"}, setup_id="s", event_id="e", checkpoint="10:30", feature_hash="h1") == "ALREADY_RECORDED"
    with pytest.raises(r9.FeatureDriftBlocked, match="BLOCKED_FEATURE_DRIFT"):
        r9.assert_append_only_feature({key: "h1"}, setup_id="s", event_id="e", checkpoint="10:30", feature_hash="h2")


def test_atomic_publication_contract_is_ordered_and_fail_closed(tmp_path):
    r9.validate_atomic_publication_contract(r9.ATOMIC_PUBLICATION_STEPS)
    with pytest.raises(r9.ProtocolBlocked):
        r9.validate_atomic_publication_contract(tuple(reversed(r9.ATOMIC_PUBLICATION_STEPS)))
    destination = tmp_path / "immutable-ledger.csv"

    with pytest.raises(r9.ProtocolBlocked, match="Git verification"):
        r9.atomic_publish_bytes(
            destination,
            b"blocked-before-write",
            validate_temporary=lambda path: assert_nonempty(path),
            protocol_repo_root=tmp_path,
        )
    assert not destination.exists()
    protocol_repo_root = _annotated_protocol_receipt_repo(tmp_path)

    def rejected(_: Path) -> None:
        raise r9.ProtocolBlocked("synthetic QA failure")

    with pytest.raises(r9.ProtocolBlocked, match="synthetic QA failure"):
        r9.atomic_publish_bytes(
            destination,
            b"bad",
            validate_temporary=rejected,
            protocol_repo_root=protocol_repo_root,
        )
    assert not destination.exists()
    digest = r9.atomic_publish_bytes(
        destination,
        b"header\n",
        validate_temporary=lambda path: assert_nonempty(path),
        protocol_repo_root=protocol_repo_root,
    )
    assert digest == r9.sha256_file(destination)
    with pytest.raises(r9.ProtocolBlocked, match="append-only"):
        r9.atomic_publish_bytes(
            destination,
            b"replacement\n",
            validate_temporary=lambda path: assert_nonempty(path),
            protocol_repo_root=protocol_repo_root,
        )


def assert_nonempty(path: Path) -> None:
    assert path.read_bytes()


def test_pre_freeze_and_historical_rows_are_rejected():
    with pytest.raises(r9.ProtocolBlocked, match="pre-freeze"):
        r9.assert_prospective_origin(
            origin="R9_PROSPECTIVE",
            row_date=r9.PROTOCOL_FREEZE_DATE,
        )
    for origin in ("R1_8682_DEVELOPMENT", "R8_146_DEVELOPMENT"):
        with pytest.raises(r9.ProtocolBlocked, match="historical development"):
            r9.assert_prospective_origin(origin=origin, row_date=r9.R9_OOS_START)
    r9.assert_prospective_origin(
        origin="R9_PROSPECTIVE",
        row_date=r9.R9_OOS_START,
    )
    with pytest.raises(r9.ProtocolBlocked, match="absent from frozen A-share calendar"):
        r9.assert_prospective_origin(
            origin="R9_PROSPECTIVE",
            row_date=date(2026, 8, 22),
        )
    with pytest.raises(r9.ProtocolBlocked, match="freeze date override"):
        r9.assert_prospective_origin(
            origin="R9_PROSPECTIVE",
            row_date=r9.R9_OOS_START,
            protocol_freeze_date=date(2026, 8, 8),
        )
    with pytest.raises(r9.ProtocolBlocked, match="OOS start override"):
        r9.assert_prospective_origin(
            origin="R9_PROSPECTIVE",
            row_date=r9.R9_OOS_START,
            oos_start=date(2026, 8, 8),
        )
    with pytest.raises(r9.ProtocolBlocked, match="calendar override"):
        r9.assert_prospective_origin(
            origin="R9_PROSPECTIVE",
            row_date=r9.R9_OOS_START,
            frozen_calendar=r9.FrozenAshareTradingCalendar(
                version="forged",
                sessions=(r9.R9_OOS_START,),
                manifest_hash="0" * 64,
            ),
        )


def test_exact_tick_reconciliation_and_minute_provenance_are_required():
    good = {
        "daily_symbol": "000001", "minute_symbol": "000001",
        "daily_trade_date": "2026-08-21", "minute_trade_date": "2026-08-21",
        "daily_s1_price": "10.50", "minute_s1_price": "10.50", "price_tick": "0.01",
    }
    r9.validate_exact_tick_reconciliation(good)
    with pytest.raises(r9.ProtocolBlocked, match="BLOCKED_PRICE_RECONCILIATION"):
        r9.validate_exact_tick_reconciliation({**good, "minute_s1_price": "10.51"})
    manifest = {
        "ASL_CODE_SHA": r9.ASL_CODE_SHA, "source": "tdx_protocol", "schema_version": "v1",
        "partition_list": "2026-08-21", "partition_hashes": "abc", "units": "shares/RMB",
        "timezone": "Asia/Shanghai", "bar_label_semantics": "RIGHT_LABELED", "ingested_at": "2026-08-21T16:00:00+08:00",
    }
    r9.validate_minute_manifest(manifest)
    with pytest.raises(r9.ProtocolBlocked):
        r9.validate_minute_manifest({**manifest, "ASL_CODE_SHA": "wrong"})


def test_ingestion_rejects_physical_disorder_duplicates_bad_grid_or_unverified_labels():
    rows = [
        {"symbol": "000001.SZ", "trade_date": "2026-08-21", "bar_time": clock}
        for clock in r9.r9_full_session_grid()
    ]
    r9.validate_minute_ingestion(rows, right_label_verified=True)
    with pytest.raises(r9.ProtocolBlocked, match="physical bar disorder"):
        r9.validate_minute_ingestion([rows[1], rows[0], *rows[2:]], right_label_verified=True)
    with pytest.raises(r9.ProtocolBlocked, match="duplicate"):
        r9.validate_minute_ingestion([*rows, rows[-1]], right_label_verified=True)
    with pytest.raises(r9.ProtocolBlocked, match="right-label"):
        r9.validate_minute_ingestion(rows, right_label_verified=False)


def test_registry_and_empty_schema_templates_match_frozen_contract():
    registry_path = REPO_ROOT / "research" / "second_launch" / "walk_forward_v01" / "r9_protocol_registry_v02.csv"
    with registry_path.open(newline="") as handle:
        assert list(csv.DictReader(handle)) == r9.protocol_registry_rows()
    for filename, expected in (
        ("r9_setup_ledger_schema_v01.csv", r9.SETUP_LEDGER_COLUMNS),
        ("r9_intraday_observation_ledger_schema_v01.csv", r9.INTRADAY_LEDGER_COLUMNS),
        ("r9_endpoint_ledger_schema_v01.csv", r9.ENDPOINT_LEDGER_COLUMNS),
    ):
        path = registry_path.parent / filename
        lines = path.read_text().splitlines()
        assert tuple(lines[0].split(",")) == expected
        assert len(lines) == 1


def test_gate_status_is_go_pre_r9_and_no_real_oos_row_is_present():
    rows = {row["key"]: row["value"] for row in r9.protocol_registry_rows()}
    assert rows["GATE_1_R1_AUTHORITY_BOUNDARY"] == "PASS"
    assert rows["GATE_2A_PROSPECTIVE_POPULATION"] == "PASS"
    assert rows["GATE_2B_OBSERVATION_TTL"] == "PASS_OWNER_FROZEN_V01"
    assert rows["GATE_2_POPULATION_EVENT_TTL"] == "PASS"
    assert rows["GATE_3_INDEPENDENT_ENDPOINT"] == "PASS"
    assert rows["GATE_4_MULTIPLICITY_UNCERTAINTY"] == "PASS"
    assert rows["GATE_5_ASL_PROVENANCE_ATOMICITY"] == "PASS"
    assert rows["PRE_R9_STATUS"] == "GO"
    assert rows["R9_RECOMMENDATION"] == "AUTHORIZED_TO_FREEZE_AND_ACCUMULATE"
    assert r9.PROTOCOL_STATUS == "GO_PRE_R9_AUTHORIZED_NO_OOS_ROWS"
    assert r9.R9_ACCUMULATION_AUTHORIZED is True
    assert r9.R9_OOS_ROWS_WRITTEN == 0
