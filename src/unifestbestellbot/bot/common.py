"""Small helpers shared across bot flows."""

import re

from aiogram import Bot
from aiogram.types import CallbackQuery, Message, User

from ..models import Registration

TELEGRAM_MESSAGE_LIMIT = 4096


def split_message(text: str, *, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split text into Telegram-sized chunks, preferring line boundaries."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    pos = 0
    in_fence = False
    while pos < len(text):
        prefix = "```\n" if in_fence else ""
        # A continued fenced block needs room for its reopening and closing
        # markers, so every individual Telegram message stays valid Markdown.
        content_limit = limit - len(prefix) - (4 if in_fence else 0)
        end = min(pos + content_limit, len(text))
        if end < len(text):
            segment = text[pos:end]
            newline = segment.rfind("\n") + 1
            sentence = max(
                (m.end() for m in re.finditer(r"[.!?][\"')\]]?\s+", segment)),
                default=0,
            )
            whitespace = max(
                (index + 1 for index, char in enumerate(segment) if char.isspace()),
                default=0,
            )
            end = pos + (newline or sentence or whitespace or len(segment))

        raw_chunk = text[pos:end]
        closes_fence = raw_chunk.count("```") % 2 == 1
        next_in_fence = in_fence != closes_fence
        suffix = "\n```" if next_in_fence else ""
        chunks.append(prefix + raw_chunk + suffix)
        in_fence = next_in_fence
        pos = end
    return chunks


def who(user: User | None) -> str:
    """Format a Telegram user for logs / channel messages."""
    if user is None:
        return "Unbekannt"
    parts = [p for p in (user.first_name, user.last_name) if p]
    name = " ".join(parts) or "Unbekannt"
    return f"{name} <@{user.username}>" if user.username else name


def display_for(reg: Registration | None, user: User | None) -> str:
    """The name to show for `user`'s actions: their self-chosen /name override
    if set, otherwise the Telegram-derived name."""
    if reg is not None and reg.display_override:
        return reg.display_override
    return who(user)


def actor(event: Message | CallbackQuery) -> User:
    """Telegram always populates from_user on user-initiated updates.
    The assert narrows the type for callers and documents the invariant."""
    assert event.from_user is not None, "event must have from_user"
    return event.from_user


def bot_of(event: Message | CallbackQuery) -> Bot:
    assert event.bot is not None, "event must have bot attached"
    return event.bot


def registration_from(user: User, group_name: str) -> Registration:
    return Registration(
        chat_id=user.id,
        group_name=group_name,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )


async def answer(event: Message | CallbackQuery, text: str, **kwargs) -> None:
    """Answer either a Message or a CallbackQuery's underlying message."""
    if isinstance(event, CallbackQuery):
        if isinstance(event.message, Message):
            await event.message.answer(text, **kwargs)
        await event.answer()
    else:
        await event.answer(text, **kwargs)


async def answer_chunks(msg: Message, text: str, **kwargs) -> None:
    """Reply with Telegram-sized chunks; attach reply markup only once."""
    for index, chunk in enumerate(split_message(text)):
        if index:
            kwargs = {key: value for key, value in kwargs.items() if key != "reply_markup"}
        await msg.answer(chunk, **kwargs)
