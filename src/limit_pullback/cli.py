"""Side-effect-free CLI skeleton for the stage-1 deliverable."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


PLANNED_COMMANDS = (
    "bootstrap",
    "update",
    "screen",
    "report",
    "run",
    "backtest",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="limit_pullback",
        description=(
            "A股涨停回调盘后筛选器（阶段1.5：纯策略计算引擎）"
        ),
        epilog=(
            "当前版本仅提供可导入的纯函数引擎；不访问网络、不建立数据库，"
            "也不执行CLI筛选、报告或回测。"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for command in PLANNED_COMMANDS:
        command_parser = subparsers.add_parser(
            command,
            help="后续阶段命令；当前版本尚未实现",
        )
        command_parser.set_defaults(_not_implemented=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "_not_implemented", False):
        parser.error(f"命令 {args.command!r} 尚未在阶段1.5实现")
    if args.command is None:
        parser.print_help()
    return 0
