import json
from contextlib import aclosing

import httpx
import pytest

from app import ntfy

NTFY_URL = "https://ntfy.example/alerts/json"


def ndjson(*events: dict) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


def stream(*events: dict) -> httpx.Response:
    return httpx.Response(200, text=ndjson(*events))


async def take(
    client: httpx.AsyncClient,
    count: int,
    **subscribe_kwargs: object,
) -> list[dict]:
    """Collect the first `count` message events from a subscription."""
    messages: list[dict] = []
    subscription = ntfy.subscribe(client, NTFY_URL, 1, **subscribe_kwargs)
    async with aclosing(subscription) as events:
        while len(messages) < count:
            event = await anext(events)
            if event["event"] == "message":
                messages.append(event)
    return messages


async def test_subscribe_skips_invalid_lines(replay, sleeps):
    response = httpx.Response(
        200,
        text='{"event": "open"}\nnot json\n[1, 2]\n\n'
        + ndjson({"event": "keepalive"}, {"event": "message", "id": "a1"}),
    )
    client, _ = replay(response)
    async with client:
        messages = await take(client, 1)
    assert [m["id"] for m in messages] == ["a1"]
    assert sleeps == []


@pytest.mark.usefixtures("sleeps")
async def test_subscribe_starts_from_saved_resume_point(replay):
    client, requests = replay(stream({"event": "message", "id": "b2"}))
    async with client:
        await take(client, 1, since="a1")
    assert requests[0].url.params["since"] == "a1"


@pytest.mark.usefixtures("sleeps")
async def test_subscribe_reports_resume_points_once_events_are_handled(replay):
    saved: list[str] = []

    async def save(since: str) -> None:
        saved.append(since)

    client, _ = replay(
        stream(
            {"event": "open", "time": 5},
            {"event": "keepalive", "time": 6},
            {"event": "message", "id": "a1"},
            {"event": "message", "id": "b2"},
        ),
    )
    async with client:
        await take(client, 2, on_resume_point=save)
    # b2 was taken but its consumer never asked for more, so it is not saved
    assert saved == ["5", "a1"]


@pytest.mark.usefixtures("sleeps")
async def test_subscribe_resumes_from_open_time_before_any_message(replay):
    client, requests = replay(
        stream({"event": "open", "time": 1_700_000_000}),
        stream({"event": "message", "id": "b2"}),
    )
    async with client:
        await take(client, 1)
    assert requests[1].url.params["since"] == "1700000000"


async def test_subscribe_keeps_backing_off_when_stream_closes_without_events(
    replay,
    sleeps,
):
    client, _ = replay(stream(), stream(), stream({"event": "message", "id": "a1"}))
    async with client:
        await take(client, 1)
    assert sleeps == [1.0, 2.0]


async def test_subscribe_resumes_after_last_message_on_reconnect(replay, sleeps):
    client, requests = replay(
        stream({"event": "message", "id": "a1"}),
        stream({"event": "message", "id": "b2"}),
    )
    async with client:
        messages = await take(client, 2)
    assert [m["id"] for m in messages] == ["a1", "b2"]
    assert "since" not in requests[0].url.params
    assert requests[1].url.params["since"] == "a1"
    assert sleeps == [ntfy.RETRY_INITIAL_DELAY]


async def test_subscribe_backs_off_exponentially_on_server_errors(replay, sleeps):
    client, _ = replay(
        httpx.Response(503),
        httpx.ConnectError("refused"),
        httpx.Response(429),
        stream({"event": "message", "id": "a1"}),
    )
    async with client:
        await take(client, 1)
    assert sleeps == [1.0, 2.0, 4.0]


async def test_subscribe_resets_backoff_once_events_arrive(replay, sleeps):
    client, _ = replay(
        httpx.Response(503),
        stream({"event": "open"}),
        httpx.Response(503),
        stream({"event": "message", "id": "a1"}),
    )
    async with client:
        await take(client, 1)
    assert sleeps == [1.0, 1.0, 2.0]


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_subscribe_retries_client_errors_at_max_delay(replay, sleeps, status):
    client, _ = replay(httpx.Response(status), stream({"event": "message", "id": "a"}))
    async with client:
        await take(client, 1)
    assert sleeps == [ntfy.RETRY_MAX_DELAY]
