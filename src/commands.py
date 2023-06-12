from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, Bot

from telegram.ext import (
    Updater,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackQueryHandler,
    CallbackContext,
)

import logging
import json

log = logging.getLogger(__name__)

from src.config import *
from src.utils import who, dev_msg, channel_msg


def developer_command(func):
    def wrapper(update: Update, context: CallbackContext):
        if update.effective_chat.id == DEVELOPER_CHAT_ID:
            func(update, context)
            message = "Successfully executed command."
        else:
            message = "Du bist nicht zur ausführung dieses Kommandos berechtigt."
            dev_msg(
                f"{who(update)} tried to execute a command for [Developer]: {update.message.text}"
            )
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
        )

    return wrapper


def festko_command(func):
    def wrapper(update: Update, context: CallbackContext):
        if context.user_data.get("group_association") == "Zentrale":
            func(update, context)
        else:
            message = "Du bist nicht zur ausführung dieses Kommandos berechtigt."
            dev_msg(
                f"{who(update)} tried to execute a command for [Zentrale]: {update.message.text}"
            )
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message,
            )

    return wrapper


def error_handler(update: object, context: CallbackContext) -> None:
    import html
    import traceback
    from telegram import ParseMode
    from telegram.error import NetworkError

    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    if isinstance(context.error, NetworkError):
        return
    log.error(msg="Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(
        None, context.error, context.error.__traceback__
    )
    tb_string = "".join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
        "</pre>\n\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    n = 4096 - 11  # for tags <pre></pre>
    if len(message) > n:
        # need to split messages
        for i in range(0, len(message), n):
            prefix = "<pre>" if i != 0 else ""
            suffix = "</pre>" if i + n < len(message) else ""
            text = prefix + message[i : i + n] + suffix
            context.bot.send_message(
                chat_id=DEVELOPER_CHAT_ID, text=text, parse_mode=ParseMode.HTML
            )
    else:
        # send the message
        context.bot.send_message(
            chat_id=DEVELOPER_CHAT_ID, text=message, parse_mode=ParseMode.HTML
        )


def start(update: Update, context: CallbackContext) -> None:
    message = """Hi, Ich bin der UnifestBestellBot. Über mich können Stände Nachschub bestellen, insbesondere Kleingeld, Becher, Bier, und Cocktailmaterialien. Als erstes solltest du deine Gruppenmitgliedschaft mit /register festlegen, um anschließend mit /request eine Anfrage stellen zu können. Alle verfügbaren Kommandos und deren Erklärung kannst du mit /help sehen."""
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def help(update: Update, context: CallbackContext) -> None:
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
    )


