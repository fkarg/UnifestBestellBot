"""Orga-only commands: /wip /close /move /message /all /tickets /help2
and the related inline ticket pickers."""

from collections.abc import Awaitable, Callable

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlmodel import Session

from .. import i18n, repo
from ..config import AppConfig
from ..models import Ticket, TicketStatus
from . import keyboards, notify
from .common import who
from .filters import IsOrga

router = Router(name="orga")


# --- Helpers -------------------------------------------------------------


def _picker(tickets: list[Ticket], action: str, header: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t.display(), callback_data=f"{action}:{t.id}")]
        for t in tickets
    ]
    rows.append(
        [InlineKeyboardButton(text=i18n.PICKER_CANCEL, callback_data=f"{action}:_cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _arg_id(msg: Message) -> int | None:
    parts = (msg.text or "").split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


# --- /tickets, /all ------------------------------------------------------


@router.message(Command("tickets"), IsOrga())
async def cmd_tickets(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, msg.from_user.id)
    open_for_group = repo.active_tickets(db_session, group_tasked=reg.group_name)
    if not open_for_group:
        await msg.answer(
            i18n.NO_OPEN_TICKETS_FOR_USER_GROUP.format(group=reg.group_name),
            reply_markup=keyboards.for_user(reg, config),
        )
        return
    body = "\n\n".join(t.display() for t in open_for_group)
    await msg.answer(
        i18n.TICKETS_FOR_GROUP_HEADER.format(group=reg.group_name, tickets=body),
        reply_markup=keyboards.for_user(reg, config),
    )


@router.message(Command("all"), IsOrga())
async def cmd_all(msg: Message, db_session: Session, config: AppConfig) -> None:
    all_open = repo.active_tickets(db_session)
    if not all_open:
        await msg.answer(i18n.NO_OPEN_TICKETS_ANYWHERE)
        return
    parts: list[str] = []
    for orga in config.orga_names():
        for_orga = [t for t in all_open if t.group_tasked == orga]
        if for_orga:
            parts.append(
                f"\n🔷 Offene Tickets für [{orga}]:\n\n"
                + "\n\n".join(t.display() for t in for_orga)
            )
    reg = repo.registration_for(db_session, msg.from_user.id)
    await msg.answer("\n".join(parts) or i18n.NO_OPEN_TICKETS_ANYWHERE,
                     reply_markup=keyboards.for_user(reg, config))


@router.message(Command("help2"), IsOrga())
async def cmd_help2(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, msg.from_user.id)
    await msg.answer(i18n.HELP_ORGA, reply_markup=keyboards.for_user(reg, config))


# --- /wip -----------------------------------------------------------------


@router.message(Command("wip"), IsOrga())
async def cmd_wip(msg: Message, db_session: Session, config: AppConfig) -> None:
    if (tid := _arg_id(msg)) is not None:
        await _do_wip(msg, db_session, config, tid)
        return
    reg = repo.registration_for(db_session, msg.from_user.id)
    candidates = repo.active_tickets(
        db_session, group_tasked=reg.group_name, status=TicketStatus.OPEN
    )
    if not candidates:
        await msg.answer(
            i18n.NO_OPEN_TICKETS_FOR_GROUP.format(group=reg.group_name),
            reply_markup=keyboards.for_user(reg, config),
        )
        return
    await msg.answer(i18n.OPEN_TICKETS_LIST, reply_markup=_picker(candidates, "wip", i18n.OPEN_TICKETS_LIST))


@router.callback_query(F.data.startswith("wip:"), IsOrga())
async def on_wip_choice(
    cb: CallbackQuery, db_session: Session, config: AppConfig
) -> None:
    suffix = cb.data.removeprefix("wip:")
    if suffix == "_cancel":
        if cb.message is not None:
            await cb.message.edit_text(i18n.PICKER_CANCELLED)
        await cb.answer()
        return
    try:
        tid = int(suffix)
    except ValueError:
        await cb.answer()
        return
    await _do_wip(cb, db_session, config, tid)
    await cb.answer()


async def _do_wip(
    event: Message | CallbackQuery,
    s: Session,
    config: AppConfig,
    tid: int,
) -> None:
    ticket = repo.get_ticket(s, tid)
    reply_to = event.message if isinstance(event, CallbackQuery) else event
    if ticket is None or ticket.is_closed():
        if reply_to is not None:
            await reply_to.answer(i18n.TICKET_NOT_FOUND_OR_CLOSED.format(uid=tid))
        return
    if ticket.is_wip():
        if reply_to is not None:
            await reply_to.answer(i18n.TICKET_ALREADY_WIP)
        return
    actor = event.from_user
    updated = repo.set_wip(s, tid, who=who(actor), actor_chat_id=actor.id)
    reg = repo.registration_for(s, actor.id)

    if isinstance(event, CallbackQuery) and event.message is not None:
        await event.message.edit_text(updated.display())
    elif reply_to is not None:
        await reply_to.answer(
            i18n.TICKET_WIP_NOTICE.format(uid=tid),
            reply_markup=keyboards.for_user(reg, config),
        )

    await notify.channel_msg(
        event.bot, i18n.CH_WIP.format(who=who(actor), group=reg.group_name, uid=tid)
    )
    await notify.group_msg(
        event.bot, s, reg.group_name,
        i18n.GROUP_TICKET_WIP_PEER.format(who=who(actor), uid=tid),
        exclude_chat_id=actor.id,
    )
    await notify.group_msg(
        event.bot, s, ticket.group_requesting,
        i18n.GROUP_TICKET_WIP_OWNER.format(uid=tid),
    )


# --- /close ---------------------------------------------------------------


@router.message(Command("close"), IsOrga())
async def cmd_close(msg: Message, db_session: Session, config: AppConfig) -> None:
    if (tid := _arg_id(msg)) is not None:
        await _do_close(msg, db_session, config, tid)
        return
    reg = repo.registration_for(db_session, msg.from_user.id)
    candidates = repo.active_tickets(
        db_session, group_tasked=reg.group_name, status=TicketStatus.WIP
    )
    if not candidates:
        await msg.answer(
            i18n.NO_WIP_TICKETS_FOR_GROUP.format(group=reg.group_name),
            reply_markup=keyboards.for_user(reg, config),
        )
        return
    await msg.answer(i18n.WIP_TICKETS_LIST, reply_markup=_picker(candidates, "close", i18n.WIP_TICKETS_LIST))


@router.callback_query(F.data.startswith("close:"), IsOrga())
async def on_close_choice(
    cb: CallbackQuery, db_session: Session, config: AppConfig
) -> None:
    suffix = cb.data.removeprefix("close:")
    if suffix == "_cancel":
        if cb.message is not None:
            await cb.message.edit_text(i18n.PICKER_CANCELLED)
        await cb.answer()
        return
    try:
        tid = int(suffix)
    except ValueError:
        await cb.answer()
        return
    await _do_close(cb, db_session, config, tid)
    await cb.answer()


async def _do_close(
    event: Message | CallbackQuery,
    s: Session,
    config: AppConfig,
    tid: int,
) -> None:
    ticket = repo.get_ticket(s, tid)
    reply_to = event.message if isinstance(event, CallbackQuery) else event
    if ticket is None or ticket.is_closed():
        if reply_to is not None:
            await reply_to.answer(i18n.TICKET_NOT_FOUND_OR_CLOSED.format(uid=tid))
        return
    actor = event.from_user
    updated = repo.close_ticket(s, tid, actor_chat_id=actor.id)
    reg = repo.registration_for(s, actor.id)

    if isinstance(event, CallbackQuery) and event.message is not None:
        await event.message.edit_text(updated.display())
    elif reply_to is not None:
        await reply_to.answer(
            i18n.TICKET_CLOSED_NOTICE.format(uid=tid),
            reply_markup=keyboards.for_user(reg, config),
        )

    await notify.channel_msg(
        event.bot, i18n.CH_CLOSED.format(who=who(actor), group=reg.group_name, uid=tid)
    )
    await notify.group_msg(
        event.bot, s, reg.group_name,
        i18n.GROUP_TICKET_CLOSED_PEER.format(who=who(actor), uid=tid),
        exclude_chat_id=actor.id,
    )
    await notify.group_msg(
        event.bot, s, ticket.group_requesting,
        i18n.GROUP_TICKET_CLOSED_OWNER.format(uid=tid),
    )


# --- /move ----------------------------------------------------------------


@router.message(Command("move"), IsOrga())
async def cmd_move(msg: Message, db_session: Session, config: AppConfig) -> None:
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer(i18n.MOVE_USAGE.format(groups=config.orga_names()))
        return
    try:
        tid = int(parts[1])
    except ValueError:
        await msg.answer(i18n.MOVE_USAGE.format(groups=config.orga_names()))
        return
    target = parts[2].strip()
    if not config.is_orga(target):
        await msg.answer(i18n.MOVE_USAGE.format(groups=config.orga_names()))
        return
    ticket = repo.get_ticket(db_session, tid)
    if ticket is None or ticket.is_closed():
        await msg.answer(i18n.TICKET_NOT_FOUND_OR_CLOSED.format(uid=tid))
        return
    if ticket.is_wip():
        await msg.answer(i18n.TICKET_MOVE_BLOCKED_WIP.format(uid=tid))
        return
    repo.move_ticket(db_session, tid, new_group=target, actor_chat_id=msg.from_user.id)
    reg = repo.registration_for(db_session, msg.from_user.id)
    await msg.answer(
        i18n.TICKET_MOVED_NOTICE.format(uid=tid, group=target),
        reply_markup=keyboards.for_user(reg, config),
    )
    await notify.channel_msg(
        msg.bot, i18n.CH_MOVED.format(uid=tid, group=target)
    )
    await notify.group_msg(
        msg.bot, db_session, target,
        i18n.GROUP_TICKET_FOR_ORGA.format(uid=tid, text=ticket.text),
    )


# --- /message -------------------------------------------------------------


@router.message(Command("message"), IsOrga())
async def cmd_message(msg: Message, db_session: Session, config: AppConfig) -> None:
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer(i18n.MESSAGE_USAGE)
        return
    try:
        tid = int(parts[1])
    except ValueError:
        await msg.answer(i18n.MESSAGE_USAGE)
        return
    body = parts[2]
    ticket = repo.get_ticket(db_session, tid)
    if ticket is None:
        await msg.answer(i18n.TICKET_NOT_FOUND_OR_CLOSED.format(uid=tid))
        return
    reg = repo.registration_for(db_session, msg.from_user.id)
    await notify.group_msg(
        msg.bot, db_session, ticket.group_requesting,
        i18n.GROUP_INCOMING_MESSAGE.format(sender=reg.group_name, message=body),
    )
    await notify.channel_msg(
        msg.bot,
        i18n.CH_MESSAGE.format(
            sender=reg.group_name, recipient=ticket.group_requesting, message=body
        ),
    )
    repo.record_message(
        db_session,
        ticket_id=tid,
        actor_chat_id=msg.from_user.id,
        message=body,
    )
    await msg.answer(i18n.MESSAGE_DELIVERED, reply_markup=keyboards.for_user(reg, config))


# --- /helpers (shift lookup) ---------------------------------------------

ShiftLookup = Callable[[str, AppConfig], Awaitable[str]]


@router.message(Command("helpers"), IsOrga())
async def cmd_helpers(
    msg: Message, db_session: Session, config: AppConfig, shift_lookup: ShiftLookup
) -> None:
    reg = repo.registration_for(db_session, msg.from_user.id)
    parts = (msg.text or "").split(maxsplit=1)
    group = parts[1].strip() if len(parts) > 1 else reg.group_name
    summary = await shift_lookup(group, config)
    await msg.answer(summary, reply_markup=keyboards.for_user(reg, config))


# --- /bug, /feature (open to everyone) ------------------------------------


@router.message(Command("bug"))
async def cmd_bug(msg: Message, db_session: Session, config: AppConfig) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer(i18n.BUG_USAGE)
        return
    await notify.dev_msg(
        msg.bot, i18n.DEV_BUG.format(who=who(msg.from_user), message=parts[1])
    )
    reg = repo.registration_for(db_session, msg.from_user.id)
    await msg.answer(i18n.BUG_FORWARDED, reply_markup=keyboards.for_user(reg, config))


@router.message(Command("feature"))
async def cmd_feature(msg: Message, db_session: Session, config: AppConfig) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer(i18n.FEATURE_USAGE)
        return
    await notify.dev_msg(
        msg.bot, i18n.DEV_FEATURE.format(who=who(msg.from_user), message=parts[1])
    )
    reg = repo.registration_for(db_session, msg.from_user.id)
    await msg.answer(i18n.FEATURE_FORWARDED, reply_markup=keyboards.for_user(reg, config))
