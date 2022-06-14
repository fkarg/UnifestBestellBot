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

log = logging.getLogger(__name__)

from lib.config import (
    GROUPS_LIST,
    GROUP_ASSOCIATION,
    UPDATES_CHANNEL_ID,
    DEVELOPER_CHAT_ID,
    REQUESTS,
    PRIORITY,
    TOKEN,
    ORGA,
)
from lib.utils import save_state

bot = Bot(token=TOKEN)


def channel_msg(message):
    log.info(message)
    bot.send_message(
        chat_id=UPDATES_CHANNEL_ID,
        text=message,
    )

def orga_msg(message, inline_options = None):
    log.info(message)
    for chat_id in ORGA:
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


def error_handler(update: object, context: CallbackContext) -> None:
    import html
    import traceback
    from telegram import ParseMode
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    log.error(msg="Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f'An exception was raised while handling an update\n'
        f'<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}'
        '</pre>\n\n'
        f'<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n'
        f'<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n'
        f'<pre>{html.escape(tb_string)}</pre>'
    )

    # Finally, send the message
    context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text=message, parse_mode=ParseMode.HTML)


def start(update: Update, context: CallbackContext):
    message = """This is the UnifestBestellBot. Stalls can request supplies, particularly money, cups, and beer/cocktail materials. To begin, you should /register for which stall you want to request material for. You can then /request supplies. You can see all available commands with /help."""
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def help(update: Update, context: CallbackContext):
    message = """Help message, WIP.
Available commands:
/start
    To show the initial welcome message and information
/register <group name>
    Register your group association. Required before requesting supplies. Provides available options when no group is given initially or group is not found. It is only possible to have on group association at a time.
/unregister
    Remove current group association. Also possible via '/register no group'
/status
    Show user group association and stats
/request <Money/Cups/Beer/Cocktail>
    WIP
/help
    Show this help message
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def unknown(update: Update, context: CallbackContext):
    message = """Command is not (yet) available.\nSend /help for an overview of available commands."""
    log.info(f"received unknown command '{update.message.text}'")
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


def get_group(update: Update):
    global GROUP_ASSOCIATION
    return GROUP_ASSOCIATION.get(update.chat.id)


def unregister(update: Update, context: CallbackContext):
    global GROUP_ASSOCIATION
    chat_id = update.effective_chat.id

    try:
        previous = GROUP_ASSOCIATION.pop(chat_id)
        save_state()
        message = f"Unregistered from Group: {previous}"
        last_name = str(update.effective_chat.to_dict().get("last_name") or "")
        channel_msg(
            f"{update.message.chat.first_name} {last_name} <@{update.message.chat.username}> unregistered from group {previous}.",
        )
    except KeyError:
        message = "No group association registered"
    context.bot.send_message(
        chat_id=chat_id,
        text=message,
    )


def association_msg(chat, group_name):
    # username is guaranteed to exist, but first_name and last_name aren't
    last_name  = str(chat.to_dict().get("last_name") or "")
    first_name = str(chat.to_dict().get("first_name") or "")
    channel_msg(
        f"{first_name} {last_name} <@{chat.username}> registered as member of group {group_name}.",
    )


def register(update: Update, context: CallbackContext):
    global GROUP_ASSOCIATION
    log.info("registering user association")

    name = " ".join(context.args)
    if name.upper() in map(str.upper, GROUPS_LIST):
        name_actual = GROUPS_LIST[list(map(str.upper, GROUPS_LIST)).index(name.upper())]
        GROUP_ASSOCIATION[update.effective_chat.id] = name_actual
        save_state()
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Registered as member of Group: {name_actual}",
        )
        association_msg(update.message.chat, name_actual)
    elif name and name == "no group":
        unregister(update, context)
    elif name and name == "Festko":
        # assign organizer
        GROUP_ASSOCIATION[update.effective_chat.id] = "Festko"
        save_state()
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Registered as Organizer.",
        )
        association_msg(update.message.chat, "Organizer")
    else:
        # provide all group options
        keyboard = [[InlineKeyboardButton(g, callback_data=g)] for g in GROUPS_LIST] + [
            [InlineKeyboardButton("<No Group>", callback_data="no group")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # reply_markup = InlineKeyboardMarkup(GROUPS_LIST)
        update.message.reply_text("Available Groups:", reply_markup=reply_markup)


@developer_command
def reset(update: Update, context: CallbackContext) -> None:
    global GROUP_ASSOCIATION
    log.warn("resetting all group associations")
    GROUP_ASSOCIATION = {}
    save_state()


def button(update: Update, context: CallbackContext) -> None:
    """Parses the CallbackQuery and updates the message text."""
    global GROUP_ASSOCIATION
    query = update.callback_query

    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    query.answer()

    # for GROUP association updates
    if query.data in GROUPS_LIST:
        GROUP_ASSOCIATION[query.message.chat.id] = query.data
        save_state()
        association_msg(query.message.chat, query.data)
        query.edit_message_text(text=f"Registered as member of group: {query.data}")
    elif query.data == "no group":
        unregister(update, context)
        query.edit_message_text(text="Cancelled group association")
    elif query.data in REQUESTS:
        query.edit_message_text(text=f"Requesting {query.data}")
        # check for open request information of group
        # if exists in db:
        #   ask for priority update
        # else:
        #   create new in db
        keyboard = [[InlineKeyboardButton(g, callback_data=g)] for g in PRIORITY]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id=query.message.chat.id, text="With Priority:", reply_markup=reply_markup)
    elif query.data in PRIORITY:
        # check for requested <item> in db first
        query.edit_message_text(text=f"Created ticket with priority: {query.data}")
        # send incoming new ticket to channel and Festko



def request(update: Update, context: CallbackContext):
    global GROUP_ASSOCIATION
    global REQUESTS
    group = GROUP_ASSOCIATION.get(update.effective_chat.id)
    if not group:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Please register your group association first"
        )
        return
    log.info(f"Group {group} request incoming")
    request = " ".join(context.args)
    if request.upper() in map(str.upper, REQUESTS):
        log.info(f"recognized {request}")
        keyboard = [[InlineKeyboardButton(g, callback_data=g)] for g in PRIORITY]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text("With Priority:", reply_markup=reply_markup)
    else:
        keyboard = [[InlineKeyboardButton(g, callback_data=g)] for g in REQUESTS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text("Request one of:", reply_markup=reply_markup)
