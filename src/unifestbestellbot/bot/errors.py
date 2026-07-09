"""Forward uncaught handler exceptions to the developer chat. Logged
locally too; the DM is so an on-call dev sees the traceback on their
phone within seconds during a live event."""

import logging
import math
import traceback

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import ErrorEvent

from ..settings import get_settings

log = logging.getLogger(__name__)

# Telegram limits messages to 4096 chars; reserve some headroom for the
# <pre> tags and labels we wrap around the traceback.
TELEGRAM_MESSAGE_LIMIT = 4096
_ERROR_CHUNK_SIZE = 3900
_TRACEBACK_BUDGET = 2400
_TRUNCATED = "\n... [truncated]"


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + _TRUNCATED


def _split_message(text: str, *, chunk_size: int = _ERROR_CHUNK_SIZE) -> list[str]:
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        return [text]

    total = math.ceil(len(text) / chunk_size)
    chunks = []
    for idx in range(total):
        header = f"[{idx + 1}/{total}]\n"
        start = idx * chunk_size
        chunks.append(header + text[start : start + chunk_size])
    return chunks


def format_crash_report(component: str, exc: BaseException) -> str:
    """Plain-text crash report for a long-running task that fell over and is
    being restarted by the supervisor. Sent to the developer chat verbatim
    (no parse_mode), so no HTML escaping is needed."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return (
        f"🔴 {component} crashed and is being restarted.\n\n"
        f"{_truncate(tb, _TRACEBACK_BUDGET)}"
    )


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

    body = f"🔴 Exception: {repr(exc)}\n\nTraceback:\n{tb}\n\nUpdate:\n{update_repr}"

    try:
        chat_id = get_settings().developer_chat_id
        for chunk in _split_message(body):
            await bot.send_message(chat_id=chat_id, text=chunk)
    except Exception:
        log.exception("failed to forward error to developer chat")
