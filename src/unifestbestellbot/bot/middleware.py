"""Per-update middleware for database sessions and update logging."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import TelegramObject, Update
from sqlmodel import Session

from ..db import get_engine

log = logging.getLogger("aiogram.event")


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


def _describe_action(event: Update) -> str:
    """A short action label that differentiates updates the bare type can't:
    the command for a message (`/stats`), the callback-data namespace for an
    inline button (`wip`), otherwise the message content type (`photo`) or a
    plain `text`. Best-effort — never raises into the log call."""
    try:
        msg = event.message or event.edited_message
        if msg is not None:
            text = msg.text or msg.caption
            if text and text.startswith("/"):
                # "/close@BotName 5" -> "/close"
                return text.split(maxsplit=1)[0].split("@", 1)[0]
            if text is not None:
                return "text"
            return msg.content_type
        if event.callback_query is not None:
            # Callback data is namespaced "wip:123" -> "wip".
            return (event.callback_query.data or "").split(":", 1)[0] or "callback"
    except Exception:
        return "?"
    return "-"


class UpdateLoggingMiddleware(BaseMiddleware):
    """Log the Telegram update type and a short action label alongside
    aiogram's usual timing data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)

        start_time = asyncio.get_running_loop().time()
        handled = False
        try:
            response = await handler(event, data)
            handled = response is not UNHANDLED
            return response
        finally:
            try:
                event_type = event.event_type
            except Exception:
                # Let aiogram handle and report unknown update types normally.
                event_type = "unknown"
            duration = (asyncio.get_running_loop().time() - start_time) * 1000
            log.info(
                "Update id=%s type=%s action=%s is %s. Duration %d ms by bot id=%d",
                event.update_id,
                event_type,
                _describe_action(event),
                "handled" if handled else "not handled",
                duration,
                data["bot"].id,
            )
