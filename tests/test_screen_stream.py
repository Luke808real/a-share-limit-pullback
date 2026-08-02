from __future__ import annotations

import hashlib
import json

from limit_pullback.screen.runner import _digest


def test_stream_hash_matches_list_hash():
    rows = [
        {"code": "000001", "trade_date": "2026-07-31", "value": None, "flag": True, "name": "测试"},
        {"code": "000002", "trade_date": "2026-07-31", "value": {"x": 1}, "flag": False},
    ]
    old = _digest(json.dumps(rows, sort_keys=True, ensure_ascii=False))
    h = hashlib.sha256()
    first = True
    h.update(b"[")
    for row in rows:
        text = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if not first:
            h.update(b", ")
        first = False
        h.update(text.encode("utf-8"))
    h.update(b"]")
    assert h.hexdigest() == old


def test_stream_hash_zero_rows_is_sha256_empty_list():
    old = _digest(json.dumps([], sort_keys=True, ensure_ascii=False))
    assert old == hashlib.sha256(b"[]").hexdigest()
    h = hashlib.sha256()
    first = True
    h.update(b"[")
    # no rows
    h.update(b"]")
    assert h.hexdigest() == old
