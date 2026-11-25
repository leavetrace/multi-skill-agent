"""Shared fixtures: every test runs offline and blind to the developer's real `.env`."""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from skillagent import config
from skillagent.config import Settings

_KEY_VARS = ("GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")


def _is_local(address: Any) -> bool:
    if not isinstance(address, tuple):  # AF_UNIX path etc.
        return True
    host = str(address[0])
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on any non-loopback connection (loopback stays allowed: asyncio's
    self-pipe uses it on Windows). Tests marked `live` are exempt."""
    if request.node.get_closest_marker("live"):
        return
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if not _is_local(address):
            raise RuntimeError(f"network access attempted in an offline test: {address!r}")
        return real_connect(self, address)

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"DNS lookup attempted in an offline test: {host!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hide real keys/overrides and the repo `.env` so results never depend on the machine."""
    for name in list(os.environ):
        if name.startswith("SKILLAGENT_") or name in _KEY_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_find_env_file", lambda: None)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Settings with a dummy Google key and test-friendly limits; override via kwargs."""

    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "llm_provider": "google",
            "google_api_key": "AIza-test-key-0000000000",
            "llm_max_retries": 3,
            "llm_rpm": 0,
        }
        values.update(overrides)
        return Settings(**values)

    return factory
