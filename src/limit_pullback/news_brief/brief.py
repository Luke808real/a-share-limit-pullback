"""News brief builder: deterministic observation-layer output.

OBSERVATION layer only: output feeds human decision-making, never the
frozen strategy. Empty or stale tables render as explicit N/A, never as
guessed content.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from limit_pullback.news_brief.asl_reader import (
    NEWS_TABLES,
    _connect,
    fetch_symbol_items,
    table_availability,
)
from limit_pullback.news_brief.models import (
    NewsBriefOutput,
    NewsItem,
    SymbolNews,
    TableAvailability,
)


def _validate_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    cleaned: list[str] = []
    for code in codes:
        code = code.strip()
        if not code.isdigit() or len(code) != 6:
            raise ValueError(f"invalid code {code!r}: must be 6 digits")
        if code not in cleaned:
            cleaned.append(code)
    return tuple(sorted(cleaned))


def _sort_key(item: NewsItem) -> tuple:
    return (
        item.event_date,
        item.publish_time or "00:00:00",
        item.title or "",
        item.table,
        item.symbol,
    )


def _content_payload(
    availability: tuple[TableAvailability, ...],
    symbol_news: tuple[SymbolNews, ...],
) -> str:
    payload = {
        "availability": [
            {
                "table": a.table,
                "exists": a.exists,
                "max_event_date": (
                    a.max_event_date.isoformat() if a.max_event_date else None
                ),
                "status": a.status,
            }
            for a in availability
        ],
        "symbol_news": [
            {
                "code": sn.code,
                "items": [
                    {
                        "table": i.table,
                        "symbol": i.symbol,
                        "event_date": i.event_date.isoformat(),
                        "publish_time": i.publish_time,
                        "title": i.title,
                        "summary": i.summary,
                        "importance": i.importance,
                        "category": i.category,
                        "reason": i.reason,
                        "net_amount": i.net_amount,
                        "url": i.url,
                    }
                    for i in sn.items
                ],
            }
            for sn in symbol_news
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_news_brief(
    *,
    db_path: Path,
    as_of: date,
    codes: tuple[str, ...],
    window_days: int = 3,
) -> NewsBriefOutput:
    """Join the ASL news tables against requested codes, deterministically."""

    if window_days < 1:
        raise ValueError("window_days must be >= 1")
    cleaned = _validate_codes(codes)
    window_start = as_of - timedelta(days=window_days - 1)

    con = _connect(db_path)
    try:
        availability: list[TableAvailability] = []
        items_by_code: dict[str, list[NewsItem]] = {code: [] for code in cleaned}
        for table in NEWS_TABLES:
            avail = table_availability(con, table, window_start)
            if avail.status != "OK":
                availability.append(avail)
                continue
            rows = fetch_symbol_items(con, table, cleaned, window_start, as_of)
            avail = TableAvailability(
                table=table,
                exists=avail.exists,
                max_event_date=avail.max_event_date,
                rows_in_window=len(rows),
                status="OK",
            )
            availability.append(avail)
            for item in rows:
                code = item.symbol.split(".", 1)[0]
                if code in items_by_code:
                    items_by_code[code].append(item)
    finally:
        con.close()

    symbol_news: list[SymbolNews] = []
    for code in cleaned:
        items = sorted(items_by_code[code], key=_sort_key, reverse=True)
        symbol_news.append(SymbolNews(code=code, items=tuple(items)))
    availability_tuple = tuple(availability)
    symbol_news_tuple = tuple(symbol_news)
    payload = _content_payload(availability_tuple, symbol_news_tuple)
    content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    return NewsBriefOutput(
        as_of=as_of,
        window_start=window_start,
        symbols_requested=cleaned,
        symbols_matched=sum(1 for sn in symbol_news_tuple if sn.items),
        availability=availability_tuple,
        symbol_news=symbol_news_tuple,
        content_hash=content_hash,
        asl_db_path=str(db_path),
    )


def _availability_line(a: TableAvailability) -> str:
    if not a.exists:
        return f"{a.table}=TABLE_MISSING"
    if a.status == "STALE":
        return f"{a.table}=STALE(max {a.max_event_date.isoformat()})"
    if a.status == "NO_ROWS_IN_WINDOW":
        return f"{a.table}=NO_ROWS_IN_WINDOW"
    return f"{a.table}=OK(rows {a.rows_in_window})"


def render_markdown(output: NewsBriefOutput) -> str:
    """Human-facing brief; explicit N/A everywhere data cannot speak."""

    lines: list[str] = []
    lines.append(f"# 消息面观察 Brief — {output.as_of.isoformat()}")
    lines.append("")
    lines.append(
        f"- 窗口: {output.window_start.isoformat()} .. {output.as_of.isoformat()}"
    )
    lines.append(f"- 数据源: {output.asl_db_path}（只读）")
    lines.append(
        "- 表状态: " + " / ".join(_availability_line(a) for a in output.availability)
    )
    lines.append(
        f"- 请求标的: {len(output.symbols_requested)} 只, 命中 {output.symbols_matched} 只"
    )
    lines.append(f"- content_hash: {output.content_hash}")
    lines.append("")
    lines.append("> OBSERVATION 层：仅供人工决策，不进入冻结策略。")

    for sn in output.symbol_news:
        lines.append("")
        lines.append(f"## {sn.code}")
        if not sn.items:
            lines.append("")
            lines.append("- N/A — 窗口内无关联消息（见表状态；STALE/TABLE_MISSING 表示数据缺口，非「无消息」）")
            continue
        for item in sn.items:
            when = item.event_date.isoformat()
            if item.publish_time:
                when = f"{when} {item.publish_time}"
            prefix = f"- [{item.table}] {when}"
            extras = []
            if item.importance:
                extras.append(f"重要性={item.importance}")
            if item.category:
                extras.append(f"类别={item.category}")
            if item.reason:
                extras.append(f"上榜原因={item.reason}")
            if item.net_amount:
                extras.append(f"净额={item.net_amount}")
            title = item.title or item.summary or ""
            suffix = "（" + "; ".join(extras) + "）" if extras else ""
            lines.append(f"{prefix} {title}{suffix}")

    lines.append("")
    lines.append("## 使用边界")
    lines.append("")
    lines.append(
        "- 本 brief 只做事件提醒；涨停/回踩判断仍以冻结策略与人工复盘为准。"
    )
    lines.append("- 任何策略结论不得直接引用本 brief；提升需 Owner 单独批准。")
    return chr(10).join(lines) + chr(10)
