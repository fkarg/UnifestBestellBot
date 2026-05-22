"""/request conversation. Uses reply keyboards + free-text fallback —
identical UX to the legacy bot, but the state machine is data-driven so
adding a category is a one-line change."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlmodel import Session

from .. import i18n, repo
from ..config import AppConfig
from ..events import EventBus
from . import keyboards, notify
from .common import actor, bot_of, who

router = Router(name="request")


class RequestFSM(StatesGroup):
    category = State()
    money = State()
    money_change = State()
    cups = State()
    amount = State()
    free = State()
    helper = State()


# --- Reply keyboards for each step ---------------------------------------


def _kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label) for label in row] for row in rows],
        resize_keyboard=True,
    )


CATEGORY_LABELS = {"Becher", "Geld", "Bier", "Cocktail", "Sonstiges", "Helfer"}
CATEGORY_KB = _kb(
    [
        ["Becher", "Geld", "/cancel"],
        ["Bier", "Cocktail", "Sonstiges"],
        ["Helfer"],
    ]
)
MONEY_KB = _kb([["Geld Abholen", "Wechselgeld"], ["Freitext", "/cancel"]])
MONEY_CHANGE_KB = _kb([["Scheine", "Münzen"], ["/cancel"]])
CUPS_KB = _kb([["Dreckige Abholen", "/cancel"], ["Shotbecher", "Normale Becher"]])
AMOUNT_KB = _kb([["0", "Freitext", "/cancel"], ["~10", "~20", "~50"]])
HELPER_KB = _kb([["zu viele", "zu wenige"], ["Helfer nicht da", "Liste Schichten"]])


# --- Follow-up table: category -> (next state, keyboard, prompt) ----------


@dataclass(frozen=True)
class _Branch:
    next_state: State
    keyboard: ReplyKeyboardMarkup | ReplyKeyboardRemove
    prompt: str


FOLLOWUPS: dict[str, _Branch] = {
    "Geld": _Branch(RequestFSM.money, MONEY_KB, i18n.ASK_MONEY),
    "Becher": _Branch(RequestFSM.cups, CUPS_KB, i18n.ASK_CUPS),
    "Bier": _Branch(RequestFSM.free, ReplyKeyboardRemove(), i18n.ASK_FREE),
    "Cocktail": _Branch(RequestFSM.free, ReplyKeyboardRemove(), i18n.ASK_FREE),
    "Sonstiges": _Branch(RequestFSM.free, ReplyKeyboardRemove(), i18n.ASK_FREE),
    "Helfer": _Branch(RequestFSM.helper, HELPER_KB, i18n.ASK_HELPER),
}


# --- Text renderers (pure functions, easy to unit-test) -------------------
#
# `stand` is the display string for the requesting stand — typically
# "Forum Süd [Cocktail]" via AppConfig.display_for. For orga members who
# request things (rare), it's just the orga group name. No team identity
# is ever included — orga handlers orient on location + stand type.


def render_collect(category: str, stand: str) -> str:
    return f"{category} abholen an {stand}"


def render_amount(stand: str, amount: str, detail: str) -> str:
    return f"{stand} hat noch {amount} {detail}"


def render_free(category: str, stand: str, free_text: str) -> str:
    return f"{stand} braucht {category}: '{free_text}'"


def render_change(stand: str, kind: str) -> str:
    return f"{stand} braucht {kind}"


# --- Entry ----------------------------------------------------------------


@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext, db_session: Session, config: AppConfig) -> None:
    await state.clear()
    reg = repo.registration_for(db_session, actor(msg).id)
    await msg.answer(i18n.REQUEST_CANCELLED, reply_markup=keyboards.for_user(reg, config))


@router.message(Command("request"))
async def cmd_request(
    msg: Message, state: FSMContext, db_session: Session, config: AppConfig
) -> None:
    current = await state.get_state()
    if current is not None:
        await msg.answer(i18n.REQUEST_IN_PROGRESS)
        return

    reg = repo.registration_for(db_session, actor(msg).id)
    if reg is None:
        await msg.answer(
            i18n.NOT_REGISTERED, reply_markup=keyboards.for_user(None, config)
        )
        return

    await state.set_state(RequestFSM.category)
    await state.update_data(group=reg.group_name)
    await msg.answer(i18n.REQUEST_INTRO, reply_markup=CATEGORY_KB)


# --- Category --------------------------------------------------------------


@router.message(RequestFSM.category, F.text.in_(CATEGORY_LABELS))
async def pick_category(msg: Message, state: FSMContext) -> None:
    category = msg.text
    assert category is not None  # F.text.in_ filter guarantees this
    await state.update_data(category=category)
    branch = FOLLOWUPS[category]
    await state.set_state(branch.next_state)
    await msg.answer(branch.prompt, reply_markup=branch.keyboard)


@router.message(RequestFSM.category)
async def category_unrecognized(msg: Message) -> None:
    await msg.answer(i18n.REQUEST_CATEGORY_UNKNOWN, reply_markup=CATEGORY_KB)


# --- Money -----------------------------------------------------------------


@router.message(RequestFSM.money, F.text == "Geld Abholen")
async def money_collect(
    msg: Message,
    state: FSMContext,
    db_session: Session,
    config: AppConfig,
    events: EventBus,
) -> None:
    data = await state.get_data()
    stand = config.display_for(data["group"])
    text = render_collect(data["category"], stand)
    await _finalize(msg, state, db_session, config, events, text=text)


@router.message(RequestFSM.money, F.text == "Wechselgeld")
async def money_change_branch(msg: Message, state: FSMContext) -> None:
    # Keep the existing first_choice ("Geld"); add money_kind detail.
    await state.update_data(money_choice="Wechselgeld")
    await state.set_state(RequestFSM.money_change)
    await msg.answer(i18n.ASK_MONEY_CHANGE, reply_markup=MONEY_CHANGE_KB)


@router.message(RequestFSM.money, F.text == "Freitext")
async def money_freetext(msg: Message, state: FSMContext) -> None:
    await state.set_state(RequestFSM.free)
    await msg.answer(i18n.ASK_FREE, reply_markup=ReplyKeyboardRemove())


@router.message(RequestFSM.money)
async def money_unrecognized(msg: Message) -> None:
    await msg.answer(i18n.REQUEST_CATEGORY_UNKNOWN, reply_markup=MONEY_KB)


@router.message(RequestFSM.money_change, F.text.in_({"Scheine", "Münzen"}))
async def money_change_pick(
    msg: Message,
    state: FSMContext,
    db_session: Session,
    config: AppConfig,
    events: EventBus,
) -> None:
    data = await state.get_data()
    stand = config.display_for(data["group"])
    text = render_change(stand, msg.text or "")
    await _finalize(msg, state, db_session, config, events, text=text)


@router.message(RequestFSM.money_change)
async def money_change_unrecognized(msg: Message) -> None:
    await msg.answer(i18n.REQUEST_CATEGORY_UNKNOWN, reply_markup=MONEY_CHANGE_KB)


# --- Cups ------------------------------------------------------------------


@router.message(RequestFSM.cups, F.text == "Dreckige Abholen")
async def cups_collect(
    msg: Message,
    state: FSMContext,
    db_session: Session,
    config: AppConfig,
    events: EventBus,
) -> None:
    data = await state.get_data()
    stand = config.display_for(data["group"])
    text = render_collect(data["category"], stand)
    await _finalize(msg, state, db_session, config, events, text=text)


@router.message(RequestFSM.cups, F.text.in_({"Shotbecher", "Normale Becher"}))
async def cups_kind(msg: Message, state: FSMContext) -> None:
    await state.update_data(detail=msg.text)
    await state.set_state(RequestFSM.amount)
    await msg.answer(i18n.ASK_AMOUNT, reply_markup=AMOUNT_KB)


@router.message(RequestFSM.cups)
async def cups_unrecognized(msg: Message) -> None:
    await msg.answer(i18n.REQUEST_CATEGORY_UNKNOWN, reply_markup=CUPS_KB)


# --- Amount ----------------------------------------------------------------


@router.message(RequestFSM.amount, F.text == "Freitext")
async def amount_freetext(msg: Message, state: FSMContext) -> None:
    await state.set_state(RequestFSM.free)
    await msg.answer(i18n.ASK_FREE, reply_markup=ReplyKeyboardRemove())


@router.message(RequestFSM.amount)
async def amount_value(
    msg: Message,
    state: FSMContext,
    db_session: Session,
    config: AppConfig,
    events: EventBus,
) -> None:
    data = await state.get_data()
    stand = config.display_for(data["group"])
    detail = data.get("detail", "")
    text = render_amount(stand, msg.text or "", detail)
    await _finalize(msg, state, db_session, config, events, text=text)


# --- Free text -------------------------------------------------------------


@router.message(RequestFSM.free)
async def free_text(
    msg: Message,
    state: FSMContext,
    db_session: Session,
    config: AppConfig,
    events: EventBus,
) -> None:
    data = await state.get_data()
    stand = config.display_for(data["group"])
    text = render_free(data["category"], stand, msg.text or "")
    await _finalize(msg, state, db_session, config, events, text=text)


# --- Helper ---------------------------------------------------------------

ShiftLookup = Callable[[str, AppConfig], Awaitable[str]]


@router.message(RequestFSM.helper, F.text == "Liste Schichten")
async def helper_list_shifts(
    msg: Message,
    state: FSMContext,
    db_session: Session,
    config: AppConfig,
    shift_lookup: ShiftLookup,
) -> None:
    data = await state.get_data()
    summary = await shift_lookup(data["group"], config)
    await state.clear()
    reg = repo.registration_for(db_session, actor(msg).id)
    await msg.answer(summary, reply_markup=keyboards.for_user(reg, config))


@router.message(RequestFSM.helper, F.text == "Helfer nicht da")
async def helper_missing(msg: Message, state: FSMContext) -> None:
    await state.set_state(RequestFSM.free)
    await msg.answer(i18n.ASK_HELPER_FREE, reply_markup=ReplyKeyboardRemove())


@router.message(RequestFSM.helper)
async def helper_amount(msg: Message, state: FSMContext) -> None:
    # "zu viele" / "zu wenige" / anything-else flows into the amount question.
    await state.update_data(detail=msg.text)
    await state.set_state(RequestFSM.amount)
    await msg.answer(i18n.ASK_AMOUNT, reply_markup=AMOUNT_KB)


# --- Finalize -------------------------------------------------------------


async def _finalize(
    msg: Message,
    state: FSMContext,
    db_session: Session,
    config: AppConfig,
    events: EventBus,
    *,
    text: str,
) -> None:
    data = await state.get_data()
    category = data["category"]
    group_tasked = config.route_category(category)
    user = actor(msg)
    bot = bot_of(msg)
    ticket = repo.create_ticket(
        db_session,
        category=category,
        text=text,
        group_requesting=data["group"],
        group_tasked=group_tasked,
        actor_chat_id=user.id,
    )
    await state.clear()

    reg = repo.registration_for(db_session, user.id)
    await msg.answer(
        i18n.REQUEST_TICKET_CREATED.format(uid=ticket.id),
        reply_markup=keyboards.for_user(reg, config),
    )

    await events.publish_ticket(ticket)
    await notify.channel_msg(bot, i18n.CH_OPEN.format(uid=ticket.id, text=text))
    await notify.group_msg(
        bot,
        db_session,
        data["group"],
        i18n.GROUP_TICKET_OPENED.format(who=who(user), text=text),
        exclude_chat_id=user.id,
    )
    await notify.group_msg(
        bot,
        db_session,
        group_tasked,
        i18n.GROUP_TICKET_FOR_ORGA.format(uid=ticket.id, text=text),
    )
