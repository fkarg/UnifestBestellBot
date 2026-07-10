"""_describe_action turns an Update into the short action label the update
log uses to differentiate actions that all share type=message."""

from types import SimpleNamespace

import pytest
from unifestbestellbot.bot.middleware import _describe_action


def _update(*, message=None, edited_message=None, callback_query=None):
    return SimpleNamespace(
        message=message,
        edited_message=edited_message,
        callback_query=callback_query,
    )


def _msg(*, text=None, caption=None, content_type="text"):
    return SimpleNamespace(text=text, caption=caption, content_type=content_type)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("/stats", "/stats"),
        ("/close 5", "/close"),
        ("/close@UnifestBot 5", "/close"),
        ("Wechselgeld", "text"),
    ],
)
def test_message_commands_and_text(text, expected):
    assert _describe_action(_update(message=_msg(text=text))) == expected


def test_non_text_message_uses_content_type():
    assert _describe_action(_update(message=_msg(content_type="photo"))) == "photo"


def test_callback_uses_namespace():
    cb = SimpleNamespace(data="wip:123")
    assert _describe_action(_update(callback_query=cb)) == "wip"


def test_callback_without_colon():
    cb = SimpleNamespace(data="cancel")
    assert _describe_action(_update(callback_query=cb)) == "cancel"


def test_edited_message_command():
    assert _describe_action(_update(edited_message=_msg(text="/help"))) == "/help"


def test_unknown_falls_back():
    assert _describe_action(_update()) == "-"
