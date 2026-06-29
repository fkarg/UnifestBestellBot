"""Fan-out helpers for the updates channel, the developer chat, and
group-membership broadcasts."""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlmodel import Session

from .. import repo
from ..settings import get_settings

log = logging.getLogger(__name__)

# Cap how long a single flood-control retry will wait, so a pathological
# `retry_after` can't stall the whole fan-out loop for minutes.
_MAX_RETRY_AFTER = 30


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


async def _send_one(bot: Bot, chat_id: int, text: str, reply_markup) -> None:
    """Send a single message, retrying once if Telegram asks us to back off
    for flood control. A second RetryAfter (or any other error) propagates
    to the caller's per-recipient handling."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except TelegramRetryAfter as e:
        wait = min(e.retry_after, _MAX_RETRY_AFTER)
        log.warning("flood control sending to %d; retrying after %ss", chat_id, wait)
        await asyncio.sleep(wait)
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


async def group_msg(
    bot: Bot,
    s: Session,
    group_name: str,
    text: str,
    *,
    exclude_chat_id: int | None = None,
    exclude_muted: bool = False,
    reply_markup=None,
) -> None:
    """Send `text` to all members of `group_name`.

    Two independent knobs, neither implied by the other:
    - `exclude_chat_id` skips one member (typically the actor whose own
      action triggered the message).
    - `exclude_muted` drops members with an active /quiet mute.

    Peer-activity notifications (a colleague did something) pass both:
    skip the actor and respect mutes. Actionable lifecycle DMs (your
    ticket was opened/closed, a /message forward) pass neither, so they
    always reach every member regardless of mute state."""
    members = repo.group_members(s, group_name, exclude_muted=exclude_muted)
    for chat_id in members:
        if chat_id == exclude_chat_id:
            continue
        try:
            await _send_one(bot, chat_id, text, reply_markup)
        except TelegramForbiddenError:
            log.warning(
                "%d blocked the bot; unregistering from [%s]", chat_id, group_name
            )
            repo.unregister(s, chat_id)
        except Exception:
            log.exception("group_msg to %d failed", chat_id)
