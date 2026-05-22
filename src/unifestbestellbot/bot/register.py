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
from .common import registration_from, who

router = Router(name="register")


@router.message(CommandStart())
async def cmd_start(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, msg.from_user.id)
    await msg.answer(i18n.START, reply_markup=keyboards.for_user(reg, config))


@router.message(Command("help"))
async def cmd_help(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, msg.from_user.id)
    text = i18n.HELP_ORGA if reg and config.is_orga(reg.group_name) else i18n.HELP
    await msg.answer(text, reply_markup=keyboards.for_user(reg, config))


@router.message(Command("register"))
async def cmd_register(msg: Message, config: AppConfig) -> None:
    choices = config.visible_stall_names() + config.orga_names()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"reg:{name}")]
            for name in choices
        ]
        + [[InlineKeyboardButton(text=i18n.PICKER_CANCEL, callback_data="reg:_cancel")]]
    )
    await msg.answer(i18n.REGISTER_PROMPT, reply_markup=kb)


@router.callback_query(F.data.startswith("reg:"))
async def on_register_choice(
    cb: CallbackQuery, db_session: Session, config: AppConfig
) -> None:
    choice = cb.data.removeprefix("reg:")
    if choice == "_cancel":
        if cb.message is not None:
            await cb.message.edit_text(i18n.REGISTER_CANCELLED)
        await cb.answer()
        return
    if not config.is_known_group(choice):
        await cb.answer(i18n.UNKNOWN_GROUP, show_alert=True)
        return

    reg = repo.upsert_registration(db_session, registration_from(cb.from_user, choice))
    if cb.message is not None:
        await cb.message.edit_text(i18n.REGISTER_SUCCESS.format(group=choice))
    # Send a follow-up message with the new reply keyboard.
    await cb.bot.send_message(
        chat_id=cb.from_user.id,
        text=i18n.REGISTER_KEYBOARD_UPDATE,
        reply_markup=keyboards.for_user(reg, config),
    )
    await notify.channel_msg(
        cb.bot, i18n.CH_REGISTER.format(who=who(cb.from_user), group=choice)
    )
    await cb.answer()


@router.message(Command("unregister"))
async def cmd_unregister(msg: Message, db_session: Session, config: AppConfig) -> None:
    previous = repo.unregister(db_session, msg.from_user.id)
    if previous:
        await msg.answer(
            i18n.UNREGISTER_SUCCESS.format(group=previous),
            reply_markup=keyboards.for_user(None, config),
        )
        await notify.channel_msg(
            msg.bot, i18n.CH_UNREGISTER.format(who=who(msg.from_user), group=previous)
        )
    else:
        await msg.answer(
            i18n.UNREGISTER_NONE, reply_markup=keyboards.for_user(None, config)
        )


@router.message(Command("status"))
async def cmd_status(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = repo.registration_for(db_session, msg.from_user.id)
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
