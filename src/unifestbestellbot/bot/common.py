"""Small helpers shared across bot flows."""

from aiogram.types import CallbackQuery, Message, User

from ..models import Registration


def who(user: User | None) -> str:
    """Format a Telegram user for logs / channel messages."""
    if user is None:
        return "Unbekannt"
    parts = [p for p in (user.first_name, user.last_name) if p]
    name = " ".join(parts) or "Unbekannt"
    return f"{name} <@{user.username}>" if user.username else name


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
        if event.message is not None:
            await event.message.answer(text, **kwargs)
        await event.answer()
    else:
        await event.answer(text, **kwargs)
