"""Developer-only commands. Defensive against accidental fat-fingering."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlmodel import Session

from .. import repo
from ..config import AppConfig
from ..models import TicketStatus
from . import notify
from .filters import IsDeveloper

router = Router(name="admin")


@router.message(Command("closeall"), IsDeveloper())
async def cmd_closeall(msg: Message, db_session: Session, config: AppConfig) -> None:
    open_tickets = repo.active_tickets(db_session)
    for t in open_tickets:
        if t.status != TicketStatus.CLOSED:
            repo.close_ticket(db_session, t.id, actor_chat_id=msg.from_user.id)
    await msg.answer(f"☑️ Closed {len(open_tickets)} ticket(s).")
    await notify.dev_msg(msg.bot, f"☑️ Closed {len(open_tickets)} ticket(s).")
