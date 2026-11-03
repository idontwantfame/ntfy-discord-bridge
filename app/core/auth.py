"""Ntfy authentication header helpers."""

import base64


def build_auth_header(
    basic_creds: tuple[str, str] | None = None,
    token: str | None = None,
) -> str | None:
    """Build the authentication header for Ntfy.

    Args:
        basic_creds: The basic credentials (username, password).
        token: The token.

    Returns:
        The authentication header.

    """
    if basic_creds:
        user, password = basic_creds
        creds_str = f"{user}:{password}"
        encoded_creds = base64.b64encode(creds_str.encode()).decode()
        return f"Basic {encoded_creds}"
    if token:
        return f"Bearer {token}"
    return None


def describe_auth(auth_header: str | None) -> str:
    """Name the authentication scheme of a header without revealing credentials.

    Args:
        auth_header: The stored Ntfy authentication header.

    Returns:
        A display label that is safe to log.

    """
    if not auth_header:
        return "None"
    if auth_header.startswith("Basic "):
        return "Basic (User/Pass)"
    if auth_header.startswith("Bearer "):
        return "Bearer Token"
    return "Custom"
