"""group_msg is the fan-out waist: it decides who receives a group message
and self-heals the membership list. These tests pin the two independent
knobs (skip-actor vs respect-mute), the flood-control retry, and the
block-then-unregister path — none of which were covered before."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import repo
from unifestbestellbot.bot import notify
from unifestbestellbot.models import Registration, now_utc


@pytest.fixture
def s():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _bot():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


def _recipients(bot) -> set[int]:
    return {c.kwargs["chat_id"] for c in bot.send_message.await_args_list}


# --- mute translation ----------------------------------------------------


async def test_actionable_message_reaches_muted_member(s):
    """exclude_muted defaults to False: actionable lifecycle DMs (e.g. 'your
    ticket was closed') must reach even a member who set /quiet."""
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))
    repo.upsert_registration(s, Registration(chat_id=2, group_name="Finanz"))
    repo.set_mute(s, 2, until=now_utc() + timedelta(minutes=30))

    bot = _bot()
    await notify.group_msg(bot, s, "Finanz", "ticket closed")
    assert _recipients(bot) == {1, 2}


async def test_peer_message_skips_actor_and_muted(s):
    """Peer-activity notifications pass exclude_chat_id (skip the actor) and
    exclude_muted=True (respect /quiet) — two independent effects."""
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))  # actor
    repo.upsert_registration(s, Registration(chat_id=2, group_name="Finanz"))  # muted
    repo.upsert_registration(s, Registration(chat_id=3, group_name="Finanz"))  # plain
    repo.set_mute(s, 2, until=now_utc() + timedelta(minutes=30))

    bot = _bot()
    await notify.group_msg(
        bot, s, "Finanz", "colleague took a ticket",
        exclude_chat_id=1, exclude_muted=True,
    )
    assert _recipients(bot) == {3}


async def test_peer_message_respects_per_kind_optout(s):
    """A member who opted out of one peer-notification kind via /notify is
    dropped for that kind only, independently of /quiet."""
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))
    repo.upsert_registration(s, Registration(chat_id=2, group_name="Finanz"))
    repo.toggle_notify_mute(s, 2, "wip")  # member 2 mutes WIP notifications

    bot = _bot()
    await notify.group_msg(
        bot, s, "Finanz", "colleague took a ticket", exclude_muted=True, kind="wip"
    )
    assert _recipients(bot) == {1}

    # A different kind still reaches member 2.
    bot2 = _bot()
    await notify.group_msg(
        bot2, s, "Finanz", "colleague closed a ticket", exclude_muted=True, kind="closed"
    )
    assert _recipients(bot2) == {1, 2}


# --- flood control -------------------------------------------------------


async def test_retries_once_on_flood_control(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))
    bot = _bot()
    # First attempt asks us to back off (retry_after=0 → no real delay),
    # the retry succeeds.
    bot.send_message.side_effect = [
        TelegramRetryAfter(method=MagicMock(), message="flood", retry_after=0),
        None,
    ]
    await notify.group_msg(bot, s, "Finanz", "hi")
    assert bot.send_message.await_count == 2


# --- block-then-unregister ----------------------------------------------


async def test_blocked_member_is_unregistered(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))
    repo.upsert_registration(s, Registration(chat_id=2, group_name="Finanz"))
    bot = _bot()
    bot.send_message.side_effect = [
        TelegramForbiddenError(method=MagicMock(), message="blocked"),
        None,
    ]
    await notify.group_msg(bot, s, "Finanz", "hi")
    # Member 1 blocked the bot and was removed; member 2 is untouched.
    assert repo.registration_for(s, 1) is None
    assert repo.registration_for(s, 2) is not None


# --- channel_msg without a configured channel ----------------------------


async def test_channel_msg_logs_when_channel_unconfigured(monkeypatch, caplog):
    monkeypatch.setattr(
        notify, "get_settings", lambda: MagicMock(updates_channel_id=None)
    )
    bot = _bot()
    with caplog.at_level("INFO"):
        await notify.channel_msg(bot, "hello world")
    bot.send_message.assert_not_awaited()
    assert "hello world" in caplog.text


async def test_channel_msg_posts_when_channel_configured(monkeypatch):
    monkeypatch.setattr(
        notify, "get_settings", lambda: MagicMock(updates_channel_id=200)
    )
    bot = _bot()
    await notify.channel_msg(bot, "hello world")
    assert bot.send_message.await_args.kwargs["chat_id"] == 200


async def test_group_message_splits_oversized_text(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))
    bot = _bot()

    await notify.group_msg(bot, s, "Finanz", "line\n" * 5000)

    texts = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert len(texts) > 1
    assert all(len(text) <= 4096 for text in texts)
    assert "".join(texts) == "line\n" * 5000
