from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
)

from src.dashboard_bridge import dashboard_publish, mqtt_set_tickets
from src.config import ORGA_GROUPS
from src.utils import who, dev_msg, channel_msg, group_msg, autoselect_keyboard
from src.tickets_data import Ticket, TicketStatus

import logging


log = logging.getLogger(__name__)


def add_ticket(context, ticket: Ticket):
    """Add ticket to bot data, or update ticket in bot data under its uid"""
    tickets = context.bot_data.get("tickets")
    if not tickets:
        context.bot_data["tickets"] = {}
        mqtt_set_tickets(context.bot_data["tickets"])

    context.bot_data["tickets"][ticket.uid] = ticket
    dashboard_publish(f"tickets/{ticket.group_tasked}/{ticket.uid}", ticket)


def create_ticket(
    update: Update,
    context: CallbackContext,
    group_requesting: str,
    text: str,
    category=None,
) -> int:
    """Create new ticket from `group_requesting` in `category`.
    Tasks group based on `category`. Return uid of newly created ticket.
    """

    log.info(f"Creating new ticket {text} from [{group_requesting}]")

    group_tasked = "Zentrale"
    if category == "Geld":
        group_tasked = "Finanz"
    elif category in ["Bier", "Cocktail", "Becher"]:
        group_tasked = "BiMi"

    ticket = Ticket(
        group_requesting,
        group_tasked,
        text,
        context,
    )

    add_ticket(context, ticket)
    group_msg(
        update,
        context,
        group_requesting,
        f"{str(TicketStatus.OPEN)}: {who(update)} in deiner Gruppe hat gerade ticket '{text}' erstellt.",
    )
    return ticket.uid


def orga_command(func):
    """Decorator for commands only groups in `orga.json` are allowed to execute."""

    def wrapper(update: Update, context: CallbackContext):
        if context.user_data.get("group_association") in ORGA_GROUPS:
            func(update, context)
        else:
            message = "Dieser Befehl ist dir nicht erlaubt. Mit /status siehst du deine Gruppenmitgliedschaft und offene Tickets in deiner Gruppe."
            group = context.user_data.get("group_association")
            dev_msg(
                f"⚠️ {who(update)}  [{group}] tried to execute a command for [ORGA]: "
                f"{update.message.text}"
            )
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message,
                reply_markup=autoselect_keyboard(update, context),
            )

    return wrapper


@orga_command
def close(update: Update, context: CallbackContext) -> None:
    """Close a ticket when provided with a uid. Otherwise, provide inline
    list of WIP tickets for group.
    """
    try:
        uid = int(context.args[0])
        close_uid(update, context, uid)
    except (ValueError, IndexError):
        group_tasked = context.user_data.get("group_association")
        keyboard = [
            [InlineKeyboardButton(str(t), callback_data=f"close #{t.uid}")]
            for t in context.bot_data["tickets"].values()
            if t.is_wip() and t.is_tasked(group_tasked)
        ]

        if keyboard:
            keyboard.append(
                [InlineKeyboardButton("❌ Abbrechen", callback_data="cancel #0")]
            )
            keyboard_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text("WIP Tickets:", reply_markup=keyboard_markup)
        else:
            update.message.reply_text(
                f"Keine Tickets WIP von [{group_tasked}].",
                reply_markup=autoselect_keyboard(update, context),
            )


def close_uid(update: Update, context: CallbackContext, uid) -> None:
    """Close ticket with `uid`."""
    from src.commands import channel_msg

    if ticket := context.bot_data["tickets"].get(uid):
        # delete ticket
        ticket.close()
        add_ticket(context, ticket)
        del context.bot_data["tickets"][uid]
        # notify others in same orga-group
        close_text = (
            f"{str(TicketStatus.CLOSED)}: {who(update)} von "
            f"[{context.user_data['group_association']}] hat "
            f"Ticket #{uid} geschlossen."
        )
        channel_msg(close_text)
        # orga_msg(update, context, close_text)
        group_msg(
            update,
            context,
            ticket.group_tasked,
            f"{str(TicketStatus.CLOSED)}: {who(update)} hat Ticket "
            f"#{uid} geschlossen.",
        )
        # notify group of ticket creators
        group_msg(
            update,
            context,
            ticket.group_requesting,
            f"{str(TicketStatus.CLOSED)}: Euer Ticket #{uid} wurde bearbeitet.",
        )
        try:
            # no message object in case of inline response
            update.message.reply_text(
                f"Ticket #{uid} ist jetzt {str(TicketStatus.CLOSED)}.",
                reply_markup=autoselect_keyboard(update, context),
            )
        except AttributeError:
            pass
    else:
        update.message.reply_text(
            f"Ticket #{uid} wurde bereits geschlossen oder existiert noch nicht.",
            reply_markup=autoselect_keyboard(update, context),
        )


