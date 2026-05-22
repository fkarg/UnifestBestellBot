"""Lightweight fakes for aiogram Message / CallbackQuery / User.

Handlers in aiogram v3 are plain async functions. To exercise them in
unit tests we construct mock event objects that look enough like the
real thing for the methods our handlers call (`.answer`, `.edit_text`,
`.bot.send_message`, `.from_user`)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery, Message, User


def fake_user(
    user_id: int = 1,
    *,
    username: str | None = "alice",
    first_name: str | None = "Alice",
    last_name: str | None = None,
) -> Any:
    u = MagicMock(spec=User)
    u.id = user_id
    u.username = username
    u.first_name = first_name
    u.last_name = last_name
    return u


def fake_bot() -> Any:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


def fake_message(
    *,
    user_id: int = 1,
    text: str | None = None,
    username: str | None = "alice",
    first_name: str | None = "Alice",
    bot: Any = None,
) -> Any:
    msg = MagicMock(spec=Message)
    msg.from_user = fake_user(user_id, username=username, first_name=first_name)
    msg.text = text
    msg.caption = None
    msg.edit_date = None
    msg.chat = MagicMock(id=user_id)
    msg.answer = AsyncMock()
    msg.edit_text = AsyncMock()
    msg.bot = bot or fake_bot()
    return msg


def fake_callback(
    *,
    user_id: int = 1,
    data: str = "",
    username: str | None = "alice",
    first_name: str | None = "Alice",
    bot: Any = None,
) -> Any:
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.from_user = fake_user(user_id, username=username, first_name=first_name)
    cb.message = fake_message(user_id=user_id, username=username, first_name=first_name, bot=bot)
    cb.bot = cb.message.bot
    cb.answer = AsyncMock()
    return cb
