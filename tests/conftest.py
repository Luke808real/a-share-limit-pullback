from __future__ import annotations

import socket
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


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]
