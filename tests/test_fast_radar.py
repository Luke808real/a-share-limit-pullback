"""Offline tests for the fast-radar observation layer (asl fast integration)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from limit_pullback.fast_radar import (
    FastRadarError,
    _parse_json_rows,
    render_radar_markdown,
    run_fast_radar,
)

SCREEN_ROWS = [
    {
        "symbol": "002667.SZ",
        "cur_date": "2026-08-13",
        "cur_close": 13.6,
        "pullback_pct": -14.73,
        "bars_since_lu": 3,
        "lu_date": "2026-08-10",
        "lu_close": 15.95,
        "adj_exact": True,
    },
]
BREADTH_ROWS = [
    {
        "trade_date": "2026-08-13",
        "advancers": 1655,
        "decliners": 5429,
        "limit_ups": 62,
        "limit_downs": 4,
        "amount_yi": 29479.63,
    },
]
LIMITUP_ROWS = [
    {
        "symbol": "600491.SH",
        "trade_date": "2026-08-13",
        "pct": 10.29,
        "amount": 249308944.0,
        "board": "main",
    },
]


def _fake_run(monkeypatch, outputs: dict[str, str]) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake(cmd: list[str], *, timeout: int = 300) -> str:
        calls.append(list(cmd))
        if "screen" in cmd:
            return outputs.get("screen", "[]")
        if "breadth" in cmd:
            return outputs.get("breadth", "[]")
        if "limitup" in cmd:
            return outputs.get("limitup", "[]")
        raise AssertionError("unexpected command: " + " ".join(cmd))

    import limit_pullback.fast_radar as mod

    monkeypatch.setattr(mod, "_run", fake)
    return calls


def test_run_fast_radar_deterministic_and_parses(monkeypatch) -> None:
    calls = _fake_run(
        monkeypatch,
        {
            "screen": json.dumps(SCREEN_ROWS),
            "breadth": json.dumps(BREADTH_ROWS),
            "limitup": json.dumps(LIMITUP_ROWS),
        },
    )
    first = run_fast_radar(as_of=date(2026, 8, 13), top=30)
    second = run_fast_radar(as_of=date(2026, 8, 13), top=30)
    assert first["content_hash"] == second["content_hash"]
    assert first["screen_n"] == 1
    assert first["limitup_n"] == 1
    assert first["breadth"][-1]["trade_date"] == "2026-08-13"
    screen_cmd = next(c for c in calls if "screen" in c)
    assert "--pullback" in screen_cmd and "--top" in screen_cmd
    assert "--date" in screen_cmd and "2026-08-13" in screen_cmd


def test_run_fast_radar_empty_is_ok_not_crash(monkeypatch) -> None:
    _fake_run(monkeypatch, {})
    payload = run_fast_radar(as_of=date(2026, 8, 13))
    assert payload["screen_n"] == 0
    assert payload["breadth"] == []
    assert "content_hash" in payload


def test_run_fast_radar_fails_closed_on_command_failure(monkeypatch) -> None:
    import limit_pullback.fast_radar as mod

    def failing(cmd: list[str], *, timeout: int = 300) -> str:
        raise FastRadarError("asl fast rc=1 boom")

    monkeypatch.setattr(mod, "_run", failing)
    with pytest.raises(FastRadarError):
        run_fast_radar(as_of=date(2026, 8, 13))


def test_parse_json_rows_rejects_garbage() -> None:
    with pytest.raises(FastRadarError):
        _parse_json_rows("137 ms", what="breadth")
    with pytest.raises(FastRadarError):
        _parse_json_rows('{"not": "a list"}', what="breadth")


def test_render_markdown_covers_na_and_rows(monkeypatch) -> None:
    _fake_run(
        monkeypatch,
        {
            "screen": json.dumps(SCREEN_ROWS),
            "breadth": json.dumps(BREADTH_ROWS),
            "limitup": json.dumps(LIMITUP_ROWS),
        },
    )
    payload = run_fast_radar(as_of=date(2026, 8, 13))
    md = render_radar_markdown(payload)
    assert "OBSERVATION" in md
    assert "002667.SZ" in md
    assert "市场广度" in md and "1655" in md
    assert "600491.SH" in md
    empty = run_fast_radar(as_of=date(2026, 8, 13)) if False else {
        "as_of": "2026-08-13",
        "breadth": [],
        "screen": [],
        "limitup_top10": [],
        "content_hash": "x" * 64,
    }
    md_empty = render_radar_markdown(empty)
    assert "N/A" in md_empty
