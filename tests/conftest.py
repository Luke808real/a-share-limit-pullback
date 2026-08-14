from __future__ import annotations

import socket
import time
from pathlib import Path
from typing import NoReturn

import pytest


@pytest.fixture(autouse=True)
def block_all_socket_network(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    if request.node.get_closest_marker("integration") is not None:
        return

    def blocked(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("network access is forbidden in the test suite")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture(autouse=True)
def no_retry_backoff_sleeps(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Provider probe/retry backoffs sleep for real wall-clock seconds; the
    offline suite asserts retry counts and statuses, never elapsed time.
    No-op time.sleep everywhere except the one test that needs a real beat."""
    if request.node.name == "test_parent_sampler_thread_stops_on_event":
        return
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]
