import json
import telegram
import logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)


def load_json(filename):
    with open(filename, "r") as f:
        return json.load(f)


token = load_json("token.json")

bot = telegram.Bot(token=token)

# for u in bot.get_updates():
#     bot.send_message(text="in progress", chat_id=u.message.from_user.id)

from telegram.ext import Updater

updater = Updater(token=token)
dispatcher = updater.dispatcher


# adding dispatcher to react to /start
from telegram import Update
from telegram.ext import CallbackContext

def start(update: Update, context: CallbackContext):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="This is the UnifestBestellBot for 2022, talk to me!",
    )

from telegram.ext import CommandHandler

start_handler = CommandHandler("start", start)
dispatcher.add_handler(start_handler)


# adding handler to echo all incoming messages
from telegram.ext import MessageHandler, Filters

def echo(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id, text=update.message.text)

echo_handler = MessageHandler(Filters.text & (~Filters.command), echo)
dispatcher.add_handler(echo_handler)


# adding handler to return stuff in caps
def caps(update: Update, context: CallbackContext):
    text_caps = ' '.join(context.args).upper()
    context.bot.send_message(chat_id=update.effective_chat.id, text=text_caps)

caps_handler = CommandHandler('caps', caps)
dispatcher.add_handler(caps_handler)

# adding inline-handler for caps
from telegram import InlineQueryResultArticle, InputTextMessageContent
def inline_caps(update: Update, context: CallbackContext):
    query = update.inline_query.query
    if not query:
        return
    results = []
    results.append(
        InlineQueryResultArticle(
            id=query.upper(),
            title='Caps',
            input_message_content=InputTextMessageContent(query.upper())
        )
    )
    context.bot.answer_inline_query(update.inline_query.id, results)

from telegram.ext import InlineQueryHandler
inline_caps_handler = InlineQueryHandler(inline_caps)
dispatcher.add_handler(inline_caps_handler)

# unknown commands
def unknown(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.")

unknown_handler = MessageHandler(Filters.command, unknown)
dispatcher.add_handler(unknown_handler)


# begin action loop
updater.start_polling()

updater.idle()
