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

from lib.config import *

bot = Bot(token=TOKEN)


def dev_msg(message):
    log.info(f"to dev: {message}")
    bot.send_message(
        chat_id=DEVELOPER_CHAT_ID,
        text=message,
    )


def channel_msg(message):
    log.info(f"to channel: {message}")
    bot.send_message(
        chat_id=UPDATES_CHANNEL_ID,
        text=message,
    )


def orga_msg(message, orga):
    log.info(f"to orga: {message}")
    for chat_id in orga:
        bot.send_message(
            chat_id=chat_id,
            text=message,
        )


def group_msg(message, group):
    log.info(f"to group {group}: {message}")
    for chat_id in group:
        bot.send_message(
            chat_id=chat_id,
            text=message,
        )


def developer_command(func):
    def wrapper(update: Update, context: CallbackContext):
        if update.effective_chat.id == DEVELOPER_CHAT_ID:
            func(update, context)
            message = "Successfully executed command."
        else:
            message = "You are not authorized to execute this command."
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
        )

    return wrapper


def festko_command(func):
    def wrapper(update: Update, context: CallbackContext):
        if context.user_data.get("group_association") == "Festko":
            func(update, context)
        else:
            message = "You are not authorized to execute this command."
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message,
            )

    return wrapper


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


def error_handler(update: object, context: CallbackContext) -> None:
    import html
    import traceback
    from telegram import ParseMode

    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
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

    # Finally, send the message
    context.bot.send_message(
        chat_id=DEVELOPER_CHAT_ID, text=message, parse_mode=ParseMode.HTML
    )


def start(update: Update, context: CallbackContext) -> None:
    # message = """This is the UnifestBestellBot. Stalls can request supplies, particularly money, cups, and beer/cocktail materials. To begin, you should /register your stall group association, for which you want to request material. You can then /request supplies. See all available commands with /help."""
    message = """Das ist der UnifestBestellBot. Über mich können Stände nachschub bestellen, insbesondere Kleingeld, Becher, Bier, und Cocktailmaterialien. Als erstes solltest du deine Gruppenzugehörigkeit mit /registrieren festlegen, um anschließend mit /anfrage eine Anfrage stellen zu können. Alle verfügbaren kommandos und deren Erklärung kannst du mit /hilfe sehen."""
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def help_de(update: Update, context: CallbackContext) -> None:
    message = """Help message, WIP: Translation
Available commands:
/start
    To show the initial welcome message and information
/register <group name>
    Register your group association. Required before requesting supplies.
    Provides available options when no group is given initially or group is not
    found. It is only possible to have one group association at a time.
/unregister
    Remove current group association. Also possible via '/register no group'
/status
    Show status of user and requests.
/request
    Answer a number of questions to specify your request. Ultimately creates a
    ticket for the Organizers.
/cancel
    Cancel the request you're currently making
/bug <message>
    make a bug report. Please be as detailed as you can and is reasonable.
/help
    Show this help message.
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def help_en(update: Update, context: CallbackContext) -> None:
    message = """Help message, WIP.
Available commands:
/start
    To show the initial welcome message and information
/register <group name>
    Register your group association. Required before requesting supplies.
    Provides available options when no group is given initially or group is not
    found. It is only possible to have one group association at a time.
/unregister
    Remove current group association. Also possible via '/register no group'
/status
    Show status of user and requests.
/request
    Answer a number of questions to specify your request. Ultimately creates a
    ticket for the Organizers.
/cancel
    Cancel the request you're currently making
/bug <message>
    make a bug report. Please be as detailed as you can and is reasonable.
/help
    Show this help message.
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def unknown(update: Update, context: CallbackContext) -> None:
    message = (
        "Command not recognized or out of context.\n\n"
        "Send /help for an overview of available commands.\n"
        "Or, /request when you want to request something."
    )
    log.warn(f"received unrecognized command '{update.message.text}'")
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
    log.info(f"registering group association of user <@{update.message.chat.username}>")

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
    context.user_data["group_association"] = group_name
    chat_id = update.effective_chat.id
    if context.bot_data.get("group_association") is None:
        context.bot_data["group_association"] = {}
    if context.bot_data["group_association"].get(group_name) is None:
        log.warn(f"{group_name} for {chat_id} not found, creating list and adding")
        context.bot_data["group_association"][group_name] = [chat_id]
        assoc = context.bot_data["group_association"].get(group_name)
        log.warn(f"After adding {group_name}: {chat_id} == {assoc}")
    else:
        context.bot_data["group_association"][group_name].append(chat_id)


