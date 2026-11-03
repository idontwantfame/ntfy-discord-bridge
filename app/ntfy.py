"""Ntfy integration module."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

import httpx

from app.core.auth import describe_auth
from app.core.logging import log
from app.discord import post_to_discord

# Ntfy sends a keepalive event every 45 seconds by default (and servers must stay
# below the Android app's hardcoded 77 second timeout), so a stream that stays
# silent for longer than this is considered dead and gets reconnected.
STREAM_READ_TIMEOUT = 90.0
CONNECT_TIMEOUT = 10.0

# Reconnect delays in seconds: doubled after each failure, reset by any event
RETRY_INITIAL_DELAY = 1.0
RETRY_MAX_DELAY = 300.0


async def _iter_events(
    response: httpx.Response,
    mapping_id: int,
) -> AsyncIterator[dict[str, Any]]:
    """Yield each event object from a Ntfy JSON stream.

    Yields:
        Each event (open, keepalive, message, ...); invalid lines are skipped.

    """
    async for line in response.aiter_lines():
        if not line.strip():
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            log.warning(
                "[ID: %(mapping_id)s] Invalid event in Ntfy stream: %(line)s",
                {"mapping_id": mapping_id, "line": line},
            )
            continue
        yield data


def _resume_point(event: dict[str, Any], since: str | None) -> str | None:
    """Pick the ``since`` value that a reconnect should resume from.

    Returns:
        The ID of the last message received or, before any message arrived,
        the server time at which the stream opened.

    """
    if event.get("event") == "message" and event.get("id"):
        return str(event["id"])
    if since is None and event.get("event") == "open" and event.get("time"):
        return str(event["time"])
    return since


def _delay_after_status_error(
    error: httpx.HTTPStatusError,
    mapping_id: int,
    ntfy_url: str,
    delay: float,
) -> float:
    """Log an HTTP error from Ntfy and pick the delay before reconnecting.

    Rate limits and server errors are transient and keep the current backoff.
    Other errors (bad credentials, unknown topic) will not fix themselves
    quickly, so they wait the maximum delay instead of hammering the server.

    Returns:
        The delay in seconds before the next connection attempt.

    """
    status_code = error.response.status_code
    is_transient = status_code == httpx.codes.TOO_MANY_REQUESTS or (
        httpx.codes.is_server_error(status_code)
    )
    details = {"mapping_id": mapping_id, "status_code": status_code, "url": ntfy_url}
    if is_transient:
        log.warning(
            "[ID: %(mapping_id)s] Ntfy error %(status_code)s for %(url)s. Retrying...",
            details,
        )
        return delay

    log.error(
        (
            "[ID: %(mapping_id)s] HTTP status error: %(status_code)s for %(url)s. "
            "Check credentials/topic. Retrying in %(delay)s seconds..."
        ),
        {**details, "delay": RETRY_MAX_DELAY},
    )
    return RETRY_MAX_DELAY


async def _subscribe(
    client: httpx.AsyncClient,
    ntfy_url: str,
    mapping_id: int,
) -> AsyncIterator[dict[str, Any]]:
    """Yield Ntfy events forever, reconnecting whenever the stream drops.

    Every reconnect passes Ntfy a ``since`` parameter (see `_resume_point`), so
    messages published while disconnected are delivered after reconnecting.

    Yields:
        Each event received from Ntfy.

    """
    since: str | None = None
    delay = RETRY_INITIAL_DELAY
    while True:
        params = {"since": since} if since else {}
        # The try must span the whole stream: read errors surface mid-iteration
        try:  # noqa: PLW0717
            async with (
                client.stream("GET", ntfy_url, params=params) as response,
                aclosing(_iter_events(response, mapping_id)) as events,
            ):
                # Check for 4xx/5xx errors (e.g., bad authorization)
                response.raise_for_status()
                log.info(
                    "[ID: %(mapping_id)s] Connected to Ntfy stream: %(ntfy_url)s",
                    {"mapping_id": mapping_id, "ntfy_url": ntfy_url},
                )
                async for event in events:
                    # Only a stream that delivers events counts as healthy
                    delay = RETRY_INITIAL_DELAY
                    since = _resume_point(event, since)
                    # Safe: every consumer closes this generator via aclosing()
                    yield event  # noqa: ASYNC119
            log.warning(
                "[ID: %(mapping_id)s] Ntfy closed the stream. Reconnecting...",
                {"mapping_id": mapping_id},
            )
        except httpx.HTTPStatusError as e:
            delay = _delay_after_status_error(e, mapping_id, ntfy_url, delay)
        except httpx.RequestError as e:
            log.warning(
                "[ID: %(mapping_id)s] Ntfy connection error: %(error)s. Retrying...",
                {"mapping_id": mapping_id, "error": str(e) or type(e).__name__},
            )
        await asyncio.sleep(delay)
        delay = min(delay * 2, RETRY_MAX_DELAY)


async def listen_to_ntfy(mapping: dict[str, Any]) -> None:
    """Forward messages from a Ntfy topic to a Discord webhook until cancelled.

    Args:
        mapping: The mapping dictionary from the database.

    """
    mapping_id = mapping["id"]
    server = mapping["ntfy_server"]
    topic = mapping["ntfy_topic"]
    auth_header = mapping.get("ntfy_auth_header")

    ntfy_url = f"{server.rstrip('/')}/{topic.lstrip('/')}/json"
    headers = {
        "User-Agent": "ntfy-discord-bridge/0.1.0",
        "Accept": "application/x-ndjson, application/json",
    }
    if auth_header:
        headers["Authorization"] = auth_header

    log.info(
        "[ID: %(mapping_id)s] Starting listening to Ntfy: %(url)s (auth: %(auth)s)",
        {"mapping_id": mapping_id, "url": ntfy_url, "auth": describe_auth(auth_header)},
    )

    # Use a separate Discord session to not block Ntfy connections
    stream_timeout = httpx.Timeout(CONNECT_TIMEOUT, read=STREAM_READ_TIMEOUT)
    async with (
        httpx.AsyncClient() as discord_client,
        httpx.AsyncClient(
            headers=headers,
            timeout=stream_timeout,
            follow_redirects=True,
        ) as ntfy_client,
        aclosing(_subscribe(ntfy_client, ntfy_url, mapping_id)) as events,
    ):
        async for event in events:
            if event.get("event") != "message":
                continue
            log.info(
                "[ID: %(mapping_id)s] Received message: %(title)s",
                {"mapping_id": mapping_id, "title": event.get("title")},
            )
            await post_to_discord(discord_client, mapping["discord_webhook"], event)
