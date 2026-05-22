"""/start, /help, /register, /unregister, /status."""

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
from . import keyboards, notify
from .common import actor, bot_of, registration_from, who

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
        bot_of(msg), i18n.CH_REGISTER.format(who=who(user), group=match)
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
        bot, i18n.CH_REGISTER.format(who=who(user), group=choice)
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