def unregister(update: Update, context: CallbackContext) -> None:
    try:
        previous = context.user_data["group_association"]
        del context.user_data["group_association"]
        context.bot_data["group_association"][previous].remove(update.effective_chat.id)

        message = f"Abmelden der Gruppenzugehörigkeit von {previous}"
        association_msg(update.message.chat, group_name=previous, register=False)
    except KeyError:
        message = "Keine Gruppenzugehörigkeit registriert"
    except AttributeError:
        association_msg(
            update.callback_query.message.chat, group_name=previous, register=False
        )
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def association_msg(chat, group_name=None, register=True) -> None:
    # username is guaranteed to exist, but first_name and last_name aren't
    first_name = str(chat.to_dict().get("first_name") or "")
    last_name = str(chat.to_dict().get("last_name") or "")
    if register:
        channel_msg(
            f"{first_name} {last_name} <@{chat.username}> registered as member of group {group_name}.",
        )
    else:
        channel_msg(
            f"{first_name} {last_name} <@{chat.username}> unregistered from group {group_name}.",
        )


def status(update: Update, context: CallbackContext) -> None:
    group = context.user_data.get("group_association")
    if group:
        update.message.reply_text(f"Mitglied der Gruppe {group}")
    else:
        update.message.reply_text("Nicht mitglied in einer Gruppe")


def details(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(f"{context.user_data}")

    try:
        association_msg(update.message.chat, group_name)
    except AttributeError:
        association_msg(update.callback_query.message.chat, group_name)

    context.bot.send_message(
        chat_id=chat_id,
        text=f"Registered as member of Group: {group_name}",
    )


def location(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    user_location = update.message.location
    lat, lon = user_location.latitude, user_location.longitude
    log.info(f"Location of @{user.username}: {lat} / {lon}")


def register_button(update: Update, context: CallbackContext) -> None:
    """Parses the CallbackQuery for group registration."""
    query = update.callback_query

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    query.answer()

    # for GROUP association updates
    if query.data in GROUPS_LIST:
        if context.user_data.get("group_association"):
            unregister(update, context)
        register_group(update, context, query.data)
        query.edit_message_text(text="Decided on Group.")
    elif query.data == "no group":
        unregister(update, context)
        query.edit_message_text(text="Cancelled group association.")
    else:
        query.edit_message_text(text="Something went very wrong ...")
        dev_msg(
            f"Query went wrong in chat with @{query.message.from_user.username}, data: {query.data}, message: {query.message.text}"
        )


def task_button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    query.answer()

    if "update #" in query.data:
        # update if someone else already takes care of it
        uid = int(query.data[8:])
        if tup := context.bot_data["tickets"].get(uid):
            if tup[2]:
                query.edit_message_text(
                    text=f"WIP: {tup[1]}",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "Update", callback_data=f"update #{uid}"
                                )
                            ]
                        ],
                    ),
                )
            # don't update on non_wip
        elif not context.bot_data["tickets"].get(uid):
            # remove WIP/Open before id
            text = query.message.text
            text = text[text.find("#") :]
            query.edit_message_text(text=f"Closed: {text}")

    elif "wip #" in query.data:
        uid = int(query.data[5:])
        group, text, _ = context.bot_data["tickets"][uid]
        context.bot_data["tickets"][uid] = (group, text, True)
        query.edit_message_text(
            text=f"WIP: {text}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Close", callback_data=f"close #{uid}")]],
            ),
        )

    elif "close #" in query.data:
        uid = int(query.data[7:])
        try:
            group, text, _ = context.bot_data["tickets"][uid]
            query.edit_message_text(text=f"Closed: {text}")
            channel_msg(f"Closed ticket #{uid}")
            del context.bot_data["tickets"][uid]
        except KeyError:
            text = query.message.text
            text = text[text.find("#") :]
            query.edit_message_text(text=f"Closed: {text}")
    else:
        query.edit_message_text(text="Something went very wrong ...")
        dev_msg(
            f"Query went wrong in chat with @{query.message.from_user.username}, data: {query.data}, message: {query.message.text}"
        )


def bug(update: Update, context: CallbackContext) -> None:
    if context.args:
        report = " ".join(context.args)
        dev_msg(report)
        update.message.reply_text("Forwarded bug report to developer.")
    else:
        update.message.reply_text("Usage of command is '/bug <message>'")


@developer_command
def reset(update: Update, context: CallbackContext) -> None:
    log.critical("resetting all context data.")
    context.bot_data.clear()
    context.user_data.clear()
    dev_msg("successfully cleared all context data.")


@orga_command
def help2(update: Update, context: CallbackContext) -> None:
    message = """Additional help message for Festko, WIP.
Available commands:
/system
    Show global state
/tickets
    Show open ticket and their ids
/help2
    Show this help message
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


@festko_command
def system_status(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(f"{context.user_data}")
    update.message.reply_text(f"{context.bot_data}")


@orga_command
def close(update: Update, context: CallbackContext) -> None:
    # close a ticket forcefully
    pass


@orga_command
def wip(update: Update, context: CallbackContext) -> None:
    # make a ticket WIP
    pass


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
