from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CallbackContext,
)

from lib.config import MAPPING, ORGA_GROUPS
from lib.utils import who

# from lib.commands import channel_msg, dev_msg, orga_msg, festko_command

import logging

log = logging.getLogger(__name__)


def group_msg(
    update: Update, context: CallbackContext, group: str, message: str
) -> None:
    log.info(f"to {group}: {message}")
    for chat_id in context.bot_data["group_association"].get(group, []):
        context.bot.send_message(
            chat_id=chat_id,
            text=message,
        )


def increase_highest_id(context: CallbackContext):
    highest = context.bot_data.get("highest_id", 0)
    context.bot_data["highest_id"] = highest + 1
    return highest


"""Tickets should contain the following information:
- id
- status: Open/Closed
- group requesting
- what (choice 1)
- what exactly (choice 2)
- how much they still have

Saved in context.bot_data['tickets'][id]
"""


def add_ticket(context, uid, group, message):
    # currently a tuple (str, str, bool)
    # with interpretation (group_name, ticket_text, is_wip)
    tickets = context.bot_data.get("tickets")
    if not tickets:
        context.bot_data["tickets"] = {}
    context.bot_data["tickets"][uid] = (group, message, False)


def create_ticket(
    update: Update, context: CallbackContext, group, category, details
) -> None:
    location = MAPPING[group]
    uid = increase_highest_id(context)

    text = f"#{uid}: Group {group} with location {location} requested someone for {category}\n\nDetails: {details}"
    add_ticket(context, uid, group, text)

    keyboard = [
        [InlineKeyboardButton("Update", callback_data=f"update #{uid}")],
        [InlineKeyboardButton("Working on it", callback_data=f"wip #{uid}")],
        [InlineKeyboardButton("Close", callback_data=f"close #{uid}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    log.info(f"new ticket {text}")
    for chat_id in context.bot_data["group_association"]["Festko"]:
        context.bot.send_message(
            chat_id=chat_id,
            text="Open: " + text,  # reply_markup=reply_markup
        )
    for chat_id in context.bot_data["group_association"][group]:
        if chat_id == update.effective_chat.id:
            continue
        context.bot.send_message(
            chat_id=chat_id,
            text=f"Someone in your group just created ticket #{uid} about {category}\n\n{details}",
            # reply_markup=InlineKeyboardMarkup(
            #     [[InlineKeyboardButton("Update", callback_data=f"update #{uid}")]],
            # ),
        )
    return uid


def orga_command(func):
    def wrapper(update: Update, context: CallbackContext):
        if context.user_data.get("group_association") in ORGA_GROUPS:
            func(update, context)
        else:
            message = "You are not authorized to execute this command."
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message,
            )

    return wrapper


@orga_command
def close(update: Update, context: CallbackContext) -> None:
    # close a ticket
    try:
        uid = int(context.args[0])
    except (ValueError, IndexError):
        update.message.reply_text("Die Benutzung des Kommandos ist /close <ticket-id>")
    if tup := context.bot_data["tickets"].get(uid):
        (group, text, is_wip) = tup
        # notify others in same orga-group
        group_msg(
            update,
            context,
            context.user_data["group_association"],
            f"{who(update)} hat Ticket {uid} geschlossen.",
        )
        # notify group of ticket creators
        group_msg(update, context, group, "Euer Ticket {uid} wurde bearbeitet.")
        # delete ticket
        context.bot_data["tickets"][uid] = (group, text, True)
    else:
        update.message.reply_text("Es gibt kein offenes Ticket mit dieser Zahl.")


@orga_command
def wip(update: Update, context: CallbackContext) -> None:
    # make a ticket WIP
    try:
        uid = int(context.args[0])
    except (ValueError, IndexError):
        update.message.reply_text("Die Benutzung des Kommandos ist /wip <ticket-id>")
    if tup := context.bot_data["tickets"].get(uid):
        (group, text, is_wip) = tup
        if is_wip:
            # someone is already working on it.
            update.message.reply_text("Jemand arbeitet bereits daran.")
        else:
            # set is_wip flag to true
            context.bot_data["tickets"][uid] = (group, text, True)
            # notify others in same orga-group
            group_msg(
                update,
                context,
                context.user_data["group_association"],
                f"{who(update)} hat angefangen, Ticket {uid} zu bearbeiten.",
            )
            # notify group of ticket creators
            group_msg(
                update,
                context,
                group,
                "Euer Ticket {uid} wurde angefangen zu bearbeiten.",
            )
    else:
        update.message.reply_text("Es gibt kein offenes Ticket mit dieser Zahl.")


@orga_command
def tickets(update: Update, context: CallbackContext) -> None:
    # list all open tickets
    message = ""
    for (uid, (group, text, is_wip)) in context.bot_data["tickets"].items():
        if is_wip:
            message += "\n\n---\nWIP " + text
        else:
            message += "\n\n---\nOpen " + text

    if message:
        message = "Liste der offenen Tickets:" + message
    else:
        message = "Momentan gibt es keine offenen Tickets."

    update.message.reply_text(message)


@orga_command
def help2(update: Update, context: CallbackContext) -> None:
    message = """Additional help message for Festko, WIP.
Available commands:
/system
    Show global state
/tickets
    Show open ticket and their ids
/close <id>
/wip <id>
/help2
    Show this help message
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )
