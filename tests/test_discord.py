import httpx

from app.classifier import EMOJI_INFO
from app.discord import (
    DISCORD_MAX_ATTEMPTS,
    build_discord_payload,
    post_to_discord,
)

WEBHOOK_URL = "https://discord.com/api/webhooks/123/token"
MESSAGE = {"title": "Backup", "message": "done", "topic": "alerts"}


def test_payload_uses_ntfy_time_topic_and_emoji_title():
    embed = build_discord_payload({**MESSAGE, "time": 1_700_000_000})["embeds"][0]
    assert embed["timestamp"] == "2023-11-14T22:13:20+00:00"
    assert embed["footer"]["text"] == "Ntfy topic: alerts"
    assert embed["title"] == f"{EMOJI_INFO} Backup"


def test_payload_truncates_fields_to_discord_limits():
    payload = build_discord_payload({"title": "t" * 300, "message": "m" * 5000})
    embed = payload["embeds"][0]
    assert len(embed["title"]) == 256
    assert len(embed["description"]) == 4096
    assert embed["description"].endswith("…")


def test_payload_falls_back_when_title_or_message_is_empty():
    embed = build_discord_payload({"title": "", "message": ""})["embeds"][0]
    assert embed["title"].endswith("New Ntfy message")
    assert embed["description"] == "*No content*"


def test_payload_ignores_malformed_time():
    embed = build_discord_payload({"time": "soon"})["embeds"][0]
    assert embed["timestamp"]


def test_payload_tolerates_malformed_fields():
    message = {"title": 5, "message": ["x"], "tags": 7, "priority": {}, "time": 1e20}
    embed = build_discord_payload(message)["embeds"][0]
    assert embed["title"] == f"{EMOJI_INFO} 5"
    assert embed["description"] == "['x']"
    assert embed["timestamp"]


def test_payload_never_pings_mentions():
    payload = build_discord_payload({"message": "@everyone"})
    assert payload["allowed_mentions"] == {"parse": []}


async def test_post_succeeds_on_first_try(replay, sleeps):
    client, requests = replay(httpx.Response(204))
    async with client:
        assert await post_to_discord(client, WEBHOOK_URL, MESSAGE)
    assert len(requests) == 1
    assert sleeps == []


async def test_post_waits_for_retry_after_header_on_rate_limit(replay, sleeps):
    client, requests = replay(
        httpx.Response(429, headers={"Retry-After": "0.5"}),
        httpx.Response(204),
    )
    async with client:
        assert await post_to_discord(client, WEBHOOK_URL, MESSAGE)
    assert len(requests) == 2
    assert sleeps == [0.5]


async def test_post_falls_back_to_retry_after_in_body(replay, sleeps):
    client, _ = replay(
        httpx.Response(429, json={"retry_after": 1.25}),
        httpx.Response(204),
    )
    async with client:
        assert await post_to_discord(client, WEBHOOK_URL, MESSAGE)
    assert sleeps == [1.25]


async def test_post_ignores_non_finite_retry_after(replay, sleeps):
    client, _ = replay(
        httpx.Response(429, headers={"Retry-After": "nan"}),
        httpx.Response(204),
    )
    async with client:
        assert await post_to_discord(client, WEBHOOK_URL, MESSAGE)
    assert sleeps == [2.0]


async def test_post_retries_server_errors(replay, sleeps):
    client, requests = replay(httpx.Response(503), httpx.Response(204))
    async with client:
        assert await post_to_discord(client, WEBHOOK_URL, MESSAGE)
    assert len(requests) == 2
    assert len(sleeps) == 1


async def test_post_drops_message_rejected_by_discord(replay, sleeps):
    client, requests = replay(httpx.Response(400, json={"message": "Invalid"}))
    async with client:
        assert not await post_to_discord(client, WEBHOOK_URL, MESSAGE)
    assert len(requests) == 1
    assert sleeps == []


async def test_post_gives_up_after_repeated_connection_errors(replay, sleeps):
    errors = [httpx.ConnectError("down") for _ in range(DISCORD_MAX_ATTEMPTS)]
    client, requests = replay(*errors)
    async with client:
        assert not await post_to_discord(client, WEBHOOK_URL, MESSAGE)
    assert len(requests) == DISCORD_MAX_ATTEMPTS
    assert len(sleeps) == DISCORD_MAX_ATTEMPTS - 1
