from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CallbackContext,
)

from lib.config import MAPPING, ORGA_GROUPS
from lib.utils import who

import logging

log = logging.getLogger(__name__)

def orga_msg(update: Update, context: CallbackContext, message: str) -> None:
    for group in ORGA_GROUPS:
        group_msg(update, context, group, message)


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
        update: Update, context: CallbackContext, group: str, text: str,
        category=None,
) -> None:
    uid = increase_highest_id(context)

    # text = f"#{uid}: Group {group} with location {location} requested someone for {category}\n\nDetails: {details}"
    # text2 = f"#{uid}: {location}{details}"
    text = f"#{uid}: {text}"

    add_ticket(context, uid, group, text)

    # keyboard = [
    #     [InlineKeyboardButton("Update", callback_data=f"update #{uid}")],
    #     [InlineKeyboardButton("Working on it", callback_data=f"wip #{uid}")],
    #     [InlineKeyboardButton("Close", callback_data=f"close #{uid}")],
    # ]
    # reply_markup = InlineKeyboardMarkup(keyboard)
    # add to group_msg as parameter
    log.info(f"new ticket {text}")
    group_msg(update, context, "Festko", f"Neues Ticket: {text}")
    if category == "Geld":
        group_msg(update, context, "Finanzer", f"Neues Ticket: {text}")
    if category in ["Bier", "Cocktails", "Becher"]:
        group_msg(update, context, "BiMi", f"Neues Ticket: {text}")
    # group_msg(update, context, group, f"{who(update)} in deiner Gruppe hat gerade ticket '{text}' erstellt.")
    for chat_id in context.bot_data["group_association"][group]:
        if chat_id == update.effective_chat.id:
            # don't send back to original requester
            continue
        context.bot.send_message(
            chat_id=chat_id,
            text=f"{who(update)} in deiner Gruppe hat gerade ticket '{text}' erstellt."
        )
    return uid


def orga_command(func):
    def wrapper(update: Update, context: CallbackContext):
        if context.user_data.get("group_association") in ORGA_GROUPS:
            func(update, context)
        else:
            message = "You are not authorized to execute this command."
            dev_msg(
                "{who(update)} tried to execute a Festko command: {update.message.text}"
            )
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
        close_uid(update, context, uid)
    except (ValueError, IndexError):
        update.message.reply_text("Die Benutzung des Kommandos ist /close <ticket-id>")


def close_uid(update: Update, context: CallbackContext, uid) -> None:
    from lib.commands import channel_msg
    if tup := context.bot_data["tickets"].get(uid):
        (group, text, is_wip) = tup
        # notify others in same orga-group
        close_text=f"{who(update)} von {context.user_data['group_association']} hat Ticket #{uid} geschlossen."
        channel_msg(close_text)
        orga_msg(update, context, close_text)
        # notify group of ticket creators
        group_msg(update, context, group, f"Euer Ticket #{uid} wurde bearbeitet.")
        # delete ticket
        del context.bot_data["tickets"][uid]
    else:
        update.message.reply_text("Es gibt kein offenes Ticket mit dieser Zahl.")


@orga_command
def wip(update: Update, context: CallbackContext) -> None:
    from lib.commands import channel_msg
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
                f"{who(update)} hat angefangen, Ticket #{uid} zu bearbeiten.",
            )
            channel_msg(f"{who(update)} von {context.user_data['group_association']} hat angefangen, Ticket #{uid} zu bearbeiten.")
            # notify group of ticket creators
            group_msg(
                update,
                context,
                group,
                f"Euer Ticket #{uid} wurde angefangen zu bearbeiten.",
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
    Show details on system state
/tickets
    Zeige eine Liste der offenen tickets und deren <id>
/wip <id>
    Beginne Arbeit an Ticket mit <id>
/close <id>
    Schließe das Ticket mit <id>
/message <ticket-id> <text>
    Sende eine Nachricht an alle Mitglieder der Gruppe,
    die ein Ticket erstellt haben
/help2
    Zeige diese Hilfenachricht
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )

@orga_command
def message(update: Update, context: CallbackContext) -> None:
    from lib.commands import channel_msg
    if len(context.args) < 2:
        update.message.reply_text("Benutzung des Kommandos ist /message <ticket-id> <nachricht>")
        return
    try:
        uid = int(context.args[0])
        group, text, is_wip = context.bot_data["tickets"][uid]
        message = f"Nachricht von {context.user_data['group_association']}: " + " ".join(context.args[1:])
        group_msg(update, context, group, message)
        channel_msg(f"An {group}: {message}")
        update.message.reply_text("Nachricht verschickt.")
    except (ValueError, IndexError):
        update.message.reply_text("Stelle sicher, dass deine ticket-id eine valide Zahl von einem offenen Ticket ist.")
        return
