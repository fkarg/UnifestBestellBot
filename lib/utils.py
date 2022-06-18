import json
import logging

log = logging.getLogger(__name__)

from telegram import Update, Bot
import telegram

from telegram.ext import CallbackContext


def set_log_level_format(logging_level, format):
    logging.addLevelName(logging_level, format % logging.getLevelName(logging_level))


def get_logging_level(args):
    if args.verbose >= 3:
        return logging.DEBUG
    if args.verbose == 2:
        return logging.INFO
    if args.verbose >= 1:
        return logging.WARNING
    return logging.ERROR


def load_json(filename):
    from lib.config import SECRETS_DIR

    with open(SECRETS_DIR / filename, "r") as f:
        return json.load(f)


def save_json(data, filename):
    from lib.config import SECRETS_DIR

    with open(SECRETS_DIR / filename, "w") as file:
        json.dump(data, file)


def who(update: Update):
    try:
        chat = update.message.chat
    except AttributeError:
        chat = update.callback_query.message.chat
    # username is 'guaranteed' to exist (might be None tho), but first_name and last_name aren't
    first_name = str(chat.to_dict().get("first_name") or "")
    last_name = str(chat.to_dict().get("last_name") or "")
    return f"{first_name} {last_name} <@{chat.username}>"


def dev_msg(message):
    from lib.config import TOKEN, DEVELOPER_CHAT_ID

    bot = Bot(token=TOKEN)
    log.info(f"to dev: {message}")
    bot.send_message(
        chat_id=DEVELOPER_CHAT_ID,
        text=message,
    )


def channel_msg(message):
    from lib.config import TOKEN, UPDATES_CHANNEL_ID

    bot = Bot(token=TOKEN)

    log.info(f"to channel: {message}")
    bot.send_message(
        chat_id=UPDATES_CHANNEL_ID,
        text=message,
    )


def group_msg(
    update: Update, context: CallbackContext, group: str, message: str
) -> None:
    log.info(f"to {group}: {message}")
    for chat_id in context.bot_data["group_association"].get(group, []):
        try:
            context.bot.send_message(
                chat_id=chat_id,
                text=message,
            )
        except telegram.error.Unauthorized as e:
            text = f"Unauthorized for sending message to {chat_id} from {context.user_data['group_association']}"
            log.error(text)
            dev_msg(text)
            # dev_msg(e)


def orga_msg(update: Update, context: CallbackContext, message: str) -> None:
    from lib.config import ORGA_GROUPS

    for group in ORGA_GROUPS:
        group_msg(update, context, group, message)
