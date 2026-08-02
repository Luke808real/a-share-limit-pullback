from __future__ import annotations

import json
from datetime import date

import pytest

import limit_pullback.cli as cli
import limit_pullback.screen.chunks as chunks_mod
import limit_pullback.screen.runner as runner_mod
from limit_pullback.cli import build_parser, main


def test_screen_command_appears_in_help(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "screen" in output


def test_screen_cli_on_empty_warehouse_is_structured_error(tmp_path, capsys):
    status = main(
        [
            "screen",
            "--as-of",
            "2026-07-30",
            "--data-root",
            str(tmp_path / "data"),
        ]
    )
    assert status == 1
    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert error["error"]["type"] in {"ValueError", "IOException"}


def test_hardware_profile_cli(capsys):
    status = main(["hardware-profile"])
    captured = capsys.readouterr()
    if status == 0:
        payload = json.loads(captured.out)
        assert "architecture" in payload
    else:
        assert status == 2
        assert "native arm64" in captured.err


def test_use_chunked_path_routing_rules():
    parser = build_parser()
    args = parser.parse_args(
        ["screen", "--as-of", "2026-07-31", "--start", "2024-01-01", "--rebuild"]
    )
    assert cli._use_chunked_path(args) is True
    args.codes = ["000001"]
    assert cli._use_chunked_path(args) is False
    args.codes = None
    args.verify_replay = True
    assert cli._use_chunked_path(args) is False
    args.verify_replay = False
    args.lookback_calendar_days = 200
    assert cli._use_chunked_path(args) is False
    args.lookback_calendar_days = 400
    args.rebuild = False
    assert cli._use_chunked_path(args) is False


def test_screen_cli_full_market_rebuild_routes_to_chunked(tmp_path, monkeypatch, capsys):
    calls: list[dict] = []

    def fake_chunked(**kwargs):
        calls.append(kwargs)
        return {"run_id": "screen-rebuild-x", "rows_count": 0}

    monkeypatch.setattr(chunks_mod, "run_chunked_screen", fake_chunked)
    status = main(
        [
            "screen",
            "--as-of",
            "2026-07-31",
            "--start",
            "2024-01-01",
            "--rebuild",
            "--data-root",
            str(tmp_path / "data"),
        ]
    )
    assert status == 0
    assert len(calls) == 1
    assert calls[0]["pool_mode"] == "formal"
    assert "codes" not in calls[0]


def test_screen_cli_code_subset_uses_run_screen(tmp_path, monkeypatch, capsys):
    calls: list[dict] = []

    def fake_run_screen(**kwargs):
        calls.append(kwargs)
        return {"run_id": "screen-rebuild-single", "rows_count": 0}

    monkeypatch.setattr(chunks_mod, "run_chunked_screen", lambda **kw: calls.append(kw))
    monkeypatch.setattr(runner_mod, "run_screen", fake_run_screen)
    status = main(
        [
            "screen",
            "--as-of",
            "2026-07-31",
            "--start",
            "2024-01-01",
            "--rebuild",
            "--codes",
            "000001",
            "--data-root",
            str(tmp_path / "data"),
        ]
    )
    assert status == 0
    assert len(calls) == 1
    assert calls[0]["codes"] == ["000001"]
