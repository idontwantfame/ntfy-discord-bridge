#!/usr/bin/env python3
"""CLI for the ntfy-discord-bridge service."""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from rich.console import Console
from rich.table import Table

from app.core import database
from app.core.auth import build_auth_header, describe_auth
from app.core.logging import log
from app.core.validation import (
    bearer_token,
    http_url,
    non_empty,
    ntfy_topic,
    server_url,
)
from app.discord import mask_webhook

console = Console()


async def cli_add(args: argparse.Namespace) -> bool:
    """Handle the 'add' command.

    Args:
        args: The arguments.

    Returns:
        True if the mapping was added, False if it already exists.

    """
    auth_header = build_auth_header(args.basic, args.token)
    return await database.add_mapping(
        args.server,
        args.topic,
        args.webhook,
        auth_header,
    )


async def cli_remove(args: argparse.Namespace) -> bool:
    """Handle the 'remove' command.

    Args:
        args: The arguments.

    Returns:
        True if the mapping was removed, False if it does not exist.

    """
    return await database.remove_mapping(args.id)


async def cli_list(_args: argparse.Namespace) -> bool:
    """Handle the 'list' command.

    Returns:
        Always True.

    """
    mappings = await database.list_mappings()

    if not mappings:
        console.print("No active mappings.", style="yellow")
        return True

    table = Table(title="Active Ntfy -> Discord Mappings")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Ntfy Server")
    table.add_column("Ntfy Topic")
    table.add_column("Discord Webhook")
    table.add_column("Auth", style="dim")

    for m in mappings:
        table.add_row(
            str(m["id"]),
            m["ntfy_server"],
            m["ntfy_topic"],
            mask_webhook(m["discord_webhook"]),
            describe_auth(m["ntfy_auth_header"]),
        )

    console.print(table)
    return True


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        The parser with the add, remove and list commands.

    """
    parser = argparse.ArgumentParser(
        description="CLI for managing the Ntfy-Discord bridge",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        help="Available commands",
    )

    # 'add' command
    parser_add = subparsers.add_parser("add", help="Add a new mapping")
    parser_add.add_argument(
        "--server",
        required=True,
        type=server_url,
        help="Ntfy server URL (e.g. https://ntfy.sh)",
    )
    parser_add.add_argument(
        "--topic",
        required=True,
        type=ntfy_topic,
        help="Ntfy topic name",
    )
    parser_add.add_argument(
        "--webhook",
        required=True,
        type=http_url,
        help="Full Discord webhook URL",
    )

    auth_group = parser_add.add_mutually_exclusive_group()
    auth_group.add_argument(
        "--basic",
        nargs=2,
        type=non_empty,
        metavar=("USER", "PASS"),
        help="Authentication Basic (username/password)",
    )
    auth_group.add_argument(
        "--token",
        type=bearer_token,
        metavar="TOKEN",
        help="Authentication Bearer Token",
    )
    parser_add.set_defaults(func=cli_add)

    # 'remove' command
    parser_remove = subparsers.add_parser("remove", help="Remove a mapping")
    parser_remove.add_argument(
        "--id",
        required=True,
        type=int,
        help="ID of the mapping to remove (use 'list' to see IDs)",
    )
    parser_remove.set_defaults(func=cli_remove)

    # 'list' command
    parser_list = subparsers.add_parser("list", help="List all active mappings")
    parser_list.set_defaults(func=cli_list)

    return parser


async def _run(args: argparse.Namespace) -> bool:
    """Make sure the database exists, then run the selected command.

    Returns:
        Whether the command succeeded.

    """
    await database.init_db()
    return await args.func(args)


def main(argv: Sequence[str] | None = None) -> int:
    """Main function.

    Args:
        argv: Command-line arguments, defaulting to sys.argv.

    Returns:
        The process exit code.

    """
    args = _build_parser().parse_args(argv)
    try:
        success = asyncio.run(_run(args))
    except Exception as e:  # noqa: BLE001 # pylint: disable=broad-exception-caught
        log.error("CLI error: %s", e, exc_info=True)
        return 1
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
