"""Read-only ASL lake access for the news observation layer.

All DuckDB connections are opened read_only. Nothing here writes to the
ASL lake; ingestion happens only through the ASL project's own CLI/steps.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from limit_pullback.news_brief.models import NewsItem, TableAvailability

NEWS_TABLES = (
    "news_headlines",
    "flash_news_wire",
    "announcement_index",
    "dragon_tiger",
)

_DATE_COL = {
    "news_headlines": "publish_date",
    "flash_news_wire": "publish_date",
    "announcement_index": "announce_date",
    "dragon_tiger": "trade_date",
}


class AslLakeUnavailableError(RuntimeError):
    """The ASL lake database cannot be opened read-only."""


def _connect(db_path: Path):
    import duckdb

    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        raise AslLakeUnavailableError(f"cannot open {db_path}: {exc}") from exc
    con.execute("SET threads=2")
    con.execute("SET memory_limit='512MB'")
    return con


def _table_exists(con, table: str) -> bool:
    rows = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name = ?",
        [table],
    ).fetchone()
    return bool(rows and rows[0])


def _max_event_date(con, table: str) -> date | None:
    date_col = _DATE_COL[table]
    row = con.execute(f"SELECT max({date_col}) FROM {table}").fetchone()
    return row[0] if row and row[0] is not None else None


def _window_rows(con, table: str, window_start: date, as_of: date) -> list[dict]:
    date_col = _DATE_COL[table]
    sql = (
        f"SELECT * FROM {table} "
        f"WHERE {date_col} >= CAST(? AS DATE) AND {date_col} <= CAST(? AS DATE)"
    )
    rows = con.execute(sql, [window_start.isoformat(), as_of.isoformat()]).fetchall()
    cols = [desc[0] for desc in con.description]
    return [dict(zip(cols, row, strict=True)) for row in rows]


def _token_matches(token: str, codes: frozenset[str]) -> str | None:
    text = token.strip().upper()
    if not text:
        return None
    code = text.split(".", 1)[0]
    return code if code in codes else None


def _related_symbol_tokens(raw) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(t.strip() for t in str(raw).split(",") if t.strip())


def table_availability(con, table: str, window_start: date) -> TableAvailability:
    """Table-level status, computed before any join."""

    if not _table_exists(con, table):
        return TableAvailability(table=table, exists=False, status="TABLE_MISSING")
    max_date = _max_event_date(con, table)
    if max_date is None:
        return TableAvailability(
            table=table, exists=True, max_event_date=None,
            rows_in_window=0, status="NO_ROWS_IN_WINDOW",
        )
    if max_date < window_start:
        return TableAvailability(
            table=table, exists=True, max_event_date=max_date,
            rows_in_window=0, status="STALE",
        )
    return TableAvailability(
        table=table, exists=True, max_event_date=max_date,
        rows_in_window=0, status="OK",
    )


def fetch_symbol_items(
    con,
    table: str,
    codes: tuple[str, ...],
    window_start: date,
    as_of: date,
) -> list[NewsItem]:
    """Rows in the window matched to requested codes (one item per code)."""

    if not _table_exists(con, table):
        return []
    code_set = frozenset(codes)
    items: list[NewsItem] = []
    for row in _window_rows(con, table, window_start, as_of):
        event_date = row.get(_DATE_COL[table])
        if event_date is None:
            continue
        if isinstance(event_date, str):
            event_date = date.fromisoformat(event_date)
        if table in ("news_headlines", "flash_news_wire"):
            matched = [
                code
                for token in _related_symbol_tokens(row.get("related_symbols"))
                if (code := _token_matches(token, code_set)) is not None
            ]
        else:
            code = _token_matches(str(row.get("symbol") or ""), code_set)
            matched = [code] if code else []
        for code in sorted(set(matched)):
            items.append(
                NewsItem(
                    table=table,
                    symbol=f"{code}.{_exchange_for(code, str(row.get('symbol') or ''))}",
                    event_date=event_date,
                    publish_time=_as_str(row.get("publish_time")),
                    title=_as_str(row.get("title")),
                    summary=_as_str(row.get("summary")),
                    importance=_as_str(row.get("importance")),
                    category=_as_str(row.get("category")),
                    reason=_as_str(row.get("reason")),
                    net_amount=_as_str(row.get("net_amount")),
                    url=_as_str(row.get("url")),
                )
            )
    return items


def _as_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _exchange_for(code: str, raw_symbol: str) -> str:
    if raw_symbol and "." in raw_symbol:
        exch = raw_symbol.rsplit(".", 1)[-1].upper()
        if exch in ("SH", "SZ", "BJ"):
            return exch
    return "SH" if code.startswith(("60", "68", "51", "58")) else "SZ"
