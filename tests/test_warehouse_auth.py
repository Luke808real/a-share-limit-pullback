from __future__ import annotations

import pytest

from limit_pullback.warehouse.auth import (
    TOKEN_MISSING_CODE,
    TushareTokenError,
    redact,
    tushare_token,
)


def test_token_missing_raises_structured_error(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    with pytest.raises(TushareTokenError) as exc_info:
        tushare_token()
    assert exc_info.value.error_code == TOKEN_MISSING_CODE
    assert TOKEN_MISSING_CODE in str(exc_info.value)


def test_redact_removes_token_from_message(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-token-value")
    assert "fake-token-value" not in redact("error with fake-token-value inside")
    assert "<redacted>" in redact("error with fake-token-value inside")


def test_redact_without_token_leaves_message(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    assert redact("plain message") == "plain message"


def test_token_value_never_printed_by_auth(capsys, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "secret-token-abc")
    token = tushare_token()
    assert token == "secret-token-abc"
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
