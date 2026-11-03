"""Discord webhook integration module."""

import asyncio
import math
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.logging import log
from app.embed import build_discord_payload

# Discord can be slow to answer, and a timeout while waiting for the response
# leaves it unknown whether the message was posted, so allow plenty of time
DISCORD_TIMEOUT = 15.0

# Delivery retries, only for failures after which Discord certainly did not
# post the message, so that a retry can never post it twice
DISCORD_MAX_ATTEMPTS = 3
DISCORD_RETRY_DELAY = 2.0  # Seconds, multiplied by the attempt number
DISCORD_MAX_RETRY_AFTER = 60.0  # Cap on the wait Discord asks for, in seconds
RETRYABLE_STATUS_CODES = {
    httpx.codes.TOO_MANY_REQUESTS,
    httpx.codes.INTERNAL_SERVER_ERROR,
    httpx.codes.BAD_GATEWAY,
    httpx.codes.SERVICE_UNAVAILABLE,
}
# Errors raised before the request reached Discord
UNSENT_REQUEST_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def mask_webhook(url: str) -> str:
    """Hide the secret token of a Discord webhook URL for display.

    Args:
        url: The Discord webhook URL (.../webhooks/<id>/<token>).

    Returns:
        The URL with its token replaced by asterisks.

    """
    parts = urlsplit(url)
    webhook_path = parts.path.rstrip("/").rpartition("/")[0]
    return f"{parts.scheme}://{parts.netloc}{webhook_path}/***"


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Pick the wait before retrying, honoring Discord's rate limit hints.

    Returns:
        The delay in seconds.

    """
    try:
        retry_after = float(
            response.headers.get("Retry-After") or response.json()["retry_after"],
        )
    except (ValueError, KeyError, TypeError):
        return DISCORD_RETRY_DELAY * attempt
    if not math.isfinite(retry_after):
        return DISCORD_RETRY_DELAY * attempt
    return min(max(retry_after, 0.0), DISCORD_MAX_RETRY_AFTER)


async def post_to_discord(
    session: httpx.AsyncClient,
    webhook_url: str,
    ntfy_message: dict[str, Any],
) -> bool:
    """Send a formatted Ntfy message to a Discord webhook.

    Rate limits, server errors and failed connections are retried a few times.
    Other rejections (e.g. a deleted webhook) are logged and the message dropped,
    and so are lost responses: the message may already be posted, and retrying
    could post it twice.

    Args:
        session: The HTTP client session.
        webhook_url: The Discord webhook URL.
        ntfy_message: The Ntfy message dictionary.

    Returns:
        True if Discord accepted the message, False if it was dropped.

    """
    payload = build_discord_payload(ntfy_message)
    topic = ntfy_message.get("topic")

    for attempt in range(1, DISCORD_MAX_ATTEMPTS + 1):
        try:
            response = await session.post(webhook_url, json=payload)
        except UNSENT_REQUEST_ERRORS as e:
            log.warning(
                "Could not connect to Discord (attempt %(attempt)s): %(error)r",
                {"attempt": attempt, "error": e},
            )
            retry_delay = DISCORD_RETRY_DELAY * attempt
        except httpx.RequestError as e:
            log.error(
                (
                    "Lost Discord's response (topic: %(topic)s): %(error)r. "
                    "Not retrying, as the message may already be posted."
                ),
                {"topic": topic, "error": e},
            )
            return False
        else:
            if response.is_success:
                log.info(
                    "Successfully sent message to Discord (topic: %(topic)s)",
                    {"topic": topic},
                )
                return True
            if response.status_code not in RETRYABLE_STATUS_CODES:
                log.error(
                    "Discord rejected the message (%(status_code)s): %(text)s",
                    {"status_code": response.status_code, "text": response.text},
                )
                return False
            retry_delay = _retry_delay(response, attempt)
            log.warning(
                "Discord returned %(status_code)s (attempt %(attempt)s)",
                {"status_code": response.status_code, "attempt": attempt},
            )

        if attempt < DISCORD_MAX_ATTEMPTS:
            await asyncio.sleep(retry_delay)

    log.error(
        "Giving up sending to Discord after %(attempts)s attempts (topic: %(topic)s)",
        {"attempts": DISCORD_MAX_ATTEMPTS, "topic": topic},
    )
    return False
