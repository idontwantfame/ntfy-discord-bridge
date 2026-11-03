"""Logging configuration for the ntfy-discord-bridge service."""

import logging
import os

from rich.logging import RichHandler

# Configure the root logger to use RichHandler for readable formatting
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, tracebacks_suppress=[])],
)

# httpx logs every request URL at INFO level, which would leak the secret
# token embedded in each Discord webhook URL
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Application logger
log = logging.getLogger("rich")
