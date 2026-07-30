"""Stage-2A CLI: one explicit network command plus inert future placeholders."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
import json
from pathlib import Path
import sys


PLANNED_COMMANDS = (
    "bootstrap",
    "update",
    "screen",
    "report",
    "run",
    "backtest",
)
SUPPORTED_CODES = ("001382", "002606", "603123")


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


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "strategy.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="limit_pullback",
        description=(
            "A股涨停回调盘后筛选器（阶段2B.2：指定股票日线回放）"
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
        help="在内存中下载并检查阶段2A允许的一只股票",
    )
    inspect_parser.add_argument("--code", required=True, choices=SUPPORTED_CODES)
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
        help="按交易日回放阶段2B允许的一只股票",
    )
    replay_parser.add_argument("--code", required=True, choices=SUPPORTED_CODES)
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
        parser.error(f"命令 {args.command!r} 尚未在阶段2B.2实现")
    if args.command == "inspect":
        return _run_inspect(args)
    if args.command == "replay":
        return _run_replay(args)
    if args.command is None:
        parser.print_help()
    return 0
