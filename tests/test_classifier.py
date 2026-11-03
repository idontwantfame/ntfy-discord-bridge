import pytest

from app.classifier import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_WARNING,
    EMOJI_ERROR,
    determine_notification_type,
)


@pytest.mark.parametrize(
    ("priority", "tags", "expected_color"),
    [
        (None, None, COLOR_INFO),
        (3, [], COLOR_INFO),
        (4, [], COLOR_WARNING),
        (5, [], COLOR_ERROR),
        ("max", [], COLOR_ERROR),
        ("urgent", [], COLOR_ERROR),
        ("high", [], COLOR_WARNING),
        ("min", [], COLOR_INFO),
        (5, ["warning"], COLOR_WARNING),
        (4, ["white_check_mark"], COLOR_SUCCESS),
        (1, ["FIRE"], COLOR_ERROR),
    ],
)
def test_tags_take_precedence_over_priority(priority, tags, expected_color):
    color, _ = determine_notification_type(priority, tags)
    assert color == expected_color


def test_color_and_emoji_match():
    assert determine_notification_type(5, None) == (COLOR_ERROR, EMOJI_ERROR)
