from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from telegram.ext import CallbackContext

import logging
import json

from src.config import GROUPS_LIST, ORGA_GROUPS, HIDDEN_GROUPS, ALL_GROUPS, DEVELOPER_CHAT_ID
from src.utils import who, dev_msg, channel_msg, autoselect_keyboard, dev_html

log = logging.getLogger(__name__)


def developer_command(func):
    """ Decorator for commands only the developer is allowed to execute
    """
    def wrapper(update: Update, context: CallbackContext):
        if update.effective_chat.id == DEVELOPER_CHAT_ID:
            func(update, context)
            message = "Successfully executed command."
        else:
            message = "Du bist nicht zur ausführung dieses Kommandos berechtigt."
            group = context.user_data.get("group_association")
            dev_msg(
                f"⚠️ {who(update)} [{group}] tried to execute a command for [Developer]: "
                f"{update.message.text}"
            )
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            reply_markup=autoselect_keyboard(update, context),
        )

    return wrapper


def error_handler(update: object, context: CallbackContext) -> None:
    """ Instead of having errors crash the whole bot, log them and send the trace
    to the developer.
    """
    import html
    import traceback
    from telegram.error import NetworkError

    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it
    # even if something breaks.
    if isinstance(context.error, NetworkError):
        return
    log.error(msg="🔴 Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception,
    # but as a list of strings rather than a single string, so we have to
    # join them together.
    tb_list = traceback.format_exception(
        None, context.error, context.error.__traceback__
    )
    tb_string = "".join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096
    # character limit.
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"An exception was raised while handling an update\n"
        f"<pre>update = "
        f"{html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
        "</pre>\n\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    dev_html(update, context, message)


def start(update: Update, context: CallbackContext) -> None:
    """ Send initial welcoming message
    """
    message = (
        "Hi, Ich bin der UnifestBestellBot. Über mich können Stände Nachschub "
        "bestellen, insbesondere Kleingeld, Becher, Bier, und Cocktailmaterialien."
        " Als erstes solltest du deine Gruppenmitgliedschaft mit /register "
        "festlegen, um anschließend mit /request eine Anfrage stellen zu können. "
        "Alle verfügbaren Kommandos und deren Erklärung kannst du mit /help sehen."
    )
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        reply_markup=autoselect_keyboard(update, context),
    )


