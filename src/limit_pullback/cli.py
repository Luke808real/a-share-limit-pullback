"""Phase-2C.1 CLI: arbitrary supported main-board inspect and replay."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
import json
from pathlib import Path
import sys

from limit_pullback.instruments import (
    InstrumentCodeError,
    parse_instrument_code,
)


PLANNED_COMMANDS = (
    "bootstrap",
    "update",
    "screen",
    "report",
    "run",
    "backtest",
)


class StructuredArgumentParser(argparse.ArgumentParser):
    """Keep command-line argument failures machine-readable on stderr."""

    def error(self, message: str) -> None:
        payload = {
            "error": {
                "type": "ArgumentError",
                "message": message,
            }
        }
        self.exit(2, json.dumps(payload, ensure_ascii=False) + "\n")


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must use YYYY-MM-DD") from exc


def _main_board_code(value: str) -> str:
    try:
        return parse_instrument_code(value).normalized_code
    except InstrumentCodeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "strategy.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = StructuredArgumentParser(
        prog="limit_pullback",
        description=(
            "A股涨停回调盘后筛选器（Phase 2C.1：沪深主板单股票评价）"
        ),
        epilog=(
            "仅 inspect/replay 会访问固定免费数据源；不建立数据库，不写文件，"
            "也不执行全市场筛选、报告或回测。"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for command in PLANNED_COMMANDS:
        command_parser = subparsers.add_parser(
            command,
            help="后续阶段命令；当前版本尚未实现",
        )
        command_parser.set_defaults(_not_implemented=True)
    inspect_parser = subparsers.add_parser(
        "inspect",
        help="无状态检查一只合法沪深主板股票",
    )
    inspect_parser.add_argument("--code", required=True, type=_main_board_code)
    inspect_parser.add_argument("--as-of", required=True, type=_iso_date)
    inspect_parser.add_argument("--days", type=_positive_integer, default=400)
    inspect_parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
        help="strategy.yaml 路径",
    )
    replay_parser = subparsers.add_parser(
        "replay",
        help="严格逐交易日回放一只合法沪深主板股票",
    )
    replay_parser.add_argument("--code", required=True, type=_main_board_code)
    replay_parser.add_argument("--start", type=_iso_date)
    replay_parser.add_argument("--as-of", required=True, type=_iso_date)
    replay_parser.add_argument(
        "--lookback-calendar-days",
        type=_positive_integer,
        default=400,
    )
    replay_parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
        help="strategy.yaml 路径",
    )
    return parser


def _run_inspect(args: argparse.Namespace) -> int:
    from limit_pullback.config import load_strategy_config
    from limit_pullback.inspect import inspect_stock
    from limit_pullback.providers import (
        AkShareLimitUpPoolProvider,
        BaoStockDailyBarProvider,
    )

    try:
        output = inspect_stock(
            code=args.code,
            as_of=args.as_of,
            days=args.days,
            config=load_strategy_config(args.config),
            daily_provider=BaoStockDailyBarProvider(),
            limit_pool_provider=AkShareLimitUpPoolProvider(),
        )
    except Exception as exc:
        error = {
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            }
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1
    print(output.model_dump_json(indent=2))
    return 0


def _run_replay(args: argparse.Namespace) -> int:
    from limit_pullback.config import load_strategy_config
    from limit_pullback.providers import (
        AkShareLimitUpPoolProvider,
        BaoStockDailyBarProvider,
    )
    from limit_pullback.replay import replay_stock

    try:
        output = replay_stock(
            code=args.code,
            start=args.start,
            as_of=args.as_of,
            lookback_calendar_days=args.lookback_calendar_days,
            config=load_strategy_config(args.config),
            daily_provider=BaoStockDailyBarProvider(),
            limit_pool_provider=AkShareLimitUpPoolProvider(),
        )
    except Exception as exc:
        error = {
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            }
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1
    print(output.model_dump_json(indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "_not_implemented", False):
        parser.error(f"命令 {args.command!r} 尚未在Phase 2C.1实现")
    if args.command == "inspect":
        return _run_inspect(args)
    if args.command == "replay":
        return _run_replay(args)
    if args.command is None:
        parser.print_help()
    return 0
