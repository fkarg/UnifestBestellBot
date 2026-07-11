"""Developer-only commands. Defensive against accidental fat-fingering."""

from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlmodel import Session

from .. import __version__, i18n, repo
from ..config import AppConfig
from ..events import EventBus
from ..models import Registration, Ticket, TicketStatus, now_utc, to_local
from . import notify
from .common import actor, answer_chunks, bot_of, display_for
from .filters import IsDeveloper

router = Router(name="admin")

# Group name attributed to the developer when closing tickets via /closeall.
# Shows up in channel logs and peer DMs so recipients can tell these closes
# apart from regular orga-driven ones.
_DEV_ACTOR_GROUP = "Entwickler"


@router.message(Command("version"), IsDeveloper())
async def cmd_version(msg: Message) -> None:
    await msg.answer(f"Version: {__version__}")


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


# --- /system (developer snapshot) -----------------------------------------

# Number of past tickets to surface: recent stand activity, and each orga
# member's last handled tickets. Kept small so the snapshot stays scannable.
_SYSTEM_RECENT = 3


def _fmt_ts(dt: datetime | None) -> str:
    return to_local(dt).strftime("%m-%d %H:%M") if dt is not None else "—"


def _fmt_registration(reg: Registration) -> str:
    name = " ".join(p for p in (reg.first_name, reg.last_name) if p) or "?"
    username = f" <@{reg.username}>" if reg.username else ""
    override = f'  (display: "{reg.display_override}")' if reg.display_override else ""
    return f"  • {reg.chat_id}  {name}{username}{override}"


def _fmt_ticket(t: Ticket) -> str:
    meta = f"{t.group_requesting}→{t.group_tasked} · opened {_fmt_ts(t.created_at)}"
    if t.who_wip:
        meta += f" · wip:{t.who_wip}"
    if t.closed_at:
        meta += f" · closed {_fmt_ts(t.closed_at)}"
    return f"  {t.display()}\n      {meta}"


@router.message(Command("system"), IsDeveloper())
async def cmd_system(msg: Message, db_session: Session, config: AppConfig) -> None:
    """Developer snapshot of live state: who is registered where, which
    tickets are open, recent stand activity, and each orga member's current
    and recently-closed work. Read-only; sends nothing to anyone else."""
    regs = repo.all_registrations(db_session)
    active = repo.active_tickets(db_session)
    recent = repo.recent_tickets(db_session, limit=_SYSTEM_RECENT)

    lines: list[str] = [f"🛠 SYSTEM STATUS · {_fmt_ts(now_utc())}", ""]

    lines.append(f"👥 REGISTRATIONS ({len(regs)})")
    current_group: str | None = None
    for reg in regs:
        if reg.group_name != current_group:
            current_group = reg.group_name
            tag = "Orga" if config.is_orga(current_group) else "Stand"
            lines.append(f"[{tag}] {current_group}")
        lines.append(_fmt_registration(reg))
    if not regs:
        lines.append("  (none)")
    lines.append("")

    lines.append(f"🎫 OPEN/WIP TICKETS ({len(active)})")
    if active:
        lines.extend(_fmt_ticket(t) for t in active)
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append(f"🏪 RECENT STAND TICKETS (last {_SYSTEM_RECENT})")
    if recent:
        lines.extend(_fmt_ticket(t) for t in recent)
    else:
        lines.append("  (none)")
    lines.append("")

    orga_regs = [r for r in regs if config.is_orga(r.group_name)]
    lines.append(f"🧑‍🔧 ORGA ACTIVITY ({len(orga_regs)})")
    for reg in orga_regs:
        wip = repo.active_tickets(
            db_session, status=TicketStatus.WIP, who_wip_chat_id=reg.chat_id
        )
        closed = repo.closed_tickets_for_chat_id(db_session, reg.chat_id)
        lines.append(f"{reg.display_name()} ({reg.chat_id}) [{reg.group_name}]")
        if wip:
            lines.append("  WIP now:")
            lines.extend(_fmt_ticket(t) for t in wip)
        else:
            lines.append("  WIP now: (none)")
        if closed:
            lines.append(f"  last {_SYSTEM_RECENT} closed:")
            # closed_tickets_for_chat_id is ascending by id; take the tail and
            # show newest first.
            lines.extend(_fmt_ticket(t) for t in reversed(closed[-_SYSTEM_RECENT:]))
    if not orga_regs:
        lines.append("  (none)")

    await answer_chunks(msg, "\n".join(lines))
