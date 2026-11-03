"""Discord webhook integration module."""

import asyncio
import math
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.classifier import determine_notification_type
from app.core.logging import log

# Discord embed field length limits
TITLE_MAX_LENGTH = 256
DESCRIPTION_MAX_LENGTH = 4096

# Delivery retries for rate limits, server errors and connection errors
DISCORD_MAX_ATTEMPTS = 3
DISCORD_RETRY_DELAY = 2.0  # Seconds, multiplied by the attempt number
DISCORD_MAX_RETRY_AFTER = 60.0  # Cap on the wait Discord asks for, in seconds


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


def _truncate(text: str, limit: int) -> str:
    """Shorten text to a Discord field limit, marking the cut with an ellipsis.

    Returns:
        The text, at most `limit` characters long.

    """
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _format_timestamp(unix_time: object) -> str:
    """Convert Ntfy's Unix time in seconds to ISO 8601.

    Returns:
        The ISO 8601 timestamp, or the current time if `unix_time` is invalid.

    """
    if isinstance(unix_time, int | float):
        try:
            return datetime.fromtimestamp(unix_time, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            pass  # Out of range: fall back to the current time
    return datetime.now(UTC).isoformat()


def build_discord_payload(ntfy_message: dict[str, Any]) -> dict[str, Any]:
    """Format a Ntfy message as a Discord webhook payload.

    Args:
        ntfy_message: The Ntfy message dictionary.

    Returns:
        The JSON payload for the Discord webhook.

    """
    # Coerce to str: the stream is external input and must never crash the bridge
    title = str(ntfy_message.get("title") or "New Ntfy message")
    message = str(ntfy_message.get("message") or "*No content*")

    # Determine notification type based on priority and tags
    color, emoji = determine_notification_type(
        ntfy_message.get("priority"),
        ntfy_message.get("tags"),
    )

    # Add emoji to title if not already present
    if not title.startswith(emoji):
        title = f"{emoji} {title}"

    return {
        "embeds": [
            {
                "title": _truncate(title, TITLE_MAX_LENGTH),
                "description": _truncate(message, DESCRIPTION_MAX_LENGTH),
                "color": color,
                "timestamp": _format_timestamp(ntfy_message.get("time")),
                "footer": {
                    "text": f"Ntfy topic: {ntfy_message.get('topic')}",
                },
            },
        ],
        # Never ping @everyone, roles or users mentioned in a notification
        "allowed_mentions": {"parse": []},
    }


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


def _is_retryable(status_code: int) -> bool:
    """Check whether a failed Discord response is worth retrying.

    Returns:
        True for rate limits and server errors.

    """
    return status_code == httpx.codes.TOO_MANY_REQUESTS or (
        httpx.codes.is_server_error(status_code)
    )


async def post_to_discord(
    session: httpx.AsyncClient,
    webhook_url: str,
    ntfy_message: dict[str, Any],
) -> bool:
    """Send a formatted Ntfy message to a Discord webhook.

    Rate limits, server errors and connection errors are retried a few times.
    Other rejections (e.g. a deleted webhook) are logged and the message dropped.

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
        except httpx.RequestError as e:
            log.warning(
                "Connection error sending to Discord (attempt %(attempt)s): %(error)r",
                {"attempt": attempt, "error": e},
            )
            retry_delay = DISCORD_RETRY_DELAY * attempt
        else:
            if response.is_success:
                log.info(
                    "Successfully sent message to Discord (topic: %(topic)s)",
                    {"topic": topic},
                )
                return True
            if not _is_retryable(response.status_code):
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
