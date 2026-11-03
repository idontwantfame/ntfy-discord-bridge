"""Shared test fixtures."""

import asyncio
from collections.abc import Awaitable, Callable

import httpx
import pytest

from app import discord, ntfy
from app.core import database

ReplayItem = httpx.Response | Exception
ReplayFactory = Callable[..., tuple[httpx.AsyncClient, list[httpx.Request]]]


class AsyncioWithSleep:
    """Stand-in for a module's ``asyncio`` that only replaces ``sleep``."""

    def __init__(self, sleep: Callable[[float], Awaitable[None]]) -> None:
        self.sleep = sleep

    def __getattr__(self, name: str) -> object:
        return getattr(asyncio, name)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Make the app's retry sleeps no-ops that record the requested delays.

    Only the app modules' view of asyncio is patched, so the event loop and
    other tasks keep the real asyncio.sleep.
    """
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    for module in (discord, ntfy):
        monkeypatch.setattr(module, "asyncio", AsyncioWithSleep(fake_sleep))
    return delays


@pytest.fixture
def replay() -> ReplayFactory:
    """Build an HTTP client that answers each request with the next queued item.

    Exceptions in the queue are raised instead of returning a response; an
    exhausted queue raises IndexError so a runaway retry loop fails fast.
    """

    def factory(*items: ReplayItem) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
        queue = list(items)
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return httpx.AsyncClient(transport=httpx.MockTransport(handler)), requests

    return factory


@pytest.fixture
def db_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the database at a fresh file in a not-yet-existing directory."""
    path = str(tmp_path / "nested" / "bridge.db")
    monkeypatch.setattr(database, "DB_PATH", path)
    return path