def unknown(update: Update, context: CallbackContext) -> None:
    message = (
        "Kommando nicht erkannt oder im falschen Zusammenhang.\n\n"
        "Sende /hilfe um eine Übersicht zu allen verfügbaren Kommandos"
        "zu bekommen. Sende alternativ /request um eine Anfrage"
        "zu stellen."
    )
    log.warn(
        f"received unrecognized command '{update.message.text}' from {who(update)}"
    )
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def inline(update: Update, context: CallbackContext) -> None:
    """Sends a message with three inline buttons attached."""
    keyboard = [
        [
            InlineKeyboardButton("Option 1", callback_data="1"),
            InlineKeyboardButton("Option 2", callback_data="2"),
        ],
        [InlineKeyboardButton("Option 3", callback_data="3")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text("Please choose:", reply_markup=reply_markup)


def register(update: Update, context: CallbackContext) -> None:
    log.info(f"registering group association of user {who(update)}")

    name = " ".join(context.args)
    if name.upper() in map(str.upper, GROUPS_LIST):
        if context.user_data.get("group_association"):
            unregister(update, context)
        name_actual = GROUPS_LIST[list(map(str.upper, GROUPS_LIST)).index(name.upper())]
        register_group(update, context, name_actual)

    elif name and name == "no group":
        unregister(update, context)
    elif name and name in ORGA_GROUPS:
        if context.user_data.get("group_association"):
            unregister(update, context)
        register_group(update, context, name)
        from src.tickets import help2

        help2(update, context)
    else:
        if context.user_data.get("group_association"):
            unregister(update, context)
        # provide all group options
        keyboard = [[InlineKeyboardButton(g, callback_data=g)] for g in GROUPS_LIST] + [
            [InlineKeyboardButton("<Keine Gruppe>", callback_data="no group")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # reply_markup = InlineKeyboardMarkup(GROUPS_LIST)
        update.message.reply_text("Mögliche Gruppen:", reply_markup=reply_markup)


def register_group(update: Update, context: CallbackContext, group_name):
    """Register user for `group_name`, which needs to be the same name as
    in `groups.json`.
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
            f"Anmelden bei Gruppe [{group_name}] erfolgreich."
        )
    except AttributeError:
        context.bot.send_message(
            chat_id=update.callback_query.message.chat.id,
            text=f"Anmelden bei Gruppe [{group_name}] erfolgreich.",
        )


def unregister(update: Update, context: CallbackContext) -> None:
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
    )


def association_msg(update, group_name, register=True) -> None:
    if register:
        channel_msg(
            f"🔵 {who(update)} registered as member of group {group_name}.",
        )
    else:
        channel_msg(
            f"🔵 {who(update)} unregistered from group {group_name}.",
        )


def status(update: Update, context: CallbackContext) -> None:
    group = context.user_data.get("group_association")
    if group:
        update.message.reply_text(f"Mitglied der Gruppe [{group}].")
    else:
        update.message.reply_text("Keine Gruppenmitgliedschaft.")
    open_tickets = []
    for (uid, ticket) in context.bot_data.get("tickets", {}).items():
        if ticket.group_requesting == group:
            open_tickets.append(str(ticket))

    if open_tickets:
        update.message.reply_text(
            f"{group} hat {len(open_tickets)} ticket offen:\n\n"
            + "\n\n---\n".join(open_tickets)
        )
    elif group:
        update.message.reply_text("Deine Gruppe hat gerade keine offenen Tickets.")


def details(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(f"{context.user_data}")

    # chat_id = update.effective_chat.id
    # context.bot.send_message(
    #     chat_id=chat_id,
    #     text=f"Registered as member of Group: {group_name}",
    # )


def location(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    user_location = update.message.location
    lat, lon = user_location.latitude, user_location.longitude
    log.info(f"Location of @{user.username}: {lat} / {lon}")


def register_button(update: Update, context: CallbackContext) -> None:
    """Parses the CallbackQuery for group registration."""
    query = update.callback_query

    # for GROUP association updates
    if query.data in GROUPS_LIST:
        if context.user_data.get("group_association"):
            unregister(update, context)
        register_group(update, context, query.data)
        query.edit_message_text(text="Gruppenauswahl getroffen.")
    elif query.data == "no group":
        unregister(update, context)
        query.edit_message_text(text="Gruppenauswahl abgebrochen.")
    else:
        query.edit_message_text(text="Something went very wrong ...")
        dev_msg(
            f"User Registration Query went wrong in chat with @{query.message.from_user.username}, data: {query.data}, message: {query.message.text}"
        )

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    query.answer()

def task_button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query

    from src.tickets import close_uid, wip_uid

    try:
        if "wip #" in query.data:
            uid = int(query.data[5:])
            wip_uid(update, context, uid)
            query.edit_message_text(text=f"WIP: #{uid}")
        elif "close #" in query.data:
            uid = int(query.data[7:])
            close_uid(update, context, uid)
            query.edit_message_text(text=f"Closed: #{uid}")
        elif "cancel" in query.data:
            query.edit_message_text(text="Abgebrochen.")
    except ValueError as e:
        log.error(e)

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    query.answer()


def feature(update: Update, context: CallbackContext) -> None:
    if context.args:
        msg = " ".join(context.args)
        dev_msg(f"feature request von {who(update)}: " + msg)
        update.message.reply_text("Feature Request an Entwickler weitergeleitet.")
    else:
        update.message.reply_text("Benutzung des Kommandos ist '/feature <message>'")


def bug(update: Update, context: CallbackContext) -> None:
    if context.args:
        report = " ".join(context.args)
        dev_msg(f"Bug report von {who(update)}: " + report)
        update.message.reply_text("Fehlerbericht an Entwickler weitergeleitet.")
    else:
        update.message.reply_text("Benutzung des Kommandos ist '/bug <message>'")


@developer_command
def reset(update: Update, context: CallbackContext) -> None:
    log.critical("resetting all bot context data.")
    context.bot_data.clear()
    dev_msg("successfully cleared all context data.")


@developer_command
def closeall(update: Update, context: CallbackContext) -> None:
    from src.tickets import close_uid

    log.critical("closing all open tickets.")
    # cannot mutate dictionary while iteration
    uids = [uid for uid in context.bot_data["tickets"].keys()]
    for uid in uids:
        close_uid(update, context, uid)

    dev_msg("successfully closed all tickets.")


@festko_command
def system_status(update: Update, context: CallbackContext) -> None:
    import html
    from telegram import ParseMode
    from src.tickets import TicketEncoder

    update.message.reply_text(f"{context.user_data}")

    message = (
        f"<pre>update = {html.escape(json.dumps(context.bot_data, indent=2, ensure_ascii=False, cls=TicketEncoder))}"
        "</pre>\n\n"
    )

    n = 4096 - 11  # for tags <pre></pre>
    if len(message) > n:
        # need to split messages
        for i in range(0, len(message), n):
            prefix = "<pre>" if i != 0 else ""
            suffix = "</pre>" if i + n < len(message) else ""
            text = prefix + message[i : i + n] + suffix
            update.message.reply_text(text, parse_mode=ParseMode.HTML)
    else:
        # Finally, send the message
        update.message.reply_text(message, parse_mode=ParseMode.HTML)
