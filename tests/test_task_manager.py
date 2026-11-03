import asyncio
from typing import Any

import pytest

from app import task_manager

pytestmark = pytest.mark.usefixtures("listeners")


@pytest.fixture
async def listeners(monkeypatch):
    """Replace real listeners with fakes and clean up any tasks left running."""
    started: list[int] = []

    async def fake_listener(mapping: dict[str, Any]) -> None:
        started.append(mapping["id"])
        if mapping.get("mode") == "crash":
            msg = "boom"
            raise RuntimeError(msg)
        if mapping.get("mode") == "finish":
            return
        await asyncio.Event().wait()

    monkeypatch.setattr(task_manager, "listen_to_ntfy", fake_listener)
    yield started
    tasks = list(task_manager.running_tasks.values())
    task_manager.running_tasks.clear()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def settle() -> None:
    """Let freshly created tasks run up to their first await."""
    for _ in range(3):
        await asyncio.sleep(0)


async def test_sync_starts_listeners_for_new_mappings(listeners):
    await task_manager.sync_listeners([{"id": 1}, {"id": 2}])
    await settle()
    assert sorted(listeners) == [1, 2]
    assert set(task_manager.running_tasks) == {1, 2}


async def test_sync_stops_listeners_for_deleted_mappings():
    await task_manager.sync_listeners([{"id": 1}, {"id": 2}])
    await settle()
    task = task_manager.running_tasks[2]

    await task_manager.sync_listeners([{"id": 1}])

    assert set(task_manager.running_tasks) == {1}
    assert task.cancelled()


@pytest.mark.parametrize("mode", ["crash", "finish"])
async def test_sync_restarts_listener_that_stopped(listeners, mode):
    mappings = [{"id": 1, "mode": mode}]
    await task_manager.sync_listeners(mappings)
    await settle()
    assert task_manager.running_tasks[1].done()

    await task_manager.sync_listeners(mappings)
    await settle()
    assert listeners == [1, 1]


async def test_sync_restarts_externally_cancelled_listener(listeners):
    await task_manager.sync_listeners([{"id": 1}])
    await settle()
    task_manager.running_tasks[1].cancel()
    await settle()

    await task_manager.sync_listeners([{"id": 1}])
    await settle()
    assert listeners == [1, 1]


async def test_sync_drops_crashed_listener_of_deleted_mapping(listeners):
    await task_manager.sync_listeners([{"id": 1, "mode": "crash"}])
    await settle()

    await task_manager.sync_listeners([])

    assert task_manager.running_tasks == {}
    assert listeners == [1]


class StopLoopError(BaseException):
    """Escapes the loop's `except Exception` to end the endless management loop."""


async def test_manage_listeners_keeps_polling_after_errors(monkeypatch):
    results: list[Any] = [
        RuntimeError("database is locked"),
        [{"id": 1}],
        StopLoopError(),
    ]

    async def fake_list_mappings() -> list[dict[str, Any]]:
        result = results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(task_manager.database, "list_mappings", fake_list_mappings)
    monkeypatch.setattr(task_manager, "POLL_INTERVAL", 0)

    with pytest.raises(StopLoopError):
        await task_manager.manage_listeners()

    assert results == []
    assert set(task_manager.running_tasks) == {1}
