"""Fallback for messages that no other router/handler claims.

Included LAST in the dispatcher so it never preempts a real flow.
FSM-state handlers (e.g. `category_unrecognized`) match before this
because they bind to a specific state; this catch-all only fires when
no state is active."""

import logging

from aiogram import Router
from aiogram.types import Message
from sqlmodel import Session

from .. import i18n, repo
from ..config import AppConfig
from . import keyboards

log = logging.getLogger(__name__)

router = Router(name="unknown")


@router.message()
async def cmd_unknown(msg: Message, db_session: Session, config: AppConfig) -> None:
    # Ignore channel posts / non-user messages — those never have from_user.
    if msg.from_user is None:
        return

    group = "Unknown"
    reg = repo.registration_for(db_session, msg.from_user.id)
    if reg is not None:
        group = reg.group_name

    text = msg.text or msg.caption or ""
    if msg.edit_date is not None:
        log.warning(
            "⚠️ received edited message %r from chat %s [%s]",
            text, msg.from_user.id, group,
        )
    else:
        log.warning(
            "⚠️ received unrecognized message %r from chat %s [%s]",
            text, msg.from_user.id, group,
        )

    await msg.answer(i18n.UNKNOWN_COMMAND, reply_markup=keyboards.for_user(reg, config))
