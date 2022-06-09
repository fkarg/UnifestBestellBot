import json
import logging
import telegram
import argparse

from pathlib import Path
from telegram import Update
from telegram.ext import (
    Updater,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    Filters,
)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext



logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)

log = logging.getLogger(__name__)

ROOT = Path(".")
SECRETS_DIR = ROOT / "unifest-secrets"

def load_json(filename):
    with open(SECRETS_DIR / filename, "r") as f:
        return json.load(f)

def save_json(data, filename):
    with open(SECRETS_DIR / filename, "w") as file:
        json.dump(data, file)

TOKEN = load_json("token.json")
GROUP_ASSOCIATION = load_json("association.json")
GROUPS_LIST = load_json("groups.json")
UPDATES_CHANNEL_ID = load_json("channel.json")
DEVELOPER_CHAT_ID = load_json("developer.json")

def save_state():
    global GROUP_ASSOCIATION
    save_json(GROUP_ASSOCIATION, "association.json")


def start(update: Update, context: CallbackContext):
    message = """This is the UnifestBestellBot. Stalls can request supplies, particularly money, cups, and beer/cocktail materials. To begin, you should /register for which stall you want to order. You can then /request supplies."""
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def help(update: Update, context: CallbackContext):
    message = """Help message, WIP.
    Available commands:
    /start
    /register
    /request
    /help
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def unknown(update: Update, context: CallbackContext):
    message = """Sorry, I didn't understand that command.\n
    Send /help to receive an overview of available commands."""
    logging.info(f"received unknown command '{update.message.text}'")
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
    )


def inline(update: Update, context: CallbackContext) -> None:
    """Sends a message with three inline buttons attached."""
    keyboard = [
        [
            InlineKeyboardButton("Option 1", callback_data='1'),
            InlineKeyboardButton("Option 2", callback_data='2'),
        ],
        [InlineKeyboardButton("Option 3", callback_data='3')],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text('Please choose:', reply_markup=reply_markup)


def get_group(update: Update):
    global GROUP_ASSOCIATION
    return GROUP_ASSOCIATION.get(update.chat.id)


def register(update: Update, context: CallbackContext):
    global GROUP_ASSOCIATION
    log.info("registering user association")

    name = ' '.join(context.args)
    if name in GROUPS_LIST:
        GROUP_ASSOCIATION[update.message.chat.id] = name
        save_state()
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Registered as member of Group: {name}",
        )
        return

    elif context.args and context.args[0] == "Festko":
        # assign organizer
        GROUP_ASSOCIATION[update.message.chat.id] = "Festko"
        save_state()
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Registered as Organizer.",
        )
        return
    else:
        # provide all group options
        keyboard = [[InlineKeyboardButton(g, callback_data=g)] for g in GROUPS_LIST]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # reply_markup = InlineKeyboardMarkup(GROUPS_LIST)

        update.message.reply_text('Available Groups:', reply_markup=reply_markup)

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



def request(update: Update, context: CallbackContext):
    pass


def main():
    # ^ dict of chat_id -> group, relevant for /request
    # fill via ... /register, by inline-answer?
    # state = load_json(SECRETS_DIR / "state.json")
    # ^ dict with current state of open orders

    # bot = telegram.Bot(token=token)

    updater = Updater(token=TOKEN)
    dispatcher = updater.dispatcher

    # add various handlers here
    dispatcher.add_handler(CommandHandler("start", start))

    dispatcher.add_handler(CommandHandler("inline", inline))
    dispatcher.add_handler(CallbackQueryHandler(button))

    dispatcher.add_handler(CommandHandler("register", register))
    dispatcher.add_handler(CommandHandler("request", request))
    dispatcher.add_handler(CommandHandler("help", help))

    dispatcher.add_handler(MessageHandler(Filters.command, unknown))

    # begin action loop
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
