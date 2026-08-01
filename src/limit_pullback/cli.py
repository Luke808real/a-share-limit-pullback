"""CLI: inspect/replay (2C.1) and local market-data warehouse (2C.2A)."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
import json
import os
from pathlib import Path
import sys

from limit_pullback.instruments import (
    InstrumentCodeError,
    parse_instrument_code,
)
from limit_pullback.warehouse.auth import TushareTokenError, redact
from limit_pullback.warehouse.layout import WarehouseLayout, resolve_data_root
from limit_pullback.warehouse.pipeline import PipelineError
from limit_pullback.warehouse.tushare_provider import CapabilityUnavailable


PLANNED_COMMANDS = (
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


def _default_trade_plan_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "trade_plan.yaml"


def _default_outcome_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "outcome_study.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = StructuredArgumentParser(
        prog="limit_pullback",
        description=(
            "A股涨停回调盘后筛选器（Phase 2C.1：沪深主板单股票评价；"
            "Phase 2C.2A：本地多源行情仓库）"
        ),
        epilog=(
            "仅 inspect/replay 会访问固定免费数据源；warehouse 命令在 data/ "
            "建立 Parquet + DuckDB 本地仓库；不执行全市场筛选、报告或回测。"
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
    probe_parser = subparsers.add_parser(
        "provider-probe",
        help="探测数据源能力并输出 AVAILABLE/UNAVAILABLE_* 状态",
    )
    probe_parser.add_argument(
        "--provider",
        choices=("tushare",),
        default="tushare",
        help="当前仅支持 tushare",
    )
    probe_parser.add_argument("--data-root", type=Path, default=None)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="历史行情 bootstrap：下载、对账、canonical 快照",
    )
    bootstrap_parser.add_argument("--start", required=True, type=_iso_date)
    bootstrap_parser.add_argument("--end", required=True, type=_iso_date)
    bootstrap_parser.add_argument("--codes", nargs="+", type=_main_board_code)
    bootstrap_parser.add_argument("--data-root", type=Path, default=None)
    bootstrap_parser.add_argument(
        "--all-main-board",
        action="store_true",
        help="从 stock_basic 枚举全部合法沪深主板代码",
    )
    bootstrap_parser.add_argument("--batch-size", type=_positive_integer, default=50)
    bootstrap_parser.add_argument(
        "--providers",
        nargs="+",
        choices=("TUSHARE", "AKSHARE", "BAOSTOCK"),
        default=("TUSHARE", "AKSHARE", "BAOSTOCK"),
    )
    bootstrap_parser.add_argument(
        "--workers",
        type=_positive_integer,
        default=1,
        help="per-code 抓取并发线程数",
    )
    bootstrap_parser.add_argument(
        "--skip-tushare-aux",
        action="store_true",
        help="跳过 Tushare 辅助数据集（adj_factor/daily_basic/suspension/price_limits）",
    )
    bootstrap_parser.add_argument(
        "--isolate-akshare",
        action="store_true",
        help="在独立子进程中抓取 AKShare（隔离 V8/mini_racer 原生崩溃）",
    )
    bootstrap_parser.add_argument(
        "--aux-backfill",
        action="store_true",
        help="使用独立 run_id 补抓 Tushare 辅助数据集并发布 RESEARCH_READY 快照",
    )
    bootstrap_parser.add_argument(
        "--snapshot-status",
        choices=("CURRENT", "SCREEN_READY", "RESEARCH_READY"),
        default="CURRENT",
    )
    bootstrap_parser.add_argument(
        "--listed-only",
        action="store_true",
        help="stock_basic 仅取上市状态（与既有 run_id 的 universe 一致）",
    )
    bootstrap_parser.add_argument(
        "--profile",
        choices=("apple-silicon-16gb",),
        default="apple-silicon-16gb",
        help="性能档（可用 LIMIT_PULLBACK_* 环境变量覆盖各参数）",
    )

    update_parser = subparsers.add_parser(
        "update",
        help="幂等每日增量更新到指定 as-of 日期",
    )
    update_parser.add_argument("--as-of", required=True, type=_iso_date)
    update_parser.add_argument("--codes", nargs="+", type=_main_board_code)
    update_parser.add_argument("--data-root", type=Path, default=None)

    status_parser = subparsers.add_parser(
        "data-status",
        help="输出仓库新鲜度与对账状态",
    )
    status_parser.add_argument("--data-root", type=Path, default=None)

    validate_parser = subparsers.add_parser(
        "data-validate",
        help="校验仓库完整性、可追溯性与 manifest",
    )
    validate_parser.add_argument("--data-root", type=Path, default=None)
    validate_parser.add_argument("--snapshot", default=None)

    screen_parser = subparsers.add_parser(
        "screen",
        help="基于canonical快照的离线全市场setup扫描（不联网）",
    )
    screen_parser.add_argument("--as-of", required=True, type=_iso_date)
    screen_parser.add_argument("--snapshot-id", default=None)
    screen_parser.add_argument("--start", type=_iso_date)
    screen_parser.add_argument("--rebuild", action="store_true")
    screen_parser.add_argument("--codes", nargs="+", type=_main_board_code)
    screen_parser.add_argument("--data-root", type=Path, default=None)
    screen_parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
        help="strategy.yaml 路径",
    )
    screen_parser.add_argument(
        "--lookback-calendar-days",
        type=_positive_integer,
        default=400,
    )
    screen_parser.add_argument("--verify-replay", action="store_true")
    screen_parser.add_argument(
        "--pool-debug",
        action="store_true",
        help="允许 PROVISIONAL 涨停池记录作为锚点（调试模式，降低数据质量）",
    )

    trade_plan_parser = subparsers.add_parser(
        "trade-plan",
        help="从已有canonical快照输出盘后B点候选与次日计划（不联网）",
    )
    trade_plan_parser.add_argument("--as-of", required=True, type=_iso_date)
    trade_plan_parser.add_argument("--snapshot-id", required=True)
    trade_plan_parser.add_argument("--data-root", type=Path, default=None)
    trade_plan_parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
        help="strategy.yaml 路径",
    )
    trade_plan_parser.add_argument(
        "--trade-plan-config",
        type=Path,
        default=_default_trade_plan_config_path(),
        help="TradePlan execution-only config path",
    )

    outcome_parser = subparsers.add_parser(
        "outcome-study",
        help="对固定canonical快照做FINAL_VINTAGE_CAUSAL信号结果研究",
    )
    outcome_parser.add_argument("--snapshot-id", required=True)
    outcome_parser.add_argument("--start", required=True, type=_iso_date)
    outcome_parser.add_argument("--end", required=True, type=_iso_date)
    outcome_parser.add_argument("--data-root", type=Path, default=None)
    outcome_parser.add_argument(
        "--config", type=Path, default=_default_config_path(), help="strategy.yaml路径"
    )
    outcome_parser.add_argument(
        "--trade-plan-config",
        type=Path,
        default=_default_trade_plan_config_path(),
    )
    outcome_parser.add_argument(
        "--outcome-config",
        type=Path,
        default=_default_outcome_config_path(),
    )
    outcome_parser.add_argument(
        "--audit-sample-size", type=_positive_integer, default=20
    )
    outcome_parser.add_argument(
        "--workers",
        type=_positive_integer,
        default=min(os.cpu_count() or 1, 8),
        help="按股票分片的进程数（每只股票内部仍按交易日顺序；上限8）",
    )

    hardware_parser = subparsers.add_parser(
        "hardware-profile",
        help="探测本机硬件并校验原生 arm64（性能验收前置检查）",
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


def _print_error(exc: BaseException) -> None:
    if isinstance(exc, TushareTokenError):
        error = {
            "error": {
                "type": "TushareTokenError",
                "code": exc.error_code,
                "message": exc.error_code,
            }
        }
    elif isinstance(exc, PipelineError):
        error = {
            "error": {
                "type": "PipelineError",
                "code": exc.code,
                "message": redact(str(exc)),
            }
        }
    elif isinstance(exc, CapabilityUnavailable):
        error = {
            "error": {
                "type": "CapabilityUnavailable",
                "code": exc.error_code,
                "message": f"{exc.capability}: {exc.status}",
            }
        }
    else:
        error = {
            "error": {
                "type": type(exc).__name__,
                "message": redact(str(exc)),
            }
        }
    print(json.dumps(error, ensure_ascii=False), file=sys.stderr)


def _run_provider_probe(args: argparse.Namespace) -> int:
    from limit_pullback.warehouse.layout import WarehouseLayout
    from limit_pullback.warehouse.probe import probe_tushare

    layout = WarehouseLayout(resolve_data_root(args.data_root))
    try:
        result = probe_tushare(layout=layout)
    except Exception as exc:
        _print_error(exc)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


def _run_bootstrap(args: argparse.Namespace) -> int:
    from limit_pullback.warehouse.layout import WarehouseLayout
    from limit_pullback.warehouse.pipeline import bootstrap
    from limit_pullback.resources import PerformanceProfile

    layout = WarehouseLayout(resolve_data_root(args.data_root))
    try:
        result = bootstrap(
            layout=layout,
            start=args.start,
            end=args.end,
            codes=args.codes or (),
            all_main_board=args.all_main_board,
            batch_size=args.batch_size,
            active_providers=tuple(args.providers),
            workers=args.workers,
            skip_tushare_aux=args.skip_tushare_aux,
            isolate_akshare=args.isolate_akshare,
            snapshot_status=args.snapshot_status,
            aux_backfill=args.aux_backfill,
            listed_only=args.listed_only,
            profile=PerformanceProfile.load(args.profile),
        )
    except Exception as exc:
        _print_error(exc)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


def _run_update(args: argparse.Namespace) -> int:
    from limit_pullback.warehouse.layout import WarehouseLayout
    from limit_pullback.warehouse.pipeline import update

    layout = WarehouseLayout(resolve_data_root(args.data_root))
    try:
        result = update(
            layout=layout,
            as_of=args.as_of,
            codes=args.codes or (),
        )
    except Exception as exc:
        _print_error(exc)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


def _run_data_status(args: argparse.Namespace) -> int:
    from limit_pullback.warehouse.layout import WarehouseLayout
    from limit_pullback.warehouse.status import data_status

    layout = WarehouseLayout(resolve_data_root(args.data_root))
    try:
        result = data_status(layout)
    except Exception as exc:
        _print_error(exc)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


def _run_data_validate(args: argparse.Namespace) -> int:
    from limit_pullback.warehouse.layout import WarehouseLayout
    from limit_pullback.warehouse.validate import data_validate

    layout = WarehouseLayout(resolve_data_root(args.data_root))
    try:
        result = data_validate(layout, snapshot_id=args.snapshot)
    except Exception as exc:
        _print_error(exc)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


def _run_screen(args: argparse.Namespace) -> int:
    from limit_pullback.screen.runner import run_screen
    from limit_pullback.warehouse.layout import WarehouseLayout

    layout = WarehouseLayout(resolve_data_root(args.data_root))
    try:
        result = run_screen(
            layout=layout,
            as_of=args.as_of,
            snapshot_id=args.snapshot_id,
            start=args.start,
            rebuild=args.rebuild,
            codes=args.codes or (),
            config_path=args.config,
            lookback_calendar_days=args.lookback_calendar_days,
            verify_replay=args.verify_replay,
            pool_debug=args.pool_debug,
        )
    except Exception as exc:
        _print_error(exc)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


def _run_trade_plan(args: argparse.Namespace) -> int:
    from limit_pullback.config import load_strategy_config, load_trade_plan_config
    from limit_pullback.trade_plan import build_trade_plan_output
    from limit_pullback.warehouse.parquet import sha256_file

    layout = WarehouseLayout(resolve_data_root(args.data_root))
    try:
        result = build_trade_plan_output(
            layout=layout,
            as_of=args.as_of,
            snapshot_id=args.snapshot_id,
            config=load_strategy_config(args.config),
            config_hash=sha256_file(args.config),
            trade_plan_config=load_trade_plan_config(
                getattr(args, "trade_plan_config", _default_trade_plan_config_path())
            ),
            execution_config_hash=sha256_file(
                getattr(args, "trade_plan_config", _default_trade_plan_config_path())
            ),
        )
    except Exception as exc:
        _print_error(exc)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


def _run_outcome_study(args: argparse.Namespace) -> int:
    from limit_pullback.config import load_strategy_config
    from limit_pullback.outcome import run_outcome_study
    from limit_pullback.warehouse.parquet import sha256_file

    layout = WarehouseLayout(resolve_data_root(args.data_root))
    try:
        summary = run_outcome_study(
            layout=layout,
            snapshot_id=args.snapshot_id,
            start=args.start,
            end=args.end,
            strategy_config=load_strategy_config(args.config),
            strategy_config_path=args.config,
            trade_plan_config_path=args.trade_plan_config,
            outcome_config_path=args.outcome_config,
            audit_sample_size=args.audit_sample_size,
            workers=getattr(args, "workers", 1),
        )
    except Exception as exc:
        _print_error(exc)
        return 1
    print(summary.model_dump_json(indent=2))
    return 0


def _run_hardware_profile(args: argparse.Namespace) -> int:
    from limit_pullback.resources import detect_hardware

    profile = detect_hardware()
    if not profile["native_arm64"]:
        print(
            json.dumps(
                {
                    "warning": (
                        "native arm64 not detected; "
                        "formal performance acceptance is stopped"
                    ),
                    **profile,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(profile, ensure_ascii=False, indent=2))
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
    if args.command == "provider-probe":
        return _run_provider_probe(args)
    if args.command == "bootstrap":
        return _run_bootstrap(args)
    if args.command == "update":
        return _run_update(args)
    if args.command == "data-status":
        return _run_data_status(args)
    if args.command == "data-validate":
        return _run_data_validate(args)
    if args.command == "screen":
        return _run_screen(args)
    if args.command == "trade-plan":
        return _run_trade_plan(args)
    if args.command == "outcome-study":
        return _run_outcome_study(args)
    if args.command == "hardware-profile":
        return _run_hardware_profile(args)
    if args.command is None:
        parser.print_help()
    return 0
