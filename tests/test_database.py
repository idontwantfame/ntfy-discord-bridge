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
