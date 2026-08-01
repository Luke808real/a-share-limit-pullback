from __future__ import annotations

import json
from datetime import date

import pytest

import limit_pullback.cli as cli
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
