import pytest

from limit_pullback.cli import PLANNED_COMMANDS, build_parser, main


def test_root_help_is_side_effect_free(capsys):
    assert main([]) == 0
    output = capsys.readouterr().out

    assert "阶段2B" in output
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


def test_replay_help_is_available(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["replay", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--code" in output
    assert "--as-of" in output
    assert "--lookback-calendar-days" in output
