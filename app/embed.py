"""Formatting of Ntfy messages as Discord embeds."""

from datetime import UTC, datetime
from typing import Any

from app.classifier import determine_notification_type

# Discord embed field length limits
TITLE_MAX_LENGTH = 256
DESCRIPTION_MAX_LENGTH = 4096


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
