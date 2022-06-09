from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from telegram.ext import (
    Updater,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    Filters,
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,
)

import logging
log = logging.getLogger(__name__)

from lib.config import GROUPS_LIST, GROUP_ASSOCIATION, UPDATES_CHANNEL_ID, DEVELOPER_CHAT_ID
from lib.utils import save_state

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


def start(update: Update, context: CallbackContext):
    message = """This is the UnifestBestellBot. Stalls can request supplies, particularly money, cups, and beer/cocktail materials. To begin, you should /register for which stall you want to order. You can then /request supplies. You can see all available commands with /help."""
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
                update, context,
            f"{update.message.chat.first_name} {last_name} <@{update.message.chat.username}> unregistered from group {previous}."
        )
    except KeyError:
        message = "No group association registered"
    context.bot.send_message(
        chat_id=chat_id,
        text=message,
    )


def channel_msg(update: Update, context: CallbackContext, message):
    log.info(message)
    context.bot.send_message(
        chat_id=UPDATES_CHANNEL_ID,
        text=message,
    )


def register(update: Update, context: CallbackContext):
    global GROUP_ASSOCIATION
    log.info("registering user association")

    name = " ".join(context.args)
    if name in GROUPS_LIST:
        GROUP_ASSOCIATION[update.effective_chat.id] = name
        save_state()
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Registered as member of Group: {name}",
        )
        last_name = str(update.message.chat.to_dict().get("last_name") or "")
        channel_msg(
            update,
            context,
            message=f"{update.message.chat.first_name} {last_name} <@{update.message.chat.username}> just registered as member of group {name}.",
        )
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
        last_name = str(update.chat.get("last_name") or "")
        context.bot.send_message(
            chat_id=UPDATES_CHANNEL_ID,
            text=f"{update.chat.first_name} {last_name} <@{update.chat.username}> just registered as Organizer.",
        )
        return
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
        query.edit_message_text(text=f"Registered as member of group: {query.data}")
    elif query.data == "no group":
        unregister(update, context)
        query.edit_message_text(text="Cancelled group association")


def request(update: Update, context: CallbackContext):
    pass
