import sqlite3
from contextlib import closing

import pytest

from app.core import database

pytestmark = pytest.mark.usefixtures("fresh_db")


@pytest.fixture
async def fresh_db(db_path: str) -> str:
    await database.init_db()
    return db_path


async def test_add_list_and_remove_mapping():
    assert await database.add_mapping(
        "https://ntfy.sh",
        "alerts",
        "https://hook",
        "Bearer x",
    )

    mappings = await database.list_mappings()
    assert len(mappings) == 1
    assert mappings[0]["ntfy_topic"] == "alerts"
    assert mappings[0]["ntfy_auth_header"] == "Bearer x"

    assert await database.remove_mapping(mappings[0]["id"])
    assert await database.list_mappings() == []


async def test_add_duplicate_mapping_returns_false():
    assert await database.add_mapping("https://ntfy.sh", "alerts", "https://hook")
    assert not await database.add_mapping("https://ntfy.sh", "alerts", "https://hook")


async def test_remove_unknown_mapping_returns_false():
    assert not await database.remove_mapping(999)


async def test_init_db_is_idempotent():
    await database.add_mapping("https://ntfy.sh", "alerts", "https://hook")
    await database.init_db()
    assert len(await database.list_mappings()) == 1


async def test_update_since_saves_resume_point():
    await database.add_mapping("https://ntfy.sh", "alerts", "https://hook")
    mapping_id = (await database.list_mappings())[0]["id"]
    assert (await database.list_mappings())[0]["ntfy_since"] is None

    await database.update_since(mapping_id, "msg123")

    assert (await database.list_mappings())[0]["ntfy_since"] == "msg123"


async def test_init_db_migrates_databases_from_older_versions(tmp_path, monkeypatch):
    old_db = tmp_path / "old.db"
    with closing(sqlite3.connect(old_db)) as db, db:
        db.execute(
            "CREATE TABLE mappings (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "ntfy_server TEXT NOT NULL, ntfy_topic TEXT NOT NULL, "
            "discord_webhook TEXT NOT NULL, ntfy_auth_header TEXT, "
            "UNIQUE(ntfy_server, ntfy_topic, discord_webhook))",
        )
        db.execute(
            "INSERT INTO mappings (ntfy_server, ntfy_topic, discord_webhook) "
            "VALUES ('https://ntfy.sh', 'alerts', 'https://hook')",
        )
    monkeypatch.setattr(database, "DB_PATH", str(old_db))

    await database.init_db()
    await database.update_since(1, "msg123")

    [mapping] = await database.list_mappings()
    assert mapping["ntfy_topic"] == "alerts"
    assert mapping["ntfy_since"] == "msg123"