@orga_command
def wip(update: Update, context: CallbackContext) -> None:
    """Change Ticket status to WIP when provided with a uid. Otherwise,
    provide inline list of OPEN tickets for group.
    """
    try:
        uid = int(context.args[0])
        wip_uid(update, context, uid)
    except (ValueError, IndexError):
        group_tasked = context.user_data.get("group_association")
        keyboard = [
            [InlineKeyboardButton(str(t), callback_data=f"wip #{t.uid}")]
            for t in context.bot_data["tickets"].values()
            if t.is_open() and t.is_tasked(group_tasked)
        ]

        if keyboard:
            keyboard.append(
                [InlineKeyboardButton("❌ Abbrechen", callback_data="cancel #0")]
            )
            keyboard_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text("Offene Tickets:", reply_markup=keyboard_markup)
        else:
            update.message.reply_text(
                f"Keine offenen Tickets für [{group_tasked}].",
                reply_markup=autoselect_keyboard(update, context),
            )


def wip_uid(update: Update, context: CallbackContext, uid: int):
    """Change status of ticket with `uid` to WIP."""
    worker = who(update)
    try:
        worker = " ".join(context.args[1:])
    except (ValueError, IndexError, TypeError):
        pass
    if ticket := context.bot_data["tickets"].get(uid):
        if ticket.is_wip():
            # someone is already working on it.
            update.message.reply_text(
                "Jemand arbeitet bereits daran.",
                reply_markup=autoselect_keyboard(update, context),
            )
        else:
            ticket.set_wip(worker)
            add_ticket(context, ticket)
            group_msg(
                update,
                context,
                context.user_data["group_association"],
                f"{worker} arbeitet jetzt an Ticket #{uid}.",
            )
            channel_msg(
                f"{str(TicketStatus.WIP)}: {worker} von "
                f"[{context.user_data['group_association']}] arbeitet jetzt "
                f"an Ticket #{uid}."
            )
            # notify group of ticket creators
            group_msg(
                update,
                context,
                ticket.group_requesting,
                f"{str(TicketStatus.WIP)}: Euer Ticket #{uid} wurde angefangen "
                "zu bearbeiten.",
            )
            try:
                # no message object in case of inline response
                update.message.reply_text(
                    f"Ticket #{uid} ist jetzt {str(TicketStatus.WIP)}.",
                    reply_markup=autoselect_keyboard(update, context),
                )
            except AttributeError:
                pass
    else:
        update.message.reply_text(
            f"Ticket #{uid} wurde bereits geschlossen oder existiert noch nicht.",
            reply_markup=autoselect_keyboard(update, context),
        )


def revoke(update: Update, context: CallbackContext) -> None:
    """Revoke a ticket your group created, e.g. because you resolved it
    yourself. Otherwise, show an inline list of applicable tickets.
    """
    try:
        uid = int(context.args[0])
        revoke_uid(update, context, uid)
    except (ValueError, IndexError):
        group_requesting = context.user_data.get("group_association")
        keyboard = [
            [InlineKeyboardButton(str(t), callback_data=f"revoke #{t.uid}")]
            for t in context.bot_data["tickets"].values()
            if t.is_requesting(group_requesting) and t.is_open()
        ]

        if keyboard:
            keyboard.append(
                [InlineKeyboardButton("❌ Abbrechen", callback_data="cancel #0")]
            )
            keyboard_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text("Offene Tickets:", reply_markup=keyboard_markup)
        else:
            update.message.reply_text(
                f"Keine offenen Tickets von [{group_requesting}].",
                reply_markup=autoselect_keyboard(update, context),
            )


def revoke_uid(update: Update, context: CallbackContext, uid: int) -> None:
    if ticket := context.bot_data["tickets"].get(uid):
        ticket.revoke()
        add_ticket(context, ticket)
        del context.bot_data["tickets"][uid]
        revoke_text = (
            f"{str(TicketStatus.REVOKED)}: {who(update)} von "
            f"[{context.user_data['group_association']}] hat "
            f"Ticket #{uid} zurückgezogen."
        )
        channel_msg(revoke_text)
        group_msg(
            update,
            context,
            ticket.group_requesting,
            f"{str(TicketStatus.REVOKED)}: {who(update)} in deiner Gruppe hat gerade ticket '{ticket.text}' zurückgezogen.",
        )
    else:
        update.message.reply_text(
            f"Ticket #{uid} wurde bereits geschlossen, existiert noch nicht, oder ist bereits in arbeit.",
            reply_markup=autoselect_keyboard(update, context),
        )


