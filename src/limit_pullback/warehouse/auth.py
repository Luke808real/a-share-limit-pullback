"""Tushare authentication.

The token is read exclusively from the ``TUSHARE_TOKEN`` environment
variable. It is never accepted through CLI flags, written to configuration,
stored in provider metadata, printed, or embedded in exceptions.
"""

from __future__ import annotations

import os

TOKEN_ENV_VAR = "TUSHARE_TOKEN"
TOKEN_MISSING_CODE = "TUSHARE_TOKEN_NOT_CONFIGURED"


class TushareTokenError(RuntimeError):
    """Raised when ``TUSHARE_TOKEN`` is not configured."""

    error_code = TOKEN_MISSING_CODE


def tushare_token() -> str:
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not token:
        raise TushareTokenError(TOKEN_MISSING_CODE)
    return token


def redact(value: str) -> str:
    """Remove any configured token from a message before it is persisted."""

    try:
        token = tushare_token()
    except TushareTokenError:
        return value
    if token and token in value:
        return value.replace(token, "<redacted>")
    return value
