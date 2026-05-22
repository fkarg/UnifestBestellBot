"""Small helpers shared across bot flows."""

from aiogram import Bot
from aiogram.types import CallbackQuery, Message, User

from ..models import Registration


def who(user: User | None) -> str:
    """Format a Telegram user for logs / channel messages."""
    if user is None:
        return "Unbekannt"
    parts = [p for p in (user.first_name, user.last_name) if p]
    name = " ".join(parts) or "Unbekannt"
    return f"{name} <@{user.username}>" if user.username else name


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
