"""Ntfy JSON stream client that keeps a topic subscription alive."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from typing import Any

import httpx

from app.core.logging import log

# Ntfy sends a keepalive event every 45 seconds by default (and servers must stay
# below the Android app's hardcoded 77 second timeout), so a stream that stays
# silent for longer than this is considered dead and gets reconnected.
STREAM_READ_TIMEOUT = 90.0
CONNECT_TIMEOUT = 10.0

# Reconnect delays in seconds: doubled after each failure, reset by any event
RETRY_INITIAL_DELAY = 1.0
RETRY_MAX_DELAY = 300.0

ResumePointCallback = Callable[[str], Awaitable[None]]


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


async def _advance(
    event: dict[str, Any],
    since: str | None,
    on_resume_point: ResumePointCallback | None,
) -> str | None:
    """Move the resume point past a handled event, reporting any change.

    Returns:
        The new resume point.

    """
    resume_point = _resume_point(event, since)
    if resume_point is not None and resume_point != since and on_resume_point:
        await on_resume_point(resume_point)
    return resume_point


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


async def subscribe(
    client: httpx.AsyncClient,
    ntfy_url: str,
    mapping_id: int,
    since: str | None = None,
    on_resume_point: ResumePointCallback | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield Ntfy events forever, reconnecting whenever the stream drops.

    Every reconnect passes Ntfy a ``since`` parameter (see `_resume_point`), so
    messages published while disconnected are delivered after reconnecting.
    The resume point only moves past an event once the consumer asks for the
    next one, so an event being handled when the process dies is replayed.

    Args:
        client: The Ntfy HTTP client.
        ntfy_url: The Ntfy JSON stream URL.
        mapping_id: The mapping ID.
        since: Where to start, e.g. a resume point saved before a restart.
        on_resume_point: Called with every new resume point, e.g. to save it.

    Yields:
        Each event received from Ntfy.

    """
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
                    # Safe: every consumer closes this generator via aclosing()
                    yield event  # noqa: ASYNC119
                    since = await _advance(event, since, on_resume_point)
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