@orga_command
def all(update: Update, context: CallbackContext) -> None:
    """Show list of all tickets, OPEN or WIP."""
    message = ""

    tickets_list = {orga_group: [] for orga_group in ORGA_GROUPS}
    for ticket in context.bot_data["tickets"].values():
        tickets_list[ticket.group_tasked].append(str(ticket))

    for orga_group in ORGA_GROUPS:
        if tickets := tickets_list[orga_group]:
            message += f"\n\n\n🔷 Offene Tickets für [{orga_group}]:\n\n"
            message += "\n\n".join(tickets)

    if not message:
        message = "Momentan gibt es keine offenen Tickets."

    update.message.reply_text(
        message,
        reply_markup=autoselect_keyboard(update, context),
    )


@orga_command
def tickets(update: Update, context: CallbackContext) -> None:
    """Show list of OPEN and WIP tickets to be done by [ORGA-GROUP] of user."""
    user_group = context.user_data.get("group_association")

    message = "\n\n".join(
        str(ticket)
        for ticket in context.bot_data["tickets"].values()
        if ticket.is_tasked(user_group)
    )

    if message:
        message = f"Liste der offenen Tickets für [{user_group}]:\n\n{message}"
    else:
        message = f"Momentan gibt es keine offenen Tickets für [{user_group}]."

    update.message.reply_text(
        message,
        reply_markup=autoselect_keyboard(update, context),
    )


@orga_command
def help2(update: Update, context: CallbackContext) -> None:
    message = """Zusätzlich verfügbare Kommandos für [ORGA]:
/all
    Zeige die Liste aller offenen tickets
    und deren <ticket-id>.
/tickets
    Zeige die Liste der offenen tickets
    und deren <id>, für deine Gruppe.
/wip [ticket-id] [tasked-worker]
    Zeige liste an offenen Tickets für
    deine Gruppe. Beginne Arbeit an
    einem Ticket durch Auswahl.
    Alternativ: sende die <ticket-id>
    mit, um die Auswahl zu überspringen,
    und setze mit <tasked-worker> den
    arbeitenden auf jemand anders dich.
    Wer am Ticket arbeitet ist nur im
    Dashboard zu sehen.
/close [ticket-id]
    Zeige liste an WIP Tickets für
    deine Gruppe. Schließe ein
    Ticket durch Auswahl.
    Alternativ: sende die <ticket-id>
    mit, um die Auswahl zu überspringen.
/message <ticket-id> <text>
    Sende eine Nachricht an alle Mitglieder
    der Gruppe, die Ticket <ticket-id>
    erstellt haben.
/dashboard
    Zeige an, ob das dashboard gerade
    verfügbar ist, und unter welchen links.
/help2
    Zeige diese Hilfenachricht.
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        reply_markup=autoselect_keyboard(update, context),
    )


@orga_command
def message(update: Update, context: CallbackContext) -> None:
    """Send message to members of a group who opened a ticket"""

    if len(context.args) < 2:
        update.message.reply_text(
            "Benutzung des Kommandos ist /message <ticket-id> <nachricht>",
            reply_markup=autoselect_keyboard(update, context),
        )
        return
    try:
        uid = int(context.args[0])
        ticket = context.bot_data["tickets"][uid]
        message = (
            f"🟣 Nachricht von {context.user_data['group_association']}: "
            + " ".join(context.args[1:])
        )
        group_msg(update, context, ticket.group_requesting, message)
        channel_msg(
            f"🟣 Nachricht von {context.user_data['group_association']} an "
            f"{ticket.group_requesting} zu #{ticket.uid}: "
            f"{' '.join(context.args[1:])}"
        )
        update.message.reply_text(
            "Nachricht verschickt.",
            reply_markup=autoselect_keyboard(update, context),
        )
    except (ValueError, IndexError):
        update.message.reply_text(
            "Stelle sicher, dass <ticket-id> eine valide Zahl von "
            "einem offenen Ticket ist.",
            reply_markup=autoselect_keyboard(update, context),
        )
        return


@orga_command
def dashboard(update: Update, context: CallbackContext) -> None:
    from src.dashboard_bridge import is_dashboard
    message = """Du kannst das dashboard unter den folgenden Links finden:

    Alle Tickets:
    http://<host>:<port>/#

    Nur Zentrale
    http://<host>:<port>/#zentrale

    Nur Finanz
    http://<host>:<port>/#finanz

    Nur BiMi
    http://<host>:<port>/#bimi
    """
    if not is_dashboard():
        message = "Das Dashboard ist gerade nicht verfügbar."
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        reply_markup=autoselect_keyboard(update, context),
    )
