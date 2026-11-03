"""Database operations for the ntfy-discord-bridge service."""

import os
import pathlib
from typing import Any

import aiosqlite

from app.core.logging import log

# Database path, preferably mounted as a Docker volume. Defaults to data/ in the
# project root, which is /app/data inside the Docker image.
DEFAULT_DB_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "bridge.db"
DB_PATH = os.environ.get("DB_PATH", str(DEFAULT_DB_PATH))


async def init_db() -> None:
    """Create the mappings table if it doesn't exist."""
    pathlib.Path(DB_PATH).parent.mkdir(exist_ok=True, parents=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ntfy_server TEXT NOT NULL,
                ntfy_topic TEXT NOT NULL,
                discord_webhook TEXT NOT NULL,
                ntfy_auth_header TEXT,
                UNIQUE(ntfy_server, ntfy_topic, discord_webhook)
            )
        """)
        await db.commit()


async def add_mapping(
    server: str,
    topic: str,
    webhook: str,
    auth_header: str | None = None,
) -> bool:
    """Add a new mapping to the database.

    Args:
        server: The ntfy server URL.
        topic: The ntfy topic.
        webhook: The Discord webhook URL.
        auth_header: The ntfy authentication header.

    Returns:
        True if the mapping was added successfully, False otherwise.

    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO mappings
                (ntfy_server, ntfy_topic, discord_webhook, ntfy_auth_header)
                VALUES (?, ?, ?, ?)
                """,
                (server, topic, webhook, auth_header),
            )
            await db.commit()
        log.info("Mapping added: %s/%s -> Discord", server, topic)
    except aiosqlite.IntegrityError:
        # The webhook URL is left out on purpose: it embeds a secret token
        log.warning("Mapping %s/%s -> this webhook already exists.", server, topic)
        return False

    return True


async def remove_mapping(mapping_id: int) -> bool:
    """Remove a mapping based on its ID.

    Args:
        mapping_id: The ID of the mapping to remove.

    Returns:
        True if the mapping was removed successfully, False otherwise.

    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM mappings WHERE id = ?", (mapping_id,))
        await db.commit()
        if cursor.rowcount == 0:
            log.warning("Mapping not found with ID: %s", mapping_id)
            return False
        log.info("Mapping removed with ID: %s", mapping_id)
        return True


async def list_mappings() -> list[dict[str, Any]]:
    """Return a list of all mappings.

    Returns:
        A list of all mappings.

    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Use Row factory to get results as dictionaries
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM mappings") as cursor:
            rows = await cursor.fetchall()
            # Convert Row objects to regular dictionaries
            return [dict(row) for row in rows]
