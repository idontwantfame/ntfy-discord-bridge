"""Listener forwarding the messages of one Ntfy -> Discord mapping."""

from contextlib import aclosing
from typing import Any

import aiosqlite
import httpx

from app.core import database
from app.core.auth import describe_auth
from app.core.logging import log
from app.discord import DISCORD_TIMEOUT, post_to_discord
from app.ntfy import CONNECT_TIMEOUT, STREAM_READ_TIMEOUT, subscribe


def _ntfy_headers(auth_header: str | None) -> dict[str, str]:
    """Build the headers for the Ntfy stream request.

    Returns:
        The request headers, including Authorization when credentials are set.

    """
    headers = {
        "User-Agent": "ntfy-discord-bridge/0.1.0",
        "Accept": "application/x-ndjson, application/json",
    }
    if auth_header:
        return {**headers, "Authorization": auth_header}
    return headers


async def listen_to_ntfy(mapping: dict[str, Any]) -> None:
    """Forward messages from a Ntfy topic to a Discord webhook until cancelled.

    The stream resumes from the mapping's saved resume point, so messages
    published while the bridge was stopped are delivered once it is back.

    Args:
        mapping: The mapping dictionary from the database.

    """
    mapping_id = mapping["id"]
    server = mapping["ntfy_server"]
    topic = mapping["ntfy_topic"]
    auth_header = mapping.get("ntfy_auth_header")
    ntfy_url = f"{server.rstrip('/')}/{topic.lstrip('/')}/json"

    log.info(
        "[ID: %(mapping_id)s] Starting listening to Ntfy: %(url)s (auth: %(auth)s)",
        {"mapping_id": mapping_id, "url": ntfy_url, "auth": describe_auth(auth_header)},
    )

    async def save_resume_point(since: str) -> None:
        # Best effort: a failed save only means a wider replay after a restart
        try:
            await database.update_since(mapping_id, since)
        except aiosqlite.Error as e:
            log.warning(
                "[ID: %(mapping_id)s] Could not save the Ntfy resume point: %(error)s",
                {"mapping_id": mapping_id, "error": e},
            )

    # Use a separate Discord session to not block Ntfy connections
    stream_timeout = httpx.Timeout(CONNECT_TIMEOUT, read=STREAM_READ_TIMEOUT)
    async with (
        httpx.AsyncClient(timeout=DISCORD_TIMEOUT) as discord_client,
        httpx.AsyncClient(
            headers=_ntfy_headers(auth_header),
            timeout=stream_timeout,
            follow_redirects=True,
        ) as ntfy_client,
        aclosing(
            subscribe(
                ntfy_client,
                ntfy_url,
                mapping_id,
                since=mapping.get("ntfy_since"),
                on_resume_point=save_resume_point,
            ),
        ) as events,
    ):
        async for event in events:
            if event.get("event") != "message":
                continue
            log.info(
                "[ID: %(mapping_id)s] Received message: %(title)s",
                {"mapping_id": mapping_id, "title": event.get("title")},
            )
            await post_to_discord(discord_client, mapping["discord_webhook"], event)
