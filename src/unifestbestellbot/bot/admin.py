"""Developer-only commands. Defensive against accidental fat-fingering."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlmodel import Session

from .. import i18n, repo
from ..config import AppConfig
from ..events import EventBus
from ..models import TicketStatus
from . import notify
from .common import actor, bot_of, display_for
from .filters import IsDeveloper

router = Router(name="admin")


# Group name attributed to the developer when closing tickets via /closeall.
# Shows up in channel logs and peer DMs so recipients can tell these closes
# apart from regular orga-driven ones.
_DEV_ACTOR_GROUP = "Entwickler"


@router.message(Command("closeall"), IsDeveloper())
async def cmd_closeall(
    msg: Message, db_session: Session, config: AppConfig, events: EventBus
) -> None:
    """Close every open and WIP ticket. Used a few times per event: once
    when wrapping up test traffic before opening, and at the end of each
    operational day to clear residual tickets after venue close.

    Fans out the same channel + group-DM notifications the regular /close
    flow would, so requesting stands and tasked orga groups know their
    tickets were closed (rather than disappearing silently)."""

    open_tickets = repo.active_tickets(db_session)
    user = actor(msg)
    bot = bot_of(msg)
    who_str = display_for(repo.registration_for(db_session, user.id), user)
    closed_count = 0

    for t in open_tickets:
        if t.id is None or t.status == TicketStatus.CLOSED:
            continue
        updated = repo.close_ticket(db_session, t.id, actor_chat_id=user.id)
        await events.publish_ticket(updated)
        await notify.channel_msg(
            bot,
            i18n.CH_CLOSED.format(who=who_str, group=_DEV_ACTOR_GROUP, uid=t.id),
        )
        await notify.group_msg(
            bot, db_session, t.group_requesting,
            i18n.GROUP_TICKET_CLOSED_OWNER.format(uid=t.id),
        )
        await notify.group_msg(
            bot, db_session, t.group_tasked,
            i18n.GROUP_TICKET_CLOSED_PEER.format(who=who_str, uid=t.id),
            exclude_muted=True,
        )
        closed_count += 1

    await msg.answer(f"☑️ Closed {closed_count} ticket(s).")
    await notify.dev_msg(bot, f"☑️ /closeall closed {closed_count} ticket(s).")
