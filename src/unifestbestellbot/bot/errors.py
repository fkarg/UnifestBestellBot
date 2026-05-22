"""Forward uncaught handler exceptions to the developer chat. Logged
locally too; the DM is so an on-call dev sees the traceback on their
phone within seconds during a live event."""

import html
import logging
import traceback

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import ErrorEvent

from ..settings import get_settings

log = logging.getLogger(__name__)

# Telegram limits messages to 4096 chars; reserve some headroom for the
# <pre> tags and labels we wrap around the traceback.
_TRACEBACK_BUDGET = 3500
_UPDATE_BUDGET = 800


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + "\n... [truncated]"


async def on_error(event: ErrorEvent, bot: Bot) -> None:
    exc = event.exception
    if isinstance(exc, TelegramNetworkError):
        log.warning("telegram network error: %s", exc)
        return

    log.exception("unhandled exception in handler", exc_info=exc)

    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    update_repr = ""
    if event.update is not None:
        try:
            update_repr = event.update.model_dump_json(exclude_none=True, indent=2)
        except Exception:
            update_repr = repr(event.update)

    body = (
        f"<b>🔴 Exception:</b> {html.escape(repr(exc))}\n\n"
        f"<b>Traceback:</b>\n<pre>{html.escape(_truncate(tb, _TRACEBACK_BUDGET))}</pre>\n\n"
        f"<b>Update:</b>\n<pre>{html.escape(_truncate(update_repr, _UPDATE_BUDGET))}</pre>"
    )

    try:
        await bot.send_message(
            chat_id=get_settings().developer_chat_id,
            text=body,
            parse_mode="HTML",
        )
    except Exception:
        log.exception("failed to forward error to developer chat")
