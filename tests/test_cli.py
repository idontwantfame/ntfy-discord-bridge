import argparse
import asyncio

import pytest
from rich.console import Console

import cli
from app.core import database
from app.core.auth import build_auth_header, describe_auth
from app.core.validation import (
    bearer_token,
    http_url,
    non_empty,
    ntfy_topic,
    server_url,
)
from app.discord import mask_webhook

WEBHOOK = "https://discord.com/api/webhooks/123/token"


def test_build_auth_header():
    assert build_auth_header(("user", "pass")) == "Basic dXNlcjpwYXNz"
    assert build_auth_header(token="tok") == "Bearer tok"
    assert build_auth_header() is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "None"),
        ("Basic dXNlcjpwYXNz", "Basic (User/Pass)"),
        ("Bearer tok", "Bearer Token"),
        ("Digest abc", "Custom"),
    ],
)
def test_describe_auth_never_reveals_credentials(header, expected):
    assert describe_auth(header) == expected


def test_server_url_is_normalized():
    assert server_url(" https://ntfy.sh/ ") == "https://ntfy.sh"


@pytest.mark.parametrize(
    "value",
    ["ntfy.sh", "ftp://ntfy.sh", "https://", "", "https://user:pass@ntfy.sh"],
)
def test_invalid_urls_are_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        http_url(value)


@pytest.mark.parametrize("value", ["", "has space", "line\nbreak", "tab\tbed"])
def test_invalid_tokens_are_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        bearer_token(value)


def test_credentials_must_not_be_empty():
    assert bearer_token("tk_abc") == "tk_abc"
    assert non_empty("pass word") == "pass word"
    with pytest.raises(argparse.ArgumentTypeError):
        non_empty("")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("/alerts", "alerts"), ("a,b-c_1", "a,b-c_1")],
)
def test_valid_topics(value, expected):
    assert ntfy_topic(value) == expected


@pytest.mark.parametrize("value", ["", "has space", "a/b", "x" * 65])
def test_invalid_topics_are_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        ntfy_topic(value)


@pytest.mark.parametrize(
    "url",
    [WEBHOOK, WEBHOOK + "/", WEBHOOK + "?thread_id=5"],
)
def test_mask_webhook_hides_token(url):
    assert mask_webhook(url) == "https://discord.com/api/webhooks/123/***"


@pytest.mark.usefixtures("db_path")
def test_list_works_before_the_service_has_ever_run():
    assert cli.main(["list"]) == 0


@pytest.mark.usefixtures("db_path")
def test_add_list_remove_round_trip(capsys, monkeypatch):
    # A wide console keeps Rich from wrapping table cells
    monkeypatch.setattr(cli, "console", Console(width=200))
    add = [
        "add",
        "--server",
        "https://ntfy.sh/",
        "--topic",
        "alerts",
        "--webhook",
        WEBHOOK,
    ]
    assert cli.main([*add, "--token", "tok"]) == 0
    assert cli.main(add) == 1  # duplicate after server URL normalization

    assert cli.main(["list"]) == 0
    output = capsys.readouterr().out
    assert "webhooks/123/***" in output
    assert "token" not in output.replace("Bearer Token", "")

    mapping_id = asyncio.run(database.list_mappings())[0]["id"]
    assert cli.main(["remove", "--id", str(mapping_id)]) == 0
    assert cli.main(["remove", "--id", str(mapping_id)]) == 1


def test_add_rejects_invalid_webhook():
    with pytest.raises(SystemExit):
        cli.main(
            ["add", "--server", "https://ntfy.sh", "--topic", "a", "--webhook", "nope"],
        )