def help(update: Update, context: CallbackContext) -> None:
    """ Send message with help / usage information
    """
    message = """Verfügbare Befehle:
/start
    Zeige initiale Willkommensnachricht an.
/register [gruppenname]
    Registriere deine Gruppenmitgliedschaft.
    Muss getan werden, bevor du Anfragen
    stellen kannst. Zeigt verfügbare
    Optionen an, wenn keine direkt
    mitegegeben wurde. Es ist nur möglich,
    eine Gruppenmitgliedschaft zu haben.
/unregister
    Entferne deine Gruppenmitgliedschaft.
/status
    Zeige deine Gruppenmitgliedschaft und
    offene Tickets deiner Gruppe an.
/request
    Erstelle eine Anfrage an Finanzer /
    BiMis / Zentrale. Mit ein paar Fragen
    kannst du genau Bestimmen, was ihr
    braucht. Daraufhin wird ein Ticket
    erstellt.
/cancel
    Breche das erstellen der momentanen
    Anfrage ab.
/bug <message>
    Schreibe einen Fehlerbericht. Bitte
    erkläre, wie der Fehler reproduziert
    werden kann.
/feature <message>
    Beschreibe eine neue Eigenschaft oder
    Fähigkeit, die der Bot haben soll.
    Möglicherweise wird es umgesetzt.
/help
    Zeige diese Hilfenachricht an.
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        reply_markup=autoselect_keyboard(update, context),
    )


def unknown(update: Update, context: CallbackContext) -> None:
    """ Reaction to an unrecognized command.
    """
    message = (
        "Kommando nicht erkannt oder im falschen Zusammenhang.\n\n"
        "Sende /help um eine Übersicht zu allen verfügbaren Kommandos "
        "zu bekommen. Sende alternativ /request um eine Anfrage "
        "zu stellen."
    )
    group = context.user_data["group_association"]
    log.warn(
        f"⚠️ received unrecognized command '{update.message.text}' from {who(update)} [{group}]"
    )
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        reply_markup=autoselect_keyboard(update, context),
    )


def register(update: Update, context: CallbackContext) -> None:
    """ Command to register group membership. If no group name is passed
    as argument, show non-hidden and non-orga groups as inline buttons.
    Unregisters previous group membership regardless of successful registration
    at another group.

    See `register_button` for more details on handling the inline-buttons.
    """
    if context.user_data.get("group_association"):
        unregister(update, context)

    name = " ".join(context.args)
    if name and name.upper() in map(str.upper, ALL_GROUPS):
        name_actual = ALL_GROUPS[list(map(str.upper, ALL_GROUPS)).index(name.upper())]
        register_group(update, context, name_actual)
        if name_actual in ORGA_GROUPS:
            from src.tickets import help2
            help2(update, context)
    elif name and name == "no group":
        unregister(update, context)
    else:
        # provide all group options
        keyboard = [[InlineKeyboardButton(g, callback_data=g)] for g in GROUPS_LIST] + [
            [InlineKeyboardButton("❌ Abbrechen", callback_data="no group")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # reply_markup = InlineKeyboardMarkup(GROUPS_LIST)
        update.message.reply_text("Mögliche Gruppen:", reply_markup=reply_markup)


def register_group(update: Update, context: CallbackContext, group_name: str):
    """Register user for group `group_name`. `group_name` needs to be the same
    name as in `groups.json` / `orga.json` / `hidden.json`, and same key as in
    `mapping.json`.
    """
    context.user_data["group_association"] = group_name
    chat_id = update.effective_chat.id
    if context.bot_data.get("group_association") is None:
        context.bot_data["group_association"] = {}
    if context.bot_data["group_association"].get(group_name) is None:
        context.bot_data["group_association"][group_name] = [chat_id]
    else:
        context.bot_data["group_association"][group_name].append(chat_id)

    association_msg(update, group_name)
    try:
        update.message.reply_text(
            text=f"Anmelden bei Gruppe [{group_name}] erfolgreich.",
            reply_markup=autoselect_keyboard(update, context),
        )
    except AttributeError:
        context.bot.send_message(
            chat_id=update.callback_query.message.chat.id,
            text=f"Anmelden bei Gruppe [{group_name}] erfolgreich.",
            reply_markup=autoselect_keyboard(update, context),
        )


def unregister(update: Update, context: CallbackContext) -> None:
    """ Unregister user from current group membership and send
    respective logs / messages
    """
    try:
        previous = context.user_data["group_association"]
        del context.user_data["group_association"]
        context.bot_data["group_association"][previous].remove(update.effective_chat.id)

        message = f"Mitgliedschaft bei Gruppe [{previous}] entfernt."
        association_msg(update, group_name=previous, register=False)
    except KeyError:
        message = "Keine Gruppenmitgliedschaft registriert. Nichts zu entfernen."
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        reply_markup=autoselect_keyboard(update, context),
    )


def association_msg(update, group_name, register=True) -> None:
    """ Log the registering / unregistering of a user.
    """
    if register:
        channel_msg(
            f"🔵 {who(update)} registered as member of group {group_name}.",
        )
    else:
        channel_msg(
            f"🔵 {who(update)} unregistered from group {group_name}.",
        )


def status(update: Update, context: CallbackContext) -> None:
    """ Give a status update to the user. Includes group association
    and status of unclosed (open and wip) tickets for the users group.
    """
    group = context.user_data.get("group_association")
    if group:
        update.message.reply_text(f"Mitglied der Gruppe [{group}].")
    else:
        update.message.reply_text(
            "Keine Gruppenmitgliedschaft.",
            reply_markup=autoselect_keyboard(update, context),
        )
    open_tickets = []
    for (uid, ticket) in context.bot_data.get("tickets", {}).items():
        if ticket.group_requesting == group:
            open_tickets.append(str(ticket))

    if open_tickets:
        update.message.reply_text(
            f"{group} hat {len(open_tickets)} Ticket offen:\n\n"
            + "\n\n---\n".join(open_tickets),
            reply_markup=autoselect_keyboard(update, context),
        )
    elif group:
        update.message.reply_text(
            "Deine Gruppe hat gerade keine offenen Tickets.",
            reply_markup=autoselect_keyboard(update, context),
        )


def details(update: Update, context: CallbackContext) -> None:
    """ Answer with the full user context data. For debugging purposes.
    """
    update.message.reply_text(
        f"{context.user_data}",
        reply_markup=autoselect_keyboard(update, context),
    )


def register_button(update: Update, context: CallbackContext) -> None:
    """Parses the CallbackQuery for group registration.
    Registers user with selected group, or cancel registration.
    """
    query = update.callback_query

    # for GROUP association updates
    if query.data in GROUPS_LIST:
        if context.user_data.get("group_association"):
            unregister(update, context)
        register_group(update, context, query.data)
        query.edit_message_text(text="Gruppenauswahl getroffen.")
    elif query.data == "no group":
        query.edit_message_text(text="Gruppenauswahl abgebrochen.")
    else:
        query.edit_message_text(text="Something went very wrong ...")
        dev_msg(
            "⚪️ User Registration Query went wrong in chat with "
            f"@{query.message.from_user.username} and {who(update)}, "
            f"data: {query.data}, message: {query.message.text}"
        )

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    query.answer()


def task_button(update: Update, context: CallbackContext) -> None:
    """ Parse the CallbackQuery for inline buttons of `/wip` and `/close`.
    """
    query = update.callback_query

    from src.tickets import close_uid, wip_uid, TicketStatus

    try:
        if "wip #" in query.data:
            uid = int(query.data[5:])
            wip_uid(update, context, uid)
            ticket = context.bot_data["tickets"].get(uid)
            query.edit_message_text(text=f"{str(ticket)}")
        elif "close #" in query.data:
            uid = int(query.data[7:])
            ticket = context.bot_data["tickets"].get(uid)
            close_uid(update, context, uid)
            ticket.close()
            query.edit_message_text(text=f"{str(ticket)}")
        elif "cancel" in query.data:
            query.edit_message_text(text="❌ Abgebrochen.")
    except ValueError as e:
        log.error(e)

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    query.answer()


def feature(update: Update, context: CallbackContext) -> None:
    """ Send a feature request to the developer.
    """
    if context.args:
        msg = " ".join(context.args)
        dev_msg(f"⚪️ feature request von {who(update)}: " + msg)
        update.message.reply_text(
            "Feature Request an Entwickler weitergeleitet.",
            reply_markup=autoselect_keyboard(update, context),
        )
    else:
        update.message.reply_text(
            "Benutzung des Kommandos ist '/feature <message>'",
            reply_markup=autoselect_keyboard(update, context),
        )


def bug(update: Update, context: CallbackContext) -> None:
    """ Send a bug report to the developer.
    """
    if context.args:
        report = " ".join(context.args)
        dev_msg(f"⚪️ Bug report von {who(update)}: " + report)
        update.message.reply_text(
            "Fehlerbericht an Entwickler weitergeleitet.",
            reply_markup=autoselect_keyboard(update, context),
        )
    else:
        update.message.reply_text(
            "Benutzung des Kommandos ist '/bug <message>'",
            reply_markup=autoselect_keyboard(update, context),
        )


@developer_command
def resetall(update: Update, context: CallbackContext) -> None:
    """ Developer command to reset all bot context data.
    """
    log.critical("resetting all bot context data.")
    context.bot_data.clear()
    dev_msg("☑️ successfully cleared all context data.")


@developer_command
def closeall(update: Update, context: CallbackContext) -> None:
    """ Developer command to close all open tickets.
    """
    from src.tickets import close_uid

    log.critical("closing all open tickets.")
    # cannot mutate dictionary while iteration
    uids = [uid for uid in context.bot_data["tickets"].keys()]
    for uid in uids:
        close_uid(update, context, uid)

    dev_msg("☑️ successfully closed all tickets.")


@developer_command
def system_status(update: Update, context: CallbackContext) -> None:
    """ Developer command to show system status.
    """
    import html
    from telegram import ParseMode
    from src.tickets import TicketEncoder

    update.message.reply_text(f"{context.user_data}")

    js = json.dumps(context.bot_data, indent=2, ensure_ascii=False, cls=TicketEncoder)

    message = f"<pre>update = {html.escape(js)}</pre>\n\n"

    dev_html(update, context, message)
