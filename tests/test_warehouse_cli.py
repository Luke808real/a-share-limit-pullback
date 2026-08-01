from __future__ import annotations

import json
from datetime import date

import pytest

import limit_pullback.cli as cli
from limit_pullback.cli import build_parser, main
from tests.warehouse_fakes import FakeProviderSet, daily_row


def test_warehouse_commands_appear_in_help(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    for command in (
        "provider-probe",
        "bootstrap",
        "update",
        "data-status",
        "data-validate",
    ):
        assert command in output


def test_bootstrap_cli_outputs_json(tmp_path, monkeypatch, capsys):
    day = date(2026, 7, 30)
    fake = FakeProviderSet(
        calendar=[day],
        tushare_daily=[daily_row("603318", day.isoformat())],
        akshare_daily=[daily_row("603318", day.isoformat())],
    )
    monkeypatch.setattr(
        cli.pipeline_mod if hasattr(cli, "pipeline_mod") else _pipeline_module(),
        "RealWarehouseProviderSet",
        lambda **kwargs: fake,
    )
    status = main(
        [
            "bootstrap",
            "--start",
            "2026-07-30",
            "--end",
            "2026-07-30",
            "--codes",
            "603318",
            "--data-root",
            str(tmp_path / "data"),
        ]
    )
    assert status == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["kind"] == "bootstrap"
    assert payload["snapshot_id"]
    assert payload["canonical_daily_rows"] == 1


def _pipeline_module():
    import limit_pullback.warehouse.pipeline as pipeline

    return pipeline


def test_provider_probe_missing_token_is_structured_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    status = main(
        ["provider-probe", "--data-root", str(tmp_path / "data")]
    )
    assert status == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["code"] == "TUSHARE_TOKEN_NOT_CONFIGURED"
    assert "df58bec9" not in captured.out + captured.err


def test_provider_probe_error_never_leaks_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TUSHARE_TOKEN", "leaky-token-123")

    class DeniedClient:
        def trade_cal(self, **kwargs):
            raise Exception("no permission for leaky-token-123")

        def stock_basic(self, **kwargs):
            raise Exception("no permission for leaky-token-123")

        def daily(self, **kwargs):
            raise Exception("no permission for leaky-token-123")

        def adj_factor(self, **kwargs):
            raise Exception("no permission for leaky-token-123")

        def daily_basic(self, **kwargs):
            raise Exception("no permission for leaky-token-123")

        def suspend_d(self, **kwargs):
            raise Exception("no permission for leaky-token-123")

        def stk_limit(self, **kwargs):
            raise Exception("no permission for leaky-token-123")

    import limit_pullback.warehouse.probe as probe_module

    monkeypatch.setattr(
        probe_module,
        "TushareProProvider",
        lambda **kwargs: __import__(
            "limit_pullback.warehouse.tushare_provider",
            fromlist=["TushareProProvider"],
        ).TushareProProvider(client_factory=lambda token: DeniedClient()),
    )
    status = main(
        ["provider-probe", "--data-root", str(tmp_path / "data")]
    )
    assert status == 0
    captured = capsys.readouterr()
    assert "leaky-token-123" not in captured.out + captured.err
    payload = json.loads(captured.out)
    assert payload["overall"] == "UNAVAILABLE_PERMISSION"


def test_data_status_cli_on_empty_warehouse(tmp_path, capsys):
    status = main(["data-status", "--data-root", str(tmp_path / "data")])
    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset_snapshot_id"] is None
    assert payload["latest_requested_date"] is None


def test_data_validate_cli_without_snapshot(tmp_path, capsys):
    status = main(["data-validate", "--data-root", str(tmp_path / "data")])
    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert any(issue["check"] == "SNAPSHOT" for issue in payload["issues"])
