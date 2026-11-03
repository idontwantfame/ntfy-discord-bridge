"""Notification classifier: picks a Discord color and emoji for a Ntfy message."""

# Discord embed colors (decimal RGB values)
COLOR_INFO = 3447003  # Blue
COLOR_SUCCESS = 3066993  # Green
COLOR_WARNING = 16776960  # Yellow
COLOR_ERROR = 15158332  # Red

# Emoji mappings
EMOJI_INFO = "ℹ️"  # noqa: RUF001
EMOJI_SUCCESS = "✅"
EMOJI_WARNING = "⚠️"
EMOJI_ERROR = "❌"

# Ntfy priorities, numeric or named (https://docs.ntfy.sh/publish/#message-priority)
URGENT_PRIORITIES = {"5", "max", "urgent"}
HIGH_PRIORITIES = {"4", "high"}

# Tag sets for notification type detection
ERROR_TAGS = {"error", "skull", "rotating_light", "fire", "boom"}
WARNING_TAGS = {"warning", "exclamation", "construction"}
SUCCESS_TAGS = {
    "white_check_mark",
    "heavy_check_mark",
    "partying_face",
    "tada",
    "check",
}


def _check_tags_for_type(tags_lower: list[str]) -> tuple[int, str] | None:
    """Check if tags indicate a specific notification type.

    Args:
        tags_lower: Lowercase list of tags.

    Returns:
        Tuple of (color, emoji) if tags match a type, None otherwise.

    """
    if any(tag in tags_lower for tag in ERROR_TAGS):
        return (COLOR_ERROR, EMOJI_ERROR)
    if any(tag in tags_lower for tag in WARNING_TAGS):
        return (COLOR_WARNING, EMOJI_WARNING)
    if any(tag in tags_lower for tag in SUCCESS_TAGS):
        return (COLOR_SUCCESS, EMOJI_SUCCESS)
    return None


def _priority_to_type(priority: int | str | None) -> tuple[int, str]:
    """Convert priority to notification type.

    Args:
        priority: The notification priority (1-5 or a name like "urgent").

    Returns:
        Tuple of (color, emoji).

    """
    priority_name = str(priority).lower()
    if priority_name in URGENT_PRIORITIES:
        return (COLOR_ERROR, EMOJI_ERROR)
    if priority_name in HIGH_PRIORITIES:
        return (COLOR_WARNING, EMOJI_WARNING)
    return (COLOR_INFO, EMOJI_INFO)


def determine_notification_type(
    priority: int | str | None,
    tags: list[str] | None,
) -> tuple[int, str]:
    """Determine notification type based on priority and tags.

    Args:
        priority: The notification priority (1-5 or string like "urgent", "high").
        tags: List of tags associated with the notification.

    Returns:
        Tuple of (color, emoji) where:
        - color: Discord embed color (decimal RGB)
        - emoji: Emoji string for the notification type

    """
    tags_lower = [str(tag).lower() for tag in tags] if isinstance(tags, list) else []

    # Check tags first (they can override priority)
    tag_result = _check_tags_for_type(tags_lower)
    if tag_result is not None:
        return tag_result

    # Determine by priority if no matching tags
    return _priority_to_type(priority)
