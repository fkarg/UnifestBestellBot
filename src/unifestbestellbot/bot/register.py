"""/start, /help, /register, /unregister, /status, /quiet, /loud."""

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlmodel import Session

from .. import i18n, repo
from ..config import AppConfig
from ..models import (
    PEER_CLOSED,
    PEER_NOTIFY_KINDS,
    PEER_OPENED,
    PEER_WIP,
    Registration,
    now_utc,
)
from . import keyboards, notify
from .common import actor, bot_of, display_for, registration_from, who

DEFAULT_QUIET_MINUTES = 30
MAX_QUIET_MINUTES = 24 * 60
MAX_DISPLAY_NAME = 64

router = Router(name="register")


@router.message(CommandStart())
async def cmd_start(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, actor(msg).id)
    await msg.answer(i18n.START, reply_markup=keyboards.for_user(reg, config))


@router.message(Command("help"))
async def cmd_help(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, actor(msg).id)
    text = i18n.HELP_ORGA if reg and config.is_orga(reg.group_name) else i18n.HELP
    await msg.answer(text, reply_markup=keyboards.for_user(reg, config))


@router.message(Command("register"))
async def cmd_register(msg: Message, db_session: Session, config: AppConfig) -> None:
    # /register <name> registers directly. Supports orga groups and hidden
    # stands, which deliberately do not appear in the inline picker (we
    # don't want a button on every volunteer's screen for the finance
    # group). Match is case-insensitive.
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) > 1:
        await _register_textual(msg, db_session, config, parts[1].strip())
        return

    # No argument — show only visible stands. Orga and hidden groups are
    # reachable only via the textual argument above.
    choices = config.visible_stall_names()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"reg:{name}")]
            for name in choices
        ]
        + [[InlineKeyboardButton(text=i18n.PICKER_CANCEL, callback_data="reg:_cancel")]]
    )
    await msg.answer(i18n.REGISTER_PROMPT, reply_markup=kb)


async def _register_textual(
    msg: Message, s: Session, config: AppConfig, query: str
) -> None:
    """Resolve a case-insensitive textual /register argument against all
    known group identifiers (visible stands, hidden stands, orga groups)
    and register the user."""
    all_groups = config.all_stall_names() + config.orga_names()
    match = next((g for g in all_groups if g.casefold() == query.casefold()), None)
    if match is None:
        await msg.answer(
            i18n.UNKNOWN_GROUP,
            reply_markup=keyboards.for_user(None, config),
        )
        return

    user = actor(msg)
    reg = repo.upsert_registration(s, registration_from(user, match))
    await msg.answer(
        i18n.REGISTER_SUCCESS.format(group=match),
        reply_markup=keyboards.for_user(reg, config),
    )
    await notify.channel_msg(
        bot_of(msg), i18n.CH_REGISTER.format(who=display_for(reg, user), group=match)
    )


@router.callback_query(F.data.startswith("reg:"))
async def on_register_choice(
    cb: CallbackQuery, db_session: Session, config: AppConfig
) -> None:
    assert cb.data is not None  # F.data.startswith filter guarantees this
    choice = cb.data.removeprefix("reg:")
    if choice == "_cancel":
        if isinstance(cb.message, Message):
            await cb.message.edit_text(i18n.REGISTER_CANCELLED)
        await cb.answer()
        return
    # Only visible stands are allowed via the picker callback path —
    # defence in depth so a hand-crafted callback can't register a user
    # for an orga or hidden group.
    if choice not in config.visible_stall_names():
        await cb.answer(i18n.UNKNOWN_GROUP, show_alert=True)
        return

    user = actor(cb)
    reg = repo.upsert_registration(db_session, registration_from(user, choice))
    if isinstance(cb.message, Message):
        await cb.message.edit_text(i18n.REGISTER_SUCCESS.format(group=choice))
    # Send a follow-up message with the new reply keyboard.
    bot = bot_of(cb)
    await bot.send_message(
        chat_id=user.id,
        text=i18n.REGISTER_KEYBOARD_UPDATE,
        reply_markup=keyboards.for_user(reg, config),
    )
    await notify.channel_msg(
        bot, i18n.CH_REGISTER.format(who=display_for(reg, user), group=choice)
    )
    await cb.answer()


@router.message(Command("unregister"))
async def cmd_unregister(msg: Message, db_session: Session, config: AppConfig) -> None:
    user = actor(msg)
    previous = repo.unregister(db_session, user.id)
    if previous:
        await msg.answer(
            i18n.UNREGISTER_SUCCESS.format(group=previous),
            reply_markup=keyboards.for_user(None, config),
        )
        await notify.channel_msg(
            bot_of(msg), i18n.CH_UNREGISTER.format(who=who(user), group=previous)
        )
    else:
        await msg.answer(
            i18n.UNREGISTER_NONE, reply_markup=keyboards.for_user(None, config)
        )


