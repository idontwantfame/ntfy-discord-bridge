import json

import aiosqlite
import httpx
import pytest

from app import listener, ntfy

NTFY_URL = "https://ntfy.example/alerts/json"
MAPPING = {
    "id": 7,
    "ntfy_server": "https://ntfy.example/",
    "ntfy_topic": "/alerts",
    "discord_webhook": "https://discord.com/api/webhooks/1/token",
    "ntfy_auth_header": "Bearer secret",
    "ntfy_since": "saved0",
}


class StopListeningError(Exception):
    """Raised by the fake transport to end the otherwise endless listener."""


@pytest.fixture
def servers(monkeypatch) -> dict[str, list[httpx.Request]]:
    """Fake Ntfy and Discord: one message, then the stream drops for good."""
    requests: dict[str, list[httpx.Request]] = {"ntfy": [], "discord": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "discord.com":
            requests["discord"].append(request)
            return httpx.Response(204)
        requests["ntfy"].append(request)
        if len(requests["ntfy"]) > 1:
            raise StopListeningError
        events = [
            {"event": "open", "time": 1},
            {"event": "message", "id": "a1", "title": "hi"},
        ]
        return httpx.Response(200, text="".join(json.dumps(e) + "\n" for e in events))

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    return requests


@pytest.fixture
def saved(monkeypatch) -> list[tuple[int, str]]:
    """Record resume points instead of writing them to the database."""
    calls: list[tuple[int, str]] = []

    async def fake_update_since(mapping_id: int, since: str) -> None:
        calls.append((mapping_id, since))

    monkeypatch.setattr(listener.database, "update_since", fake_update_since)
    return calls


@pytest.mark.usefixtures("sleeps")
async def test_listen_forwards_messages_and_saves_resume_point(servers, saved):
    with pytest.raises(StopListeningError):
        await listener.listen_to_ntfy(MAPPING)

    first, second = servers["ntfy"]
    assert str(first.url) == f"{NTFY_URL}?since=saved0"
    assert first.headers["Authorization"] == "Bearer secret"
    assert second.url.params["since"] == "a1"
    embed = json.loads(servers["discord"][0].content)["embeds"][0]
    assert embed["title"].endswith("hi")
    assert saved == [(7, "a1")]


async def test_listen_keeps_going_when_resume_point_cannot_be_saved(
    servers,
    sleeps,
    monkeypatch,
):
    async def failing_update_since(*_args: object) -> None:
        msg = "database is locked"
        raise aiosqlite.OperationalError(msg)

    monkeypatch.setattr(listener.database, "update_since", failing_update_since)

    with pytest.raises(StopListeningError):
        await listener.listen_to_ntfy(MAPPING)

    assert servers["ntfy"][1].url.params["since"] == "a1"
    assert sleeps == [ntfy.RETRY_INITIAL_DELAY]


def test_ntfy_headers_only_include_authorization_when_set():
    assert "Authorization" not in listener._ntfy_headers(None)
    assert listener._ntfy_headers("Basic x")["Authorization"] == "Basic x"
