"""Offline tests for the news brief observation layer."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from limit_pullback.news_brief import build_news_brief, render_markdown
from limit_pullback.news_brief.models import NewsBriefOutput

HEADLINES_SCHEMA = (
    "(news_id VARCHAR, publish_date DATE, publish_time VARCHAR, title VARCHAR,"
    " summary VARCHAR, related_symbols VARCHAR, channel VARCHAR, source VARCHAR,"
    " data_version VARCHAR, fetched_at TIMESTAMP)"
)
WIRE_SCHEMA = (
    "(wire_id VARCHAR, wire_source VARCHAR, item_hash VARCHAR, publish_date DATE,"
    " publish_time VARCHAR, title VARCHAR, summary VARCHAR, related_symbols VARCHAR,"
    " importance VARCHAR, channel VARCHAR, source VARCHAR, data_version VARCHAR,"
    " fetched_at TIMESTAMP)"
)
ANNOUNCEMENT_SCHEMA = (
    "(announcement_id VARCHAR, symbol VARCHAR, title VARCHAR, announce_date DATE,"
    " category VARCHAR, url VARCHAR, source VARCHAR, data_version VARCHAR,"
    " fetched_at TIMESTAMP)"
)
DRAGON_SCHEMA = (
    "(symbol VARCHAR, trade_date DATE, reason VARCHAR, buy_amount DOUBLE,"
    " sell_amount DOUBLE, net_amount DOUBLE, source VARCHAR, data_version VARCHAR,"
    " fetched_at TIMESTAMP)"
)


@pytest.fixture
def asl_db(tmp_path) -> Path:
    db = tmp_path / "ashare-lake.duckdb"
    con = duckdb.connect(str(db))
    con.execute(f"CREATE TABLE news_headlines {HEADLINES_SCHEMA}")
    con.execute(f"CREATE TABLE flash_news_wire {WIRE_SCHEMA}")
    con.execute(f"CREATE TABLE announcement_index {ANNOUNCEMENT_SCHEMA}")
    con.execute(f"CREATE TABLE dragon_tiger {DRAGON_SCHEMA}")
    con.close()
    return db


def _insert(db: Path, table: str, rows: list[tuple]) -> None:
    con = duckdb.connect(str(db))
    try:
        placeholders = ", ".join(["?"] * len(rows[0]))
        con.executemany(
            f"INSERT INTO {table} VALUES ({placeholders})", rows
        )
    finally:
        con.close()


def _full_asl(db: Path) -> NewsBriefOutput:
    _insert(
        db,
        "news_headlines",
        [
            ("n1", date(2026, 8, 13), "09:15", "600468 相关快讯", "摘要A",
             "600468.SH,000001.SZ", "fast_news", "eastmoney", "v1", None),
            ("n2", date(2026, 8, 10), "14:00", "旧新闻窗口外", "摘要B",
             "600468.SH", "fast_news", "eastmoney", "v1", None),
        ],
    )
    _insert(
        db,
        "flash_news_wire",
        [
            ("w1", "eastmoney", "h1", date(2026, 8, 13), "10:00", "快讯标题", None,
             "600468.SH", "high", "fast_news", "eastmoney", "v1", None),
        ],
    )
    _insert(
        db,
        "announcement_index",
        [
            ("a1", "000659.SZ", "珠海中富公告", date(2026, 8, 13), "业绩预告",
             "http://example/a1", "cninfo", "v1", None),
        ],
    )
    _insert(
        db,
        "dragon_tiger",
        [
            ("002112.SZ", date(2026, 8, 13), "日涨幅偏离值达7%", 100.0, 50.0, 50.0,
             "eastmoney", "v1", None),
        ],
    )
    return build_news_brief(
        db_path=db,
        as_of=date(2026, 8, 13),
        codes=("600468", "000659", "002112", "000001"),
        window_days=3,
    )


def test_build_matches_all_tables_and_is_deterministic(asl_db) -> None:
    first = _full_asl(asl_db)
    second = build_news_brief(
        db_path=asl_db,
        as_of=date(2026, 8, 13),
        codes=("600468", "000659", "002112", "000001"),
        window_days=3,
    )
    assert first.content_hash == second.content_hash
    assert first.model_dump_json() == second.model_dump_json()
    assert first.symbols_matched == 4
    by_code = {sn.code: sn for sn in first.symbol_news}
    assert len(by_code["600468"].items) == 2  # headline + wire
    assert by_code["600468"].items[0].event_date == date(2026, 8, 13)
    assert by_code["600468"].items[0].publish_time in ("10:00", "09:15")
    assert by_code["000659"].items[0].table == "announcement_index"
    assert by_code["002112"].items[0].table == "dragon_tiger"
    assert by_code["002112"].items[0].reason is not None
    assert len(by_code["000001"].items) == 1  # related token in headline row
    assert all(a.status == "OK" for a in first.availability)


def test_window_filter_excludes_older_rows(asl_db) -> None:
    brief = _full_asl(asl_db)
    by_code = {sn.code: sn for sn in brief.symbol_news}
    titles = [i.title for i in by_code["600468"].items]
    assert "旧新闻窗口外" not in titles


def test_bare_code_token_matches(asl_db) -> None:
    _insert(
        asl_db,
        "flash_news_wire",
        [
            ("w2", "eastmoney", "h2", date(2026, 8, 13), "11:00", "裸代码匹配", None,
             "600468", "low", "fast_news", "eastmoney", "v1", None),
        ],
    )
    brief = build_news_brief(
        db_path=asl_db,
        as_of=date(2026, 8, 13),
        codes=("600468",),
        window_days=3,
    )
    assert any("裸代码匹配" == i.title for i in brief.symbol_news[0].items)


def test_missing_table_reported_not_crash(asl_db) -> None:
    con = duckdb.connect(str(asl_db))
    try:
        con.execute("DROP TABLE announcement_index")
    finally:
        con.close()
    brief = build_news_brief(
        db_path=asl_db,
        as_of=date(2026, 8, 13),
        codes=("000659",),
        window_days=3,
    )
    avail = {a.table: a for a in brief.availability}
    assert avail["announcement_index"].status == "TABLE_MISSING"
    assert brief.symbol_news[0].items == ()
    md = render_markdown(brief)
    assert "TABLE_MISSING" in md
    assert "N/A" in md


def test_empty_tables_render_no_rows(asl_db) -> None:
    brief = build_news_brief(
        db_path=asl_db,
        as_of=date(2026, 8, 13),
        codes=("600468",),
        window_days=3,
    )
    assert {a.status for a in brief.availability} == {"NO_ROWS_IN_WINDOW"}
    assert brief.symbols_matched == 0
    md = render_markdown(brief)
    assert "NO_ROWS_IN_WINDOW" in md


def test_stale_table_status(asl_db) -> None:
    _insert(
        asl_db,
        "news_headlines",
        [
            ("n9", date(2026, 7, 30), "10:00", "窗口外旧数据", None,
             "600468.SH", "fast_news", "eastmoney", "v1", None),
        ],
    )
    brief = build_news_brief(
        db_path=asl_db,
        as_of=date(2026, 8, 13),
        codes=("600468",),
        window_days=3,
    )
    avail = {a.table: a for a in brief.availability}
    assert avail["news_headlines"].status == "STALE"
    assert brief.symbol_news[0].items == ()


def test_invalid_code_rejected(asl_db) -> None:
    with pytest.raises(ValueError):
        build_news_brief(
            db_path=asl_db, as_of=date(2026, 8, 13), codes=("12345",), window_days=3
        )
    with pytest.raises(ValueError):
        build_news_brief(
            db_path=asl_db, as_of=date(2026, 8, 13), codes=("abc123",), window_days=3
        )


def test_render_markdown_has_observation_boundary(asl_db) -> None:
    brief = _full_asl(asl_db)
    md = render_markdown(brief)
    assert brief.content_hash in md
    assert "OBSERVATION" in md
    assert "## 600468" in md
    assert "## 000001" in md  # unmatched code still rendered with N/A