@router.message(Command("status"))
async def cmd_status(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, actor(msg).id)
    if reg is None:
        await msg.answer(
            i18n.STATUS_NO_REGISTRATION,
            reply_markup=keyboards.for_user(None, config),
        )
        return
    open_tickets = repo.tickets_requested_by(db_session, reg.group_name)
    if open_tickets:
        body = "\n\n---\n".join(t.display() for t in open_tickets)
        text = i18n.STATUS_WITH_TICKETS.format(
            group=reg.group_name, count=len(open_tickets), tickets=body
        )
    else:
        text = i18n.STATUS_NO_TICKETS.format(group=reg.group_name)
    await msg.answer(text, reply_markup=keyboards.for_user(reg, config))


@router.message(Command("name"))
async def cmd_name(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, actor(msg).id)
    if reg is None:
        await msg.answer(i18n.NOT_REGISTERED, reply_markup=keyboards.for_user(None, config))
        return

    parts = (msg.text or "").split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    if not arg:
        current = reg.display_override or who(actor(msg))
        await msg.answer(
            i18n.NAME_CURRENT.format(name=current),
            reply_markup=keyboards.for_user(reg, config),
        )
        return
    if arg == "-":
        repo.set_display_override(db_session, reg.chat_id, None)
        await msg.answer(i18n.NAME_CLEARED, reply_markup=keyboards.for_user(reg, config))
        return
    name = arg[:MAX_DISPLAY_NAME]
    repo.set_display_override(db_session, reg.chat_id, name)
    await msg.answer(
        i18n.NAME_SET.format(name=name), reply_markup=keyboards.for_user(reg, config)
    )


_NOTIFY_LABELS = {
    PEER_OPENED: i18n.NOTIFY_LABEL_OPENED,
    PEER_WIP: i18n.NOTIFY_LABEL_WIP,
    PEER_CLOSED: i18n.NOTIFY_LABEL_CLOSED,
}


def _notify_panel(reg: Registration) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{i18n.NOTIFY_OFF if reg.is_peer_kind_muted(kind) else i18n.NOTIFY_ON}"
                f" {_NOTIFY_LABELS[kind]}",
                callback_data=f"notif:{kind}",
            )
        ]
        for kind in PEER_NOTIFY_KINDS
    ]
    rows.append(
        [InlineKeyboardButton(text=i18n.NOTIFY_DONE_BTN, callback_data="notif:_done")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("notify"))
async def cmd_notify(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, actor(msg).id)
    if reg is None:
        await msg.answer(i18n.NOT_REGISTERED, reply_markup=keyboards.for_user(None, config))
        return
    await msg.answer(i18n.NOTIFY_HEADER, reply_markup=_notify_panel(reg))


@router.callback_query(F.data.startswith("notif:"))
async def on_notify_toggle(cb: CallbackQuery, db_session: Session) -> None:
    assert cb.data is not None
    suffix = cb.data.removeprefix("notif:")
    reg = repo.registration_for(db_session, actor(cb).id)
    if reg is None:
        await cb.answer()
        return
    if suffix == "_done":
        if isinstance(cb.message, Message):
            await cb.message.edit_text(i18n.NOTIFY_DONE)
        await cb.answer()
        return
    if suffix in PEER_NOTIFY_KINDS:
        repo.toggle_notify_mute(db_session, reg.chat_id, suffix)
        reg = repo.registration_for(db_session, reg.chat_id)
        if reg is not None and isinstance(cb.message, Message):
            await cb.message.edit_text(i18n.NOTIFY_HEADER, reply_markup=_notify_panel(reg))
    await cb.answer()


@router.message(Command("quiet"))
async def cmd_quiet(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, actor(msg).id)
    if reg is None:
        await msg.answer(i18n.NOT_REGISTERED, reply_markup=keyboards.for_user(None, config))
        return

    parts = (msg.text or "").split(maxsplit=1)
    minutes = DEFAULT_QUIET_MINUTES
    if len(parts) > 1:
        try:
            minutes = int(parts[1].strip())
        except ValueError:
            await msg.answer(i18n.QUIET_USAGE, reply_markup=keyboards.for_user(reg, config))
            return
        if minutes < 1 or minutes > MAX_QUIET_MINUTES:
            await msg.answer(i18n.QUIET_USAGE, reply_markup=keyboards.for_user(reg, config))
            return

    until = now_utc() + timedelta(minutes=minutes)
    repo.set_mute(db_session, reg.chat_id, until=until)
    await msg.answer(
        i18n.QUIET_SET.format(minutes=minutes),
        reply_markup=keyboards.for_user(reg, config),
    )


@router.message(Command("loud"))
async def cmd_loud(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, actor(msg).id)
    if reg is None:
        await msg.answer(i18n.NOT_REGISTERED, reply_markup=keyboards.for_user(None, config))
        return

    was_muted = reg.mute_peer_until is not None
    repo.set_mute(db_session, reg.chat_id, until=None)
    text = i18n.LOUD_SET if was_muted else i18n.LOUD_ALREADY
    await msg.answer(text, reply_markup=keyboards.for_user(reg, config))
