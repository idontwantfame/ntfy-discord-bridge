"""Main module for the ntfy-discord-bridge service."""

import asyncio
import signal

import uvloop

from app.core import database
from app.core.logging import log
from app.task_manager import manage_listeners


async def main() -> None:
    """Main function."""
    log.info("🚀 Starting Ntfy-Discord Bridge...")
    await database.init_db()
    log.info("Database initialized at %s", database.DB_PATH)

    # As PID 1 in a container, Python would ignore the SIGTERM sent by
    # `docker stop`, so cancel the main task to shut down cleanly instead
    main_task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, main_task.cancel)

    try:
        await manage_listeners()
    except asyncio.CancelledError:
        log.info("👋 Shutting down...")


if __name__ == "__main__":
    # Use uvloop for higher performance
    uvloop.run(main())
