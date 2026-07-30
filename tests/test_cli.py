from limit_pullback.cli import PLANNED_COMMANDS, build_parser, main


def test_root_help_is_side_effect_free(capsys):
    assert main([]) == 0
    output = capsys.readouterr().out

    assert "阶段1.5" in output
    for command in PLANNED_COMMANDS:
        assert command in output


def test_explicit_help_exits_successfully(capsys):
    parser = build_parser()
    try:
        parser.parse_args(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "不访问网络" in capsys.readouterr().out
