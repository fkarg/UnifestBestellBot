"""Per-update middleware: opens a SQLModel Session and injects it into
handler/filter kwargs as `db_session`."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlmodel import Session

from ..db import get_engine


class SessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        with Session(get_engine()) as s:
            data["db_session"] = s
            return await handler(event, data)
