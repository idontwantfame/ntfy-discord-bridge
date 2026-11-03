"""Argparse argument types validating user-supplied mapping settings."""

import argparse
import re
from urllib.parse import urlsplit

# Ntfy topic names, optionally comma-separated to subscribe to several at once
NTFY_TOPIC_PATTERN = re.compile(r"[-_A-Za-z0-9]{1,64}(,[-_A-Za-z0-9]{1,64})*")


def http_url(value: str) -> str:
    """Validate an absolute http(s) URL.

    Args:
        value: The raw argument value.

    Returns:
        The URL stripped of surrounding whitespace.

    Raises:
        argparse.ArgumentTypeError: If the value is not an http(s) URL.

    """
    url = value.strip()
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        msg = f"expected an http(s) URL, got {value!r}"
        raise argparse.ArgumentTypeError(msg)
    # Credentials in the URL would be stored and logged in plain text
    if parts.username or parts.password:
        msg = "URL must not contain credentials; use --basic or --token instead"
        raise argparse.ArgumentTypeError(msg)
    return url


def server_url(value: str) -> str:
    """Validate a Ntfy server URL and drop any trailing slash.

    Args:
        value: The raw argument value.

    Returns:
        The normalized server URL, so equal servers compare equal.

    """
    return http_url(value).rstrip("/")


def ntfy_topic(value: str) -> str:
    """Validate a Ntfy topic name (or comma-separated names).

    Args:
        value: The raw argument value.

    Returns:
        The topic without surrounding whitespace or slashes.

    Raises:
        argparse.ArgumentTypeError: If the value is not a valid topic name.

    """
    topic = value.strip().strip("/")
    if not NTFY_TOPIC_PATTERN.fullmatch(topic):
        msg = f"invalid topic {value!r}: use 1-64 letters, digits, '-' or '_'"
        raise argparse.ArgumentTypeError(msg)
    return topic


def non_empty(value: str) -> str:
    """Validate a required credential, such as a Basic auth user or password.

    Args:
        value: The raw argument value.

    Returns:
        The value, unchanged.

    Raises:
        argparse.ArgumentTypeError: If the value is empty.

    """
    if not value:
        msg = "must not be empty"
        raise argparse.ArgumentTypeError(msg)
    return value


def bearer_token(value: str) -> str:
    """Validate a Bearer token, which goes into an HTTP header verbatim.

    Args:
        value: The raw argument value.

    Returns:
        The token, unchanged.

    Raises:
        argparse.ArgumentTypeError: If the token is empty or contains
            whitespace or control characters.

    """
    if not value or any(ch.isspace() or not ch.isprintable() for ch in value):
        msg = "token must be non-empty, without whitespace or control characters"
        raise argparse.ArgumentTypeError(msg)
    return value
