from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
import telegram
from telegram.ext import (
    Updater,
    CallbackContext,
)

from src.config import MAPPING, ORGA_GROUPS
from src.utils import who, dev_msg, channel_msg, orga_msg, group_msg

from enum import Enum, auto
import logging

log = logging.getLogger(__name__)


def increase_highest_id(context: CallbackContext):
    highest = context.bot_data.get("highest_id", 0)
    context.bot_data["highest_id"] = highest + 1
    return highest

class TicketStatus(Enum):
    OPEN = auto()
    WIP = auto()
    CLOSED = auto()

    def __repr__(self):
        return "<%s.%s>" % (self.__class__.__name__, self._name_)

    def __str__(self):
        return self._name_


class Ticket:
    def __init__(self,
                 update: Update,
                 context: CallbackContext,
                 status: TicketStatus,
                 group_requesting: str,
                 group_tasked: str,
                 text: str,
                 category: str = None,
    ):
        self.uid = increase_highest_id(context)
        self.status = status
        self.group_requesting = group_requesting
        self.group_tasked = group_tasked
        self.text = text

    def __str__(self):
        return f"{self.status} #{self.uid}: {self.text}"

    def get_uid(self) -> int:
        return self.uid

    def is_open(self) -> bool:
        return self.status == TicketStatus.OPEN

    def is_wip(self) -> bool:
        return self.status == TicketStatus.WIP

    def is_closed(self) -> bool:
        return self.status == TicketStatus.CLOSED

    def set_wip(self):
        assert self.status == TicketStatus.OPEN
        self.status = TicketStatus.WIP

    def set_close(self):
        assert self.status == TicketStatus.WIP
        self.status = TicketStatus.CLOSED

    def is_tasked(self, group: str) -> bool:
        return self.group_tasked == group


def add_ticket(context, ticket: Ticket):
    tickets = context.bot_data.get("tickets")
    if not tickets:
        context.bot_data["tickets"] = {}
    context.bot_data["tickets"][ticket.uid] = ticket


def create_ticket(
    update: Update,
    context: CallbackContext,
    group_requesting: str,
    text: str,
    category=None,
) -> None:

    log.info(f"Creating new ticket {text} from [{group_requesting}]")

    group_tasked = "Zentrale"
    if category == "Geld":
        group_tasked = "Finanz"
    elif category in ["Bier", "Cocktail", "Becher"]:
        group_tasked = "BiMi"

    ticket = Ticket(update, context,
                    TicketStatus.OPEN,
                    group_requesting,
                    group_tasked,
                    text,
                    category,
    )

    add_ticket(context, ticket)

    # keyboard = [
    #     [InlineKeyboardButton("Update", callback_data=f"update #{uid}")],
    #     [InlineKeyboardButton("Working on it", callback_data=f"wip #{uid}")],
    #     [InlineKeyboardButton("Close", callback_data=f"close #{uid}")],
    # ]
    # reply_markup = InlineKeyboardMarkup(keyboard)

    for chat_id in context.bot_data["group_association"][group_requesting]:
        if chat_id == update.effective_chat.id:
            # don't send back to original requester
            continue
        context.bot.send_message(
            chat_id=chat_id,
            text=f"{who(update)} in deiner Gruppe hat gerade ticket '{text}' erstellt.",
        )
    return ticket.uid


