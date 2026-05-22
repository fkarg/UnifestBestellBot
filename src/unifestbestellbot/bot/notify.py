"""Fan-out helpers for the updates channel, the developer chat, and
group-membership broadcasts."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlmodel import Session

from .. import repo
from ..settings import get_settings

log = logging.getLogger(__name__)


async def channel_msg(bot: Bot, text: str) -> None:
    """Best-effort log to the updates channel. Honours Telegram flood control."""
    chat_id = get_settings().updates_channel_id
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except TelegramRetryAfter as e:
        log.warning("flood control on channel, dropping message after %ss", e.retry_after)
    except Exception:
        log.exception("channel_msg failed")


async def dev_msg(bot: Bot, text: str) -> None:
    chat_id = get_settings().developer_chat_id
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        log.exception("dev_msg failed")


async def group_msg(
    bot: Bot,
    s: Session,
    group_name: str,
    text: str,
    *,
    exclude_chat_id: int | None = None,
    reply_markup=None,
) -> None:
    """Send `text` to all members of `group_name` except `exclude_chat_id`.
    Drops registrations whose chat blocked the bot."""
    members = repo.group_members(s, group_name)
    for chat_id in members:
        if chat_id == exclude_chat_id:
            continue
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        except TelegramForbiddenError:
            log.warning(
                "%d blocked the bot; unregistering from [%s]", chat_id, group_name
            )
            repo.unregister(s, chat_id)
        except Exception:
            log.exception("group_msg to %d failed", chat_id)
