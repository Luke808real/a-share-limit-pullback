"""Whole-market radar via the ASL "asl fast" tool (OBSERVATION layer).

Read-only over the ASL lake. Produces a deterministic radar payload and a
markdown section appended to the daily watchlist. This is a fast
observation net for the human workflow; it is NOT a strategy input and
never feeds frozen semantics.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import date
from pathlib import Path

DEFAULT_ASL_BIN = (
    "/Users/luke808/AI/ashare-lake-architecture-convergence-v01/.venv/bin/asl"
)
DEFAULT_ASL_CONFIG = "/Users/luke808/AI/asl-shared-config.toml"


class FastRadarError(RuntimeError):
    """The asl fast tool could not produce the radar (fail-closed)."""


def _asl_bin() -> str:
    return os.environ.get("ASL_BIN", DEFAULT_ASL_BIN)


def _asl_config() -> str:
    return os.environ.get("ASL_CONFIG", DEFAULT_ASL_CONFIG)


def _run(cmd: list[str], *, timeout: int = 300) -> str:
    """Run one asl fast command; raise FastRadarError on any failure."""

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FastRadarError(f"asl fast spawn failed: {exc}") from exc
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip().splitlines()[-3:]
        raise FastRadarError(
            "asl fast rc=" + str(completed.returncode) + " " + " | ".join(tail)
        )
    return completed.stdout


def _parse_json_rows(stdout: str, *, what: str) -> list[dict]:
    try:
        rows = json.loads(stdout.strip() or "[]")
    except json.JSONDecodeError as exc:
        raise FastRadarError(f"{what}: stdout is not JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise FastRadarError(f"{what}: expected a JSON array")
    return rows


def run_fast_radar(*, as_of: date, top: int = 30) -> dict:
    """Run the three radar queries and return a deterministic payload."""

    bin_path = _asl_bin()
    config = _asl_config()
    screen_cmd = [
        bin_path, "fast", "screen", "--config", config,
        "--date", as_of.isoformat(),
        "--pullback", "--limitup-within", "5",
        "--pullback-min", "3", "--pullback-max", "15",
        "--top", str(top), "--json", "--no-timer",
    ]
    breadth_cmd = [
        bin_path, "fast", "stats", "breadth", "--config", config,
        "--days", "1", "--json",
    ]
    limitup_cmd = [
        bin_path, "fast", "stats", "limitup", "--config", config,
        "--json",
    ]
    screen_rows = _parse_json_rows(_run(screen_cmd), what="screen")
    breadth_rows = _parse_json_rows(_run(breadth_cmd), what="breadth")
    limitup_rows = _parse_json_rows(_run(limitup_cmd), what="limitup")
    payload = {
        "as_of": as_of.isoformat(),
        "screen_n": len(screen_rows),
        "screen": screen_rows[:top],
        "breadth": breadth_rows,
        "limitup_n": len(limitup_rows),
        "limitup_top10": limitup_rows[:10],
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    payload["content_hash"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return payload


def render_radar_markdown(payload: dict) -> str:
    """Human-facing radar section (explicit N/A everywhere)."""

    lines: list[str] = []
    lines.append("")
    lines.append("## 全市场雷达（OBSERVATION，asl fast）")
    lines.append("")
    lines.append(f"- as_of: {payload.get('as_of')}  content_hash: {payload.get('content_hash')}")
    lines.append("- 口径：涨停=原始收盘 vs 板块涨跌停价（主板10%/创业科创20%/北交30%，ST未识别）；")
    lines.append("  回调=后复权价（复权因子缺失时回退原始价，以 adj_is_exact 标记）。")
    lines.append("- 定位：快路径观察网，不进入冻结策略；最终判断仍以人工与冻结引擎为准。")
    lines.append("")
    breadth = payload.get("breadth") or []
    if breadth:
        row = breadth[-1]
        lines.append(
            f"- 市场广度（{row.get('trade_date')}）：上涨 {row.get('advancers')} / "
            f"下跌 {row.get('decliners')} / 涨停 {row.get('limit_ups')} / "
            f"跌停 {row.get('limit_downs')} / 成交额 {row.get('amount_yi')} 亿"
        )
    else:
        lines.append("- 市场广度：N/A（无数据）")
    lines.append("")
    screen = payload.get("screen") or []
    if screen:
        lines.append(f"### 涨停回踩候选（回调 3-15%，前 {len(screen)} 只）")
        lines.append("")
        lines.append(
            "| symbol | cur_date | cur_close | pullback_pct | bars_since_lu | lu_date | lu_close | adj_exact |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in screen:
            lines.append(
                f"| {row.get('symbol')} | {row.get('cur_date')} | {row.get('cur_close')} | "
                f"{row.get('pullback_pct')} | {row.get('bars_since_lu')} | {row.get('lu_date')} | "
                f"{row.get('lu_close')} | {row.get('adj_exact')} |"
            )
    else:
        lines.append("### 涨停回踩候选：N/A（窗口内无候选或数据缺失）")
    limitup = payload.get("limitup_top10") or []
    if limitup:
        lines.append("")
        lines.append("### 当日涨停榜（按成交额前 10）")
        lines.append("")
        for row in limitup:
            amount_yi = round((row.get("amount") or 0) / 1e8, 2)
            lines.append(
                f"- {row.get('symbol')} {row.get('trade_date')} 涨幅 {row.get('pct')}% "
                f"成交额 {amount_yi} 亿（{row.get('board')}）"
            )
    return chr(10).join(lines) + chr(10)
