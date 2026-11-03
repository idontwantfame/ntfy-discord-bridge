"""Task management module for handling listener tasks."""

import asyncio
from typing import Any

from app.core import database
from app.core.logging import log
from app.listener import listen_to_ntfy

# How often the database is checked for added or removed mappings (seconds)
POLL_INTERVAL = 30

# Dictionary storing active listening tasks (mapping ID -> asyncio task)
running_tasks: dict[int, asyncio.Task] = {}


def _cleanup_failed_tasks() -> list[int]:
    """Check for failed/completed tasks and clean them up.

    Listeners reconnect on their own, so a finished task means it crashed.

    Returns:
        List of mapping IDs that failed and should be restarted.

    """
    failed_task_ids = []
    for mapping_id, task in list(running_tasks.items()):
        if task.done():
            failed_task_ids.append(mapping_id)
            _log_task_failure(mapping_id, task)
            # Remove the failed task
            running_tasks.pop(mapping_id, None)
    return failed_task_ids


def _log_task_failure(mapping_id: int, task: asyncio.Task) -> None:
    """Log task failure information.

    Args:
        mapping_id: The mapping ID.
        task: The failed task.

    """
    if task.cancelled():
        log.warning(
            "Task [ID: %(mapping_id)s] was cancelled unexpectedly.",
            {"mapping_id": mapping_id},
        )
        return

    exception = task.exception()
    if exception:
        log.error(
            (
                "Task [ID: %(mapping_id)s] has failed: %(error)s. "
                "Will restart if mapping still exists."
            ),
            {"mapping_id": mapping_id, "error": exception},
            exc_info=exception,
        )
    else:
        log.warning(
            "Task [ID: %(mapping_id)s] has completed unexpectedly.",
            {"mapping_id": mapping_id},
        )


def _start_new_listeners(
    mappings: list[dict[str, Any]],
    failed_task_ids: list[int],
) -> None:
    """Start new listeners for mappings that don't have active tasks.

    Args:
        mappings: List of mappings from database.
        failed_task_ids: List of mapping IDs that failed and should be restarted.

    """
    for mapping in mappings:
        mapping_id = mapping["id"]
        if mapping_id not in running_tasks:
            if mapping_id in failed_task_ids:
                log.info(
                    ("Restarting failed listener for mapping [ID: %(mapping_id)s]..."),
                    {"mapping_id": mapping_id},
                )
            else:
                log.info(
                    ("Found new mapping [ID: %(mapping_id)s], starting listener..."),
                    {"mapping_id": mapping_id},
                )
            task = asyncio.create_task(listen_to_ntfy(mapping))
            running_tasks[mapping_id] = task


async def _stop_deleted_listeners(stale_task_ids: set[int]) -> None:
    """Stop and cancel tasks for deleted mappings.

    Args:
        stale_task_ids: Set of mapping IDs that no longer exist in database.

    """
    for mapping_id in stale_task_ids:
        log.info(
            ("Mapping [ID: %(mapping_id)s] has been deleted, stopping listener..."),
            {"mapping_id": mapping_id},
        )
        task = running_tasks.pop(mapping_id)
        task.cancel()
        # Unlike awaiting the task, asyncio.wait never swallows a cancellation
        # of this coroutine itself (e.g. during shutdown)
        await asyncio.wait([task])
        if not task.cancelled() and task.exception() is not None:
            _log_task_failure(mapping_id, task)


async def sync_listeners(mappings: list[dict[str, Any]]) -> None:
    """Start, restart and stop listener tasks to match the given mappings.

    Args:
        mappings: All mappings currently in the database.

    """
    failed_task_ids = _cleanup_failed_tasks()
    current_mapping_ids = {m["id"] for m in mappings}
    await _stop_deleted_listeners(set(running_tasks) - current_mapping_ids)
    _start_new_listeners(mappings, failed_task_ids)


async def manage_listeners() -> None:
    """Main management loop.

    Checks the database and dynamically starts/stops listening tasks.
    """
    while True:
        try:
            log.debug("🔄 Checking for database updates...")
            await sync_listeners(await database.list_mappings())
        except Exception as e:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            log.error(
                "Error in management loop: %(error)r",
                {"error": e},
                exc_info=True,
            )

        await asyncio.sleep(POLL_INTERVAL)