def orga_command(func):
    def wrapper(update: Update, context: CallbackContext):
        if context.user_data.get("group_association") in ORGA_GROUPS:
            func(update, context)
        else:
            message = "You are not authorized to execute this command."
            dev_msg(
                f"{who(update)} tried to execute a command for [ORGA]: {update.message.text}"
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
        group_tasked = context.user_data.get("group_association")
        keyboard = [[InlineKeyboardButton(str(t), callback_data=f"close #{t.uid}")] for t in context.bot_data["tickets"].values() if t.is_wip() and t.is_tasked(group_tasked)]
        keyboard_markup = InlineKeyboardMarkup(keyboard)

        if keyboard:
            update.message.reply_text("WIP Tickets:", reply_markup=keyboard_markup)
        else:
            update.message.reply_text(f"Keine Tickets WIP von [{group_tasked}].")


def close_uid(update: Update, context: CallbackContext, uid) -> None:
    from src.commands import channel_msg

    if ticket := context.bot_data["tickets"].get(uid):
        # notify others in same orga-group
        close_text = f"{who(update)} von {context.user_data['group_association']} hat Ticket #{ticket.uid} geschlossen."
        channel_msg(close_text)
        # orga_msg(update, context, close_text)
        group_msg(
            update,
            context,
            context.user_data["group_association"],
            f"{who(update)} hat Ticket #{ticket.uid} geschlossen.",
        )
        # notify group of ticket creators
        group_msg(update, context, ticket.group_requesting, f"Euer Ticket #{ticket.uid} wurde bearbeitet.")
        # delete ticket
        del context.bot_data["tickets"][uid]
    else:
        update.message.reply_text(f"Es gibt kein WIP Ticket #{uid}.")


@orga_command
def wip(update: Update, context: CallbackContext) -> None:
    from src.commands import channel_msg

    # make a ticket WIP
    try:
        uid = int(context.args[0])
        wip_uid(update, context, uid)
    except (ValueError, IndexError):
        group_tasked = context.user_data.get("group_association")
        keyboard = [[InlineKeyboardButton(str(t), callback_data=f"wip #{t.uid}")] for t in context.bot_data["tickets"].values() if t.is_open() and t.is_tasked(group_tasked)]
        keyboard_markup = InlineKeyboardMarkup(keyboard)

        if keyboard:
            update.message.reply_text("Offene Tickets:", reply_markup=keyboard_markup)
        else:
            update.message.reply_text(f"Keine offenen Tickets für [{group_tasked}].")

def wip_uid(update: Update, context: CallbackContext, uid: int):
    if ticket := context.bot_data["tickets"].get(uid):
        if ticket.is_wip():
            # someone is already working on it.
            update.message.reply_text("Jemand arbeitet bereits daran.")
        else:
            ticket.set_wip()
            add_ticket(context, ticket)
            group_msg(
                update,
                context,
                context.user_data["group_association"],
                f"{who(update)} arbeitet jetzt an Ticket #{uid}.",
            )
            channel_msg(
                f"{who(update)} von [{context.user_data['group_association']}] arbeitet jetzt an Ticket #{uid}."
            )
            # notify group of ticket creators
            group_msg(
                update,
                context,
                ticket.group_requesting,
                f"Euer Ticket #{uid} wurde angefangen zu bearbeiten.",
            )
    else:
        update.message.reply_text(f"Es gibt kein offenes Ticket #{uid}.")

@orga_command
def all(update: Update, context: CallbackContext) -> None:
    # list all open tickets
    message = ""
    for (uid, ticket) in context.bot_data["tickets"].items():
        message += f"\n\n---\n{str(ticket)}"

    if message:
        message = "Liste aller offenen Tickets:" + message
    else:
        message = "Momentan gibt es keine offenen Tickets."

    update.message.reply_text(message)


@orga_command
def tickets(update: Update, context: CallbackContext) -> None:
    # list open tickets to be done by [ORGA-GROUP]
    group_tasked = context.user_data.get("group_association")
    message = ""
    for (uid, ticket) in context.bot_data["tickets"].items():
        if ticket.group_tasked == group_tasked:
            message += f"\n\n---\n{str(ticket)}"

    if message:
        message = f"Liste der offenen Tickets für [{group_tasked}]:{message}"
    else:
        message = f"Momentan gibt es keine offenen Tickets für [{group_tasked}]."

    update.message.reply_text(message)


@orga_command
def help2(update: Update, context: CallbackContext) -> None:
    message = """Zusätzlicher Hilfetext für [ORGA], WIP.
Zusätzlich verfügbare Kommandos:
/all
    Zeige die Liste aller offenen tickets
    und deren <id>.
/tickets
    Zeige die Liste der offenen tickets
    und deren <id>, für deine Gruppe.
/wip <id>
    Beginne Arbeit an Ticket mit <id>.
/close <id>
    Schließe das Ticket mit <id>.
/message <ticket-id> <text>
    Sende eine Nachricht an alle Mitglieder
    der Gruppe, die Ticket <ticket-id>
    erstellt haben.
/help2
    Zeige diese Hilfenachricht.
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


@orga_command
def message(update: Update, context: CallbackContext) -> None:

    if len(context.args) < 2:
        update.message.reply_text(
            "Benutzung des Kommandos ist /message <ticket-id> <nachricht>"
        )
        return
    try:
        uid = int(context.args[0])
        group, text, is_wip = context.bot_data["tickets"][uid]
        message = (
            f"Nachricht von {context.user_data['group_association']}: "
            + " ".join(context.args[1:])
        )
        group_msg(update, context, group, message)
        channel_msg(f"An {group}: {message}")
        update.message.reply_text("Nachricht verschickt.")
    except (ValueError, IndexError):
        update.message.reply_text(
            "Stelle sicher, dass deine ticket-id eine valide Zahl von einem offenen Ticket ist."
        )
        return
