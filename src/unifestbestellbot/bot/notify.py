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
    """Send `text` to all members of `group_name`.

    When `exclude_chat_id` is set, the message is treated as a
    *peer-activity* notification (something one of the user's
    colleagues just did): the actor themselves is skipped, and
    members who set a /quiet mute that is still in effect are also
    skipped. When `exclude_chat_id` is None the message is broadcast
    to every member of the group regardless of mute state (used for
    actionable lifecycle notifications like the initial OPEN to an
    orga group or a /message forward to the requesting stand)."""
    peer_mode = exclude_chat_id is not None
    members = repo.group_members(s, group_name, exclude_muted=peer_mode)
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
