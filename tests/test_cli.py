import json

import pytest

import limit_pullback.cli as cli
from limit_pullback.cli import PLANNED_COMMANDS, build_parser, main


def test_root_help_is_side_effect_free(capsys):
    assert main([]) == 0
    output = capsys.readouterr().out

    assert "Phase 2C.1" in output
    for command in PLANNED_COMMANDS:
        assert command in output


def test_explicit_help_exits_successfully(capsys):
    parser = build_parser()
    try:
        parser.parse_args(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "仅 inspect/replay 会访问固定免费数据源" in capsys.readouterr().out


def test_inspect_help_is_available(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["inspect", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--code" in output
    assert "--as-of" in output
    assert "--days" in output
    assert "001382,002606,603123" not in output


def test_replay_help_is_available(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["replay", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--code" in output
    assert "--as-of" in output
    assert "--lookback-calendar-days" in output


def test_outcome_study_workers_are_bounded_by_cli_input():
    args = build_parser().parse_args(
        [
            "outcome-study",
            "--snapshot-id",
            "snap-test",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-02",
            "--workers",
            "2",
        ]
    )
    assert args.workers == 2
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(
            [
                "outcome-study",
                "--snapshot-id",
                "snap-test",
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-02",
                "--workers",
                "0",
            ]
        )
    assert exc_info.value.code == 2


def test_diagnosis_arguments_reach_read_only_dispatch(monkeypatch, tmp_path):
    received = []

    def fake_run(args):
        received.append((args.episodes_path, args.output_dir))
        return 0

    monkeypatch.setattr(cli, "_run_diagnosis", fake_run)
    episodes = tmp_path / "episodes.parquet"
    output = tmp_path / "diagnosis"

    assert main(
        [
            "diagnosis",
            "--episodes-path",
            str(episodes),
            "--output-dir",
            str(output),
        ]
    ) == 0
    assert received == [(episodes, output)]


@pytest.mark.parametrize("command", ("inspect", "replay"))
@pytest.mark.parametrize("code", ("603318", "002640", "600199", "002891"))
def test_arbitrary_supported_code_reaches_command_dispatch(
    command,
    code,
    monkeypatch,
):
    received = []

    def fake_run(args):
        received.append(args.code)
        return 0

    monkeypatch.setattr(
        cli,
        "_run_inspect" if command == "inspect" else "_run_replay",
        fake_run,
    )
    date_args = (
        ["--as-of", "2026-07-30", "--days", "400"]
        if command == "inspect"
        else [
            "--as-of",
            "2026-07-30",
            "--lookback-calendar-days",
            "400",
        ]
    )

    assert main([command, "--code", code, *date_args]) == 0
    assert received == [code]


@pytest.mark.parametrize(
    ("code", "error_marker"),
    (
        ("300001", "UNSUPPORTED_MARKET_BOARD"),
        ("301001", "UNSUPPORTED_MARKET_BOARD"),
        ("688001", "UNSUPPORTED_MARKET_BOARD"),
        ("200001", "UNSUPPORTED_MARKET_BOARD"),
        ("900001", "UNSUPPORTED_MARKET_BOARD"),
        ("830001", "UNSUPPORTED_MARKET_BOARD"),
        ("12345", "INVALID_CODE_LENGTH"),
        ("ABC123", "NON_NUMERIC_CODE"),
    ),
)
def test_invalid_code_is_json_argument_error_before_dispatch(
    code,
    error_marker,
    capsys,
    monkeypatch,
):
    dispatched = False

    def fail_if_dispatched(args):
        nonlocal dispatched
        dispatched = True
        return 0

    monkeypatch.setattr(cli, "_run_inspect", fail_if_dispatched)
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "inspect",
                "--code",
                code,
                "--as-of",
                "2026-07-30",
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["type"] == "ArgumentError"
    assert error_marker in error["error"]["message"]
    assert dispatched is False


def test_valid_code_without_data_is_json_business_error(
    capsys,
    monkeypatch,
):
    import limit_pullback.inspect as inspect_module

    def no_data(**kwargs):
        raise ValueError(
            "daily source has no trading observation for 603318 on 2026-07-30"
        )

    monkeypatch.setattr(inspect_module, "inspect_stock", no_data)
    args = build_parser().parse_args(
        [
            "inspect",
            "--code",
            "603318",
            "--as-of",
            "2026-07-30",
        ]
    )

    assert cli._run_inspect(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["type"] == "ValueError"
    assert "no trading observation for 603318" in error["error"]["message"]
